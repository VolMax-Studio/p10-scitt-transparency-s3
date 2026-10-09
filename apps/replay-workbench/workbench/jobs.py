"""Job supervisor: at most one active job, a dedicated worker process per job, events, cancellation and restart recovery."""
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
from .worker import proc_start_ticks, write_json_atomic

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKER_PY = os.path.join(APP_DIR, "workbench", "worker.py")
JOB_ID_RE = re.compile(r"^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}$")
PKG_ID_RE = re.compile(r"^[0-9a-f]{64}$")
WORKER_ENV_KEYS = ("PATH", "HOME", "USER", "LOGNAME", "LANG", "RUSTUP_HOME", "CARGO_HOME")
TERMINAL_STATES = ("DONE",)


def abs_path_ok(v):
    if not isinstance(v, str) or "\x00" in v or len(v) > 4096 or not os.path.isabs(v):
        return False
    return ".." not in v.split("/") and os.path.normpath(v) == (v.rstrip("/") or "/")


class Busy(Exception):
    pass


class BadRequest(Exception):
    pass


def valid_job_id(s):
    return isinstance(s, str) and bool(JOB_ID_RE.match(s))


class JobManager:
    def __init__(self, workspace, module, module_ref="workbench.modules:default_module", extra_sys_path=(), worker_py=WORKER_PY, default_deadline_minutes=None):
        self.ws = workspace
        self.module = module
        self.module_ref = module_ref
        self.extra_sys_path = list(extra_sys_path)
        self.worker_py = worker_py
        self.min_deadline_minutes = 1
        self.default_deadline_minutes = default_deadline_minutes or module.profile["limits"]["deadline_minutes"]
        self.lock = threading.Lock()
        self.active = None            # {"job_id", "proc"}
        self.orphans = {}             # job_id -> (pid, ticks) for recovered jobs whose process may still run
        self.recover()

    # ---- paths -------------------------------------------------------------------------------------------------------------
    def job_dir(self, job_id):
        if not valid_job_id(job_id):
            raise BadRequest("bad job id")
        return self.ws.p("runs", job_id)

    def _read(self, job_id, name):
        try:
            with open(os.path.join(self.job_dir(job_id), name), encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    # ---- recovery ----------------------------------------------------------------------------------------------------------
    def recover(self):
        """Unfinished jobs found at startup are marked interrupted; they are never rerun or promoted."""
        base = self.ws.p("runs")
        for jid in sorted(os.listdir(base)):
            if not valid_job_id(jid):
                continue
            st = self._read(jid, "status.json")
            if st is not None and st.get("state") == "DONE":
                continue
            alive = False
            pid, ticks = (st or {}).get("worker_pid"), (st or {}).get("worker_start_ticks")
            if pid and ticks is not None and proc_start_ticks(pid) == ticks:
                alive = True
            cpg = (st or {}).get("child_pgid")
            if cpg and (st or {}).get("child_start_ticks") is not None and proc_start_ticks(cpg) == st["child_start_ticks"]:
                alive = True
            if alive:
                self.orphans[jid] = (pid, ticks)
                continue
            new = dict(st or {"kind": "unknown"}, state="DONE", execution="APP_FAILURE", phase="interrupted",
                       recovery="The application restarted before this job finished; partial files are preserved and not promoted.")
            write_json_atomic(os.path.join(base, jid, "status.json"), new)
            if not os.path.exists(os.path.join(base, jid, "result.json")):
                write_json_atomic(os.path.join(base, jid, "result.json"), {
                    "job_id": jid, "kind": new.get("kind"), "execution": {"status": "APP_FAILURE", "reason": "INTERRUPTED_BY_RESTART"},
                    "p10": {"state": "NOT_EVALUATED"}, "reproduction": {"status": "NOT_EVALUATED", "badge": False, "checks": [], "reasons": ["interrupted"]}})

    def _refresh_orphans(self):
        for jid, (pid, ticks) in list(self.orphans.items()):
            if proc_start_ticks(pid) != ticks:
                del self.orphans[jid]
                st = self._read(jid, "status.json") or {}
                write_json_atomic(os.path.join(self.job_dir(jid), "status.json"), dict(st, state="DONE", execution="APP_FAILURE", phase="interrupted"))
                if not os.path.exists(os.path.join(self.job_dir(jid), "result.json")):
                    write_json_atomic(os.path.join(self.job_dir(jid), "result.json"), {
                        "job_id": jid, "kind": st.get("kind"), "execution": {"status": "APP_FAILURE", "reason": "INTERRUPTED_BY_RESTART"},
                        "p10": {"state": "NOT_EVALUATED"}, "reproduction": {"status": "NOT_EVALUATED", "badge": False, "checks": [], "reasons": ["interrupted"]}})

    # ---- start -------------------------------------------------------------------------------------------------------------
    def is_busy(self):
        self._refresh_orphans()
        a = self.active
        return bool((a and a["proc"].poll() is None) or self.orphans)

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
            if self.is_busy():
                raise Busy("another job is active")
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
                                        stdout=wout, stderr=subprocess.STDOUT, start_new_session=True, close_fds=True)
            self.active = {"job_id": job_id, "proc": proc}
            threading.Thread(target=self._watch, args=(job_id, proc), daemon=True).start()
            return job_id

    def _watch(self, job_id, proc):
        rc = proc.wait()
        st = self._read(job_id, "status.json") or {}
        if st.get("state") != "DONE":     # worker died without finishing: application failure, never a P10 result
            cpg = st.get("child_pgid")
            if cpg:
                try:
                    os.killpg(cpg, signal.SIGKILL)
                except OSError:
                    pass
            write_json_atomic(os.path.join(self.job_dir(job_id), "status.json"), dict(st, state="DONE", execution="APP_FAILURE", phase="worker-crashed"))
            if not os.path.exists(os.path.join(self.job_dir(job_id), "result.json")):
                write_json_atomic(os.path.join(self.job_dir(job_id), "result.json"), {
                    "job_id": job_id, "kind": st.get("kind"), "execution": {"status": "APP_FAILURE", "reason": f"WORKER_CRASHED(exit {rc})"},
                    "p10": {"state": "NOT_EVALUATED"}, "reproduction": {"status": "NOT_EVALUATED", "badge": False, "checks": [], "reasons": ["worker crashed"]}})

    # ---- queries -----------------------------------------------------------------------------------------------------------
    def status(self, job_id):
        st = self._read(job_id, "status.json")
        if st is None:
            return None
        job = self._read(job_id, "job.json") or {}
        res = self._read(job_id, "result.json") if st.get("state") == "DONE" else None
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
        if job_id in self.orphans:
            pid, ticks = self.orphans[job_id]
            if proc_start_ticks(pid) == ticks:
                try:
                    os.kill(pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                return True
        return False

    def _escalate(self, job_id, proc):
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            st = self._read(job_id, "status.json") or {}
            for pg in (st.get("child_pgid"), proc.pid):
                if pg:
                    try:
                        os.killpg(pg, signal.SIGKILL)
                    except OSError:
                        pass

    def shutdown(self, wait=40):
        a = self.active
        if a and a["proc"].poll() is None:
            self.cancel(a["job_id"])
            try:
                a["proc"].wait(timeout=wait)
            except subprocess.TimeoutExpired:
                pass
