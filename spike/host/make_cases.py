#!/usr/bin/env python3
"""NON-NORMATIVE FEASIBILITY SPIKE. Builds cases.json for s3_spike_chain.py.

Control cases reuse the ratified S2b fixtures UNCHANGED, with their own bound inputs:
  * s2a-post/*  : request.cbor, iB.json, target_payload.json (retained file), tB.expected (comparison only); pB/inst from S2b profile/
  * s2a-t11/*   : request.cbor, pB.json, inst.bin, tB.expected (comparison only)
  * E/*, M/*    : request.cbor only (S2b-level stop paths; no S2a stage)
Expectations are read from each fixture's own expected.json; the composed outcome for S2b-level controls is the frozen S2b prereg r7 s16.6
table (Invalid(binding) -> REJECT; Invalid(replay|request) and Unavailable -> HALT).

usage: make_cases.py --s2b DIR --fixtures DIR --out cases.json
"""
import argparse, json, os, sys

# (control id, vector dir relative to S2b vectors/)
CONTROLS = [
    ("C-ACC", "s2a-post/POST-BASE-match"),
    ("C-POST-REJ", "s2a-post/BIND-A10-mismatch"),
    ("C-POST-HALT", "s2a-post/T13-T5-closureAt-none"),
    ("C-S2A-REJ", "s2a-t11/N13b"),
    ("C-S2A-HALT", "s2a-t11/N7a"),
    ("C-S2B-REJ", "E/E10-unprotected"),
    ("C-S2B-HALT", "M/M1"),
    ("C-S2B-UNAV", "M/M8"),
]


def with_code(post):
    """Add the exact post-S2a code, detail and helper requirement to an expectation {verdict, rule}.
    SOURCE: spike annotation derived by inspection of orchestration/post_s2a.py (codes and the T5 detail text), NOT read from the ratified
    vectors' expected.json, which record only verdict and rule. A result that merely has the same verdict and rule but a different code
    (for example HALT/T5 with code ClosureAtUnavailable) must not satisfy a control."""
    if post is None:
        return None
    post = dict(post)
    v, r = post["verdict"], post.get("rule")
    if "code" not in post:
        if v == "BINDING_MATCH":
            post["code"] = "BindingMatch"
        elif v == "REJECT":
            post["code"] = "BindingMismatch"
        elif v == "HALT" and r and r.startswith("T"):
            post["code"] = "TargetAdjudicationNotEstablished"
        elif v == "HALT" and r and r.startswith("A"):
            post["code"] = "BindingMaterialUnavailable"
    if v == "HALT" and r == "T5":
        post.setdefault("detail_contains", "closureAt returned none")
    post.setdefault("helper_required", not (v == "HALT" and r in ("T1", "T2", "T3", "T4", "T6")))
    if v == "BINDING_MATCH":
        post.setdefault("rows_all_match", True)
    return post


def inventory(dirpath, extra=()):
    names = ["request.cbor", "pB.json", "inst.bin", "iB.json", "target_payload.json", "tB.expected", "expected.json"] + list(extra)
    return {n: os.path.exists(os.path.join(dirpath, n)) for n in names}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--s2b", required=True)
    ap.add_argument("--fixtures", help="optional directory of direct spike fixtures; NOT used by the host runner (the capture path uses G5-returned paths)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    V = os.path.join(a.s2b, "vectors")
    prof = os.path.join(a.s2b, "profile")
    cases, inv = [], {}
    for cid, rel in CONTROLS:
        d = os.path.join(V, rel)
        ex = json.load(open(os.path.join(d, "expected.json")))
        have = inventory(d)
        inv[cid] = {"dir": rel, "files": have}
        c = {"id": cid, "request": os.path.join(d, "request.cbor"), "source": rel}
        fam = rel.split("/")[0]
        e = {}
        if fam in ("E", "M"):
            if not os.path.exists(c["request"]):
                # E/M vectors keep the request under request.cbor as well
                raise SystemExit(f"{rel}: no request.cbor")
            x = ex["expected"]
            e["s2b"] = {k: x[k] for k in ("status", "class", "reason") if k in x}
            e["composed_after_s2b"] = "REJECT" if x.get("class") == "binding" else "HALT"
        else:
            e["s2b"] = {"status": "Verified"}
            if os.path.exists(os.path.join(d, "tB.expected")):
                c["tb_expected"] = os.path.join(d, "tB.expected")
            if fam == "s2a-post":
                c["pb"], c["inst"] = os.path.join(prof, "pB.json"), os.path.join(prof, "inst.bin")
                c["ib"] = os.path.join(d, "iB.json")
                c["retained_target_payload"] = os.path.join(d, "target_payload.json")
                e["s2a"] = ".accept" if ex["s2a_precondition"] == "accept" else None
                e["e2e"] = ex.get("s1_end_to_end_expected")
                e["post"] = with_code(ex["post_s2a_expected"])
            else:   # s2a-t11
                c["pb"], c["inst"] = os.path.join(d, "pB.json"), os.path.join(d, "inst.bin")
                if have["iB.json"]:
                    c["ib"] = os.path.join(d, "iB.json")
                e["s2a"] = ex["s2a_expected_outcome"]
        c["expect"] = e
        cases.append(c)
    # volmax-owner fixtures (public material only), if present
    fx = a.fixtures
    if fx and os.path.isdir(fx):
        for name in sorted(os.listdir(fx)):
            d = os.path.join(fx, name)
            if not os.path.exists(os.path.join(d, "request.cbor")):
                continue
            ex = json.load(open(os.path.join(d, "expect.json")))
            ex["post"] = with_code(ex.get("post"))
            c = {"id": "FX-" + name, "request": os.path.join(d, "request.cbor"), "source": "spike/fixtures/" + name,
                 "pb": os.path.join(d, "pB.json"), "inst": os.path.join(d, "inst.bin"), "ib": os.path.join(d, "iB.json"),
                 "retained_target_payload": os.path.join(d, "target_payload.json"), "tb_expected": os.path.join(d, "tB.expected"), "expect": ex}
            cases.append(c)
            inv["FX-" + name] = {"dir": "spike/fixtures/" + name, "files": inventory(d, ("expect.json",))}
    json.dump(cases, open(a.out, "w"), indent=1)
    json.dump(inv, open(os.path.splitext(a.out)[0] + ".inventory.json", "w"), indent=1, sort_keys=True)
    print(f"{len(cases)} cases -> {a.out}")
    for cid, v in inv.items():
        miss = [k for k, ok in v["files"].items() if not ok]
        print(f"  {cid:<12} {v['dir']:<34} missing: {','.join(miss) or '-'}")


if __name__ == "__main__":
    main()
