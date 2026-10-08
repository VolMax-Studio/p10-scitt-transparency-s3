#!/usr/bin/env python3
"""CANDIDATE S3-C chain stages (non-normative; see CONTRACT.md). Library used by s3c_verify.py and by the test harness.

Stages after G5: S2b entry -> composition (S2b prereg r7 s16.6) -> S2a runner -> post-S2a with the real closureAt helper.
Nothing here knows an expected verdict, an expected tB or a fixture: the only inputs are the explicit file paths of ChainInputs, which s3c_verify.py takes
exclusively from a successful anchored G5 result, and the frozen A12-A14 digests read from the pinned S2b freeze record.

Functions marked REUSED are copied verbatim from spike/glue/s3_spike_chain.py (candidate TCB code requiring review); the harness compares their source text with
the spike's. Everything else is new in this candidate. Successful execution adopts nothing.
"""
import hashlib, json, os, re, subprocess, sys, time

# REUSED from spike/glue/s3_spike_chain.py (candidate TCB code requiring review): HEX64
HEX64 = re.compile(r"[0-9a-f]{64}")

# REUSED from spike/glue/s3_spike_chain.py (candidate TCB code requiring review): sha256_file
def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        h.update(f.read())
    return h.hexdigest()

# REUSED from spike/glue/s3_spike_chain.py (candidate TCB code requiring review): sha256_bytes
def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()

# REUSED from spike/glue/s3_spike_chain.py (candidate TCB code requiring review): Log
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

# REUSED from spike/glue/s3_spike_chain.py (candidate TCB code requiring review): compose_s2b
def compose_s2b(res):
    """S2b prereg r7 s16.6 (frozen table), applied to an entry result.json. Returns 'continue' | 'HALT' | 'REJECT'."""
    st = res.get("status")
    if st == "Verified":
        return "continue"
    if st == "Invalid":
        return "REJECT" if res["reason"]["class"] == "Binding" else "HALT"   # Invalid(binding) -> REJECT; Invalid(replay|request) -> HALT
    if st == "Unavailable":
        return "HALT"
    return None

# REUSED from spike/glue/s3_spike_chain.py (candidate TCB code requiring review): norm_s2a
def norm_s2a(cov_result):
    """-> (outcome, reason-token|None) from the S2a runner `cov` result object."""
    out = cov_result["outcome"]
    reason = None
    if out != "accept":
        m = re.search(r"\.((?:c\d+[a-z]?|tb5)_[A-Za-z0-9_]+)", cov_result.get("repr", ""))
        reason = m.group(1) if m else None
    return out, reason

# REUSED from spike/glue/s3_spike_chain.py (candidate TCB code requiring review): frozen_a12_a14
def frozen_a12_a14(freeze_record_text):
    """The three frozen composite digests, read from the S2b schema freeze record (frozen/StatementPayloadSchemaV0_r9_FREEZE.txt)."""
    out = {}
    for label, key in (("CodecArtifactV0:", "codec_digest"), ("CapabilityProofV0:", "capability_proof_digest"), ("ProofArtifactV0:", "proof_digest")):
        m = re.search(re.escape(label) + r"\s*\n\s*([0-9a-f]{64})\s*\n", freeze_record_text)
        if not m:
            raise ValueError(f"freeze record has no {label}")
        out[key] = m.group(1)
    return out

# REUSED from spike/glue/s3_spike_chain.py (candidate TCB code requiring review): _job
def _job(obj, op):
    if not isinstance(obj, dict):
        return None, "job output is not an object"
    if "error" in obj:
        return None, f"runner error: {obj.get('error')}"
    if obj.get("op") != op:
        return None, f"op {obj.get('op')!r} != {op!r}"
    return obj, None

# REUSED from spike/glue/s3_spike_chain.py (candidate TCB code requiring review): parse_codec_job
def parse_codec_job(obj, op):
    """tb / inst / pb strict decode + re-encode identity. -> (True, None) | (False, error)."""
    v, e = _job(obj, op)
    if e:
        return False, e
    if v.get("decode") is not True or v.get("reencode_identical") is not True:
        return False, f"{op}: decode={v.get('decode')!r} reencode_identical={v.get('reencode_identical')!r}"
    return True, None

