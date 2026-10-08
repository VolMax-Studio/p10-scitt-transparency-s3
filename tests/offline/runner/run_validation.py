#!/usr/bin/env python3
"""TEST HARNESS (not acceptance code) validating the CANDIDATE S3-C runner (verifier/runner/s3c_verify.py).

All expectation comparisons live here; the runner never sees them. Parts:
  captures   the existing exploratory captures (run2, run3/ML-2, detached-closure) through the single command, twice each: outcome BINDING_MATCH, exit 0, A1-A15 match,
             verdict.json byte-identical across the two runs, tB hash equal to the independently derived expectation stored beside each capture and to the earlier chain run's tB
  controls   the eight ratified propagation controls (prereg 7.3): each fixture packaged as a capture (materialize_control.py) and run through the single command; a control that
             cannot be packaged (capture format needs a complete prefix) is reported as such and run through the chain stages directly with its own bound inputs
  packaging  the G5 packaging cases (N-P1..N-P7 variants, N-D1 and the extra G5 cases, reused from tests/offline/g5/run_g5_tests.py) through the single command: a packaging
             failure must end as S3-FAIL(packaging) with the exact G5 reason, with no later stage run; BASE and N-D1 must end as BINDING_MATCH

usage: run_validation.py --s1 D --s2a D --s2b D --entry BIN --g5 BIN --work DIR --out DIR [--lean-bin-dir D] [--parts captures,controls,packaging] [--python PY]
"""
import argparse, hashlib, importlib.util, json, os, shutil, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
RUNNER = os.path.join(REPO, "verifier", "runner", "s3c_verify.py")
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(REPO, "verifier", "runner")); sys.path.insert(0, os.path.join(REPO, "spike", "glue"))
import materialize_control as MC
import s3c_chain as C
import s3_spike_chain as SG          # comparison helpers of the spike (match_post, match_s2b, norm_expected_s2a): harness-only use

sha = lambda b: hashlib.sha256(b).hexdigest()
rd = lambda p: open(p, "rb").read()
EVID = os.path.join(REPO, "ts-prototype", "evidence")
CAPTURES = [
    ("run2", "lifecycle-run2", "lifecycle-run2/capture", "lifecycle-run2/ANCHOR.sha256", "lifecycle-run2/expected/tB.expected", "lifecycle-run2/chain/cases/EXPLORATORY-RUN2/s2b/tB.bin", 7, 6),
    ("run3-ml2", "lifecycle-run3-ml2", "lifecycle-run3-ml2/capture", "lifecycle-run3-ml2/ANCHOR.sha256", "lifecycle-run3-ml2/expected/tB.expected",
     "lifecycle-run3-ml2/chain/cases/EXPLORATORY-RUN3-ML2/s2b/tB.bin", 8, 7),
    ("detached-closure", "exploratory-ml1-detached-closure", "exploratory-ml1-detached-closure/capture", "exploratory-ml1-detached-closure/ANCHOR.sha256",
     "exploratory-ml1-detached-closure-corrected/expected/tB.expected", "exploratory-ml1-detached-closure-corrected/chain/cases/EXPLORATORY-ML1-DETACHED-CORRECTED/s2b/tB.bin", 7, 6),
]


class Ctx:
    pass


def command(a, capture, anchor, out):
    argv = [a.python, "-B", RUNNER, "--capture", capture, "--anchor", anchor, "--out", out, "--s1", a.s1, "--s2a", a.s2a, "--s2b", a.s2b, "--entry", a.entry, "--g5", a.g5]
    if a.lean_bin_dir:
        argv += ["--lean-bin-dir", a.lean_bin_dir]
    p = subprocess.run(argv, capture_output=True, text=True)
    v = json.load(open(os.path.join(out, "verdict.json"))) if os.path.exists(os.path.join(out, "verdict.json")) else None
    info = json.load(open(os.path.join(out, "run-info.json"))) if os.path.exists(os.path.join(out, "run-info.json")) else {}
    return p.returncode, v, info


def keep(a, label, out):
    d = os.path.join(a.out, "verdicts", label); os.makedirs(d, exist_ok=True)
    for f in ("verdict.json", "run-info.json"):
        if os.path.exists(os.path.join(out, f)):
            shutil.copy(os.path.join(out, f), d)


