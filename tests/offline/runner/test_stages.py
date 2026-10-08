#!/usr/bin/env python3
"""TEST HARNESS (not acceptance code) for the candidate runner's stage logic. No Lean, no real S2b launchers: a fake S2b tree supplies the REAL post_s2a.py and the
real freeze record plus stub launchers, and a stub entry replays outputs of a committed real run (EXPLORATORY-RUN2). It shows that stage failures, malformed output and
missing helpers are infrastructure failures that never become HALT/REJECT/BINDING_MATCH, and that frozen HALT/REJECT results are propagated as such.

usage: test_stages.py --s2b DIR       (unittest; exits non-zero on failure)
"""
import argparse, json, os, shutil, stat, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(REPO, "verifier", "runner"))
import s3c_chain as C

RUN2 = os.path.join(REPO, "ts-prototype", "evidence", "lifecycle-run2")
S2B_REAL = None
rd = lambda p: open(p, "rb").read()


class Fake:
    def __init__(self, tmp):
        self.root = tmp
        self.s2b = os.path.join(tmp, "s2b"); os.makedirs(os.path.join(self.s2b, "orchestration")); os.makedirs(os.path.join(self.s2b, "frozen"))
        shutil.copy(os.path.join(S2B_REAL, "orchestration", "post_s2a.py"), os.path.join(self.s2b, "orchestration"))
        shutil.copy(os.path.join(S2B_REAL, "frozen", "StatementPayloadSchemaV0_r9_FREEZE.txt"), os.path.join(self.s2b, "frozen"))
        self.base_lines = open(os.path.join(RUN2, "chain/logs/002-s2a-runner.stdout")).read().splitlines()
        self.req = os.path.join(tmp, "request.cbor"); open(self.req, "wb").write(b"stub")
        cap = os.path.join(RUN2, "capture")
        self.pb, self.inst, self.ib = (os.path.join(cap, "material", n) for n in ("pB.json", "inst.bin", "iB.json"))
        self.s2a = os.path.join(tmp, "s2a"); os.makedirs(self.s2a)
        self.entry = os.path.join(tmp, "entry.py")
        open(self.entry, "w").write(f"""#!{sys.executable}
import json, os, shutil, sys
a = sys.argv; out = a[a.index('--out') + 1]; os.makedirs(out, exist_ok=True)
cfg = json.load(open({json.dumps(os.path.join(tmp, 'entry.json'))}))
src = {json.dumps(os.path.join(RUN2, 'chain/cases/EXPLORATORY-RUN2/s2b'))}
if cfg.get('result') == 'real':
    shutil.copy(os.path.join(src, 'result.json'), out)
elif cfg.get('result') is not None:
    json.dump(cfg['result'], open(os.path.join(out, 'result.json'), 'w'))
if cfg.get('files', True):
    for n in ('tB.bin', 'target.leaf_index.txt', 'target.payload.bin', 'target.sub.txt'):
        shutil.copy(os.path.join(src, n), out)
sys.exit(cfg['rc'])
""")
        os.chmod(self.entry, 0o755)
        self.set_entry(rc=0, result="real")
        self.set_s2a(self.base_lines)
        self.set_closureat(rc=1, out="")

    def set_entry(self, **cfg): json.dump(cfg, open(os.path.join(self.root, "entry.json"), "w"))

    def _launcher(self, name, rc, lines, stderr=()):
        p = os.path.join(self.s2b, "orchestration", name)
        with open(p, "w") as fh:
            fh.write("#!/usr/bin/env bash\n" + "".join(f"echo '{l}' >&2\n" for l in stderr) + "cat <<'EOF_STUB'\n" + "\n".join(lines) + ("\n" if lines else "") + "EOF_STUB\nexit %d\n" % rc)
        os.chmod(p, 0o755)

    def set_s2a(self, lines, rc=0): self._launcher("launch_s2a_runner.sh", rc, lines)

    def set_closureat(self, rc, out, attest=True):
        self._launcher("launch_closureat.sh", rc, out.splitlines() if out else [], ["helper-binary-sha256 " + "ab" * 32] if attest else [])

    def run(self, name):
        out = os.path.join(self.root, "out-" + name); os.makedirs(out)
        inp = C.ChainInputs(self.req, self.pb, self.inst, self.ib, None)
        return C.run_chain(inp, out, self.s2b, self.s2a, self.entry, C.Log(out))


