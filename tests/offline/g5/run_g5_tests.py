#!/usr/bin/env python3
"""TEST HARNESS for candidate G5 (verifier/g5). Not acceptance code.

For each case it builds a mutated COPY of a materialized capture, runs the G5 binary with the external anchor of the (possibly
re-anchored) capture.json, and checks the exact reason code. It also runs the gate-then-chain driver: the traced chain is invoked only
after G5 PASS; for every G5 failure the harness asserts the chain was not invoked and that its output directory was never created.

Mutations that need CBOR edits (N-P3, N-P4, N-D1 and extras) use `cbor2` and are only applied to the REQUEST envelope; every signed
object, Receipt and payload inside stays byte-identical (bstr contents are not touched). The cbor2 round trip of the unmodified request
is asserted equal to the original bytes. N-P2 flips one byte of a leaf INSIDE the raw request in place (no re-encoding).

usage: run_g5_tests.py --g5 BIN --glue spike/glue/s3_spike_chain.py --entry BIN --s2a DIR --s2b DIR --fixture DIR --work DIR --out report.json
                       [--no-chain] [--runner "unshare -n"]
Env: P10_LEAN_BIN_DIR must name the pinned Lean directory for the chain runs.
"""
import argparse, hashlib, json, os, shutil, subprocess, sys
import cbor2

HERE = os.path.dirname(os.path.abspath(__file__))
sha = lambda b: hashlib.sha256(b).hexdigest()


def rd(p): return open(p, "rb").read()


def wr(p, b):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "wb").write(b)


def load_idx(d): return json.loads(rd(os.path.join(d, "capture.json")))


def save_idx(d, idx):
    b = (json.dumps(idx, sort_keys=True, indent=1, ensure_ascii=False) + "\n").encode("utf-8")
    wr(os.path.join(d, "capture.json"), b)
    return sha(b)


def refs(node):
    if isinstance(node, dict):
        if "path" in node and "sha256" in node:
            yield node
        for v in node.values():
            yield from refs(v)
    elif isinstance(node, list):
        for v in node:
            yield from refs(v)


def ref(idx, path):
    r = [x for x in refs(idx) if x["path"] == path]
    assert len(r) == 1, path
    return r[0]


def reindex(d, idx, path):
    """Make the index agree with the (changed) file at `path`; returns the new capture.json hash (a legitimately re-anchored packaging)."""
    ref(idx, path)["sha256"] = sha(rd(os.path.join(d, path)))
    return save_idx(d, idx)