# REUSED from spike/glue/s3_spike_chain.py (candidate TCB code requiring review): parse_cov_job
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

# REUSED from spike/glue/s3_spike_chain.py (candidate TCB code requiring review): parse_e2e_job
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

# REUSED from spike/glue/s3_spike_chain.py (candidate TCB code requiring review): INFRA_POST_CODES
INFRA_POST_CODES = ("ClosureAtUnavailable", "ClosureAtInconsistent", "NOT_EVIDENCE")


# ---------------------------------------------------------------------------------------------------- new in this candidate

FORMAT = "P10-S3-C-Verdict-v0-candidate"
S2B_EXIT = {"Verified": 0, "Invalid": 10, "Unavailable": 11}


class ChainInputs:
    """Explicit file paths. s3c_verify.py builds this ONLY from a successful anchored G5 result."""

    def __init__(self, request, pb, inst, ib, retained_target_payload=None):
        self.request, self.pb, self.inst, self.ib, self.retained_target_payload = request, pb, inst, ib, retained_target_payload


def read_s2b_result(path):
    """Strict reading of the entry's result.json -> (obj, None) | (None, error)."""
    try:
        obj = json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError) as e:
        return None, f"result.json unreadable: {e}"
    if not isinstance(obj, dict) or obj.get("status") not in S2B_EXIT:
        return None, f"result.json has no known status: {str(obj)[:120]}"
    if obj["status"] == "Invalid":
        r = obj.get("reason")
        if not (isinstance(r, dict) and isinstance(r.get("class"), str) and isinstance(r.get("reason"), str)):
            return None, "Invalid result without a reason object"
    return obj, None


def _fresh():
    return {"outcome": None, "stage": None, "reason": None, "s2b": None, "s2a": None, "post": None, "tB_sha256": None, "s2a_result_lines_sha256": None,
            "frozen_a12_a14": None, "request_sha256": None, "infra": [], "info": {}}


def _infra(res, stage, code, message):
    res["outcome"], res["stage"], res["reason"] = "S3-FAIL(infrastructure)", stage, {"code": code}
    res["infra"].append(f"{stage}: {code}: {message}")
    return res


def _packaging(res, stage, code, message):
    res["outcome"], res["stage"], res["reason"] = "S3-FAIL(packaging)", stage, {"code": code}
    res["infra"].append(f"{stage}: {code}: {message}")
    return res


