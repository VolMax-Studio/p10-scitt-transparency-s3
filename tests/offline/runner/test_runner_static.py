#!/usr/bin/env python3
"""TEST HARNESS (not acceptance code): static and command-line properties of the candidate runner that need no Lean.

  * reused spike functions are textually identical to the spike's (REUSED markers in s3c_chain.py);
  * PINNED_INPUTS.json hashes match the current TCB source files;
  * the runner has no option and no string constant that could carry an expectation, a fixture, generator metadata or producer tooling;
  * usage errors, pin failures and an unavailable network isolation end as the contract says (exit 2 / infrastructure, no stage run).

usage: test_runner_static.py --s1 D --s2a D --s2b D --entry BIN --g5 BIN --capture D --anchor-file F [--lean-bin-dir D]
"""
import argparse, ast, hashlib, json, os, re, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
RUNNER = os.path.join(REPO, "verifier", "runner")
A = None


def segs(path, names):
    src = open(path).read(); t = ast.parse(src); out = {}
    for n in t.body:
        if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name in names: out[n.name] = ast.get_source_segment(src, n)
        if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", None) in names: out[n.targets[0].id] = ast.get_source_segment(src, n)
    return out


def run(extra, out, env=None, anchor_file=None):
    argv = [sys.executable, "-B", os.path.join(RUNNER, "s3c_verify.py"), "--capture", A.capture, "--anchor-file", anchor_file or A.anchor_file, "--out", out,
            "--s1", A.s1, "--s2a", A.s2a, "--s2b", A.s2b, "--entry", A.entry, "--g5", A.g5] + (["--lean-bin-dir", A.lean_bin_dir] if A.lean_bin_dir else []) + extra
    return subprocess.run(argv, capture_output=True, text=True, env=env)


class Static(unittest.TestCase):
    def test_reused_functions_are_textually_identical(self):
        chain = open(os.path.join(RUNNER, "s3c_chain.py")).read()
        marked = re.findall(r"# REUSED from spike/glue/s3_spike_chain.py [^\n]*: (\w+)", chain)
        self.assertEqual(sorted(marked), sorted(['HEX64', 'sha256_file', 'sha256_bytes', 'Log', 'compose_s2b', 'frozen_a12_a14', 'INFRA_POST_CODES']))   # the lenient spike readers were replaced in r13
        a = segs(os.path.join(REPO, "spike", "glue", "s3_spike_chain.py"), set(marked)); b = segs(os.path.join(RUNNER, "s3c_chain.py"), set(marked))
        self.assertEqual(sorted(a), sorted(marked)); self.assertEqual(a, b)

    def test_pinned_hashes_match_sources(self):
        pins = json.load(open(os.path.join(RUNNER, "PINNED_INPUTS.json")))
        for rel, want in pins["tcb_sources"].items():
            self.assertEqual(hashlib.sha256(open(os.path.join(REPO, rel), "rb").read()).hexdigest(), want, rel)

    def test_no_expectation_fixture_or_producer_inputs(self):
        h = subprocess.run([sys.executable, os.path.join(RUNNER, "s3c_verify.py"), "--help"], capture_output=True, text=True).stdout
        opts = set(re.findall(r"--[a-z0-9-]+", h))
        self.assertEqual(opts, {"--help", "--capture", "--anchor", "--anchor-file", "--out", "--s1", "--s2a", "--s2b", "--entry", "--g5", "--lean-bin-dir", "--pinned", "--no-offline"})
        bad = re.compile(r"tB\.expected|expect\.json|PUBLIC_META|fixtures|producer|issuer_tool|MANIFEST|\.pem|private[ _-]?key", re.I)
        for f in ("s3c_verify.py", "s3c_chain.py"):
            t = ast.parse(open(os.path.join(RUNNER, f)).read())
            for n in ast.walk(t):
                if isinstance(n, ast.Constant) and isinstance(n.value, str) and not (isinstance(getattr(n, "parent", None), ast.Expr)):
                    if bad.search(n.value) and len(n.value) < 200:    # short string constants (paths, option names); docstrings are long
                        self.fail(f"{f}: suspicious string constant {n.value!r}")


