"""Job supervisor: one active job per workspace (across application instances), a dedicated worker process per job,
events, cancellation, restart recovery and shutdown.

Consistency rules
* result.json is the single authoritative terminal record. It is published exactly once (exclusive link); whoever publishes first wins.
  status.json is progress information only. A job is DONE iff result.json exists.
* Two locks live in the workspace: instance.lock (held by the application instance for its lifetime; a second instance refuses to start)
  and active-job.lock (taken here, handed to the worker as an inherited descriptor and held for the worker's lifetime; it is the
  one-active-job guard even when the owning instance has died).
* Signals to recorded processes are sent only after an identity check (start time, and for workers the command line).
"""
import json
import os
import re
import secrets
import signal
import subprocess
import sys
import threading
import time

from . import reports
from .util import (downgrade, group_signal_ok, is_worker_process, kill_group_guarded, publish_result, read_json, register_interrupt, try_lock,
                   write_json_atomic)

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKER_PY = os.path.join(APP_DIR, "workbench", "worker.py")
JOB_ID_RE = re.compile(r"^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}$")
PKG_ID_RE = re.compile(r"^[0-9a-f]{64}$")
WORKER_ENV_KEYS = ("PATH", "HOME", "USER", "LOGNAME", "LANG", "RUSTUP_HOME", "CARGO_HOME")


def abs_path_ok(v):
    if not isinstance(v, str) or "\x00" in v or len(v) > 4096 or not os.path.isabs(v):
        return False
    return ".." not in v.split("/") and os.path.normpath(v) == (v.rstrip("/") or "/")


class Busy(Exception):
    pass


class BadRequest(Exception):
    pass


class WorkspaceInUse(Exception):
    pass


def valid_job_id(s):
    return isinstance(s, str) and bool(JOB_ID_RE.match(s))


