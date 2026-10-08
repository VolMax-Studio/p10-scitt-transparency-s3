#!/usr/bin/env python3
"""Pre-verification RECORD (S3 producer/orchestration evidence, not a verifier result) for a run in which an operator statement was registered between producer roles.
Built only from the RETAINED run directory (submit log, producer derivation log, returned responses, public export) and the preregistered `expected_layout` of run-config.json.
Records: producer ordinal vs returned index per statement; the closure's admission refs and the recomputed preclosure digest from the actual authenticated subject view; the
adjudication refs; retention of every registered leaf. Exit 1 if any recorded expectation fails.
usage: producer_index_record.py --s2b DIR --config DIR --run DIR --run-config FILE --out FILE
"""
import argparse, json, os, sys
import cbor2
ap = argparse.ArgumentParser()
for k in ("s2b", "config", "run", "run-config", "out"): ap.add_argument("--" + k, required=True)
a = ap.parse_args()
for sub in ("tests/differential", "tests/s2a", "orchestration"): sys.path.insert(0, os.path.join(a.s2b, sub))
import gen_corpus as G
import post_scenarios as PS
import post_s2a as P
rd = lambda p: open(p, "rb").read()
cfg = json.load(open(a.run_config)); exp = cfg["expected_layout"]
meta = json.load(open(os.path.join(a.config, "PUBLIC_META.json"))); subj = meta["identity"]["instance_subject"]; owner = meta["identity"]["owner_iss"]
steps = [json.loads(l) for l in open(os.path.join(a.run, "producer", "steps.jsonl"))]
slog = json.load(open(os.path.join(a.run, "submit-log.json")))
names = sorted(os.listdir(os.path.join(a.run, "export"))); n = len(names)
PT_INV = {v: k for k, v in G.PT.items()}
dec = []
for i, nm in enumerate(names):
    st = rd(os.path.join(a.run, "export", nm))[61:]
    t = cbor2.loads(st); claims = cbor2.loads(t.value[0])[15]
    try: j = json.loads(t.value[2]); kind, pred = PT_INV.get(j["predicateType"]), j["predicate"]
    except Exception: kind, pred = None, None
    dec.append({"idx": i, "iss": claims[1], "sub": claims[2], "kind": kind, "pred": pred})
subjd = [d for d in dec if d["sub"] == subj]
by = lambda k: [d["idx"] for d in subjd if d["kind"] == k]
resp = {i: json.load(open(os.path.join(a.run, "returned", f"{i:06d}.response.json"))) for i in range(n)}
rec, ok = {"leaves": n}, True
def chk(name, cond, detail=None):
    global ok; ok &= bool(cond); rec.setdefault("checks", []).append({"check": name, "ok": bool(cond), **({"detail": detail} if detail is not None else {})})
# ordinal vs index
inst_step = [s for s in steps if s["role"] == "instance"][0]
rec["per_statement"] = [{"index": i, "returned_index": resp[i]["index"], "source": slog[i]["source"], "producer_ordinal": slog[i]["producer_ordinal"],
                         "role": next((s["role"] for s in steps if s["next_index"] == i), "operator-insert"), "origin": slog[i]["origin"]} for i in range(n)]
chk("the instance producer ordinal differs from its returned index", inst_step["ordinal"] != resp[inst_step["next_index"]]["index"], {"ordinal": inst_step["ordinal"], "index": inst_step["next_index"]})
chk("returned indices equal log positions and every registration was fresh", all(resp[i]["index"] == i and not slog[i]["duplicate"] for i in range(n)))
chk("exactly one registration is an operator insert, not a producer role", [s["source"] for s in slog].count("operator-insert") == 1 and len(steps) == n - 1)
chk("producer prefix size equals the next index at every step", all(s["prefix_size"] == s["next_index"] for s in steps))
# layout
lay = exp["layout"]
chk("registered layout equals the preregistered layout", [(d["idx"], d["kind"] or ("note" if d["sub"].endswith(":note") else "bootstrap")) for d in dec] == [(x["index"], x["what"]) for x in lay],
    [(d["idx"], d["kind"] or d["sub"]) for d in dec])
# closure refs and preclosure recomputed from the actual authenticated subject view
ci = by("closure")[0]; cl = [d for d in dec if d["idx"] == ci][0]["pred"]
view = {}
for d in subjd:
    if d["idx"] >= ci: continue
    tok = {"profile": "profileCommit", "instance": "instanceCommit", "admission": "admission"}.get(d["kind"])
    view[d["idx"]] = P.Detailed(d["idx"], d["iss"].encode(), tok, "verified", tok, None)
pre = PS.preclosure_digest(view, ci, owner=owner.encode()).hex()
rec["closure"] = {"index": ci, "ordered_admission_refs": cl["ordered_admission_refs"], "actual_admission_indices": by("admission"), "preclosure_digest_in_statement": cl["checkpoint_preclosure_transcript_digest"],
                  "preclosure_digest_recomputed_from_retained_prefix": pre, "view": [[str(i), d.kind, d.iss.decode()] for i, d in sorted(view.items())]}
chk("closure references the actual admission index", cl["ordered_admission_refs"] == [str(x) for x in by("admission")] == [str(exp["admission_index"])])
chk("closure preclosure digest equals the recomputation from the retained authenticated subject view", cl["checkpoint_preclosure_transcript_digest"] == pre)
ai = by("adjudication")[0]; ad = [d for d in dec if d["idx"] == ai][0]["pred"]
rec["adjudication"] = {"index": ai, "profile_commitment_ref": ad["profile_commitment_ref"], "instance_commitment_ref": ad["instance_commitment_ref"], "evidence_closure_ref": ad["evidence_closure_ref"]}
chk("adjudication references the actual profile, instance and closure indices", [ad["profile_commitment_ref"], ad["instance_commitment_ref"], ad["evidence_closure_ref"]] == [str(x) for x in (by("profile")[0], by("instance")[0], by("closure")[0])] == [str(x) for x in exp["adjudication_refs"]])
# retention of all leaves
miss = []
for i in range(n):
    sub = "operator" if os.path.exists(os.path.join(a.run, "operator", "submissions", f"{i:06d}.cose")) else "issuer"
    for rel in (f"{sub}/submissions/{i:06d}.cose", f"returned/{i:06d}.receipt.cbor", f"returned/{i:06d}.response.json", f"public-checkpoints/{i:06d}.checkpoint", f"export/{i:06d}.leaf_input"):
        if not os.path.exists(os.path.join(a.run, rel)): miss.append(rel)
chk("retention: submission, Receipt, response, public checkpoint and public export for every registered leaf", not miss and n == exp["leaves"], miss)
rec["all_expectations_hold"] = ok
json.dump(rec, open(a.out, "w"), indent=1); print(json.dumps({"all_expectations_hold": ok, "checks": [(c["check"][:70], c["ok"]) for c in rec["checks"]]}, indent=1)); sys.exit(0 if ok else 1)