class Stages(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(); self.f = Fake(self.tmp)

    def tearDown(self): shutil.rmtree(self.tmp, ignore_errors=True)

    def check(self, r, outcome, stage=None, code=None):
        self.assertEqual(r["outcome"], outcome, r)
        if stage: self.assertEqual(r["stage"], stage, r)
        if code: self.assertEqual((r["reason"] or {}).get("code"), code, r)

    # ---- S2B / composition
    def test_entry_without_result_is_infrastructure(self):
        self.f.set_entry(rc=0, result=None, files=False)
        self.check(self.f.run("a"), "S3-FAIL(infrastructure)", "s2b", "ENTRY_RESULT")

    def test_entry_exit_must_match_status(self):
        self.f.set_entry(rc=10, result="real")      # result.json says Verified
        self.check(self.f.run("a"), "S3-FAIL(infrastructure)", "s2b", "ENTRY_EXIT_MISMATCH")

    def test_unknown_status_is_infrastructure(self):
        self.f.set_entry(rc=2, result={"status": "TransportError"}, files=False)
        self.check(self.f.run("a"), "S3-FAIL(infrastructure)", "s2b", "ENTRY_RESULT")

    def test_target_failure_is_packaging(self):
        self.f.set_entry(rc=20, result=None, files=False)
        self.check(self.f.run("a"), "S3-FAIL(packaging)", "s2b", "TARGET_EXTRACTION")

    def test_binding_invalid_is_reject_and_stops(self):
        self.f.set_entry(rc=10, result={"status": "Invalid", "reason": {"class": "Binding", "reason": "LeafInputDomainViolation"}}, files=False)
        r = self.f.run("a"); self.check(r, "REJECT", "s2b"); self.assertEqual(r["reason"]["reason"], "LeafInputDomainViolation")
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "out-a", "s2a_jobs.tsv")))      # no S2a call

    def test_replay_invalid_and_unavailable_are_halt(self):
        self.f.set_entry(rc=10, result={"status": "Invalid", "reason": {"class": "Replay", "reason": "RootMismatch"}}, files=False)
        self.check(self.f.run("a"), "HALT", "s2b")
        self.f.set_entry(rc=11, result={"status": "Unavailable", "reason": {"class": "Material", "reason": "MissingIndex"}}, files=False)
        self.check(self.f.run("b"), "HALT", "s2b")

    # ---- S2A
    def test_s2a_runner_failure_is_infrastructure(self):
        self.f.set_s2a([], rc=1); self.check(self.f.run("a"), "S3-FAIL(infrastructure)", "s2a", "S2A_RUNNER_NOT_RUN")

    def test_s2a_short_or_non_json_output(self):
        self.f.set_s2a(self.f.base_lines[:4]); self.check(self.f.run("a"), "S3-FAIL(infrastructure)", "s2a", "S2A_OUTPUT_COUNT")
        self.f.set_s2a(self.f.base_lines[:4] + ["not json"]); self.check(self.f.run("b"), "S3-FAIL(infrastructure)", "s2a", "S2A_OUTPUT_NOT_JSON")

    def test_s2a_codec_and_cov_errors(self):
        L = list(self.f.base_lines); L[0] = json.dumps({"op": "tb", "decode": True, "reencode_identical": False})
        self.f.set_s2a(L); self.check(self.f.run("a"), "S3-FAIL(infrastructure)", "s2a", "S2A_CODEC")
        L = list(self.f.base_lines); L[1] = json.dumps({"error": "boom"})
        self.f.set_s2a(L); self.check(self.f.run("b"), "S3-FAIL(infrastructure)", "s2a", "S2A_CODEC")
        L = list(self.f.base_lines); L[3] = json.dumps({"op": "cov", "result": {"outcome": "accept", "repr": "x"}})      # accept without evidence digest
        self.f.set_s2a(L); self.check(self.f.run("c"), "S3-FAIL(infrastructure)", "s2a", "S2A_COV_MALFORMED")

    def test_s2a_reject_and_halt_are_frozen_outcomes(self):
        L = list(self.f.base_lines); L[3] = json.dumps({"op": "cov", "result": {"outcome": "reject", "repr": "P10S2.CoverageOutcome.reject .c3_profileAfterFirstAdmission"}})
        self.f.set_s2a(L); r = self.f.run("a"); self.check(r, "REJECT", "s2a"); self.assertEqual(r["reason"], {"token": "c3_profileAfterFirstAdmission"})
        L = list(self.f.base_lines); L[3] = json.dumps({"op": "cov", "result": {"outcome": "halt", "repr": "P10S2.CoverageOutcome.halt .c2_subjectPayloadUnavailable"}})
        self.f.set_s2a(L); r = self.f.run("b"); self.check(r, "HALT", "s2a"); self.assertEqual(r["reason"], {"token": "c2_subjectPayloadUnavailable"})

    def test_e2e_must_be_explicit(self):
        L = list(self.f.base_lines); L[4] = json.dumps({"op": "e2e", "result": "maybe"})
        self.f.set_s2a(L); self.check(self.f.run("a"), "S3-FAIL(infrastructure)", "s2a", "S2A_E2E_MALFORMED")
        L = list(self.f.base_lines); L[4] = json.dumps({"op": "e2e", "result": False})
        self.f.set_s2a(L); self.check(self.f.run("b"), "S3-FAIL(infrastructure)", "s2a", "S2A_E2E_MALFORMED")

    # ---- closureAt (the S2A stub is the real recorded output, so the post stage reaches T5)
    def test_closureat_not_run_or_malformed_is_infrastructure(self):
        self.f.set_closureat(1, ""); self.check(self.f.run("a"), "S3-FAIL(infrastructure)", "post-s2a", "CLOSUREAT_NOT_RUN")
        self.f.set_closureat(0, "garbage line"); self.check(self.f.run("b"), "S3-FAIL(infrastructure)", "post-s2a", "CLOSUREAT_MALFORMED")
        self.f.set_closureat(0, ""); self.check(self.f.run("c"), "S3-FAIL(infrastructure)", "post-s2a", "CLOSUREAT_NOT_RUN")      # zero lines for one job

    def test_unattested_closureat_answer_is_not_accepted(self):
        real = open(os.path.join(RUN2, "chain/logs/003-closureat-batch.stdout")).read()
        self.f.set_closureat(0, real.strip(), attest=False)
        self.check(self.f.run("a"), "S3-FAIL(infrastructure)", "post-s2a", "CLOSUREAT_UNATTESTED")

    def test_attested_well_formed_answer_is_read(self):
        # a recorded real answer through a stub launcher that attests a (fake) helper hash: the harness's own stand-in; only shows the reading path, not helper authenticity
        real = open(os.path.join(RUN2, "chain/logs/003-closureat-batch.stdout")).read()
        self.f.set_closureat(0, real.strip())
        r = self.f.run("a")
        self.check(r, "BINDING_MATCH", "post-s2a")
        self.assertEqual(r["info"].get("closure_helper_binary_sha256"), "ab" * 32)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--s2b", required=True); a, rest = ap.parse_known_args()
    S2B_REAL = a.s2b
    unittest.main(argv=[sys.argv[0]] + rest, verbosity=2)