class JobManager:
    def __init__(self, workspace, module, module_ref="workbench.modules:default_module", extra_sys_path=(), worker_py=WORKER_PY,
                 default_deadline_minutes=None, orphan_grace=15.0):
        self.ws = workspace
        self.module = module
        self.module_ref = module_ref
        self.extra_sys_path = list(extra_sys_path)
        self.worker_py = worker_py
        self.min_deadline_minutes = 1
        self.orphan_grace = orphan_grace        # seconds a recovered/stopped worker gets to seal its job after TERM, before KILL
        self.default_deadline_minutes = default_deadline_minutes or module.profile["limits"]["deadline_minutes"]
        self.lock = threading.Lock()
        self.active = None              # {"job_id", "proc"}
        self._abandoned = False
        self._instance_fd = try_lock(self.ws.p("instance.lock"))
        if self._instance_fd is None:
            raise WorkspaceInUse(f"another application instance is using the workspace {self.ws.root}")
        self.recover()

    # ---- paths -------------------------------------------------------------------------------------------------------------
    def job_dir(self, job_id):
        if not valid_job_id(job_id):
            raise BadRequest("bad job id")
        return self.ws.p("runs", job_id)

    def _read(self, job_id, name):
        return read_json(os.path.join(self.job_dir(job_id), name))

    # ---- sealing interrupted jobs ------------------------------------------------------------------------------------------
    def _interrupt(self, jid, reason, grace=None):
        """Seal a job that has no result: stop its (identity-checked) worker and child group, publish an APP_FAILURE result,
        regenerate the application report from that result. Never reruns anything. Safe to call repeatedly."""
        jd = self.job_dir(jid)
        if os.path.exists(os.path.join(jd, "result.json")):
            return
        grace = self.orphan_grace if grace is None else grace
        if register_interrupt(jd, reason, timeout=min(grace, 5.0)) == "too_late":
            return          # the worker published first: the job finished before the interruption and its result stands
        reason = (read_json(os.path.join(jd, "interrupt.json")) or {}).get("reason", reason)     # one reason, whoever seals first
        st = read_json(os.path.join(jd, "status.json")) or {}
        wpid, wticks = st.get("worker_pid"), st.get("worker_start_ticks")
        if is_worker_process(wpid, wticks, jd):
            try:
                os.kill(wpid, signal.SIGTERM)
            except OSError:
                pass
            end = time.monotonic() + grace
            while time.monotonic() < end and is_worker_process(wpid, wticks, jd) and not os.path.exists(os.path.join(jd, "result.json")):
                time.sleep(0.1)
            if is_worker_process(wpid, wticks, jd) and not os.path.exists(os.path.join(jd, "result.json")):
                try:
                    os.kill(wpid, signal.SIGKILL)
                except OSError:
                    pass
        # leftover child group (identity of its leader must still match)
        cpg, cticks = st.get("child_pgid"), st.get("child_start_ticks")
        if cpg and group_signal_ok(jd, cpg, cticks):
            kill_group_guarded(jd, cpg, cticks, signal.SIGTERM)
            end = time.monotonic() + 5
            while time.monotonic() < end and group_signal_ok(jd, cpg, cticks):
                time.sleep(0.1)
            kill_group_guarded(jd, cpg, cticks, signal.SIGKILL)
        if os.path.exists(os.path.join(jd, "result.json")):
            return
        base = {"job_id": jid, "kind": st.get("kind"), "finished": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "execution": {"status": "APP_FAILURE", "reason": reason}, "p10": {"state": "NOT_EVALUATED"},
                "reproduction": {"status": "NOT_EVALUATED", "badge": False, "checks": [], "reasons": ["the job was interrupted; any partial records are preserved but not promoted"]}}
        base = downgrade(base, "APP_FAILURE", reason, "the job was interrupted; any partial records are preserved but not promoted")
        if not publish_result(jd, base, timeout=5.0):
            return
        spec = read_json(os.path.join(jd, "job.json"))
        try:
            if spec is None:
                raise ValueError("no job.json")
            reports.finalize(jd, spec, base)
        except Exception:
            try:
                os.unlink(os.path.join(jd, "app-report.json"))      # a stale report must not contradict the sealed result
            except OSError:
                pass
        try:
            write_json_atomic(os.path.join(jd, "status.json"), dict(st, state="DONE", execution="APP_FAILURE", phase="interrupted", child_pgid=None))
        except OSError:
            pass

    def recover(self):
        """At startup: unfinished jobs (no result.json) are interrupted: live orphan workers are stopped, results sealed as APP_FAILURE."""
        for jid in sorted(os.listdir(self.ws.p("runs"))):
            if valid_job_id(jid):
                self._interrupt(jid, "INTERRUPTED_BY_RESTART")

    def _simulate_crash(self):
        """Test seam: behave like an application instance that died without cleanup (its workers keep running)."""
        self._abandoned = True
        self._release_instance_lock()

    def _release_instance_lock(self):
        if self._instance_fd is not None:
            os.close(self._instance_fd)
            self._instance_fd = None

    # ---- start -------------------------------------------------------------------------------------------------------------
    def is_busy(self):
        """True while any worker of this workspace (from any instance, or orphaned) holds the active-job lock."""
        fd = try_lock(self.ws.p("active-job.lock"))
        if fd is None:
            return True
        os.close(fd)
        return False

    def start(self, kind, package_id, lean_bin, allowed_signers=None, deadline_minutes=None):
        if kind not in ("readiness", "run"):
            raise BadRequest("kind must be readiness or run")
        if not isinstance(package_id, str) or not PKG_ID_RE.match(package_id):
            raise BadRequest("package_id must be a 64-hex package digest")
        managed = self.ws.p("packages", package_id)
        if not os.path.isdir(managed):
            raise BadRequest("package is not imported")
        for name, v, req in (("lean_bin", lean_bin, True), ("allowed_signers", allowed_signers, False)):
            if v in (None, "") and not req:
                continue
            if not abs_path_ok(v):
                raise BadRequest(f"{name} must be a normalized absolute path")
        lim = self.module.profile["limits"]
        dl = self.default_deadline_minutes if deadline_minutes in (None, "") else deadline_minutes
        if isinstance(dl, bool) or not isinstance(dl, (int, float)) or not (self.min_deadline_minutes <= dl <= 24 * 60):
            raise BadRequest("deadline_minutes must be between 1 and 1440")
        with self.lock:
            lock_fd = try_lock(self.ws.p("active-job.lock"))
            if lock_fd is None:
                raise Busy("another job is active in this workspace")
            try:
                job_id = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-" + secrets.token_hex(4)
                jd = self.ws.p("runs", job_id)
                old = os.umask(0o077)
                try:
                    os.mkdir(jd, 0o700)
                finally:
                    os.umask(old)
                spec = {"job_id": job_id, "kind": kind, "package_id": package_id, "managed_dir": managed, "workspace": self.ws.root,
                        "host_config": {"lean_bin": lean_bin, "allowed_signers": allowed_signers or None},
                        "module_ref": self.module_ref, "extra_sys_path": self.extra_sys_path, "deadline_s": float(dl) * 60.0,
                        "log_limit": lim["log_bytes"], "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        "module_description": self.module.describe(), "profile": self.module.profile}
                write_json_atomic(os.path.join(jd, "job.json"), spec)
                write_json_atomic(os.path.join(jd, "status.json"), {"state": "RUNNING", "execution": "RUNNING", "phase": "queued", "kind": kind})
                env = {k: os.environ[k] for k in WORKER_ENV_KEYS if k in os.environ}
                with open(os.path.join(jd, "worker.out"), "wb") as wout:
                    proc = subprocess.Popen([sys.executable, "-I", "-B", self.worker_py, jd], shell=False, env=env, stdin=subprocess.DEVNULL,
                                            stdout=wout, stderr=subprocess.STDOUT, start_new_session=True, close_fds=True, pass_fds=(lock_fd,))
            finally:
                os.close(lock_fd)       # the worker keeps the lock through its inherited descriptor
            self.active = {"job_id": job_id, "proc": proc}
            threading.Thread(target=self._watch, args=(job_id, proc), daemon=True).start()
            return job_id

    def _watch(self, job_id, proc):
        rc = proc.wait()
        if self._abandoned:
            return
        try:
            if not os.path.exists(os.path.join(self.job_dir(job_id), "result.json")):     # worker died without sealing: application failure
                self._interrupt(job_id, f"WORKER_CRASHED(exit {rc})", grace=0)
        except OSError:
            pass            # the job directory itself is gone or unwritable: nothing left to seal in this process

    # ---- queries -----------------------------------------------------------------------------------------------------------
    def _worker_alive(self, jid):
        a = self.active
        if a and a["job_id"] == jid:
            return a["proc"].poll() is None
        st = self._read(jid, "status.json") or {}
        return is_worker_process(st.get("worker_pid"), st.get("worker_start_ticks"), self.job_dir(jid))

    def status(self, job_id):
        st = self._read(job_id, "status.json") or {}
        job = self._read(job_id, "job.json") or {}
        if not st and not job:
            return None
        res = self._read(job_id, "result.json")
        if res is None and not self._worker_alive(job_id):
            self._interrupt(job_id, "WORKER_GONE_WITHOUT_RESULT", grace=0)
            res = self._read(job_id, "result.json")
        if res is not None:      # result.json is authoritative; keep the progress record consistent with it
            st = dict(st, state="DONE", execution=res["execution"]["status"])
        return {"job_id": job_id, "kind": job.get("kind"), "created": job.get("created"), "package_id": job.get("package_id"),
                "execution_kind": (job.get("module_description") or {}).get("execution_kind"), "synthetic": (job.get("module_description") or {}).get("synthetic"),
                "status": st, "result": res}

    def list(self):
        out = []
        for jid in sorted(os.listdir(self.ws.p("runs")), reverse=True)[:50]:
            if valid_job_id(jid):
                s = self.status(jid)
                if s:
                    out.append({"job_id": jid, "kind": s["kind"], "created": s["created"], "execution": s["status"].get("execution"), "state": s["status"].get("state")})
        return out

    def events(self, job_id, after=0, limit=500, tail=32768):
        jd = self.job_dir(job_id)
        evs = []
        try:
            with open(os.path.join(jd, "events.jsonl"), encoding="utf-8") as f:
                for line in f:
                    try:
                        e = json.loads(line)
                    except ValueError:
                        continue
                    if e.get("seq", 0) > after:
                        evs.append(e)
                        if len(evs) >= limit:
                            break
        except OSError:
            pass

        def tail_of(name):
            p = os.path.join(jd, name)
            try:
                size = os.path.getsize(p)
                with open(p, "rb") as f:
                    f.seek(max(0, size - tail))
                    return {"text": f.read(tail).decode("utf-8", "replace"), "size": size}
            except OSError:
                return {"text": "", "size": 0}
        return {"events": evs, "next": evs[-1]["seq"] if evs else after, "stdout": tail_of("stdout.log"), "stderr": tail_of("stderr.log")}

    def export(self, job_id):
        jd = self.job_dir(job_id)
        done = os.path.exists(os.path.join(jd, "result.json"))
        return reports.export_archive(jd, tmp_dir=self.ws.p("tmp"), partial=not done)

    # ---- cancel / shutdown -------------------------------------------------------------------------------------------------
    def cancel(self, job_id):
        a = self.active
        if a and a["job_id"] == job_id and a["proc"].poll() is None:
            try:
                os.kill(a["proc"].pid, signal.SIGTERM)
            except ProcessLookupError:
                return False
            threading.Thread(target=self._escalate, args=(job_id, a["proc"]), daemon=True).start()
            return True
        return False

    def _escalate(self, job_id, proc, wait=30):
        try:
            proc.wait(timeout=wait)
        except subprocess.TimeoutExpired:
            self._force_stop(job_id, proc)

    def _force_stop(self, job_id, proc):
        st = self._read(job_id, "status.json") or {}
        kill_group_guarded(self.job_dir(job_id), st.get("child_pgid"), st.get("child_start_ticks"), signal.SIGKILL)
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)       # the worker leads its own session/group (we started it)
            except OSError:
                pass

    def shutdown(self, wait=40):
        """Stop the active worker (TERM, then KILL) and make sure its job is sealed as interrupted."""
        a = self.active
        if a and a["proc"].poll() is None:
            jid, proc = a["job_id"], a["proc"]
            register_interrupt(self.job_dir(jid), "INTERRUPTED_BY_SHUTDOWN", timeout=min(wait, 5.0))     # loses if the job already published
            try:
                os.kill(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                proc.wait(timeout=wait)
            except subprocess.TimeoutExpired:
                self._force_stop(jid, proc)
                proc.wait()
            self._interrupt(jid, "INTERRUPTED_BY_SHUTDOWN", grace=0)

    def close(self):
        self.shutdown()
        self._release_instance_lock()
