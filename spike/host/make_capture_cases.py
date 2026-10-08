#!/usr/bin/env python3
"""NON-NORMATIVE FEASIBILITY SPIKE. Builds chain cases for the ANCHORED CAPTURE PATH from a G5 PASS result ONLY.

Inputs of the chain come exclusively from the paths G5 returned for the capture it checked (request, pB, inst, iB, retained target
payload). There is no fallback to a source fixture directory: the expectation file is read for expected outcomes only (comparison), and
an expectation file that lives inside the capture root is refused.

usage: make_capture_cases.py --id ID --g5-result g5.json --expect expect.json --out cases.json [--append]
Refuses unless g5 == "PASS" and anchor_checked is true, and unless every returned path lies under the returned capture root.
"""
import argparse, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from make_cases import with_code


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", required=True)
    ap.add_argument("--g5-result", required=True)
    ap.add_argument("--expect", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--append", action="store_true")
    a = ap.parse_args()
    g = json.load(open(a.g5_result))
    if g.get("g5") != "PASS":
        sys.exit(f"refusing: G5 result is {g.get('g5')!r}, not PASS")
    if g.get("anchor_checked") is not True:
        sys.exit("refusing: G5 PASS without anchor_checked=true is not an anchored capture")
    root = os.path.realpath(g["root"])
    paths = {}
    for k in ("request", "profile_artifact", "instance_commitment", "s1_instance", "retained_target_payload"):
        v = g.get(k)
        if v is None:
            if k == "retained_target_payload":
                paths[k] = None
                continue
            sys.exit(f"refusing: G5 result has no {k}")
        rp = os.path.realpath(v)
        if os.path.commonpath([root, rp]) != root:
            sys.exit(f"refusing: {k} path {v} is outside the checked capture root {root}")
        paths[k] = rp
    ex = os.path.realpath(a.expect)
    if os.path.commonpath([root, ex]) == root:
        sys.exit("refusing: the expectation file must not be inside the capture")
    exp = json.load(open(ex))
    case = {"id": a.id, "source": "anchored capture " + root, "request": paths["request"], "pb": paths["profile_artifact"], "inst": paths["instance_commitment"],
            "ib": paths["s1_instance"], "retained_target_payload": paths["retained_target_payload"],
            "tb_expected": os.path.join(os.path.dirname(ex), "tB.expected"), "expect": dict(exp, post=with_code(exp.get("post")))}
    if not os.path.exists(case["tb_expected"]):
        del case["tb_expected"]
    cases = json.load(open(a.out)) if a.append and os.path.exists(a.out) else []
    cases.append(case)
    json.dump(cases, open(a.out, "w"), indent=1)
    print(f"{a.id}: inputs taken from G5-returned paths under {root}")


if __name__ == "__main__":
    main()