class Cli(unittest.TestCase):
    def setUp(self): self.tmp = tempfile.mkdtemp()

    def test_usage_errors_exit_2(self):
        for extra, anchor in ((["--anchor", "xyz"], None),):
            r = subprocess.run([sys.executable, "-B", os.path.join(RUNNER, "s3c_verify.py"), "--capture", A.capture, "--anchor", "xyz", "--out", os.path.join(self.tmp, "o1"),
                                "--s1", A.s1, "--s2a", A.s2a, "--s2b", A.s2b, "--entry", A.entry, "--g5", A.g5], capture_output=True, text=True)
            self.assertEqual(r.returncode, 2, r.stderr)
        # neither --anchor nor --anchor-file
        r = subprocess.run([sys.executable, "-B", os.path.join(RUNNER, "s3c_verify.py"), "--capture", A.capture, "--out", os.path.join(self.tmp, "o2"), "--s1", A.s1, "--s2a", A.s2a,
                            "--s2b", A.s2b, "--entry", A.entry, "--g5", A.g5], capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)
        # non-empty out
        os.makedirs(os.path.join(self.tmp, "o3")); open(os.path.join(self.tmp, "o3", "x"), "w").close()
        self.assertEqual(run([], os.path.join(self.tmp, "o3")).returncode, 2)

    def _base(self, out, anchor=None, capture=None, extra=()):
        return [sys.executable, "-B", os.path.join(RUNNER, "s3c_verify.py"), "--capture", capture or A.capture, "--anchor", anchor or "0" * 64, "--out", out, "--s1", A.s1, "--s2a", A.s2a,
                "--s2b", A.s2b, "--entry", A.entry, "--g5", A.g5] + (["--lean-bin-dir", A.lean_bin_dir] if A.lean_bin_dir else []) + list(extra)

    def test_direct_inner_call_does_not_skip_the_isolation_test(self):
        # r13 regression: a direct `--_inner "unshare -n"` call WITHOUT any isolation used to be recorded as network_isolated=true
        r = subprocess.run(self._base(os.path.join(self.tmp, "i1"), extra=["--_inner", "unshare -n"]), capture_output=True, text=True)
        self.assertEqual(r.returncode, 40, r.stdout + r.stderr)
        v = json.load(open(os.path.join(self.tmp, "i1", "verdict.json"))); info = json.load(open(os.path.join(self.tmp, "i1", "run-info.json")))
        self.assertEqual((v["outcome"], v["stage"], v["reason"]["code"]), ("S3-FAIL(infrastructure)", "preflight", "NETWORK_ISOLATION"))
        self.assertIs(info["network_isolated"], False)
        self.assertEqual(info.get("commands", []), [])                                    # no stage ran
        self.assertEqual(info["launcher_claim_not_evidence"], "unshare -n")

    def test_no_offline_records_the_actual_network_state(self):
        r = subprocess.run(self._base(os.path.join(self.tmp, "i2"), extra=["--no-offline"]), capture_output=True, text=True)
        self.assertEqual(r.returncode, 30, r.stdout + r.stderr)                           # wrong anchor: G5 failure, so the connected run reached G5
        info = json.load(open(os.path.join(self.tmp, "i2", "run-info.json")))
        self.assertIs(info["network_isolated"], False)                                    # measured here, not assumed from the flag

    def test_non_empty_out_is_refused_on_every_invocation_path(self):
        for n, extra in enumerate(([], ["--_inner", "unshare -n"], ["--no-offline"])):
            d = os.path.join(self.tmp, f"e{n}"); os.makedirs(d); open(os.path.join(d, "stale"), "w").close()
            r = subprocess.run(self._base(d, extra=extra), capture_output=True, text=True)
            self.assertEqual(r.returncode, 2, (extra, r.stdout, r.stderr))
            self.assertEqual(os.listdir(d), ["stale"])                                    # nothing was written into it

    def test_executable_identity_pin_is_checked_before_the_binary_runs(self):
        pins = json.load(open(os.path.join(RUNNER, "PINNED_INPUTS.json")))
        self.assertTrue(all(pins["executables"][k]["sha256"] for k in ("entry", "g5")))   # the candidate pins both executables
        pins["executables"]["g5"]["sha256"] = "0" * 64
        pf = os.path.join(self.tmp, "bad-pins.json"); json.dump(pins, open(pf, "w"))
        r = subprocess.run(self._base(os.path.join(self.tmp, "x1"), extra=["--pinned", pf]), capture_output=True, text=True)
        self.assertEqual(r.returncode, 40, r.stdout + r.stderr)
        v = json.load(open(os.path.join(self.tmp, "x1", "verdict.json"))); info = json.load(open(os.path.join(self.tmp, "x1", "run-info.json")))
        self.assertEqual((v["stage"], v["reason"]["code"]), ("preflight", "EXECUTABLE_HASH"))
        self.assertNotIn("g5", [c["name"] for c in info["commands"]])                     # G5 never ran

    def test_wrong_pin_is_infrastructure_and_runs_no_stage(self):
        r = subprocess.run([sys.executable, "-B", os.path.join(RUNNER, "s3c_verify.py"), "--capture", A.capture, "--anchor-file", A.anchor_file, "--out", os.path.join(self.tmp, "o4"),
                            "--s1", A.s1, "--s2a", A.s2a, "--s2b", A.s2a, "--entry", A.entry, "--g5", A.g5], capture_output=True, text=True)    # S2a checkout given as S2b
        self.assertEqual(r.returncode, 40, r.stdout + r.stderr)
        v = json.load(open(os.path.join(self.tmp, "o4", "verdict.json")))
        self.assertEqual((v["outcome"], v["stage"], v["reason"]["code"]), ("S3-FAIL(infrastructure)", "preflight", "PIN_S2B"))
        info = json.load(open(os.path.join(self.tmp, "o4", "run-info.json")))
        self.assertEqual([c["name"] for c in info.get("commands", [])], [])                       # not even G5 ran

    def test_unavailable_isolation_is_infrastructure(self):
        env = dict(os.environ, PATH="/nonexistent")
        r = run([], os.path.join(self.tmp, "o5"), env=env)
        self.assertEqual(r.returncode, 40, r.stdout + r.stderr)
        v = json.load(open(os.path.join(self.tmp, "o5", "verdict.json")))
        self.assertEqual((v["stage"], v["reason"]["code"]), ("preflight", "NETWORK_ISOLATION"))

    def test_wrong_anchor_is_packaging_failure_and_only_g5_runs(self):
        r = subprocess.run([sys.executable, "-B", os.path.join(RUNNER, "s3c_verify.py"), "--capture", A.capture, "--anchor", "0" * 64, "--out", os.path.join(self.tmp, "o6"),
                            "--s1", A.s1, "--s2a", A.s2a, "--s2b", A.s2b, "--entry", A.entry, "--g5", A.g5] + (["--lean-bin-dir", A.lean_bin_dir] if A.lean_bin_dir else []), capture_output=True, text=True)
        self.assertEqual(r.returncode, 30, r.stdout + r.stderr)
        v = json.load(open(os.path.join(self.tmp, "o6", "verdict.json")))
        self.assertEqual((v["outcome"], v["stage"], v["reason"]["code"], v["g5"]["result"]), ("S3-FAIL(packaging)", "g5", "E_INDEX_ANCHOR_MISMATCH", "FAIL"))
        info = json.load(open(os.path.join(self.tmp, "o6", "run-info.json")))
        self.assertEqual([c["name"] for c in info["commands"]], ["preflight", "g5"])
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "o6", "s2b")))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    for k in ("s1", "s2a", "s2b", "entry", "g5", "capture", "anchor-file"): ap.add_argument("--" + k, required=True)
    ap.add_argument("--lean-bin-dir")
    A, rest = ap.parse_known_args()
    unittest.main(argv=[sys.argv[0]] + rest, verbosity=2)