def part_captures(a, rep):
    rows = []
    for cid, _, cap, anc, tbexp, tbprev, size, target in CAPTURES:
        anchor = open(os.path.join(EVID, anc)).read().split()[0]
        res, bytes_ = [], []
        for n in (1, 2):
            out = os.path.join(a.work, f"cap-{cid}-{n}")
            rc, v, info = command(a, os.path.join(EVID, cap), anchor, out)
            res.append((rc, v, info)); bytes_.append(rd(os.path.join(out, "verdict.json")))
            keep(a, f"captures/{cid}-run{n}", out)
        rc, v, info = res[0]
        checks = {
            "exit 0 and outcome BINDING_MATCH (both runs)": all(r[0] == 0 and r[1]["outcome"] == "BINDING_MATCH" for r in res),
            "G5 PASS with the anchor": v["g5"]["result"] == "PASS",
            "S2b Verified with the expected checkpoint size and target index": v["s2b"]["status"] == "Verified" and v["s2b"]["checkpoint_size"] == size and v["s2b"]["target_leaf_index"] == target,
            "S2a accept and S1 e2e some": v["s2a"]["outcome"] == "accept" and v["s2a"]["e2e"] == "some",
            "post-S2a BINDING_MATCH with A1-A15 all match": v["post"]["result"] == "BINDING_MATCH" and [v["post"]["rows"].get(f"A{i}") for i in range(1, 16)] == ["match"] * 15,
            "tB equals the independently derived expectation stored beside the capture (comparison here only)": v["tB_sha256"] == sha(rd(os.path.join(EVID, tbexp))),
            "tB equals the tB of the earlier spike-glue chain run": v["tB_sha256"] == sha(rd(os.path.join(EVID, tbprev))),
            "verdict.json byte-identical across the two runs": bytes_[0] == bytes_[1],
            "closureAt helper binary hash attested": bool((info.get("chain_info") or {}).get("closure_helper_binary_sha256")),
            "network isolated": info.get("network_isolated") is True,
        }
        rows.append({"id": cid, "verdict_sha256": sha(bytes_[0]), "checks": checks, "ok": all(checks.values())})
        print(f"captures/{cid:<18} {'ok' if rows[-1]['ok'] else 'FAIL'}  " + ("" if rows[-1]["ok"] else str([k for k, x in checks.items() if not x])), flush=True)
    rep["captures"] = rows


def post_with_hash(v, info):
    p = dict(v["post"] or {}); p["closure_helper_binary_sha256"] = (info.get("chain_info") or {}).get("closure_helper_binary_sha256"); return p


def compare_control(c, v, info):
    """Expectation (from the ratified fixture's own recorded expectation, via spike/host/make_cases.py) vs the runner verdict."""
    e = c["expect"]; bad = []
    s2b = dict(v["s2b"] or {})
    if "s2b" in e:
        if e["s2b"]["status"] == "Verified":
            if s2b.get("status") != "Verified": bad.append(f"s2b status {s2b.get('status')}")
        else:
            ok, d = SG.match_s2b(e["s2b"], {"status": s2b.get("status"), "reason": {"class": s2b.get("class") or "", "reason": s2b.get("reason") or ""}})
            if not ok: bad.append("s2b: " + d)
    if "composed_after_s2b" in e and not (v["outcome"] == e["composed_after_s2b"] and v["stage"] == "s2b"):
        bad.append(f"composed {v['outcome']}@{v['stage']} != {e['composed_after_s2b']}@s2b")
    if e.get("s2a"):
        want = SG.norm_expected_s2a(e["s2a"]) if e["s2a"].startswith(".") else (e["s2a"], None)
        got = (v["s2a"] or {}).get("outcome"), (v["s2a"] or {}).get("reason")
        if not (got[0] == want[0] and (want[1] is None or got[1] == want[1])): bad.append(f"s2a {got} != {want}")
        if want[0] in ("reject", "halt") and not (v["outcome"] == want[0].upper() and v["stage"] == "s2a"): bad.append(f"final {v['outcome']}@{v['stage']} for s2a {want[0]}")
    if e.get("e2e") and (v["s2a"] or {}).get("e2e") != e["e2e"]: bad.append(f"e2e {(v['s2a'] or {}).get('e2e')} != {e['e2e']}")
    if e.get("post"):
        if not v["post"]: bad.append("post not run")
        else:
            ok, d = SG.match_post(e["post"], post_with_hash(v, info))
            if not ok: bad.append("post: " + d)
            if v["outcome"] != e["post"]["verdict"] or v["stage"] != "post-s2a": bad.append(f"final {v['outcome']}@{v['stage']} != {e['post']['verdict']}@post-s2a")
    return bad


