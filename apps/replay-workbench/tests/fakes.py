"""Injected test dependencies: synthetic archives/records/profile, a scripted command context and a stub module.

Everything here is synthetic. A StubModule run is a SYNTHETIC TEST RUN, never an offline P10 run.
"""
import copy
import hashlib
import io
import json
import os
import stat
import sys
import tarfile

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, APP)
from workbench.modules.s3 import S3Module  # noqa: E402
from workbench.worker import RunResult  # noqa: E402

sha = lambda b: hashlib.sha256(b).hexdigest()
with open(os.path.join(APP, "profiles", "s3-accepted-rev2.json")) as _f:
    SHIPPED = json.load(_f)
REPO_PIN = "e56d3ea8bbe14c9c88a0dde339c29b55b1032a66"


def dumps(o):
    return (json.dumps(o, indent=1, sort_keys=True) + "\n").encode()


def good_verdict(**over):
    v = {"format": "synthetic", "outcome": "BINDING_MATCH", "stage": "post-s2a", "reason": {"code": "BindingMatch", "rule": None},
         "executables_pinned": {"entry": True, "g5": True}, "post": {"rows": {"A1": "match", "A2": "match"}}}
    v.update(over)
    return v


def good_info(**over):
    i = {"network_isolated": True, "problems": [], "tcb_source_mismatch": [], "runner_source_sha256": dict(SHIPPED["runner_source_sha256"]),
         "entry_binary_sha256": SHIPPED["entry_binary_sha256"], "g5_binary_sha256": SHIPPED["g5_binary_sha256"]}
    i.update(over)
    return i


VERDICT_BYTES = dumps(good_verdict())


def test_profile(verdict_bytes=VERDICT_BYTES, archive_sha="0" * 64, **limits):
    p = copy.deepcopy(SHIPPED)
    p["archive"]["sha256"] = archive_sha
    p["accepted_verdict_sha256"] = sha(verdict_bytes)
    p["references"] = ["repo/ref/runner/verdict.json", "repo/ref/runner-2/verdict.json"]
    p["limits"].update(limits)
    return p


def make_tar(path, members, root="p10-s3-offline"):
    """members: list of (name, kind, data/target, mode); kinds: dir, file, sym, hard, fifo."""
    with tarfile.open(path, "w:gz") as tf:
        for name, kind, data, mode in members:
            ti = tarfile.TarInfo(name)
            ti.mtime = 1700000000
            ti.mode = mode
            if kind == "dir":
                ti.type = tarfile.DIRTYPE
                tf.addfile(ti)
            elif kind == "file":
                ti.size = len(data)
                tf.addfile(ti, io.BytesIO(data))
            elif kind == "sym":
                ti.type, ti.linkname = tarfile.SYMTYPE, data
                tf.addfile(ti)
            elif kind == "hard":
                ti.type, ti.linkname = tarfile.LNKTYPE, data
                tf.addfile(ti)
            elif kind == "fifo":
                ti.type = tarfile.FIFOTYPE
                tf.addfile(ti)
    return path


def good_members():
    return [("p10-s3-offline", "dir", None, 0o755), ("p10-s3-offline/verify_offline.sh", "file", b"#!/bin/bash\nexit 0\n", 0o755),
            ("p10-s3-offline/data", "dir", None, 0o755), ("p10-s3-offline/data/a.txt", "file", b"hello\n", 0o4644)]


class ScriptedCtx:
    """Stands in for the worker's ctx: records every command and answers from a handler(argv, cwd) -> RunResult|None."""

    def __init__(self, tmp, handler=None):
        self.tmpdir = tmp
        self.workspace = tmp
        self.calls = []
        self.handler = handler

    def run(self, argv, env=None, cwd=None, timeout=120):
        self.calls.append({"argv": list(argv), "env": env, "cwd": cwd})
        r = self.handler(argv, cwd) if self.handler else None
        return r if r is not None else RunResult(0, "", "")

    def emit(self, *a):
        pass


