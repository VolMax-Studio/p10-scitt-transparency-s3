#!/usr/bin/env python3
"""CANDIDATE S3-C chain stages (non-normative; see CONTRACT.md). Library used by s3c_verify.py and by the test harness.

Stages after G5: S2b entry -> composition (S2b prereg r7 s16.6) -> S2a runner -> post-S2a with the real closureAt helper.
Nothing here knows an expected verdict, an expected tB or a fixture: the only inputs are the explicit file paths of ChainInputs, which s3c_verify.py takes
exclusively from a successful anchored G5 result on its private snapshot of the capture, and the frozen A12-A14 digests read from the pinned S2b freeze record.

Readers of stage output validate INTERFACE STRUCTURE only (closed member sets, types, duplicate JSON keys, known enumerations, internal consistency of one stage's
outputs). They contain no P10 rule and no list of P10 reasons; a stage output that does not parse as the interface is an infrastructure failure, never an outcome.

Functions marked REUSED are copied verbatim from spike/glue/s3_spike_chain.py (candidate TCB code requiring review); the harness compares their source text with
the spike's. The strict readers below replace the spike's lenient ones (r13 correction pass). Successful execution adopts nothing.
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

# REUSED from spike/glue/s3_spike_chain.py (candidate TCB code requiring review): INFRA_POST_CODES
INFRA_POST_CODES = ("ClosureAtUnavailable", "ClosureAtInconsistent", "NOT_EVIDENCE")


# ---------------------------------------------------------------------------------------------------- new in this candidate

FORMAT = "P10-S3-C-Verdict-v0-candidate"
S2B_EXIT = {"Verified": 0, "Invalid": 10, "Unavailable": 11}
# Frozen S2b result classes (src/p10_replay/replay.rs ResultClass) and the combinations the frozen composition table (S2b prereg r7 s16.6) lists.
S2B_CLASSES = {"Request", "Replay", "Binding", "Material", "Capability"}
S2B_LISTED = {"Invalid": {"Request", "Replay", "Binding"}, "Unavailable": {"Material", "Capability"}}
TOKEN_SHAPE = re.compile(r"(?:c\d+[a-z]?|tb\d+)_[A-Za-z0-9_]+")          # shape of the frozen S2a reason constructors; NOT a list of reasons
COV_REPR = re.compile(r"P10S2\.CoverageOutcome\.(accept|reject|halt)(?: \((.*)\))?", re.S)
REASON_REPR = re.compile(r"P10S2\.(RejectReason|HaltReason)\.([A-Za-z0-9_]+)")


class StrictJsonError(ValueError):
    pass


def strict_loads(text):
    """json.loads that rejects duplicate object keys and NaN/Infinity (a duplicate key would otherwise let the last member silently win)."""
    def pairs(items):
        d = {}
        for k, v in items:
            if k in d:
                raise StrictJsonError(f"duplicate member {k!r}")
            d[k] = v
        return d

    def const(c):
        raise StrictJsonError(f"non-finite number {c}")
    return json.loads(text, object_pairs_hook=pairs, parse_constant=const)


class ChainInputs:
    """Explicit file paths. s3c_verify.py builds this ONLY from a successful anchored G5 result on its private snapshot."""

    def __init__(self, request, pb, inst, ib, retained_target_payload=None):
        self.request, self.pb, self.inst, self.ib, self.retained_target_payload = request, pb, inst, ib, retained_target_payload


def read_s2b_result(path):
    """Strict reading of the entry's result.json -> (obj, None) | (None, (code, message)). Interface structure only."""
    try:
        obj = strict_loads(open(path, encoding="utf-8").read())
    except (OSError, ValueError) as e:
        return None, ("ENTRY_RESULT", f"result.json unreadable or not strict JSON: {e}")
    if not isinstance(obj, dict) or obj.get("status") not in S2B_EXIT:
        return None, ("ENTRY_RESULT", f"result.json has no known status: {str(obj)[:120]}")
    st = obj["status"]
    if st in S2B_LISTED:
        r = obj.get("reason")
        if not (isinstance(r, dict) and isinstance(r.get("class"), str) and isinstance(r.get("reason"), str) and r["reason"].strip()):
            return None, ("S2B_REASON_MISSING", f"{st} result without a class and a non-empty reason")
        if r["class"] not in S2B_CLASSES:
            return None, ("S2B_UNKNOWN_CLASS", f"unknown S2b result class {r['class']!r}")
        if r["class"] not in S2B_LISTED[st]:
            return None, ("S2B_UNLISTED_COMBINATION", f"{st}({r['class']}) is not a combination of the frozen composition table")
    else:
        if not (isinstance(obj.get("checkpoint_size"), int) and not isinstance(obj.get("checkpoint_size"), bool) and isinstance(obj.get("transcript_sha256"), str) and HEX64.fullmatch(obj["transcript_sha256"])):
            return None, ("ENTRY_RESULT", "Verified result without an integer checkpoint_size and a 64-hex transcript_sha256")
    return obj, None


# ---- S2A runner output: closed schemas, per input and stage -------------------------------------------------------------------------

