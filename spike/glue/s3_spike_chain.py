#!/usr/bin/env python3
"""NON-NORMATIVE FEASIBILITY SPIKE (not the S3 acceptance runner; adoption needs review against the completed S3 preregistration).

Runs the traced chain over one or more cases:

    request.cbor -> s3-spike-entry (unchanged pinned S2b crate: decode_request, replay_p0_p9; target sub/payload extracted from the
    authenticated target) -> S2b result composition (S2b prereg r7 s16.6) -> pinned S2a runner (tb/inst/pb/cov/e2e)
    -> existing post_s2a.evaluate with the real Lean closureAt helper.

Rules this script follows:
  * Expected artifacts (tB.expected, expected verdicts) are read ONLY after all stages of a case have produced their actual outputs,
    and only to compare. They never feed a stage.
  * PostS2aInputs are built from actual outputs: the actual tB, the S2b Receipt leaf_index, the target payload and protected `sub`
    extracted from the authenticated target by the entry, the actual S2a cov/e2e results, the frozen A12-A14 digests read from the
    S2b freeze record. No generator-known value is used.
  * It imports the unchanged S2b `orchestration/post_s2a.py` and calls the unchanged S2b launchers. It does not modify S2b/S2a/S1.
  * Lean stages need the pinned Lean (selected by the S2b launchers by SHA-256). If a Lean stage cannot run, the stage is reported as
    NOT RUN with the launcher's stderr; nothing is substituted.

usage: s3_spike_chain.py --cases cases.json --out DIR --s2b DIR --s2a DIR --entry BIN [--s2b-only]
"""
import argparse, hashlib, json, os, re, subprocess, sys, tempfile, time

HEX64 = re.compile(r"[0-9a-f]{64}")


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


class Log:
    """Every external command: argv, exit code, stdout/stderr files and their hashes."""

    def __init__(self, out):
        self.out, self.n, self.entries = out, 0, []
        os.makedirs(os.path.join(out, "logs"), exist_ok=True)

    def run(self, argv, name, env=None, cwd=None):
        self.n += 1
        tag = f"{self.n:03d}-{name}"
        t0 = time.time()
        try:
            p = subprocess.run(argv, capture_output=True, env=env, cwd=cwd)
            rc, so, se = p.returncode, p.stdout, p.stderr
        except OSError as e:
            rc, so, se = 127, b"", f"cannot execute: {e}".encode()
        fo, fe = os.path.join("logs", tag + ".stdout"), os.path.join("logs", tag + ".stderr")
        open(os.path.join(self.out, fo), "wb").write(so)
        open(os.path.join(self.out, fe), "wb").write(se)
        e = {"n": self.n, "name": name, "argv": argv, "exit": rc, "stdout": fo, "stdout_sha256": sha256_bytes(so),
             "stderr": fe, "stderr_sha256": sha256_bytes(se), "seconds": round(time.time() - t0, 2)}
        self.entries.append(e)
        return rc, so.decode("utf-8", "replace"), se.decode("utf-8", "replace")


# ---------------------------------------------------------------------------------------------------- pure helpers (unit-tested)

def compose_s2b(res):
    """S2b prereg r7 s16.6 (frozen table), applied to an entry result.json. Returns 'continue' | 'HALT' | 'REJECT'."""
    st = res.get("status")
    if st == "Verified":
        return "continue"
    if st == "Invalid":
        return "REJECT" if res["reason"]["class"] == "Binding" else "HALT"   # Invalid(binding) -> REJECT; Invalid(replay|request) -> HALT
    if st == "Unavailable":
        return "HALT"
    return None   # TransportError etc.: not a P10 outcome (S3-FAIL packaging), no composition


def norm_s2a(cov_result):
    """-> (outcome, reason-token|None) from the S2a runner `cov` result object."""
    out = cov_result["outcome"]
    reason = None
    if out != "accept":
        m = re.search(r"\.((?:c\d+[a-z]?|tb5)_[A-Za-z0-9_]+)", cov_result.get("repr", ""))
        reason = m.group(1) if m else None
    return out, reason


