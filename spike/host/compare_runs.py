#!/usr/bin/env python3
"""NON-NORMATIVE FEASIBILITY SPIKE. Compares two chain runs: tB bytes, S2b/S2a/post verdict projection, helper binary hashes.
Excluded from comparison: logs, timings, temporary paths. usage: compare_runs.py RUN_A RUN_B OUT.json"""
import hashlib, json, os, sys
a, b, out = sys.argv[1:4]
ra, rb = (json.load(open(os.path.join(d, "report.json"))) for d in (a, b))


def proj(r):
    o = {}
    for k, c in r["cases"].items():
        post = c.get("post")
        o[k] = {"composed_after_s2b": c["composed_after_s2b"], "s2b": c["s2b"], "s2a": c.get("s2a"),
                "post": ({x: post.get(x) for x in ("result", "code", "rule", "rows", "closure_helper_binary_sha256")} if isinstance(post, dict) else post), "pass": c["pass"]}
    return o


res = {"verdict_projection_identical": proj(ra) == proj(rb)}
tb = {}
for k in ra["cases"]:
    pa, pb_ = os.path.join(a, "cases", k, "s2b", "tB.bin"), os.path.join(b, "cases", k, "s2b", "tB.bin")
    if os.path.exists(pa) or os.path.exists(pb_):
        h = lambda p: hashlib.sha256(open(p, "rb").read()).hexdigest() if os.path.exists(p) else None
        tb[k] = {"a": h(pa), "b": h(pb_), "identical": h(pa) == h(pb_)}
res["tB"] = tb
res["s2a_runner_binary_identical"] = ra["s2a_runner"].get("info", {}).get("helper-binary-sha256") == rb["s2a_runner"].get("info", {}).get("helper-binary-sha256")
res["closureat_binary_identical"] = ra["closureat_helper"].get("helper-binary-sha256") == rb["closureat_helper"].get("helper-binary-sha256")
res["all_identical"] = res["verdict_projection_identical"] and all(v["identical"] for v in tb.values()) and res["s2a_runner_binary_identical"] and res["closureat_binary_identical"]
json.dump(res, open(out, "w"), indent=1, sort_keys=True)
print("run comparison:", "IDENTICAL" if res["all_identical"] else "DIFFERENT", json.dumps({k: v for k, v in res.items() if k != "tB"}))
raise SystemExit(0 if res["all_identical"] else 1)