def _obj(line, op, allowed):
    try:
        o = strict_loads(line)
    except ValueError as e:
        return None, f"{op}: not strict JSON: {e}"
    if not isinstance(o, dict):
        return None, f"{op}: not a JSON object"
    if o.get("op") != op:
        return None, f"{op}: op {o.get('op')!r}"
    extra = set(o) - allowed - {"op"}
    if extra:
        return None, f"{op}: unknown members {sorted(extra)}"
    return o, None


def parse_codec(line, op):
    """tb / inst / pb job line -> ({'decode': bool, 'reencode_identical': bool|None}, None) | (None, error). A job-level `error` is an error (the job did not run)."""
    o, e = _obj(line, op, {"decode", "reencode_identical", "error"})
    if e:
        return None, e
    if "error" in o:
        return None, f"{op}: job error: {o['error']}"
    if not isinstance(o.get("decode"), bool):
        return None, f"{op}: decode is not a boolean"
    if o["decode"]:
        if not isinstance(o.get("reencode_identical"), bool):
            return None, f"{op}: decode=true without a boolean reencode_identical"
        return {"decode": True, "reencode_identical": o["reencode_identical"]}, None
    if "reencode_identical" in o:
        return None, f"{op}: decode=false with a reencode_identical member"
    return {"decode": False, "reencode_identical": None}, None


def parse_cov(line):
    """cov job line -> ({'error': str}, None) for a job-level error | ({'outcome', 'token', 'evidence_digest'}, None) | (None, error)."""
    o, e = _obj(line, "cov", {"result", "error"})
    if e:
        return None, e
    if ("result" in o) == ("error" in o):
        return None, "cov: exactly one of result and error is required"
    if "error" in o:
        return ({"error": o["error"]}, None) if isinstance(o["error"], str) else (None, "cov: error is not a string")
    r = o["result"]
    if not isinstance(r, dict) or set(r) - {"outcome", "evidence_digest", "repr"} or r.get("outcome") not in ("accept", "reject", "halt") or not isinstance(r.get("repr"), str):
        return None, f"cov: malformed result {str(r)[:120]}"
    m = COV_REPR.fullmatch(r["repr"])
    if not m or m.group(1) != r["outcome"]:
        return None, f"cov: repr {r['repr'][:80]!r} does not agree with outcome {r['outcome']!r}"
    if r["outcome"] == "accept":
        if "evidence_digest" not in r or not (isinstance(r["evidence_digest"], str) and HEX64.fullmatch(r["evidence_digest"])):
            return None, "cov: accept without a 64-hex evidence_digest"
        return {"outcome": "accept", "token": None, "evidence_digest": r["evidence_digest"]}, None
    if "evidence_digest" in r:
        return None, f"cov: {r['outcome']} with an evidence_digest"
    rm = REASON_REPR.fullmatch(m.group(2) or "")
    want = "RejectReason" if r["outcome"] == "reject" else "HaltReason"
    if not rm or rm.group(1) != want or not TOKEN_SHAPE.fullmatch(rm.group(2)):
        return None, f"cov: {r['outcome']} without a recognizable {want} token in {r['repr'][:100]!r}"
    return {"outcome": r["outcome"], "token": rm.group(2), "evidence_digest": None}, None


def parse_e2e(line):
    """e2e job line -> (True|False, None) only for an explicit `some` (with evidence_repr) or `none`."""
    o, e = _obj(line, "e2e", {"result", "evidence_repr", "error"})
    if e:
        return None, e
    if "error" in o:
        return None, f"e2e: job error: {o['error']}"
    if o.get("result") == "some" and isinstance(o.get("evidence_repr"), str):
        return True, None
    if o.get("result") == "none" and "evidence_repr" not in o:
        return False, None
    return None, f"e2e: result {o.get('result')!r} is neither an explicit some (with evidence_repr) nor none"


