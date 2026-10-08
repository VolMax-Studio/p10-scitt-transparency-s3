#!/usr/bin/env python3
"""CANDIDATE S3-C acceptance runner (non-normative; contract: CONTRACT.md). One command verifies one capture:

    isolation test (in this process) + preflight -> private snapshot of the capture -> G5 (anchored, on the snapshot) ->
    [only on G5 PASS, with G5-returned snapshot paths only] S2b entry -> composition -> S2a runner -> post-S2a (real closureAt)

It has no input for expected verdicts, expected tB, fixtures or producer tooling, and it reads none. Outcomes: BINDING_MATCH | REJECT | HALT | S3-FAIL(packaging) |
S3-FAIL(infrastructure); usage errors exit 2. Candidate TCB code; reuses spike code reported in CONTRACT.md; successful execution adopts nothing.

usage: s3c_verify.py --capture DIR (--anchor HEX64 | --anchor-file FILE) --out DIR --s1 DIR --s2a DIR --s2b DIR --entry BIN --g5 BIN
                     [--lean-bin-dir DIR] [--pinned FILE] [--no-offline]
"""
import argparse, hashlib, json, os, platform, re, shutil, socket, stat, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import s3c_chain as C

EXIT = {"BINDING_MATCH": 0, "REJECT": 11, "HALT": 12, "S3-FAIL(packaging)": 30, "S3-FAIL(infrastructure)": 40}
ISO_TEST = """
import socket, sys
names = [n for _, n in socket.if_nameindex()]
if any(n != 'lo' for n in names):
    sys.exit(1)
for fam, addr in ((socket.AF_INET, ('1.1.1.1', 53)), (socket.AF_INET6, ('2606:4700:4700::1111', 53))):
    try:
        s = socket.socket(fam, socket.SOCK_STREAM); s.settimeout(3); s.connect(addr)
    except OSError:
        continue
    sys.exit(1)
sys.exit(0)
"""


def isolation_here():
    """Is THIS process (the one that runs every stage; children inherit its network namespace) network-isolated? Interfaces other than loopback, or a successful external
    connection, mean no. Returns (bool, detail). Never inferred from an argument."""
    names = [n for _, n in socket.if_nameindex()]
    if any(n != "lo" for n in names):
        return False, {"interfaces": names}
    for fam, addr in ((socket.AF_INET, ("1.1.1.1", 53)), (socket.AF_INET6, ("2606:4700:4700::1111", 53))):
        try:
            s = socket.socket(fam, socket.SOCK_STREAM); s.settimeout(3); s.connect(addr); s.close()
        except OSError:
            continue
        return False, {"interfaces": names, "external_connection_succeeded": addr[0]}
    return True, {"interfaces": names}


class SnapshotError(Exception):
    def __init__(self, code, msg):
        super().__init__(msg); self.code = code


def snapshot_capture(src, dst):
    """Copy the capture into a private directory WITHOUT interpreting it: regular files byte-for-byte, directories, symlinks recreated as symlinks (not followed), FIFOs recreated
    as FIFOs; file names are handled as raw bytes so unsafe names are preserved for G5 to reject. Other special files cannot be reproduced and are refused (they could never pass G5)."""
    if out_overlaps_capture(src, dst):
        raise SnapshotError("SNAPSHOT_DESTINATION_OVERLAPS_SOURCE", f"destination {os.path.realpath(dst)} equals, lies inside or contains the source {os.path.realpath(src)}")
    s, d = os.fsencode(src), os.fsencode(dst)
    os.makedirs(d, mode=0o700)
    for root, dirs, files in os.walk(s, followlinks=False):
        rel = os.path.relpath(root, s)
        droot = d if rel == b"." else os.path.join(d, rel)
        for name in dirs + files:
            sp, dp = os.path.join(root, name), os.path.join(droot, name)
            try:
                m = os.lstat(sp).st_mode
                if stat.S_ISLNK(m):
                    os.symlink(os.readlink(sp), dp)
                elif stat.S_ISDIR(m):
                    os.mkdir(dp, 0o700)
                elif stat.S_ISREG(m):
                    with open(sp, "rb") as fi, open(dp, "xb") as fo:
                        shutil.copyfileobj(fi, fo, 1 << 20)
                    os.chmod(dp, 0o400)
                elif stat.S_ISFIFO(m):
                    os.mkfifo(dp, 0o400)
                else:
                    raise SnapshotError("SNAPSHOT_SPECIAL_FILE", f"{os.fsdecode(sp)!r} is a socket or device")
            except SnapshotError:
                raise
            except OSError as e:
                raise SnapshotError("SNAPSHOT_IO", f"{os.fsdecode(sp)!r}: {e}")