def norm_expected_s2a(text):
    """'.reject .c3_profileAfterFirstAdmission' -> ('reject','c3_profileAfterFirstAdmission'); '.accept (...)' -> ('accept', None)."""
    m = re.match(r"\s*\.(accept|reject|halt)\s*(?:\.([A-Za-z0-9_]+))?", text)
    return (m.group(1), m.group(2)) if m else (None, None)


def frozen_a12_a14(freeze_record_text):
    """The three frozen composite digests, read from the S2b schema freeze record (frozen/StatementPayloadSchemaV0_r9_FREEZE.txt)."""
    out = {}
    for label, key in (("CodecArtifactV0:", "codec_digest"), ("CapabilityProofV0:", "capability_proof_digest"), ("ProofArtifactV0:", "proof_digest")):
        m = re.search(re.escape(label) + r"\s*\n\s*([0-9a-f]{64})\s*\n", freeze_record_text)
        if not m:
            raise ValueError(f"freeze record has no {label}")
        out[key] = m.group(1)
    return out


def match_s2b(expect, res):
    """Compare an expected S2b outcome dict with the entry result. Returns (ok, detail)."""
    if res.get("status") != expect["status"]:
        return False, f"status {res.get('status')} != {expect['status']}"
    if expect["status"] == "Verified":
        return True, ""
    r = res["reason"]
    if "class" in expect and r["class"].lower() != expect["class"].lower():
        return False, f"class {r['class']} != {expect['class']}"
    if "reason" in expect and not r["reason"].startswith(expect["reason"]):
        return False, f"reason {r['reason']} != {expect['reason']}"
    return True, ""


# Strict reading of S2a runner output (source: orchestration/helper/S2aRunner.lean). Format problems and runner errors are
# INFRASTRUCTURE failures; they are returned as errors and can never turn into a semantic value (for example e2e "false" -> A15 REJECT).

def _job(obj, op):
    if not isinstance(obj, dict):
        return None, "job output is not an object"
    if "error" in obj:
        return None, f"runner error: {obj.get('error')}"
    if obj.get("op") != op:
        return None, f"op {obj.get('op')!r} != {op!r}"
    return obj, None


def parse_codec_job(obj, op):
    """tb / inst / pb strict decode + re-encode identity. -> (True, None) | (False, error)."""
    v, e = _job(obj, op)
    if e:
        return False, e
    if v.get("decode") is not True or v.get("reencode_identical") is not True:
        return False, f"{op}: decode={v.get('decode')!r} reencode_identical={v.get('reencode_identical')!r}"
    return True, None


def parse_cov_job(obj):
    """-> (result dict, None) | (None, error). outcome in accept/reject/halt; accept needs a 64-hex evidence digest."""
    v, e = _job(obj, "cov")
    if e:
        return None, e
    r = v.get("result")
    if not isinstance(r, dict) or r.get("outcome") not in ("accept", "reject", "halt") or not isinstance(r.get("repr"), str):
        return None, f"cov: malformed result {r!r}"
    if r["outcome"] == "accept" and not (isinstance(r.get("evidence_digest"), str) and HEX64.fullmatch(r["evidence_digest"])):
        return None, "cov: accept without a 64-hex evidence_digest"
    return r, None


def parse_e2e_job(obj):
    """-> (True|False, None) only for an explicit "some"/"none"; anything else -> (None, error)."""
    v, e = _job(obj, "e2e")
    if e:
        return None, e
    r = v.get("result")
    if r == "some" and isinstance(v.get("evidence_repr"), str):
        return True, None
    if r == "none":
        return False, None
    return None, f"e2e: result {r!r} is neither an explicit some (with evidence_repr) nor none"


INFRA_POST_CODES = ("ClosureAtUnavailable", "ClosureAtInconsistent", "NOT_EVIDENCE")