def part_controls(a, rep):
    cj = os.path.join(a.work, "controls-cases.json")
    subprocess.run([a.python, "-B", os.path.join(REPO, "spike", "host", "make_cases.py"), "--s2b", a.s2b, "--out", cj], check=True, capture_output=True)
    cases = json.load(open(cj)); rows = []
    prof_pb, prof_inst, p2_ib = (os.path.join(a.s2b, "profile", "pB.json"), os.path.join(a.s2b, "profile", "inst.bin"), os.path.join(a.s2a, "vectors", "P2", "iB.json"))
    for c in cases:
        cid = c["id"]; row = {"id": cid, "source": c["source"]}
        vec = os.path.join(a.s2b, "vectors", c["source"])
        cap = os.path.join(a.work, f"ctl-{cid}", "capture")
        m = MC.materialize(vec, cap, a.s2b, a.s2a, cid); row["packaged"] = m["packaged"]
        if m["packaged"]:
            out = os.path.join(a.work, f"ctl-{cid}", "run")
            rc, v, info = command(a, cap, m["anchor"], out); keep(a, f"controls/{cid}", out)
            bad = compare_control(c, v, info)
            row.update({"via": "single command on the packaged fixture", "supplied_from_profile_or_filler": m["filler"], "exit": rc, "outcome": v["outcome"], "stage": v["stage"], "reason": v["reason"], "mismatches": bad})
        else:
            row["why_not_packaged"] = m["why"]
            # packaging view: the single command must end as S3-FAIL(packaging) only if the capture exists; here no capture can be built, so the control is run through the chain stages
            out = os.path.join(a.work, f"ctl-{cid}", "direct"); os.makedirs(out)
            os.environ["P10_LEAN_BIN_DIR"] = a.lean_bin_dir or os.environ.get("P10_LEAN_BIN_DIR", "")
            inp = C.ChainInputs(c["request"], c.get("pb", prof_pb), c.get("inst", prof_inst), c.get("ib", p2_ib), c.get("retained_target_payload"))
            r = C.run_chain(inp, out, a.s2b, a.s2a, a.entry, C.Log(out))
            v = {"outcome": r["outcome"], "stage": r["stage"], "reason": r["reason"], "s2b": r["s2b"], "s2a": r["s2a"], "post": r["post"]}
            bad = compare_control(c, v, {"chain_info": r["info"]})
            row.update({"via": "chain stages directly (harness), fixture's own request", "outcome": v["outcome"], "stage": v["stage"], "reason": v["reason"], "mismatches": bad})
        row["ok"] = not row["mismatches"]
        rows.append(row)
        print(f"controls/{cid:<12} {'ok' if row['ok'] else 'FAIL'}  {row['outcome']}@{row['stage']}  via={row['via'][:30]}  {row['mismatches'] or ''}", flush=True)
    rep["controls"] = rows


