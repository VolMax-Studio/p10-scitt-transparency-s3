#!/usr/bin/env python3
"""CANDIDATE S3-C acceptance runner (non-normative; contract: CONTRACT.md). One command verifies one capture:

    preflight + isolation -> G5 (anchored) -> [only on G5 PASS, with G5-returned paths only] S2b entry -> composition -> S2a runner -> post-S2a (real closureAt)

It has no input for expected verdicts, expected tB, fixtures or producer tooling, and it reads none. Outcomes: BINDING_MATCH | REJECT | HALT | S3-FAIL(packaging) |
S3-FAIL(infrastructure); usage errors exit 2. Candidate TCB code; reuses spike code reported in CONTRACT.md; successful execution adopts nothing.

usage: s3c_verify.py --capture DIR (--anchor HEX64 | --anchor-file FILE) --out DIR --s1 DIR --s2a DIR --s2b DIR --entry BIN --g5 BIN
                     [--lean-bin-dir DIR] [--pinned FILE] [--no-offline]
"""
import argparse, hashlib, json, os, platform, re, shutil, subprocess, sys, time

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


def write_outputs(out, verdict, info):
    os.makedirs(out, exist_ok=True)
    open(os.path.join(out, "verdict.json"), "wb").write(canonical(verdict))
    json.dump(info, open(os.path.join(out, "run-info.json"), "w"), indent=1, sort_keys=True, default=str)


def new_verdict(anchor):
    return {"format": C.FORMAT, "outcome": None, "stage": None, "reason": None, "anchor_sha256": anchor, "g5": {"result": "NOT RUN", "reason": None},
            "request_sha256": None, "tB_sha256": None, "s2b": None, "s2a": None, "s2a_result_lines_sha256": None, "post": None, "frozen_a12_a14": None}


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
    if os.path.exists(out) and os.listdir(out):
        usage("--out must be new or empty")
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


def inner(a, anchor, isolation):
    t0 = time.time()
    out = os.path.abspath(a.out)
    os.makedirs(out, exist_ok=True)
    log = C.Log(out)
    v = new_verdict(anchor)
    info = {"network_isolated": not a.no_offline and isolation != "none (--no-offline)", "isolation": isolation, "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "host": {"platform": platform.platform(), "python": sys.version.split()[0]}, "capture": os.path.abspath(a.capture),
            "runner_source_sha256": {f: C.sha256_file(os.path.join(HERE, f)) for f in ("s3c_verify.py", "s3c_chain.py")}}

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

    # ---- P: pins, TCB hashes, preflight
    try:
        pinned = json.load(open(a.pinned, encoding="utf-8"))
    except (OSError, ValueError) as e:
        info["problems"] = [f"pinned inputs unreadable: {e}"]
        return finish("S3-FAIL(infrastructure)", "preflight", {"code": "PINNED_INPUTS"})
    err = check_pins(a, pinned, info)
    if err:
        info["problems"] = [err[1]]
        return finish("S3-FAIL(infrastructure)", "preflight", {"code": err[0]})
    pf = [sys.executable, "-B", os.path.join(REPO, "spike", "host", "preflight.py"), "--s1", a.s1, "--s2a", a.s2a, "--s2b", a.s2b, "--out", os.path.join(out, "preflight.json")]
    if a.lean_bin_dir:
        pf += ["--lean-bin-dir", a.lean_bin_dir]
    rc, so, se = log.run(pf, "preflight")
    if rc != 0:
        info["problems"] = ["preflight failed: " + (so + se)[-400:]]
        return finish("S3-FAIL(infrastructure)", "preflight", {"code": "PREFLIGHT"})
    try:
        sel = json.load(open(os.path.join(out, "preflight.json")))["selected_lean_bin_dir"]
    except (OSError, ValueError, KeyError):
        sel = None
    if not sel:
        info["problems"] = ["preflight selected no Lean directory"]
        return finish("S3-FAIL(infrastructure)", "preflight", {"code": "NO_LEAN"})
    os.environ["P10_LEAN_BIN_DIR"] = sel
    info["lean_bin_dir"] = sel
    for lab, p in (("entry", a.entry), ("g5", a.g5)):
        info[lab + "_binary_sha256"] = C.sha256_file(p) if os.path.exists(p) else None

    # ---- G5 (nothing else may run before it passes)
    rc, so, se = log.run([a.g5, "--capture", a.capture, "--index-sha256", anchor], "g5")
    try:
        g = json.loads(so)
        assert isinstance(g, dict)
    except (ValueError, AssertionError):
        info["problems"] = [f"G5 output is not one JSON object (exit {rc}): {so[:200]} {se[:200]}"]
        return finish("S3-FAIL(infrastructure)", "g5", {"code": "G5_OUTPUT"})
    info["g5_output"] = g
    if rc == 30 and g.get("g5") == "FAIL" and isinstance(g.get("reason"), str):
        v["g5"] = {"result": "FAIL", "reason": g["reason"]}
        info["problems"] = [str(g.get("detail"))]
        return finish("S3-FAIL(packaging)", "g5", {"code": g["reason"]})
    if rc != 0 or g.get("g5") != "PASS":
        info["problems"] = [f"G5 exit {rc} with result {g.get('g5')!r}"]
        return finish("S3-FAIL(infrastructure)", "g5", {"code": "G5_EXIT"})
    if g.get("anchor_checked") is not True:
        info["problems"] = ["G5 PASS without anchor_checked=true is not an anchored capture"]
        return finish("S3-FAIL(infrastructure)", "g5", {"code": "G5_UNANCHORED"})
    v["g5"] = {"result": "PASS", "reason": None}
    root = os.path.realpath(g["root"])
    if root != os.path.realpath(a.capture):
        info["problems"] = ["G5 checked a different root than --capture"]
        return finish("S3-FAIL(infrastructure)", "g5", {"code": "G5_ROOT"})
    paths = {}
    for k in ("request", "profile_artifact", "instance_commitment", "s1_instance", "retained_target_payload"):
        val = g.get(k)
        if val is None:
            if k == "retained_target_payload":
                paths[k] = None
                continue
            info["problems"] = [f"G5 result has no {k}"]
            return finish("S3-FAIL(infrastructure)", "g5", {"code": "G5_MISSING_PATH"})
        rp = os.path.realpath(val)
        if os.path.commonpath([root, rp]) != root or not os.path.isfile(rp):
            info["problems"] = [f"G5-returned path {val} is not a file under the checked capture root"]
            return finish("S3-FAIL(infrastructure)", "g5", {"code": "G5_PATH_OUTSIDE"})
        paths[k] = rp

    # ---- chain, from G5-returned paths only
    inp = C.ChainInputs(paths["request"], paths["profile_artifact"], paths["instance_commitment"], paths["s1_instance"], paths["retained_target_payload"])
    res = C.run_chain(inp, out, a.s2b, a.s2a, a.entry, log)
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
    if a._inner is not None:
        return inner(a, anchor, a._inner)
    return outer(a, anchor)


if __name__ == "__main__":
    raise SystemExit(main())