def match_post(expect, post):
    """Exact comparison of a post-S2a evidence record with an expectation {verdict, rule, code, detail_contains?, helper_required?}."""
    if post.get("result") != expect["verdict"]:
        return False, f"result {post.get('result')} != {expect['verdict']}"
    if post.get("rule") != expect.get("rule"):
        return False, f"rule {post.get('rule')} != {expect.get('rule')}"
    if "code" in expect and post.get("code") != expect["code"]:
        return False, f"code {post.get('code')} != {expect['code']}"
    if "detail_contains" in expect and expect["detail_contains"] not in (post.get("detail") or ""):
        return False, f"detail {post.get('detail')!r} lacks {expect['detail_contains']!r}"
    if expect.get("helper_required") and not post.get("closure_helper_binary_sha256"):
        return False, "no closureAt helper binary hash recorded for a result that requires the real helper"
    if expect.get("rows_all_match"):
        rows = post.get("rows") or {}
        want = [f"A{i}" for i in range(1, 16)]
        bad = [r for r in want if rows.get(r) != "match"]
        if bad:
            return False, f"rows not 'match': { {r: rows.get(r) for r in bad} }"
    return True, ""


def match_s2b_detail(expect, res):
    """Optional structural expectations on a Verified S2b result: checkpoint size, subject-entry indices, unreadable rows."""
    if res.get("status") != "Verified":
        return False, f"status {res.get('status')}"
    got = {"checkpoint_size": res.get("checkpoint_size"), "subject_idx": [o["idx"] for o in res.get("subject_observations", [])],
           "unreadable": [u["idx"] for u in res.get("unreadable_rows", [])]}
    bad = {k: (got[k], v) for k, v in expect.items() if got.get(k) != v}
    return (not bad), (f"differs: {bad}" if bad else "")


