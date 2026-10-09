"""Small shared helpers: atomic writes, exclusive result claim, process-identity guards, result downgrade."""
import fcntl
import json
import os
import secrets
import signal


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
    """Publish result.json exactly once. Returns True if this caller won; False if a result already exists (never overwrites)."""
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


def try_lock(path):
    """Non-blocking exclusive flock; returns an open fd or None if somebody else holds it."""
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        return None
    return fd


def proc_start_ticks(pid):
    try:
        with open(f"/proc/{pid}/stat") as f:
            return int(f.read().rsplit(")", 1)[1].split()[19])
    except (OSError, ValueError, IndexError):
        return None


def proc_alive(pid):
    """True if the process exists and is not a zombie."""
    try:
        with open(f"/proc/{pid}/stat") as f:
            return f.read().rsplit(")", 1)[1].split()[0] != "Z"
    except (OSError, IndexError):
        return False


def is_worker_process(pid, ticks, job_dir):
    """Identity guard before signalling a recorded worker: same start time AND a worker.py command line naming this job directory."""
    if not pid or ticks is None or proc_start_ticks(pid) != ticks or not proc_alive(pid):
        return False
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            args = f.read().split(b"\0")
    except OSError:
        return False
    return any(a.endswith(b"worker.py") for a in args) and os.fsencode(job_dir) in args


def group_leader_ok(pgid, ticks):
    """Identity guard before signalling a recorded process group: its leader must still be the process we recorded."""
    return bool(pgid) and ticks is not None and proc_start_ticks(pgid) == ticks and proc_alive(pgid)


def kill_group_guarded(pgid, ticks, sig):
    if group_leader_ok(pgid, ticks):
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
