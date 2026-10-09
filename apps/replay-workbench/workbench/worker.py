"""Dedicated worker process: one per job. Resource settings, offline subprocesses, cancellation, bounded logs.

Started by workbench.jobs as `python3 -I -B worker.py <job-dir>`. It reads <job-dir>/job.json, writes status.json / events.jsonl /
result.json atomically and never prints secrets. It knows nothing about P10 semantics; the module supplies commands and collection.
"""
import importlib
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import traceback

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

from workbench import reports  # noqa: E402

MAX_EVENTS = 5000
CMD_CAPTURE = 1 << 20


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def write_json_atomic(path, obj):
    tmp = f"{path}.tmp{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1, sort_keys=True)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def proc_start_ticks(pid):
    try:
        with open(f"/proc/{pid}/stat") as f:
            return int(f.read().rsplit(")", 1)[1].split()[19])
    except (OSError, ValueError, IndexError):
        return None


class Cancelled(Exception):
    pass


class RunResult:
    def __init__(self, rc, stdout="", stderr="", timed_out=False):
        self.rc, self.stdout, self.stderr, self.timed_out = rc, stdout, stderr, timed_out


class Worker:
    def __init__(self, job_dir):
        self.dir = job_dir
        self.spec = json.load(open(os.path.join(job_dir, "job.json"), encoding="utf-8"))
        self.tmpdir = os.path.join(job_dir, "tmp")
        os.makedirs(self.tmpdir, mode=0o700, exist_ok=True)
        self.workspace = self.spec["workspace"]
        self.cancel = threading.Event()
        self.cancel_reason = None
        self.seq = 0
        self.status = {"state": "RUNNING", "execution": "RUNNING", "phase": "starting", "worker_pid": os.getpid(),
                       "worker_start_ticks": proc_start_ticks(os.getpid()), "child_pgid": None, "started": now(), "kind": self.spec["kind"]}
        self.t0 = time.monotonic()
        self.deadline_at = self.t0 + float(self.spec["deadline_s"])
        self.cmd_n = 0
        # ctx object handed to modules
        self.ctx = self
        self.tmpdir_ctx = self.tmpdir

    # ---- status / events ---------------------------------------------------------------------------------------------------
    def save_status(self, **kw):
        self.status.update(kw)
        self.status["updated"] = now()
        write_json_atomic(os.path.join(self.dir, "status.json"), self.status)

    def emit(self, kind, text):
        if self.seq > MAX_EVENTS:
            return
        self.seq += 1
        if self.seq == MAX_EVENTS:
            kind, text = "info", "event limit reached; further events are not recorded (logs continue)"
        line = json.dumps({"seq": self.seq, "t": now(), "elapsed": round(time.monotonic() - self.t0, 1), "kind": kind, "text": str(text)[:500]})
        with open(os.path.join(self.dir, "events.jsonl"), "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def phase(self, name):
        self.save_status(phase=name)
        self.emit("phase", name)

    # ---- resource settings -------------------------------------------------------------------------------------------------
    def apply_resources(self):
        info = {}
        try:
            os.nice(10)
            info["nice"] = os.getpriority(os.PRIO_PROCESS, 0)
        except OSError as e:
            info["nice_error"] = type(e).__name__
        try:
            cpus = sorted(os.sched_getaffinity(0))
            keep = set(cpus[:2])
            os.sched_setaffinity(0, keep)
            info["cpus"] = sorted(keep)
        except (AttributeError, OSError) as e:
            info["affinity_error"] = type(e).__name__
        info["limits_note"] = "scheduling priority and CPU affinity only; not a RAM limit"
        self.save_status(resources=info)
        return info

    # ---- supervised subprocess ---------------------------------------------------------------------------------------------
    @property
    def deadline_hit(self):
        return time.monotonic() > self.deadline_at

    def kill_group(self, pgid):
        """TERM, wait 5 s, KILL. Child cleanup is verified by probing the group."""
        def alive():
            try:
                os.killpg(pgid, 0)
                return True
            except (ProcessLookupError, PermissionError):
                return False
        if not alive():
            return {"term": False, "kill": False}
        try:
            os.killpg(pgid, signal.SIGTERM)
        except ProcessLookupError:
            return {"term": False, "kill": False}
        end = time.monotonic() + 5.0
        while time.monotonic() < end and alive():
            time.sleep(0.1)
        killed = False
        if alive():
            try:
                os.killpg(pgid, signal.SIGKILL)
                killed = True
            except ProcessLookupError:
                pass
            end = time.monotonic() + 3.0
            while time.monotonic() < end and alive():
                time.sleep(0.05)
        return {"term": True, "kill": killed, "group_gone": not alive()}

    def supervise(self, argv, env, cwd, out_path, err_path, log_limit, line_cb=None, timeout=None):
        """Run argv (shell=False) in a new session; returns dict(rc, signal, cancelled, deadline, overflow, timed_out)."""
        res = {"rc": None, "signal": None, "cancelled": False, "deadline": False, "overflow": False, "timed_out": False, "start_error": None}
        if self.cancel.is_set():
            res["cancelled"] = True
            return res
        try:
            p = subprocess.Popen(argv, shell=False, env=env, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 start_new_session=True, close_fds=True)
        except OSError as e:
            res["start_error"] = f"{type(e).__name__}: {e}"
            return res
        pgid = p.pid
        self.save_status(child_pgid=pgid, child_start_ticks=proc_start_ticks(pgid))
        overflow = threading.Event()

        def drain(stream, path, is_out):
            n = 0
            buf = b""
            try:
                with open(path, "ab") as f:
                    while True:
                        b = stream.read1(65536) if hasattr(stream, "read1") else stream.read(65536)
                        if not b:
                            break
                        if n + len(b) > log_limit:
                            f.write(b[:max(0, log_limit - n)])
                            overflow.set()
                            break
                        n += len(b)
                        f.write(b)
                        f.flush()
                        if is_out and line_cb:
                            buf += b
                            while b"\n" in buf:
                                line, buf = buf.split(b"\n", 1)
                                line_cb(line.decode("utf-8", "replace"))
                            buf = buf[-4096:]
            except OSError:
                pass

        ts = [threading.Thread(target=drain, args=(p.stdout, out_path, True), daemon=True),
              threading.Thread(target=drain, args=(p.stderr, err_path, False), daemon=True)]
        for t in ts:
            t.start()
        t_end = time.monotonic() + timeout if timeout else None
        stop = None
        while p.poll() is None:
            if self.cancel.is_set():
                stop = "cancelled"
            elif self.deadline_hit:
                stop = "deadline"
            elif overflow.is_set():
                stop = "overflow"
            elif t_end and time.monotonic() > t_end:
                stop = "timeout"
            if stop:
                res["cleanup"] = self.kill_group(pgid)
                break
            time.sleep(0.1)
        try:
            p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(pgid, signal.SIGKILL)
            p.wait()
        for t in ts:
            t.join(timeout=5)
        if not stop:
            self.kill_group(pgid)   # reap stray children of a normally exited command; no-op when the group is gone
        if stop is None and overflow.is_set():
            stop = "overflow"
        rc = p.returncode
        res.update(rc=rc if rc is not None and rc >= 0 else None, signal=-rc if rc is not None and rc < 0 else None)
        res["cancelled"] = stop == "cancelled"
        res["deadline"] = stop == "deadline"
        res["overflow"] = stop == "overflow"
        res["timed_out"] = stop == "timeout"
        self.save_status(child_pgid=None)
        return res

    # ---- ctx API used by modules -------------------------------------------------------------------------------------------
    def run(self, argv, env=None, cwd=None, timeout=120):
        self.cmd_n += 1
        o = os.path.join(self.tmpdir, f"cmd-{self.cmd_n:03d}.out")
        e = os.path.join(self.tmpdir, f"cmd-{self.cmd_n:03d}.err")
        r = self.supervise(argv, env if env is not None else {}, cwd, o, e, CMD_CAPTURE, timeout=timeout)

        def tail(p):
            try:
                with open(p, "rb") as f:
                    return f.read(CMD_CAPTURE).decode("utf-8", "replace")
            except OSError:
                return ""
        if r["cancelled"] or r["deadline"]:
            raise Cancelled("deadline" if r["deadline"] else "cancelled")
        if r["start_error"]:
            return RunResult(127, "", r["start_error"])
        rc = r["rc"] if r["rc"] is not None else -(r["signal"] or 1)
        return RunResult(rc, tail(o), tail(e), timed_out=r["timed_out"])

    # ---- main --------------------------------------------------------------------------------------------------------------
    def load_module(self):
        for p in self.spec.get("extra_sys_path", []):
            if p not in sys.path:
                sys.path.insert(0, p)
        mod, _, attr = self.spec["module_ref"].partition(":")
        return getattr(importlib.import_module(mod), attr)()

    def finish(self, execution, reason, extra=None):
        res = {"job_id": self.spec["job_id"], "kind": self.spec["kind"], "execution": {"status": execution, "reason": reason},
               "finished": now(), "elapsed_seconds": round(time.monotonic() - self.t0, 1)}
        res.update(extra or {})
        return res

    def handle_term(self, signum, frame):
        self.cancel_reason = "signal %d" % signum
        self.cancel.set()

    def main(self):
        signal.signal(signal.SIGTERM, self.handle_term)
        signal.signal(signal.SIGINT, self.handle_term)
        res = None
        try:
            self.apply_resources()
            module = self.load_module()
            res = self.run_job(module)
        except Cancelled as c:
            res = self.finish("CANCELLED", str(c), {"p10": {"state": "NOT_EVALUATED"}, "reproduction": {"status": "NOT_EVALUATED", "badge": False, "checks": [], "reasons": ["interrupted"]}})
        except BaseException as e:
            with open(os.path.join(self.dir, "worker-error.txt"), "w") as f:
                traceback.print_exc(file=f)
            res = self.finish("APP_FAILURE", "WORKER_EXCEPTION:" + type(e).__name__,
                              {"p10": {"state": "NOT_EVALUATED"}, "reproduction": {"status": "NOT_EVALUATED", "badge": False, "checks": [], "reasons": ["worker exception"]}})
        try:
            reports.finalize(self.dir, self.spec, res)
        except BaseException:
            with open(os.path.join(self.dir, "report-error.txt"), "w") as f:
                traceback.print_exc(file=f)
        write_json_atomic(os.path.join(self.dir, "result.json"), res)
        self.save_status(state="DONE", execution=res["execution"]["status"], phase="done")
        self.emit("state", res["execution"]["status"])

    def prepare_signers(self):
        src = self.spec["host_config"].get("allowed_signers")
        if not src:
            return None
        dst = os.path.join(self.dir, "allowed_signers.pub")
        st = os.stat(src)
        if not os.path.isfile(src) or st.st_size > (1 << 20):
            raise ValueError("allowed-signers file must be a regular file of at most 1 MiB")
        data = open(src, "rb").read()
        if b"PRIVATE KEY" in data:
            raise ValueError("the allowed-signers file contains private key material; supply only the public file")
        with open(dst, "wb") as f:
            f.write(data)
        os.chmod(dst, 0o600)
        import hashlib
        return {"path": dst, "sha256": hashlib.sha256(data).hexdigest(), "source_path": src}

    def run_job(self, module):
        spec = self.spec
        host = dict(spec["host_config"])
        try:
            signers = self.prepare_signers()
        except (OSError, ValueError) as e:
            return self.finish("BLOCKED", "ALLOWED_SIGNERS_REJECTED: " + str(e)[:200], {"p10": {"state": "NOT_EVALUATED"}, "readiness": [],
                                                                                      "reproduction": {"status": "NOT_EVALUATED", "badge": False, "checks": [], "reasons": []}})
        if signers:
            host["allowed_signers"] = signers["path"]
        managed = spec["managed_dir"]
        self.phase("readiness")
        recs = module.inspect(managed, host, self.ctx)
        write_json_atomic(os.path.join(self.dir, "readiness.json"), recs)
        bad = module.blocking(recs)
        base = {"readiness": recs, "signers": signers and {"sha256": signers["sha256"]}, "readiness_blocking": [b["id"] for b in bad]}
        if spec["kind"] == "readiness":
            return self.finish("COMPLETED", None, {**base, "p10": {"state": "NOT_EVALUATED", "note": "readiness has no P10 outcome"},
                                                   "reproduction": {"status": "NOT_EVALUATED", "badge": False, "checks": [], "reasons": []}})
        if bad:
            return self.finish("BLOCKED", "READINESS_FAILED", {**base, "p10": {"state": "NOT_EVALUATED"},
                                                              "reproduction": {"status": "NOT_EVALUATED", "badge": False, "checks": [], "reasons": ["readiness failed; the wrapper was not started"]}})
        out_dir = os.path.join(self.dir, "runner-out")
        cmd = module.command(managed, host, out_dir, self.ctx)
        self.phase("wrapper")
        self.save_status(command_argv=cmd["argv"], namespace_flag=cmd.get("namespace_flag"))
        self.emit("info", "starting wrapper: " + " ".join(cmd["argv"]))

        seen = [0]

        def on_line(line):          # wrapper phase headers: navigation only, capped so a noisy log cannot flood the event stream
            if line.startswith("== ") and seen[0] < 200:
                seen[0] += 1
                self.emit("phase", line[:200])
                self.save_status(phase=line[:200])
        r = self.supervise(cmd["argv"], cmd["env"], cmd.get("cwd"), os.path.join(self.dir, "stdout.log"), os.path.join(self.dir, "stderr.log"),
                           spec["log_limit"], line_cb=on_line)
        self.phase("collecting")
        if r["start_error"]:
            exitinfo = {"app_failure": "WRAPPER_START_FAILED"}
        elif r["overflow"]:
            exitinfo = {"app_failure": "LOG_LIMIT_EXCEEDED"}
        else:
            exitinfo = {"wrapper_exit": r["rc"], "signal": r["signal"], "cancelled": r["cancelled"], "deadline": r["deadline"]}
        col = module.collect(exitinfo, out_dir, managed)
        col.update(base)
        col.update({"command": {"argv": cmd["argv"], "cwd": cmd.get("cwd"), "namespace_flag": cmd.get("namespace_flag"),
                                "env_keys": sorted(k for k in cmd["env"]), "output_dir": out_dir, "no_retry": True},
                    "supervision": {k: r.get(k) for k in ("signal", "cancelled", "deadline", "overflow", "cleanup", "start_error")}})
        ex = col.pop("execution")
        return self.finish(ex["status"], ex["reason"], col)


def main(argv):
    if len(argv) != 2:
        print("usage: worker.py JOB_DIR", file=sys.stderr)
        return 2
    Worker(argv[1]).main()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
