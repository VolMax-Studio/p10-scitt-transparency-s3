"""Small shared helpers: atomic writes, exclusive result claim, process-identity guards, result downgrade."""
import fcntl
import json
import os
import secrets
import signal
import time


def write_json_atomic(path, obj):
    tmp = f"{path}.tmp{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1, sort_keys=True)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def claim_result(job_dir, res):
    """Low-level primitive: the CALLER MUST HOLD the seal lock (publish_result and Worker.publish do). Publish result.json exactly once. Returns True if this caller won; False if a result already exists (never overwrites)."""
    final = os.path.join(job_dir, "result.json")
    tmp = os.path.join(job_dir, f".result.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(res, f, indent=1, sort_keys=True)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    try:
        os.link(tmp, final)
        return True
    except FileExistsError:
        return False
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


class SealLock:
    """Per-job synchronization point between final-result publication (worker or supervisor) and interruption registration.

    Whoever holds the lock decides: interruption registration checks for a published result and writes interrupt.json only under it;
    the worker reads interrupt.json, writes the final report and publishes result.json only under it. A process that dies releases it.
    `timeout=None` blocks; otherwise the lock is tried for that many seconds and `held` tells whether it was obtained.
    """

    def __init__(self, job_dir, timeout=None):
        self.path, self.timeout, self.fd, self.held = os.path.join(job_dir, "seal.lock"), timeout, None, False

    def __enter__(self):
        self.fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        if self.timeout is None:
            fcntl.flock(self.fd, fcntl.LOCK_EX)
            self.held = True
            return self
        end = time.monotonic() + self.timeout
        while True:
            try:
                fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.held = True
                break
            except BlockingIOError:
                if time.monotonic() >= end:
                    break
                time.sleep(0.02)
        return self

    def __exit__(self, *exc):
        os.close(self.fd)       # closing releases the flock
        return False


def register_interrupt(job_dir, reason, timeout=None):
    """Record that the application is interrupting this job. The marker is written ONLY while holding the seal lock. Returns:
    'registered'  the lock was held, no result existed, interrupt.json now exists;
    'too_late'    a result was already published: the job finished first and its result stands (nothing is written);
    'timeout'     the lock could not be obtained in time (its holder is slow or unresponsive): nothing was written, nothing is decided.
                  The caller must not retry blindly; it may stop a verified owner and call again (see JobManager._interrupt)."""
    if os.path.exists(os.path.join(job_dir, "result.json")):
        return "too_late"                       # a committed result is final; existence is monotonic so no lock is needed to read it
    with SealLock(job_dir, timeout) as lk:
        if not lk.held:
            return "timeout"
        if os.path.exists(os.path.join(job_dir, "result.json")):
            return "too_late"
        final = os.path.join(job_dir, "interrupt.json")
        tmp = f"{final}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:                 # complete content or nothing: readers never see a partial marker
            json.dump({"reason": reason, "by_pid": os.getpid()}, f)
            f.flush()
            os.fsync(f.fileno())
        try:
            os.link(tmp, final)
        except FileExistsError:
            pass
        finally:
            os.unlink(tmp)
        return "registered"


def publish_result(job_dir, res, timeout=None):
    """Publish result.json (supervisor side) ONLY while holding the seal lock. Returns True if this call published it, False if a result
    already existed (the committed result stands), None if the lock could not be obtained in time (nothing was published)."""
    if os.path.exists(os.path.join(job_dir, "result.json")):
        return False
    with SealLock(job_dir, timeout) as lk:
        if not lk.held:
            return None
        return claim_result(job_dir, res)


def try_lock(path):
    """Non-blocking exclusive flock; returns an open fd or None if somebody else holds it."""
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        return None
    return fd


PROC_ENABLED = True      # tests switch this off to emulate a host without a usable /proc


def proc_start_ticks(pid):
    if not PROC_ENABLED:
        return None
    try:
        with open(f"/proc/{pid}/stat") as f:
            return int(f.read().rsplit(")", 1)[1].split()[19])
    except (OSError, ValueError, IndexError):
        return None


def proc_identity_available():
    """True when process start times can be read (/proc). Identity checks then use them in addition to the lock-based checks."""
    return proc_start_ticks(os.getpid()) is not None


def proc_alive(pid):
    """True if the process exists and is not a zombie (a zombie is only distinguishable when /proc is readable)."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    if not PROC_ENABLED:
        return True
    try:
        with open(f"/proc/{pid}/stat") as f:
            return f.read().rsplit(")", 1)[1].split()[0] != "Z"
    except (OSError, IndexError):
        return True            # cannot tell: exists as far as signalling is concerned


def lock_held(path):
    """True if another open file description currently holds the exclusive flock on `path` (the holder died => released)."""
    if not os.path.exists(path):
        return False
    fd = try_lock(path)
    if fd is None:
        return True
    os.close(fd)
    return False


def worker_lock_path(job_dir):
    return os.path.join(job_dir, "worker.lock")


def child_lock_path(job_dir):
    return os.path.join(job_dir, "child.lock")


def is_worker_process(pid, ticks, job_dir):
    """Identity guard before signalling a recorded worker.

    The worker holds worker.lock for its whole life, so "the lock is held" means a worker of THIS job is alive and PID reuse cannot fake it
    (needs no /proc). When /proc is readable the recorded start time and the worker.py command line naming this job directory must match as well.
    """
    if not pid or not lock_held(worker_lock_path(job_dir)) or not proc_alive(pid):
        return False
    if not proc_identity_available():
        return True
    if ticks is None or proc_start_ticks(pid) != ticks:
        return False
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            args = f.read().split(b"\0")
    except OSError:
        return False
    return any(a.endswith(b"worker.py") for a in args) and os.fsencode(job_dir) in args


def group_signal_ok(job_dir, pgid, ticks):
    """Identity guard before signalling a recorded process group. Safe if (a) child.lock is still held: the supervised command passes it
    to its whole group, so some member lives and the group id cannot have been reused; or (b) /proc shows the recorded leader unchanged."""
    if not pgid:
        return False
    if lock_held(child_lock_path(job_dir)):
        return True
    return ticks is not None and proc_start_ticks(pgid) == ticks and proc_alive(pgid)


def group_has_live_members(job_dir, pgid, use_lock=True):
    """True while a non-zombie member of process group `pgid` exists. A zombie (e.g. reparented to a PID 1 that never reaps, as in some
    containers) is not a live member. Order: child.lock (released when every holder has exited), then a /proc scan, then a signal probe."""
    if use_lock and lock_held(child_lock_path(job_dir)):
        return True
    if proc_identity_available():
        try:
            names = os.listdir("/proc")
        except OSError:
            names = []
        for n in names:
            if n.isdigit():
                try:
                    with open(f"/proc/{n}/stat") as f:
                        rest = f.read().rsplit(")", 1)[1].split()
                except (OSError, IndexError):
                    continue
                if rest[0] != "Z" and rest[2] == str(pgid):
                    return True
        return False
    if use_lock:
        return False               # no /proc, lock released: every process that held it has exited
    try:
        os.killpg(pgid, 0)
        return True
    except OSError:
        return False


def kill_group_guarded(job_dir, pgid, ticks, sig):
    if group_signal_ok(job_dir, pgid, ticks):
        try:
            os.killpg(pgid, sig)
            return True
        except OSError:
            return False
    return False


TERM, KILL = signal.SIGTERM, signal.SIGKILL


def downgrade(res, status, reason, note):
    """Return a copy of a result converted to an application failure: no success badge, nothing promoted, original observation kept aside."""
    old_p10, old_rp = res.get("p10") or {}, res.get("reproduction") or {}
    out = dict(res)
    out["execution"] = {"status": status, "reason": reason}
    out["p10"] = {"state": "NOT_EVALUATED", "outcome": None, "stage": None, "reason": None, "rows": None,
                  "record_problems": old_p10.get("record_problems"), "note": "not promoted: " + note}
    out["reproduction"] = {"status": "NOT_EVALUATED", "badge": False, "checks": [], "reasons": [note]}
    out["downgraded_from"] = {"execution": res.get("execution"), "p10_state": old_p10.get("state"),
                              "reproduction_status": old_rp.get("status"), "note": "observations before the failure; not a result"}
    return out