def build_package(managed, profile, lean_bin):
    """Create a synthetic managed package satisfying the file-level readiness checks of `profile`."""
    root = os.path.join(managed, profile["archive"]["root"])
    def w(rel, data, mode=0o644):
        p = os.path.join(root, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(data)
        os.chmod(p, mode)
    wrap = b"#!/bin/bash\n# synthetic wrapper\n"
    profile["wrapper"]["sha256"] = sha(wrap)
    w(profile["wrapper"]["path"], wrap, 0o755)
    for rel in list(profile["files"]):
        data = ("synthetic " + rel).encode()
        profile["files"][rel] = sha(data)
        w(rel, data)
    w(profile["anchor_file"], (profile["anchor_sha256"] + "\n").encode())
    for rel in profile["references"]:
        w(rel, VERDICT_BYTES)
    w("PACKAGE_SHA256SUMS", b"0" * 64 + b"  x\n")
    w("repo/deployment/candidate/freeze-set.sha256", b"0" * 64 + b"  y\n" + b"1" * 64 + b"  z\n")
    for d in ("repo/spike/s3-entry", "deps/s1", "deps/s2a", "deps/s2b"):
        os.makedirs(os.path.join(root, *d.split("/")), exist_ok=True)
    os.makedirs(lean_bin, exist_ok=True)
    for t in ("lean", "lake"):
        with open(os.path.join(lean_bin, t), "w") as f:
            f.write("#!/bin/sh\n")
        os.chmod(os.path.join(lean_bin, t), 0o755)
    return root


def good_handler(profile, sum_rc=0, sum_out="", sig_ok=True):
    deps = {"s1": profile["dependencies"]["s1"], "s2a": profile["dependencies"]["s2a"], "s2b": profile["dependencies"]["s2b"]}

    def h(argv, cwd):
        a = argv
        if a[0] == "rustc":
            return RunResult(0, "rustc 1.82.0 (f6e511eec 2024-10-15)\n", "")
        if a[0] == "sha256sum":
            return RunResult(sum_rc, sum_out, "")
        if a[0] == "git":
            rest = [x for x in a[1:]]
            if "verify-tag" in rest:
                return RunResult(0 if sig_ok else 1, "", "" if sig_ok else "bad signature")
            if rest[:2] == ["rev-parse", "HEAD"]:
                d = os.path.basename(cwd.rstrip("/"))
                return RunResult(0, (deps.get(d) or profile["s3_package_head"]) + "\n", "")
            if rest[:1] == ["status"]:
                return RunResult(0, "", "")
            if rest[:1] == ["cat-file"]:
                return RunResult(0, "object x\n-----BEGIN SSH SIGNATURE-----\n", "")
            if rest[:1] == ["rev-parse"]:
                name = rest[1]
                tag = name.split("^")[0]
                t = profile["tags"][tag]
                return RunResult(0, (t["target"] if name.endswith("^{commit}") else t["object"]) + "\n", "")
        if a[0] == "unshare" and "preflight.py" in " ".join(a):
            out = a[a.index("--out") + 1]
            with open(out, "w") as f:
                json.dump({"selected_lean_bin_dir": "x", "checks": [{"id": "c1", "ok": True, "required": True, "detail": "ok"}]}, f)
            return RunResult(0, "", "")
        return RunResult(0, "", "")
    return h


def wrapper_script(exit_code=0, verdict=None, info=None, body="", out_name="verdict.json"):
    """Bash text for a stub wrapper: $1 is the fresh output directory."""
    lines = ["#!/bin/bash", 'OUT="$1"', 'mkdir -p "$OUT"', "echo '== 1. host prerequisites (stub)'"]
    if verdict is not None:
        lines.append("cat > \"$OUT/verdict.json\" <<'__V__'\n" + (verdict.decode() if isinstance(verdict, bytes) else verdict) + "__V__")
    if info is not None:
        lines.append("cat > \"$OUT/run-info.json\" <<'__I__'\n" + (info.decode() if isinstance(info, bytes) else info) + "__I__")
    lines += [body, f"exit {exit_code}"]
    return "\n".join(lines) + "\n"


class StubModule(S3Module):
    """Synthetic module: readiness answers and wrapper script come from stub_config.json; collect() is the real mapping logic."""

    def __init__(self, cfg):
        super().__init__(cfg["profile"], synthetic=cfg.get("synthetic", True))
        self.cfg = cfg

    def inspect(self, managed_dir, host_config, ctx):
        return self.cfg["readiness"]

    def command(self, managed_dir, host_config, fresh_output, ctx):
        assert not os.path.exists(fresh_output)
        sab = self.cfg.get("sabotage") or {}      # test-only fault injection into the job directory (a stub cannot be selected in production)
        d = ctx.dir
        if sab.get("stdout_dir"):
            os.mkdir(os.path.join(d, "stdout.log"))
        if sab.get("stdout_devfull"):
            os.symlink("/dev/full", os.path.join(d, "stdout.log"))
        if sab.get("report_dir"):
            os.mkdir(os.path.join(d, "app-report.json"))
        if sab.get("profile_fifo"):         # finalization blocks at the first write of profile.json until a test opens the FIFO for reading
            os.mkfifo(os.path.join(d, "profile.json"))
        if sab.get("status_dir"):
            os.remove(os.path.join(d, "status.json"))
            os.mkdir(os.path.join(d, "status.json"))
        return {"argv": ["bash", self.cfg["script"], fresh_output], "env": {"PATH": "/usr/bin:/bin"}, "cwd": managed_dir, "namespace_flag": None, "output_dir": fresh_output}


def make_module():
    for p in sys.path:
        f = os.path.join(p, "stub_config.json")
        if os.path.isfile(f):
            return StubModule(json.load(open(f)))
    raise RuntimeError("stub_config.json not found on sys.path")