def run_chain(inp, out, s2b, s2a, entry, log):
    """Run S2B, CMP, S2A and POST for one capture. Never raises for stage problems: returns the result dict (see _fresh)."""
    import tempfile
    res = _fresh()
    sys.path.insert(0, os.path.join(s2b, "orchestration"))
    import post_s2a as P   # unchanged S2b source

    # ---- A12-A14: frozen values from the pinned S2b freeze record
    try:
        a12 = frozen_a12_a14(open(os.path.join(s2b, "frozen", "StatementPayloadSchemaV0_r9_FREEZE.txt"), encoding="utf-8").read())
    except (OSError, ValueError) as e:
        return _infra(res, "preflight", "FREEZE_RECORD", str(e))
    res["frozen_a12_a14"] = a12
    fz = P.FrozenArtifactDigests(a12["codec_digest"], a12["capability_proof_digest"], a12["proof_digest"])
    res["request_sha256"] = sha256_file(inp.request)

    # ---- S2B
    sdir = os.path.join(out, "s2b")
    argv = [entry, "verify", "--request", inp.request, "--out", sdir]
    if inp.retained_target_payload:
        argv += ["--expect-target-payload", inp.retained_target_payload]
    rc, so, se = log.run(argv, "s2b-entry")
    if rc == 20:
        return _packaging(res, "s2b", "TARGET_EXTRACTION", "target extraction or retained-payload equality failed: " + se[-200:])
    r2b, err = read_s2b_result(os.path.join(sdir, "result.json"))
    if err:
        return _infra(res, "s2b", "ENTRY_RESULT", err + " (exit " + str(rc) + ")")
    if rc != S2B_EXIT[r2b["status"]]:
        return _infra(res, "s2b", "ENTRY_EXIT_MISMATCH", f"exit {rc} does not belong to status {r2b['status']}")
    res["s2b"] = {"status": r2b["status"]}
    if r2b["status"] == "Invalid":
        res["s2b"].update({"class": r2b["reason"]["class"], "reason": r2b["reason"]["reason"]})
    elif r2b["status"] == "Unavailable":
        r = r2b.get("reason")
        if isinstance(r, dict):
            res["s2b"].update({"class": r.get("class"), "reason": r.get("reason")})
    comp = compose_s2b(r2b)   # CMP
    if comp != "continue":
        res["outcome"], res["stage"], res["reason"] = comp, "s2b", dict(res["s2b"])
        return res
    tb = os.path.join(sdir, "tB.bin")
    try:
        res["tB_sha256"] = sha256_file(tb)
        leaf_index = int(open(os.path.join(sdir, "target.leaf_index.txt")).read())
        tpay = open(os.path.join(sdir, "target.payload.bin"), "rb").read()
        tsub = open(os.path.join(sdir, "target.sub.txt"), encoding="utf-8").read()
    except (OSError, ValueError) as e:
        return _infra(res, "s2b", "VERIFIED_OUTPUTS_MISSING", str(e))
    res["s2b"]["checkpoint_size"] = r2b.get("checkpoint_size")
    res["s2b"]["target_leaf_index"] = leaf_index

    # ---- S2A (one fresh Lean build): tb, inst, pb, cov, e2e on the exact files
    jobs = [["tb", tb], ["inst", inp.inst], ["pb", inp.pb], ["cov", tb, inp.pb, inp.inst], ["e2e", tb, inp.pb, inp.ib, inp.inst]]
    jf = os.path.join(out, "s2a_jobs.tsv")
    open(jf, "w").write("".join("\t".join(j) + "\n" for j in jobs))
    rc, so, se = log.run(["bash", os.path.join(s2b, "orchestration", "launch_s2a_runner.sh"), s2a, jf], "s2a-runner")
    for ln in se.splitlines():
        for k in ("helper-binary-sha256", "helper-source-sha256", "lean-toolchain", "lean-executable-sha256"):
            if ln.startswith(k + " "):
                res["info"]["s2a_" + k] = ln.split(" ", 1)[1]
    if rc != 0:
        return _infra(res, "s2a", "S2A_RUNNER_NOT_RUN", f"exit {rc}: " + se[-300:])
    lines = [l for l in so.splitlines() if l.strip()]
    if len(lines) != len(jobs):
        return _infra(res, "s2a", "S2A_OUTPUT_COUNT", f"expected {len(jobs)} result lines, got {len(lines)}")
    try:
        objs = [json.loads(l) for l in lines]
    except ValueError as e:
        return _infra(res, "s2a", "S2A_OUTPUT_NOT_JSON", str(e))
    res["s2a_result_lines_sha256"] = [sha256_bytes(l.encode()) for l in lines]
    for nm, j in zip(("tb", "inst", "pb"), objs[:3]):
        ok_, e_ = parse_codec_job(j, nm)
        if not ok_:
            return _infra(res, "s2a", "S2A_CODEC", e_)
    cov, e_ = parse_cov_job(objs[3])
    if e_:
        return _infra(res, "s2a", "S2A_COV_MALFORMED", e_)
    outcome, reason = norm_s2a(cov)
    res["s2a"] = {"outcome": outcome, "reason": reason, "evidence_digest": cov.get("evidence_digest")}
    if outcome != "accept":
        res["outcome"], res["stage"], res["reason"] = outcome.upper(), "s2a", {"token": reason}
        return res
    e2er, e_ = parse_e2e_job(objs[4])
    if e_:
        return _infra(res, "s2a", "S2A_E2E_MALFORMED", e_)
    res["s2a"]["e2e"] = "some" if e2er else "none"

    # ---- POST (inputs from actual outputs only)
    try:
        inp_post = P.PostS2aInputs(True, open(tb, "rb").read(), open(inp.pb, "rb").read(), open(inp.ib, "rb").read(), leaf_index, tpay, tsub,
                                   bytes.fromhex(cov["evidence_digest"]), e2er, fz)
    except OSError as e:
        return _infra(res, "post-s2a", "POST_INPUT", str(e))
    answers = {}

    class Recording:
        def __init__(self):
            self.jobs = []
            self.answers = answers

        def __call__(self, tb_, pb_, inst_b, k):
            key = (tb_, pb_, inst_b, k)
            if key in answers:
                return answers[key]
            if key not in self.jobs:
                self.jobs.append(key)
            raise P.ClosureAtUnavailable("recording pass")

    rec = Recording()
    P.evaluate(inp_post, rec)    # recording pass: collects the closureAt questions
    if rec.jobs:
        cdir = os.path.join(out, "closureat"); os.makedirs(cdir, exist_ok=True)
        cl = []
        for n, (tb_, pb_, ib_, k) in enumerate(rec.jobs):
            ps = []
            for nm, data in (("t", tb_), ("p", pb_), ("i", ib_)):
                p = os.path.join(cdir, f"{n}{nm}"); open(p, "wb").write(data); ps.append(p)
            cl.append("\t".join(ps + [str(k)]))
        jf2 = os.path.join(cdir, "jobs.tsv"); open(jf2, "w").write("\n".join(cl) + "\n")
        rc, so, se = log.run(["bash", os.path.join(s2b, "orchestration", "launch_closureat.sh"), "--batch", s2a, jf2], "closureat-batch")
        for ln in se.splitlines():
            for k_ in ("helper-binary-sha256", "helper-source-sha256", "lean-toolchain", "lean-executable-sha256"):
                if ln.startswith(k_ + " "):
                    res["info"]["closureat_" + k_] = ln.split(" ", 1)[1]
        outs = [l for l in so.splitlines() if l.strip()]
        if rc != 0 or len(outs) != len(rec.jobs):
            return _infra(res, "post-s2a", "CLOSUREAT_NOT_RUN", f"exit {rc}, {len(outs)} lines for {len(rec.jobs)} jobs: " + se[-300:])
        hb = res["info"].get("closureat_helper-binary-sha256")
        if not (isinstance(hb, str) and HEX64.fullmatch(hb)):
            return _infra(res, "post-s2a", "CLOSUREAT_UNATTESTED", "the launcher did not attest a 64-hex helper binary hash; an answer from an unattested helper is not accepted")
        try:
            for job, line in zip(rec.jobs, outs):
                answers[job] = P.parse_helper_output(line, job[3], res["info"].get("closureat_helper-binary-sha256"), trusted=True)
        except P.ClosureAtUnavailable as e:
            return _infra(res, "post-s2a", "CLOSUREAT_MALFORMED", str(e))
    v = P.evaluate(inp_post, rec)
    try:
        pr = P.evidence_record(v)
    except P.UntrustedVerdictError as e:
        return _infra(res, "post-s2a", "NOT_EVIDENCE", str(e))
    res["info"]["closure_helper_binary_sha256"] = pr.get("closure_helper_binary_sha256")
    res["post"] = {"result": pr["result"], "rule": pr.get("rule"), "code": pr.get("code"), "detail": pr.get("detail"), "rows": pr.get("rows")}
    if pr.get("code") in INFRA_POST_CODES:
        return _infra(res, "post-s2a", pr["code"], str(pr.get("detail")))
    if pr["result"] not in ("BINDING_MATCH", "REJECT", "HALT"):
        return _infra(res, "post-s2a", "POST_RESULT_UNKNOWN", str(pr["result"]))
    res["outcome"], res["stage"] = pr["result"], "post-s2a"
    res["reason"] = {"rule": pr.get("rule"), "code": pr.get("code")}
    return res