def analyze_s2a(lines):
    """The five S2A job lines (tb, inst, pb, cov, e2e) -> (result, None) | (None, (code, message)).

    Codec diagnostics are kept PER INPUT and never preempt an established frozen coverage outcome:
      * pb decode=false is a diagnostic; S2a itself reports c1_profileDigest / c1_profileDecode as a coverage REJECT, which is then the outcome;
      * the S2a `cov` job needs a decoding transcript and a decoding instance commitment; when the runner reports that it could not decode one, the frozen entry point
        produced NO coverage outcome. That is reported as an infrastructure failure with its own code (S2A_TRANSCRIPT_DECODE / S2A_INSTANCE_DECODE) and is never mapped to a
        P10 HALT or REJECT here (no frozen reason exists for it);
      * contradictory helper outputs (an outcome that cannot coexist with the codec results of the same run) are S2A_CONTRADICTION.
    """
    codec = {}
    for op, line in zip(("tb", "inst", "pb"), lines[:3]):
        c, e = parse_codec(line, op)
        if e:
            return None, ("S2A_" + op.upper() + "_JOB", e)
        codec[op] = c
    cov, e = parse_cov(lines[3])
    if e:
        return None, ("S2A_COV_MALFORMED", e)
    if "error" in cov:
        msg = cov["error"]
        if msg == "tB does not strict-decode":
            return (None, ("S2A_TRANSCRIPT_DECODE", "the S2a runner could not decode the transcript produced by S2b; no frozen coverage outcome exists")) if codec["tb"]["decode"] is False \
                else (None, ("S2A_CONTRADICTION", "cov reports an undecodable transcript but the tb job decoded it"))
        if msg == "instB does not strict-decode":
            return (None, ("S2A_INSTANCE_DECODE", "the S2a runner could not decode the instance commitment; no frozen coverage outcome exists")) if codec["inst"]["decode"] is False \
                else (None, ("S2A_CONTRADICTION", "cov reports an undecodable instance commitment but the inst job decoded it"))
        return None, ("S2A_COV_JOB_ERROR", msg)
    # an outcome exists: the runner decoded tB and instB to produce it
    if codec["tb"]["decode"] is not True or codec["inst"]["decode"] is not True:
        return None, ("S2A_CONTRADICTION", "cov produced an outcome although the tb or inst job reports a decode failure")
    if cov["outcome"] == "accept":
        bad = [op for op, c in codec.items() if c["decode"] is not True or c["reencode_identical"] is not True]
        if bad:
            return None, ("S2A_CONTRADICTION", f"cov accepted although the codec results of {bad} are not decode=true and reencode_identical=true")
        e2e, e = parse_e2e(lines[4])
        if e:
            return None, ("S2A_E2E_MALFORMED", e)
        return {"codec": codec, "cov": cov, "e2e": e2e}, None
    return {"codec": codec, "cov": cov, "e2e": None}, None


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
    res = _fresh()
    sys.path.insert(0, os.path.join(s2b, "orchestration"))
    import post_s2a as P   # unchanged S2b source

    # ---- A12-A14: frozen values from the pinned S2b freeze record
    try:
        with open(os.path.join(s2b, "frozen", "StatementPayloadSchemaV0_r9_FREEZE.txt"), encoding="utf-8") as fh:
            a12 = frozen_a12_a14(fh.read())
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
        return _infra(res, "s2b", err[0], err[1] + f" (exit {rc})")
    if rc != S2B_EXIT[r2b["status"]]:
        return _infra(res, "s2b", "ENTRY_EXIT_MISMATCH", f"exit {rc} does not belong to status {r2b['status']}")
    res["s2b"] = {"status": r2b["status"]}
    if r2b["status"] in S2B_LISTED:
        res["s2b"].update({"class": r2b["reason"]["class"], "reason": r2b["reason"]["reason"]})
    comp = compose_s2b(r2b)   # CMP (REUSED, applied only to a structurally validated result)
    if comp not in ("continue", "HALT", "REJECT"):
        return _infra(res, "s2b", "COMPOSITION", f"composition returned {comp!r}")
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
    if res["tB_sha256"] != r2b["transcript_sha256"]:
        return _infra(res, "s2b", "ENTRY_TB_MISMATCH", "tB.bin does not hash to the transcript_sha256 in result.json")
    res["s2b"]["checkpoint_size"] = r2b["checkpoint_size"]
    res["s2b"]["target_leaf_index"] = leaf_index

    # ---- S2A (one fresh Lean build): tb, inst, pb, cov, e2e on the exact files
    jobs = [["tb", tb], ["inst", inp.inst], ["pb", inp.pb], ["cov", tb, inp.pb, inp.inst], ["e2e", tb, inp.pb, inp.ib, inp.inst]]
    jf = os.path.join(out, "s2a_jobs.tsv")
    with open(jf, "w") as fh:
        fh.write("".join("\t".join(j) + "\n" for j in jobs))
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
    res["s2a_result_lines_sha256"] = [sha256_bytes(l.encode()) for l in lines]
    an, err = analyze_s2a(lines)
    if err:
        return _infra(res, "s2a", err[0], err[1])
    cov = an["cov"]
    res["s2a"] = {"outcome": cov["outcome"], "reason": cov["token"], "evidence_digest": cov["evidence_digest"], "e2e": None if an["e2e"] is None else ("some" if an["e2e"] else "none"),
                  "codec": an["codec"]}
    if cov["outcome"] != "accept":
        res["outcome"], res["stage"], res["reason"] = cov["outcome"].upper(), "s2a", {"token": cov["token"]}
        return res
    e2er = an["e2e"]

    # ---- POST (inputs from actual outputs only)
    try:
        with open(tb, "rb") as f1, open(inp.pb, "rb") as f2, open(inp.ib, "rb") as f3:
            inp_post = P.PostS2aInputs(True, f1.read(), f2.read(), f3.read(), leaf_index, tpay, tsub, bytes.fromhex(cov["evidence_digest"]), e2er, fz)
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
                p = os.path.join(cdir, f"{n}{nm}")
                with open(p, "wb") as fh:
                    fh.write(data)
                ps.append(p)
            cl.append("\t".join(ps + [str(k)]))
        jf2 = os.path.join(cdir, "jobs.tsv")
        with open(jf2, "w") as fh:
            fh.write("\n".join(cl) + "\n")
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
                answers[job] = P.parse_helper_output(line, job[3], hb, trusted=True)
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