def flip(d, rel):
    p = os.path.join(d, rel)
    b = bytearray(rd(p))
    b[len(b) // 2] ^= 1
    wr(p, bytes(b))


def req_obj(d):
    raw = rd(os.path.join(d, "request.cbor"))
    obj = cbor2.loads(raw)
    assert cbor2.dumps(obj) == raw, "cbor2 round trip differs from the original request"
    return raw, obj


def req_put(d, obj):
    wr(os.path.join(d, "request.cbor"), cbor2.dumps(obj))


# ------------------------------------------------------------------------------------------ cases
# each returns (anchor) : the sha256 to hand to G5 as the external anchor of capture.json

def c_base(d): return sha(rd(os.path.join(d, "capture.json")))

def c_np1a(d):   # flipped prefix byte; index and anchor unchanged
    flip(d, "prefix/000001.cose"); return c_base(d)

def c_np1b(d):   # same, but the index is updated to the new bytes (re-anchored): only the request correspondence can catch it
    idx = load_idx(d); flip(d, "prefix/000001.cose"); return reindex(d, idx, "prefix/000001.cose")

def _flip_leaf_in_request(d):
    raw, obj = req_obj(d)
    leaf = obj[2][3][1][1]
    assert raw.count(leaf) == 1
    pos = raw.index(leaf) + len(leaf) // 2
    b = bytearray(raw); b[pos] ^= 1
    wr(os.path.join(d, "request.cbor"), bytes(b))

def c_np2a(d):   # request leaf byte flipped in place; index not updated
    _flip_leaf_in_request(d); return c_base(d)

def c_np2b(d):   # same, request hash consistently updated in a re-anchored index
    idx = load_idx(d); _flip_leaf_in_request(d); return reindex(d, idx, "request.cbor")

def c_np3(d):    # one leaf record removed from request.cbor (index re-anchored)
    idx = load_idx(d); raw, obj = req_obj(d)
    obj[2][3] = [r for r in obj[2][3] if r[0] != 2]
    req_put(d, obj); return reindex(d, idx, "request.cbor")

def c_np4(d):    # one leaf record duplicated in request.cbor (index re-anchored)
    idx = load_idx(d); raw, obj = req_obj(d)
    obj[2][3].append(list(obj[2][3][2]))
    req_put(d, obj); return reindex(d, idx, "request.cbor")

def c_np5(d):    # extra file in prefix/ that is not indexed
    wr(os.path.join(d, "prefix/000099.cose"), b"\xd2\x84\x40\xa0\xf6\x40"); return c_base(d)

def c_np6a(d):   # retained Receipt byte flipped, index unchanged
    flip(d, "receipts/000004.receipt.cbor"); return c_base(d)

def c_np6b(d):   # same, re-anchored index
    idx = load_idx(d); flip(d, "receipts/000004.receipt.cbor"); return reindex(d, idx, "receipts/000004.receipt.cbor")

def make_np7(path, source_getter, stale_anchor):
    def f(d, ctx):
        idx = load_idx(d); old_anchor = c_base(d)
        wr(os.path.join(d, path), source_getter(ctx))
        if not stale_anchor:
            return c_base(d)                       # (a) file replaced, index untouched
        new = reindex(d, idx, path)                # (b) index rewritten to match, but the external anchor is the committed one
        assert new != old_anchor
        return old_anchor
    return f

def c_xs1(d):    # submission bytes differ from the exported leaf (re-anchored)
    idx = load_idx(d); flip(d, "submissions/000001.cose"); return reindex(d, idx, "submissions/000001.cose")

def c_xs2(d):    # issuer-originated leaf without a submission
    idx = load_idx(d)
    idx["submissions"] = [s for s in idx["submissions"] if s["index"] != "3"]
    os.remove(os.path.join(d, "submissions/000003.cose")); return save_idx(d, idx)

def c_xp1(d):    # symbolic link in the capture
    os.symlink("/etc/hostname", os.path.join(d, "prefix/link.cose")); return c_base(d)

def c_xp2(d):    # path traversal in the index
    idx = load_idx(d); ref(idx, "provenance/MATERIALIZATION.json")["path"] = "../escape"; return save_idx(d, idx)

def c_xp3(d):    # REGRESSION: a root file literally named `prefix\000001.cose` beside the legitimate prefix/000001.cose.
    # The earlier inventory rewrote backslash to slash, merged the two names, never hashed the extra file and reported PASS.
    wr(os.path.join(d, "prefix\\000001.cose"), b"extra file that no hash covers"); return c_base(d)

def c_xp4(d):    # a non-UTF-8 file name in prefix/
    with open(os.path.join(os.fsencode(d), b"prefix", b"\xff.cose"), "wb") as f: f.write(b"x")
    return c_base(d)

def c_xp5(d):    # a control character in a file name
    wr(os.path.join(d, "prefix/new\nline.cose"), b"x"); return c_base(d)

def c_xi1(d):    # duplicate member name in capture.json
    p = os.path.join(d, "capture.json"); t = rd(p).decode()
    t = t.replace('"format":', '"format": "x",\n "format":', 1); wr(p, t.encode()); return c_base(d)

def c_xi2(d):    # a JSON number instead of a decimal string
    p = os.path.join(d, "capture.json"); t = rd(p).decode()
    t = t.replace('"index": "0"', '"index": 0', 1); wr(p, t.encode()); return c_base(d)

def c_xt1(d):    # request target is another leaf than the indexed target
    idx = load_idx(d); raw, obj = req_obj(d)
    obj[2][2] = obj[2][3][3][1]
    req_put(d, obj); return reindex(d, idx, "request.cbor")

def c_xr1(d):    # request carries no selected Receipt
    idx = load_idx(d); raw, obj = req_obj(d)
    obj[2][1] = None
    req_put(d, obj); return reindex(d, idx, "request.cbor")

def c_xd1(d):    # request carries a detached payload with no capture file
    idx = load_idx(d); raw, obj = req_obj(d)
    obj[2][4] = [[4, b"detached-without-file"]]
    req_put(d, obj); return reindex(d, idx, "request.cbor")

def c_xx1(d):    # request is not a valid ReplayRequestV0
    idx = load_idx(d); wr(os.path.join(d, "request.cbor"), b"\xa0"); return reindex(d, idx, "request.cbor")

def c_nd1(d):    # delivery order permuted, indices unchanged (derived request, re-anchored)
    idx = load_idx(d); raw, obj = req_obj(d)
    L = obj[2][3]; obj[2][3] = [L[i] for i in (4, 0, 3, 1, 2)]
    req_put(d, obj); return reindex(d, idx, "request.cbor")


CASES = [
    # id, mutation, expected G5 result ("PASS" or reason), run chain after a PASS?
    ("BASE", c_base, "PASS", True),
    ("N-P1a", c_np1a, "E_FILE_HASH_MISMATCH", False),
    ("N-P1b", c_np1b, "E_LEAF_BYTES_MISMATCH", False),
    ("N-P2a", c_np2a, "E_FILE_HASH_MISMATCH", False),
    ("N-P2b", c_np2b, "E_LEAF_BYTES_MISMATCH", False),
    ("N-P3", c_np3, "E_PREFIX_FILE_UNMATCHED", False),
    ("N-P4", c_np4, "E_REQUEST_LEAF_DUPLICATE", False),
    ("N-P5", c_np5, "E_FILE_NOT_INDEXED", False),
    ("N-P6a", c_np6a, "E_FILE_HASH_MISMATCH", False),
    ("N-P6b", c_np6b, "E_RECEIPT_BYTES_MISMATCH", False),
    ("N-D1", c_nd1, "PASS", True),
    ("X-S1", c_xs1, "E_SUBMISSION_MISMATCH", False),
    ("X-S2", c_xs2, "E_SUBMISSION_MISSING", False),
    ("X-P1", c_xp1, "E_PATH_UNSAFE", False),
    ("X-P2", c_xp2, "E_PATH_UNSAFE", False),
    ("X-P3", c_xp3, "E_PATH_UNSAFE", False),
    ("X-P4", c_xp4, "E_PATH_UNSAFE", False),
    ("X-P5", c_xp5, "E_PATH_UNSAFE", False),
    ("X-I1", c_xi1, "E_INDEX_MALFORMED", False),
    ("X-I2", c_xi2, "E_INDEX_MALFORMED", False),
    ("X-T1", c_xt1, "E_TARGET_BYTES_MISMATCH", False),
    ("X-R1", c_xr1, "E_RECEIPT_ABSENT", False),
    ("X-D1", c_xd1, "E_DETACHED_UNMATCHED", False),
    ("X-X1", c_xx1, "E_REQUEST_DECODE", False),
]
NP7 = [("pB", "material/pB.json"), ("inst", "material/inst.bin"), ("iB", "material/iB.json"), ("target-payload", "material/target_payload.json"), ("request", "request.cbor")]


def main():
    ap = argparse.ArgumentParser()
    for k in ("g5", "glue", "entry", "s2a", "s2b", "fixture", "work", "out"):
        ap.add_argument("--" + k, required=True)
    ap.add_argument("--no-chain", action="store_true")
    ap.add_argument("--runner", default="")
    ap.add_argument("--python", default=sys.executable)
    a = ap.parse_args()
    work = os.path.abspath(a.work)
    if os.path.exists(work) and os.listdir(work):
        sys.exit("work dir must be empty")
    os.makedirs(work, exist_ok=True)
    base = os.path.join(work, "base")
    subprocess.run([a.python, "-B", os.path.join(HERE, "materialize_capture.py"), "--fixture", a.fixture, "--out", base], check=True, capture_output=True)

    sources = {  # ratified, valid, but different objects (for N-P7 replacements)
        "material/pB.json": lambda: rd(os.path.join(a.s2b, "profile", "pB.json")),
        "material/inst.bin": lambda: rd(os.path.join(a.s2b, "profile", "inst.bin")),
        "material/iB.json": lambda: rd(os.path.join(a.s2a, "vectors", "P1", "iB.json")),
        "material/target_payload.json": lambda: rd(os.path.join(a.s2b, "vectors", "s2a-post", "BIND-A10-mismatch", "target_payload.json")),
        "request.cbor": lambda: rd(os.path.join(a.s2b, "vectors", "s2a-post", "POST-BASE-match", "request.cbor")),
    }
    cases = list(CASES)
    for name, path in NP7:
        for variant, stale in (("a", False), ("b", True)):
            exp = "E_FILE_HASH_MISMATCH" if not stale else "E_INDEX_ANCHOR_MISMATCH"
            cases.append((f"N-P7-{name}-{variant}", (lambda p=path, s=stale: (lambda d: make_np7(p, lambda ctx: sources[p](), s)(d, None)))(), exp, False))

    spawn = {"chain": 0}
    results, base_tb = [], None

    def g5(d, anchor):
        p = subprocess.run([a.g5, "--capture", d, "--index-sha256", anchor], capture_output=True, text=True)
        try:
            out = json.loads(p.stdout)
        except Exception:
            out = {"g5": "NO-OUTPUT", "stderr": p.stderr[-300:]}
        out["exit"] = p.returncode
        return out

    def chain(cid, d, res, tb_expected):
        spawn["chain"] += 1
        fx = json.load(open(os.path.join(a.fixture, "expect.json")))
        post = {"verdict": "BINDING_MATCH", "rule": None, "code": "BindingMatch", "helper_required": True}
        case = {"id": "CAP-" + cid, "request": res["request"], "pb": res["profile_artifact"], "inst": res["instance_commitment"], "ib": res["s1_instance"],
                "retained_target_payload": res["retained_target_payload"], "expect": {"s2b": fx["s2b"], "s2a": fx["s2a"], "e2e": fx["e2e"], "post": post}}
        if tb_expected:
            case["tb_expected"] = tb_expected
        cj = os.path.join(work, f"chain-{cid}.cases.json")
        json.dump([case], open(cj, "w"), indent=1)
        outd = os.path.join(work, f"chain-{cid}")
        argv = (a.runner.split() if a.runner else []) + [a.python, "-B", a.glue, "--cases", cj, "--out", outd, "--s2b", a.s2b, "--s2a", a.s2a, "--entry", a.entry]
        p = subprocess.run(argv, capture_output=True, text=True)
        rep = json.load(open(os.path.join(outd, "report.json"))) if os.path.exists(os.path.join(outd, "report.json")) else {}
        row = (rep.get("cases") or {}).get("CAP-" + cid, {})
        return {"exit": p.returncode, "pass": row.get("pass"), "checks": row.get("checks"), "out": outd, "post": row.get("post") if isinstance(row.get("post"), dict) else row.get("post")}

    for cid, mut, expected, run_chain in cases:
        d = os.path.join(work, cid)
        shutil.copytree(base, d, symlinks=True)
        anchor = mut(d)
        r = g5(d, anchor)
        got = "PASS" if r.get("g5") == "PASS" else r.get("reason", r.get("g5"))
        row = {"id": cid, "expected": expected, "actual": got, "g5_exit": r["exit"], "detail": r.get("detail"), "ok": got == expected, "chain_invoked": False}
        chain_dir = os.path.join(work, f"chain-{cid}")
        if got == "PASS" and run_chain and not a.no_chain:
            tbe = None if cid == "BASE" else base_tb
            ch = chain(cid, d, r, tbe)
            row["chain_invoked"], row["chain"] = True, {k: ch[k] for k in ("exit", "pass", "checks", "post")}
            row["ok"] = row["ok"] and ch["exit"] == 0 and ch["pass"] is True
            if cid == "BASE":
                base_tb = os.path.join(ch["out"], "cases", "CAP-BASE", "s2b", "tB.bin")
        if got != "PASS":
            # stages that MUST NOT be called after a packaging failure: S2b replay, S2a runner, closureAt helper, post-S2a
            row["chain_output_dir_exists"] = os.path.exists(chain_dir)
            row["ok"] = row["ok"] and not row["chain_invoked"] and not row["chain_output_dir_exists"] and r["exit"] == 30
        results.append(row)

    summary = {"cases": len(results), "all_ok": all(r["ok"] for r in results), "chain_invocations": spawn["chain"],
               "chain_invocations_expected": sum(1 for _, _, e, rc in CASES if rc) if not a.no_chain else 0,
               "g5_binary_sha256": sha(rd(a.g5)), "capture_base_json_sha256": sha(rd(os.path.join(base, "capture.json")))}
    json.dump({"summary": summary, "results": results}, open(a.out, "w"), indent=1)
    w = max(len(r["id"]) for r in results)
    for r in results:
        print(f"{r['id']:<{w}}  {'ok  ' if r['ok'] else 'FAIL'}  expected={r['expected']:<28} actual={r['actual']}" + (f"  chain_invoked={r['chain_invoked']}" ))
    print(json.dumps(summary))
    return 0 if summary["all_ok"] and summary["chain_invocations"] == summary["chain_invocations_expected"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