def part_packaging(a, rep):
    spec = importlib.util.spec_from_file_location("g5tests", os.path.join(REPO, "tests", "offline", "g5", "run_g5_tests.py")); G = importlib.util.module_from_spec(spec); spec.loader.exec_module(G)
    work = os.path.join(a.work, "pk"); os.makedirs(work)
    base = os.path.join(work, "base")
    subprocess.run([a.python, "-B", os.path.join(REPO, "tests", "offline", "g5", "materialize_capture.py"), "--fixture", os.path.join(REPO, "spike", "fixtures", "volmax-owner"), "--out", base], check=True, capture_output=True)
    sources = {"material/pB.json": lambda: rd(os.path.join(a.s2b, "profile", "pB.json")), "material/inst.bin": lambda: rd(os.path.join(a.s2b, "profile", "inst.bin")),
               "material/iB.json": lambda: rd(os.path.join(a.s2a, "vectors", "P1", "iB.json")),
               "material/target_payload.json": lambda: rd(os.path.join(a.s2b, "vectors", "s2a-post", "BIND-A10-mismatch", "target_payload.json")),
               "request.cbor": lambda: rd(os.path.join(a.s2b, "vectors", "s2a-post", "POST-BASE-match", "request.cbor"))}
    cases = list(G.CASES)
    for name, path in G.NP7:
        for variant, stale in (("a", False), ("b", True)):
            cases.append((f"N-P7-{name}-{variant}", (lambda p=path, s=stale: (lambda d: G.make_np7(p, lambda ctx: sources[p](), s)(d, None)))(), "E_FILE_HASH_MISMATCH" if not stale else "E_INDEX_ANCHOR_MISMATCH", False))
    rows = []
    for cid, mut, expected, full in cases:
        d = os.path.join(work, cid); shutil.copytree(base, d, symlinks=True)
        anchor = mut(d); out = os.path.join(work, "out-" + cid)
        rc, v, info = command(a, d, anchor, out)
        if expected == "PASS":
            ok = rc == 0 and v["outcome"] == "BINDING_MATCH" and v["g5"]["result"] == "PASS"
            row = {"id": cid, "expected": "PASS then BINDING_MATCH", "actual": f"{v['outcome']} (exit {rc})", "ok": ok}
            keep(a, f"packaging/{cid}", out)
        else:
            names = [c["name"] for c in info.get("commands", [])]
            ok = (rc == 30 and v["outcome"] == "S3-FAIL(packaging)" and v["stage"] == "g5" and v["reason"]["code"] == expected and v["g5"] == {"result": "FAIL", "reason": expected}
                  and names == ["preflight", "g5"] and not os.path.exists(os.path.join(out, "s2b")) and not os.path.exists(os.path.join(out, "s2a_jobs.tsv")))
            row = {"id": cid, "expected": expected, "actual": (v or {}).get("reason", {}).get("code") if v else None, "exit": rc, "stages_run": names, "ok": ok}
            keep(a, f"packaging/{cid}", out)
        rows.append(row)
        print(f"packaging/{cid:<22} {'ok' if row['ok'] else 'FAIL'}  expected={row['expected']}  actual={row['actual']}", flush=True)
    rep["packaging"] = rows


def main():
    ap = argparse.ArgumentParser()
    for k in ("s1", "s2a", "s2b", "entry", "g5", "work", "out"): ap.add_argument("--" + k, required=True)
    ap.add_argument("--lean-bin-dir"); ap.add_argument("--parts", default="captures,controls,packaging"); ap.add_argument("--python", default=sys.executable)
    a = ap.parse_args()
    for k in ("work", "out"):
        p = os.path.abspath(getattr(a, k)); setattr(a, k, p)
        if os.path.exists(p) and os.listdir(p): sys.exit(f"{k} must be empty")
        os.makedirs(p, exist_ok=True)
    rep = {"runner_sha256": {f: sha(rd(os.path.join(REPO, "verifier", "runner", f))) for f in ("s3c_verify.py", "s3c_chain.py", "PINNED_INPUTS.json")},
           "g5_binary_sha256": sha(rd(a.g5)), "entry_binary_sha256": sha(rd(a.entry))}
    for p in a.parts.split(","):
        {"captures": part_captures, "controls": part_controls, "packaging": part_packaging}[p](a, rep)
    allok = all(r["ok"] for p in a.parts.split(",") for r in rep[p])
    rep["all_ok"] = allok
    json.dump(rep, open(os.path.join(a.out, "validation-report.json"), "w"), indent=1, sort_keys=True)
    print("VALIDATION:", "ALL OK" if allok else "FAILURES")
    return 0 if allok else 1


if __name__ == "__main__":
    raise SystemExit(main())