def usage(msg):
    print("usage: " + msg, file=sys.stderr)
    sys.exit(2)


def canonical(obj):
    return (json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def sh(argv, cwd=None):
    p = subprocess.run(argv, capture_output=True, text=True, cwd=cwd)
    return p.returncode, p.stdout.strip(), p.stderr.strip()


def parse_args(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--capture", required=True)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--anchor")
    g.add_argument("--anchor-file")
    ap.add_argument("--out", required=True)
    for k in ("s1", "s2a", "s2b", "entry", "g5"):
        ap.add_argument("--" + k, required=True)
    ap.add_argument("--lean-bin-dir")
    ap.add_argument("--pinned", default=os.path.join(HERE, "PINNED_INPUTS.json"))
    ap.add_argument("--no-offline", action="store_true")
    ap.add_argument("--_inner", default=None, help=argparse.SUPPRESS)   # isolation prefix chosen by the outer process
    return ap.parse_args(argv)


def read_anchor(a):
    raw = a.anchor if a.anchor is not None else None
    if raw is None:
        try:
            raw = open(a.anchor_file, encoding="utf-8").read().split()[0]
        except (OSError, IndexError) as e:
            usage(f"cannot read the anchor file: {e}")
    if not re.fullmatch(r"[0-9a-f]{64}", raw):
        usage("the anchor must be 64 lowercase hex characters (the SHA-256 of capture.json)")
    return raw


def out_overlaps_capture(capture, out):
    """True if the RESOLVED output path equals the capture, lies inside it, or contains it (symlinks resolved, also in the parents of a not-yet-existing output)."""
    c, o = os.path.realpath(capture), os.path.realpath(out)
    cp = os.path.commonpath([c, o])
    return cp == c or cp == o


def require_separate_out(capture, out):
    """Refuse an output directory that overlaps the capture, before ANY output is created (an output inside the capture would be copied into its own snapshot)."""
    if out_overlaps_capture(capture, out):
        usage(f"--out must be a directory separate from the capture: the resolved output {os.path.realpath(out)} equals, lies inside or contains the resolved capture {os.path.realpath(capture)}")


def require_empty_out(out):
    if os.path.exists(out) and (not os.path.isdir(out) or os.listdir(out)):
        usage("--out must be new or empty")


def write_outputs(out, verdict, info):
    os.makedirs(out, exist_ok=True)
    open(os.path.join(out, "verdict.json"), "wb").write(canonical(verdict))
    json.dump(info, open(os.path.join(out, "run-info.json"), "w"), indent=1, sort_keys=True, default=str)


def new_verdict(anchor):
    return {"format": C.FORMAT, "outcome": None, "stage": None, "reason": None, "anchor_sha256": anchor, "g5": {"result": "NOT RUN", "reason": None},
            "request_sha256": None, "tB_sha256": None, "s2b": None, "s2a": None, "s2a_result_lines_sha256": None, "post": None, "frozen_a12_a14": None,
            "executables_pinned": None}


def isolation_prefix():
    for cand in (["unshare", "-n"], ["unshare", "-rn"]):
        try:
            if subprocess.run(cand + ["true"], capture_output=True).returncode == 0 and subprocess.run(cand + [sys.executable, "-c", ISO_TEST], capture_output=True).returncode == 0:
                return cand
        except OSError:
            pass
    return None


def outer(a, anchor):
    out = os.path.abspath(a.out)
    require_separate_out(a.capture, out)
    require_empty_out(out)
    if a.no_offline:
        return inner(a, anchor, "none (--no-offline)")
    pre = isolation_prefix()
    if pre is None:
        v = new_verdict(anchor)
        v.update({"outcome": "S3-FAIL(infrastructure)", "stage": "preflight", "reason": {"code": "NETWORK_ISOLATION"}})
        write_outputs(out, v, {"error": "network isolation could not be established or tested ('unshare -n' / 'unshare -rn'); pass --no-offline to accept a CONNECTED run", "network_isolated": False})
        print("S3-FAIL(infrastructure): network isolation could not be established (see run-info.json)")
        return EXIT["S3-FAIL(infrastructure)"]
    argv = pre + [sys.executable, "-B", os.path.abspath(__file__)] + [x for x in sys.argv[1:]] + ["--_inner", " ".join(pre)]
    return subprocess.run(argv).returncode


def check_pins(a, pinned, info):
    """P: pins of the three checkouts, TCB source hashes, preflight. Returns None or (code, message)."""
    for key, d in (("s1", a.s1), ("s2a", a.s2a), ("s2b", a.s2b)):
        rc, head, _ = sh(["git", "-C", d, "rev-parse", "HEAD"])
        rc2, dirty, _ = sh(["git", "-C", d, "status", "--porcelain"])
        want = pinned[key]["commit"]
        if rc != 0 or head != want:
            return ("PIN_" + key.upper(), f"{key} checkout HEAD {head!r} != pinned {want}")
        if rc2 != 0 or dirty:
            return ("PIN_" + key.upper() + "_DIRTY", f"{key} checkout is not clean")
    bad = []
    for rel, want in pinned["tcb_sources"].items():
        p = os.path.join(REPO, rel)
        got = C.sha256_file(p) if os.path.exists(p) else None
        if got != want:
            bad.append(rel)
    info["tcb_source_mismatch"] = bad
    if bad:
        return ("TCB_SOURCE_HASH", "reused TCB source differs from the pinned hash: " + ", ".join(bad))
    return None


def inner(a, anchor, launcher_claim):
    """The process that runs every stage. `launcher_claim` is only the label the outer process (or a direct caller) gave: it proves nothing and is recorded as such.
    Isolation is tested HERE, in this process, whatever the argument says."""
    t0 = time.time()
    out = os.path.abspath(a.out)
    require_separate_out(a.capture, out)
    require_empty_out(out)          # every invocation path, including a direct --_inner call
    os.makedirs(out, exist_ok=True)
    log = C.Log(out)
    v = new_verdict(anchor)
    iso_ok, iso_detail = isolation_here()
    info = {"network_isolated": iso_ok, "isolation_test": iso_detail, "launcher_claim_not_evidence": launcher_claim,
            "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "host": {"platform": platform.platform(), "python": sys.version.split()[0]},
            "capture": os.path.abspath(a.capture), "runner_source_sha256": {f: C.sha256_file(os.path.join(HERE, f)) for f in ("s3c_verify.py", "s3c_chain.py")}}

    def finish(outcome, stage, reason, res=None):
        v["outcome"], v["stage"], v["reason"] = outcome, stage, reason
        if res:
            for k in ("request_sha256", "tB_sha256", "s2b", "s2a", "s2a_result_lines_sha256", "post", "frozen_a12_a14"):
                v[k] = res.get(k)
            info["chain_info"], info["problems"] = res.get("info"), res.get("infra")
        info["commands"], info["seconds"] = log.entries, round(time.time() - t0, 1)
        write_outputs(out, v, info)
        print(f"{outcome}  stage={stage}  reason={json.dumps(reason, sort_keys=True)}\n  verdict: {os.path.join(out, 'verdict.json')}")
        return EXIT[outcome]

    def infra(stage, code, msg):
        info["problems"] = [msg]
        return finish("S3-FAIL(infrastructure)", stage, {"code": code})

    if not iso_ok and not a.no_offline:
        return infra("preflight", "NETWORK_ISOLATION", f"this process is not network-isolated ({iso_detail}); stages are not run (pass --no-offline to accept a CONNECTED run)")

    # ---- P: pins, TCB hashes, preflight
    try:
        pinned = C.strict_loads(open(a.pinned, encoding="utf-8").read())
    except (OSError, ValueError) as e:
        return infra("preflight", "PINNED_INPUTS", f"pinned inputs unreadable: {e}")
    err = check_pins(a, pinned, info)
    if err:
        return infra("preflight", err[0], err[1])
    pf = [sys.executable, "-B", os.path.join(REPO, "spike", "host", "preflight.py"), "--s1", a.s1, "--s2a", a.s2a, "--s2b", a.s2b, "--out", os.path.join(out, "preflight.json")]
    if a.lean_bin_dir:
        pf += ["--lean-bin-dir", a.lean_bin_dir]
    rc, so, se = log.run(pf, "preflight")
    if rc != 0:
        return infra("preflight", "PREFLIGHT", "preflight failed: " + (so + se)[-400:])
    try:
        sel = C.strict_loads(open(os.path.join(out, "preflight.json"), encoding="utf-8").read())["selected_lean_bin_dir"]
    except (OSError, ValueError, KeyError, TypeError):
        sel = None
    if not sel:
        return infra("preflight", "NO_LEAN", "preflight selected no Lean directory")
    os.environ["P10_LEAN_BIN_DIR"] = sel
    info["lean_bin_dir"] = sel

    # ---- executables: private copies, identity checked against the pins when pinned (identity, not reproducible compilation), and the copies are what runs
    bindir = os.path.join(out, "bin"); os.makedirs(bindir)
    exe, pinned_flags = {}, {}
    for lab, src in (("entry", a.entry), ("g5", a.g5)):
        dst = os.path.join(bindir, lab)
        shutil.copyfile(src, dst); os.chmod(dst, 0o500)
        got = C.sha256_file(dst); info[lab + "_binary_sha256"] = got
        want = (pinned.get("executables") or {}).get(lab, {}).get("sha256")
        pinned_flags[lab] = want is not None
        if want is not None and want != got:
            v["executables_pinned"] = pinned_flags
            return infra("preflight", "EXECUTABLE_HASH", f"{lab} binary hash {got} differs from the pinned {want}")
        exe[lab] = dst
    v["executables_pinned"] = pinned_flags

    # ---- private snapshot of the capture: G5 and every later stage see only this copy
    snap = os.path.join(out, "snapshot")
    try:
        snapshot_capture(a.capture, snap)
    except SnapshotError as e:
        info["problems"] = [str(e)]
        if e.code == "SNAPSHOT_SPECIAL_FILE":
            return finish("S3-FAIL(packaging)", "snapshot", {"code": e.code})
        return finish("S3-FAIL(infrastructure)", "snapshot", {"code": e.code})
    except OSError as e:
        return infra("snapshot", "SNAPSHOT_IO", str(e))

    # ---- G5 on the snapshot (nothing else may run before it passes)
    rc, so, se = log.run([exe["g5"], "--capture", snap, "--index-sha256", anchor], "g5")
    try:
        g = C.strict_loads(so)
        assert isinstance(g, dict)
    except (ValueError, AssertionError):
        return infra("g5", "G5_OUTPUT", f"G5 output is not one strict JSON object (exit {rc}): {so[:200]} {se[:200]}")
    info["g5_output"] = g
    if rc == 30 and g.get("g5") == "FAIL" and isinstance(g.get("reason"), str):
        v["g5"] = {"result": "FAIL", "reason": g["reason"]}
        info["problems"] = [str(g.get("detail"))]
        return finish("S3-FAIL(packaging)", "g5", {"code": g["reason"]})
    if rc != 0 or g.get("g5") != "PASS":
        return infra("g5", "G5_EXIT", f"G5 exit {rc} with result {g.get('g5')!r}")
    if g.get("anchor_checked") is not True:
        return infra("g5", "G5_UNANCHORED", "G5 PASS without anchor_checked=true is not an anchored capture")
    v["g5"] = {"result": "PASS", "reason": None}
    root = os.path.realpath(g["root"]) if isinstance(g.get("root"), str) else None
    if root != os.path.realpath(snap):
        return infra("g5", "G5_ROOT", "G5 checked a different root than the private snapshot")
    paths = {}
    for k in ("request", "profile_artifact", "instance_commitment", "s1_instance", "retained_target_payload"):
        val = g.get(k)
        if val is None:
            if k == "retained_target_payload":
                paths[k] = None
                continue
            return infra("g5", "G5_MISSING_PATH", f"G5 result has no {k}")
        rp = os.path.realpath(val) if isinstance(val, str) else ""
        if not rp or os.path.commonpath([root, rp]) != root or not os.path.isfile(rp):
            return infra("g5", "G5_PATH_OUTSIDE", f"G5-returned path {val} is not a file under the checked snapshot")
        paths[k] = rp

    # ---- chain, from G5-returned snapshot paths only
    inp = C.ChainInputs(paths["request"], paths["profile_artifact"], paths["instance_commitment"], paths["s1_instance"], paths["retained_target_payload"])
    res = C.run_chain(inp, out, a.s2b, a.s2a, exe["entry"], log)
    info["input_sha256"] = {k: C.sha256_file(p) for k, p in paths.items() if p}
    return finish(res["outcome"], res["stage"], res["reason"], res)


def main(argv=None):
    a = parse_args(argv if argv is not None else sys.argv[1:])
    anchor = read_anchor(a)
    for k in ("capture", "s1", "s2a", "s2b"):
        if not os.path.isdir(getattr(a, k)):
            usage(f"--{k} is not a directory")
    for k in ("entry", "g5"):
        if not os.path.isfile(getattr(a, k)):
            usage(f"--{k} is not a file")
    require_separate_out(a.capture, a.out)        # every invocation path (outer, direct --_inner, --no-offline) passes through here, before anything is written
    if a._inner is not None:
        return inner(a, anchor, a._inner)
    return outer(a, anchor)


if __name__ == "__main__":
    raise SystemExit(main())