# ---------------------------------------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--s2b", required=True)
    ap.add_argument("--s2a", required=True)
    ap.add_argument("--entry", required=True)
    ap.add_argument("--s2b-only", action="store_true", help="stop after the S2b stage (no Lean)")
    ap.add_argument("--inject-closureat-unavailable", action="store_true",
                    help="TEST HOOK: skip the closureAt helper run to simulate helper unavailability (controls must then FAIL, never match)")
    a = ap.parse_args()
    out = os.path.abspath(a.out)
    os.makedirs(out, exist_ok=True)
    log = Log(out)
    cases = json.load(open(a.cases))
    sys.path.insert(0, os.path.join(a.s2b, "orchestration"))
    import post_s2a as P   # unchanged S2b source

    freeze = open(os.path.join(a.s2b, "frozen", "StatementPayloadSchemaV0_r9_FREEZE.txt"), encoding="utf-8").read()
    a12 = frozen_a12_a14(freeze)
    fz = P.FrozenArtifactDigests(a12["codec_digest"], a12["capability_proof_digest"], a12["proof_digest"])
    report = {"a12_a14_source": "S2b frozen/StatementPayloadSchemaV0_r9_FREEZE.txt", "a12_a14": a12, "cases": {}}
    hashes = {}

    def H(label, path):
        hashes[label] = sha256_file(path)
        return hashes[label]

    # ---------------- stage 1: S2b (per case)
    state = {}
    for c in cases:
        cid = c["id"]
        cd = os.path.join(out, "cases", cid)
        os.makedirs(cd, exist_ok=True)
        st = {"case": c, "dir": cd, "stages": {}}
        state[cid] = st
        H(f"{cid}/request.cbor", c["request"])
        argv = [a.entry, "verify", "--request", c["request"], "--out", os.path.join(cd, "s2b")]
        if c.get("retained_target_payload"):
            argv += ["--expect-target-payload", c["retained_target_payload"]]
            H(f"{cid}/retained_target_payload", c["retained_target_payload"])
        rc, so, se = log.run(argv, f"s2b-{cid}")
        st["s2b_exit"] = rc
        try:
            res = json.load(open(os.path.join(cd, "s2b", "result.json")))
        except Exception as e:
            res = {"status": "NoResult", "error": str(e), "stderr": se[-300:]}
        st["s2b"] = res
        st["composed"] = compose_s2b(res)
        if rc == 20:
            st["composed"] = None   # target extraction / retained-payload equality failure: S3-FAIL(target), not a P10 outcome
        if res.get("status") == "Verified":
            H(f"{cid}/tB.actual", os.path.join(cd, "s2b", "tB.bin"))

    # ---------------- stage 2: S2a runner (one fresh Lean build for all cases)
    s2a_jobs, s2a_index = [], {}
    if not a.s2b_only:
        for cid, st in state.items():
            c = st["case"]
            if st["composed"] != "continue" or st["s2b_exit"] != 0:
                continue
            tb = os.path.join(st["dir"], "s2b", "tB.bin")
            idx = {}
            for op, extra in (("tb", [tb]), ("inst", [c["inst"]]), ("pb", [c["pb"]]), ("cov", [tb, c["pb"], c["inst"]])):
                idx[op] = len(s2a_jobs)
                s2a_jobs.append([op] + extra)
            if c.get("ib"):
                idx["e2e"] = len(s2a_jobs)
                s2a_jobs.append(["e2e", tb, c["pb"], c["ib"], c["inst"]])
            s2a_index[cid] = idx
            for lab in ("pb", "inst", "ib"):
                if c.get(lab):
                    H(f"{cid}/{lab}", c[lab])
    s2a_res, s2a_info, s2a_run = [], {}, None
    if s2a_jobs:
        jf = os.path.join(out, "s2a_jobs.tsv")
        open(jf, "w").write("".join("\t".join(j) + "\n" for j in s2a_jobs))
        rc, so, se = log.run(["bash", os.path.join(a.s2b, "orchestration", "launch_s2a_runner.sh"), a.s2a, jf], "s2a-runner")
        s2a_run = {"exit": rc}
        for ln in se.splitlines():
            for k in ("helper-target", "helper-binary-sha256", "helper-source-sha256", "lean-toolchain", "lean-executable", "lean-executable-sha256", "lean-pinned-sha256"):
                if ln.startswith(k + " "):
                    s2a_info[k] = ln.split(" ", 1)[1]
        if rc == 0:
            try:
                s2a_res = [json.loads(l) for l in so.splitlines() if l.strip()]
                if len(s2a_res) != len(s2a_jobs):
                    s2a_run["error"] = f"expected {len(s2a_jobs)} result lines, got {len(s2a_res)}"
                    s2a_res = []
            except json.JSONDecodeError as e:
                s2a_run["error"] = f"non-JSON runner output: {e}"
        else:
            s2a_run["error"] = "S2a runner did not run (see logs); stage NOT RUN"
            s2a_run["stderr_tail"] = se[-600:]
    report["s2a_runner"] = {"info": s2a_info, **(s2a_run or {"exit": None, "note": "no case reached S2a" if not a.s2b_only else "skipped (--s2b-only)"})}

    # ---------------- stage 3: post-S2a (recording pass -> one fresh closureAt build -> evaluate)
    post_inputs, answers, cinfo = {}, {}, {}
    if s2a_res:
        for cid, idx in s2a_index.items():
            st = state[cid]
            c = st["case"]
            tbj, instj, pbj, covj = (s2a_res[idx[k]] for k in ("tb", "inst", "pb", "cov"))
            st["stages"]["s2a_codec"] = {"tb": tbj, "inst": instj, "pb": pbj}
            st["s2a_cov"] = covj
            st["infra"] = st.get("infra", [])
            codec_ok = True
            for nm, j in (("tb", tbj), ("inst", instj), ("pb", pbj)):
                ok_, err_ = parse_codec_job(j, nm)
                if not ok_:
                    codec_ok = False
                    st["infra"].append("S2a codec: " + err_)
            st["s2a_codec_ok"] = codec_ok
            cov, err_ = parse_cov_job(covj)
            if err_:
                st["infra"].append("S2a cov: " + err_)
            if not codec_ok or cov is None:
                continue
            outcome, reason = norm_s2a(cov)
            st["s2a"] = (outcome, reason)
            if outcome != "accept":
                continue
            e2er = None
            if "e2e" in idx:
                st["s2a_e2e"] = s2a_res[idx["e2e"]]
                e2er, err_ = parse_e2e_job(st["s2a_e2e"])
                if err_:
                    st["infra"].append("S2a e2e: " + err_)
                    continue
            else:
                st["s2a_e2e"] = None
            if not c.get("ib"):
                st["post_not_run"] = "no S1 instance bytes (iB) for this case"
                continue
            t = st["s2b"]["target"]
            tdir = os.path.join(st["dir"], "s2b")
            post_inputs[cid] = P.PostS2aInputs(
                True, open(os.path.join(tdir, "tB.bin"), "rb").read(), open(c["pb"], "rb").read(), open(c["ib"], "rb").read(),
                int(open(os.path.join(tdir, "target.leaf_index.txt")).read()), open(os.path.join(tdir, "target.payload.bin"), "rb").read(),
                open(os.path.join(tdir, "target.sub.txt"), encoding="utf-8").read(),
                bytes.fromhex(cov["evidence_digest"]), e2er, fz)

        class Recording:
            def __init__(self):
                self.jobs = []

            def __call__(self, tb, pb, inst_b, k):
                key = (tb, pb, inst_b, k)
                if key in answers:
                    return answers[key]
                if key not in self.jobs:
                    self.jobs.append(key)
                raise P.ClosureAtUnavailable("recording pass")

        rec = Recording()
        for cid, inp in post_inputs.items():
            P.evaluate(inp, rec)
        if rec.jobs and a.inject_closureat_unavailable:
            cinfo["error"] = "TEST HOOK: closureAt helper deliberately not run (--inject-closureat-unavailable)"
            report["fault_injected"] = "closureat-unavailable"
        elif rec.jobs and not a.s2b_only:
            tmp = tempfile.mkdtemp()
            lines = []
            for n, (tb, pb, ib, k) in enumerate(rec.jobs):
                ps = []
                for nm, data in (("t", tb), ("p", pb), ("i", ib)):
                    p = os.path.join(tmp, f"{n}{nm}")
                    open(p, "wb").write(data)
                    ps.append(p)
                lines.append("\t".join(ps + [str(k)]))
            jf = os.path.join(tmp, "jobs.tsv")
            open(jf, "w").write("\n".join(lines) + "\n")
            open(os.path.join(out, "closureat_jobs.tsv"), "w").write("\n".join(lines) + "\n")
            rc, so, se = log.run(["bash", os.path.join(a.s2b, "orchestration", "launch_closureat.sh"), "--batch", a.s2a, jf], "closureat-batch")
            for ln in se.splitlines():
                for k in ("helper-binary-sha256", "helper-source-sha256", "lean-toolchain", "lean-executable-sha256"):
                    if ln.startswith(k + " "):
                        cinfo[k] = ln.split(" ", 1)[1]
            outs = [l for l in so.splitlines() if l.strip()]
            if rc == 0 and len(outs) == len(rec.jobs):
                try:
                    for job, line in zip(rec.jobs, outs):
                        answers[job] = P.parse_helper_output(line, job[3], cinfo.get("helper-binary-sha256"), trusted=True)
                except P.ClosureAtUnavailable as e:
                    answers.clear()
                    cinfo["error"] = f"closureAt output malformed: {e}"
            else:
                cinfo["error"] = f"closureAt batch did not run (exit {rc}); stage NOT RUN"
                cinfo["stderr_tail"] = se[-600:]
        rec.answers = answers
        for cid, inp in post_inputs.items():
            v = P.evaluate(inp, rec)
            try:
                state[cid]["post"] = P.evidence_record(v)
            except P.UntrustedVerdictError as e:
                state[cid]["post"] = {"result": "NOT_EVIDENCE", "code": "NOT_EVIDENCE", "rule": None, "detail": str(e)}
            if state[cid]["post"].get("code") in INFRA_POST_CODES:
                state[cid].setdefault("infra", []).append(f"post-S2a: {state[cid]['post'].get('code')} ({state[cid]['post'].get('detail')})")
    report["closureat_helper"] = cinfo

    # ---------------- comparison (expected artifacts read only here)
    for cid, st in state.items():
        c = st["case"]
        exp = c.get("expect", {})
        row = {"s2b": st["s2b"], "composed_after_s2b": st["composed"], "checks": []}

        def chk(name, ok, detail=""):
            row["checks"].append({"check": name, "ok": bool(ok), "detail": detail})

        if "s2b" in exp:
            ok, d = match_s2b(exp["s2b"], st["s2b"])
            chk("s2b-result", ok, d)
        if "s2b_detail" in exp:
            ok, d = match_s2b_detail(exp["s2b_detail"], st["s2b"])
            chk("s2b-structure", ok, d)
        if "composed_after_s2b" in exp:
            chk("s2b-composed", st["composed"] == exp["composed_after_s2b"], f"{st['composed']} vs {exp['composed_after_s2b']}")
        if st["s2b"].get("status") == "Verified":
            tgt = st["s2b"].get("target") or {}
            chk("target-extracted-from-authenticated-target", st["s2b_exit"] == 0 and "sub" in tgt and tgt.get("payload_equals_retained_file") in (True, None),
                f"exit={st['s2b_exit']} target={tgt}")
            if c.get("tb_expected"):
                got, want = sha256_file(os.path.join(st["dir"], "s2b", "tB.bin")), sha256_file(c["tb_expected"])
                chk("tB-actual-equals-tB.expected (comparison only)", got == want, f"{got[:16]} vs {want[:16]}")
        if "s2a" in exp and exp["s2a"]:
            if a.s2b_only or not s2a_res:
                row["s2a"] = "NOT RUN"
            else:
                want = norm_expected_s2a(exp["s2a"]) if exp["s2a"].startswith(".") else (exp["s2a"], None)
                got = st.get("s2a")
                chk("s2a-outcome", got is not None and got[0] == want[0] and (want[1] is None or got[1] == want[1]), f"{got} vs {want}")
                row["s2a"] = {"actual": got, "codec_ok": st.get("s2a_codec_ok")}
        if "e2e" in exp and exp["e2e"] and not a.s2b_only and s2a_res and st.get("s2a_e2e") is not None:
            val, err_ = parse_e2e_job(st["s2a_e2e"])
            chk("s1-e2e", err_ is None and (("some" if val else "none") == exp["e2e"]), f"{err_ or ('some' if val else 'none')} vs {exp['e2e']}")
        if "post" in exp and exp["post"]:
            if "post" not in st:
                row["post"] = "NOT RUN"
            else:
                row["post"] = st["post"]
                ok_, d_ = match_post(exp["post"], st["post"])
                chk("post-s2a-result-code-rule", ok_, d_ or f"{st['post']['result']}/{st['post'].get('code')}/{st['post'].get('rule')}")
        row["infra_failures"] = st.get("infra", [])
        chk("no-infrastructure-failure", not row["infra_failures"], "; ".join(row["infra_failures"]))
        row["pass"] = bool(row["checks"]) and all(x["ok"] for x in row["checks"])
        row["not_run"] = [k for k in ("s2a", "post") if row.get(k) == "NOT RUN"]
        report["cases"][cid] = row

    report["commands"] = log.entries
    report["artifact_hashes"] = hashes
    json.dump(report, open(os.path.join(out, "report.json"), "w"), indent=1, sort_keys=True, default=str)
    width = max(len(k) for k in report["cases"]) if report["cases"] else 10
    for cid, row in report["cases"].items():
        status = "PASS" if row["pass"] else "FAIL"
        if row["not_run"]:
            status = f"INCOMPLETE (checked stages pass={row['pass']}; NOT RUN: {','.join(row['not_run'])})"
        print(f"{cid:<{width}}  {status}")
        for x in row["checks"]:
            if not x["ok"]:
                print(f"    FAIL {x['check']}: {x['detail']}")
    anyfail = any((not r["pass"]) or r["not_run"] for r in report["cases"].values())
    return 1 if anyfail else 0


if __name__ == "__main__":
    raise SystemExit(main())
