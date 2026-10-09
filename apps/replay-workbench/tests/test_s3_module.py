import json
import os
import tempfile
import unittest

from . import fakes
from workbench.modules.s3 import S3Module


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.t = self.tmp.name
        self.profile = fakes.test_profile()
        self.managed = os.path.join(self.t, "managed")
        self.lean = os.path.join(self.t, "lean", "bin")
        self.root = fakes.build_package(self.managed, self.profile, self.lean)
        self.mod = S3Module(self.profile)
        self.tmpdir = os.path.join(self.t, "jt")
        os.makedirs(self.tmpdir)

    def ctx(self, **kw):
        return fakes.ScriptedCtx(self.tmpdir, fakes.good_handler(self.profile, **kw))

    def inspect(self, signers=None, **kw):
        c = self.ctx(**kw)
        recs = self.mod.inspect(self.managed, {"lean_bin": self.lean, "allowed_signers": signers}, c)
        return {r["id"]: r for r in recs}, c

    def out_dir(self, verdict=fakes.VERDICT_BYTES, info=None):
        d = os.path.join(self.t, "out" + str(len(os.listdir(self.t))))
        os.makedirs(d)
        if verdict is not None:
            with open(os.path.join(d, "verdict.json"), "wb") as f:
                f.write(verdict)
        if info is not None:
            with open(os.path.join(d, "run-info.json"), "wb") as f:
                f.write(info)
        return d

    def collect(self, exit_, verdict=fakes.VERDICT_BYTES, info=fakes.dumps(fakes.good_info()), mod=None):
        ex = exit_ if isinstance(exit_, dict) else {"wrapper_exit": exit_}
        return (mod or self.mod).collect(ex, self.out_dir(verdict, info), self.managed)


class Readiness(Base):
    # case 3
    def test_all_pass_has_no_blocking_row(self):
        recs, _ = self.inspect()
        self.assertEqual(self.mod.blocking(list(recs.values())), [], [r for r in recs.values() if r["status"] == "fail"])
        self.assertEqual(recs["sum-PACKAGE_SHA256SUMS"]["listed"], 1)
        self.assertEqual(recs["sum-frozen set"]["listed"], 2)
        self.assertEqual(recs["netns"]["method"], "-n")

    def test_silent_nonzero_checksum_status_blocks(self):
        recs, _ = self.inspect(sum_rc=1, sum_out="")
        r = recs["sum-PACKAGE_SHA256SUMS"]
        self.assertEqual(r["status"], "fail")
        self.assertIn("status 1", r["detail"])
        self.assertIn("printed nothing", r["detail"])
        self.assertTrue(self.mod.blocking(list(recs.values())))

    def test_checksum_text_alone_does_not_pass(self):
        recs, _ = self.inspect(sum_rc=1, sum_out="x: OK\n")
        self.assertEqual(recs["sum-frozen set"]["status"], "fail")

    def test_hash_mismatch_blocks(self):
        with open(os.path.join(self.root, "verify_offline.sh"), "ab") as f:
            f.write(b"# tampered\n")
        recs, _ = self.inspect()
        self.assertEqual(recs["sha-verify_offline.sh"]["status"], "fail")

    def test_missing_lean_blocks(self):
        os.remove(os.path.join(self.lean, "lake"))
        recs, _ = self.inspect()
        self.assertEqual(recs["lean-bin"]["status"], "fail")
        self.assertEqual(recs["preflight"]["status"], "not_checked")

    def test_namespace_failure_blocks_with_diagnostic(self):
        c = fakes.ScriptedCtx(self.tmpdir, lambda a, cwd: fakes.RunResult(1, "", "unshare: unshare failed: Operation not permitted") if a[0] == "unshare" else fakes.good_handler(self.profile)(a, cwd))
        recs = {r["id"]: r for r in self.mod.inspect(self.managed, {"lean_bin": self.lean, "allowed_signers": None}, c)}
        self.assertEqual(recs["netns"]["status"], "fail")
        self.assertIn("Operation not permitted", recs["netns"]["detail"])

    def test_signature_not_checked_without_file(self):
        recs, c = self.inspect()
        self.assertEqual(recs["sigcheck-v0.1.0-s3-accepted"]["status"], "not_checked")
        self.assertIn("Signature not checked", recs["sigcheck-v0.1.0-s3-accepted"]["detail"])
        self.assertEqual(recs["sigpresent-v0.1.0-s3-accepted"]["status"], "pass")      # presence shown separately
        self.assertFalse(any("verify-tag" in x["argv"] for x in c.calls))

    def test_signature_checked_with_file(self):
        recs, c = self.inspect(signers="/abs/allowed")
        self.assertEqual(recs["sigcheck-v0.1.0-s3-accepted"]["status"], "pass")
        recs, _ = self.inspect(signers="/abs/allowed", sig_ok=False)
        self.assertEqual(recs["sigcheck-v0.1.0-s3-accepted"]["status"], "fail")

    def test_readiness_never_runs_wrapper_or_runner(self):
        _, c = self.inspect()
        flat = [" ".join(x["argv"]) for x in c.calls]
        self.assertFalse(any("verify_offline.sh" in f or "s3c_verify.py" in f for f in flat))
        self.assertFalse(any(f.startswith(("sudo", "pip", "apt", "curl", "wget", "sysctl")) for f in flat))


class Command(Base):
    # case 4
    def test_fixed_argv_env_and_fresh_output(self):
        out = os.path.join(self.t, "fresh-out")
        c = self.ctx()
        cmd = self.mod.command(self.managed, {"lean_bin": self.lean, "allowed_signers": "/abs/signers"}, out, c)
        self.assertEqual(cmd["argv"], ["unshare", "-n", "--", "bash", os.path.join(self.root, "verify_offline.sh"), out])
        self.assertTrue(os.path.isabs(cmd["argv"][-1]))
        for forbidden in ("--no-offline", "--pinned", "--_inner", "--expected", "--fixture"):
            self.assertNotIn(forbidden, " ".join(cmd["argv"]))
        self.assertEqual(cmd["env"]["LEAN_BIN"], self.lean)
        self.assertEqual(cmd["env"]["ALLOWED_SIGNERS"], "/abs/signers")
        # references are not runner inputs
        self.assertFalse(any("verdict.json" in a for a in cmd["argv"]))
        self.assertFalse(any("verdict.json" in v for v in cmd["env"].values()))

    def test_unshare_rn_only_when_n_fails(self):
        def h(a, cwd):
            if a[:2] == ["unshare", "-n"]:
                return fakes.RunResult(1, "", "denied")
            return None
        cmd = self.mod.command(self.managed, {"lean_bin": self.lean}, os.path.join(self.t, "o"), fakes.ScriptedCtx(self.tmpdir, h))
        self.assertEqual(cmd["argv"][:3], ["unshare", "-rn", "--"])

    def test_no_namespace_means_no_command(self):
        h = lambda a, cwd: fakes.RunResult(1, "", "denied") if a[0] == "unshare" else None
        with self.assertRaises(RuntimeError):
            self.mod.command(self.managed, {"lean_bin": self.lean}, os.path.join(self.t, "o"), fakes.ScriptedCtx(self.tmpdir, h))

    def test_existing_output_directory_refused(self):
        os.makedirs(os.path.join(self.t, "exists"))
        with self.assertRaises(RuntimeError):
            self.mod.command(self.managed, {"lean_bin": self.lean}, os.path.join(self.t, "exists"), self.ctx())

    def test_overrides_are_stripped(self):
        host = {"PATH": "/usr/bin:/bin", "HOME": "/home/x", "VERIFY_OFFLINE_TEST_EXPECT": "/evil", "VERIFY_OFFLINE_SOURCE_ONLY": "1", "BASH_ENV": "/evil", "ENV": "/evil",
                "PYTHONPATH": "/evil", "PYTHONSTARTUP": "/evil", "LD_PRELOAD": "/evil", "LD_LIBRARY_PATH": "/evil", "GIT_DIR": "/evil", "RUSTC_WRAPPER": "/evil", "CC": "/evil", "LANG": "C"}
        env = self.mod.build_env({"lean_bin": self.lean, "allowed_signers": None}, self.tmpdir, host_env=host)
        for k in ("VERIFY_OFFLINE_TEST_EXPECT", "VERIFY_OFFLINE_SOURCE_ONLY", "BASH_ENV", "ENV", "PYTHONPATH", "PYTHONSTARTUP", "LD_PRELOAD", "LD_LIBRARY_PATH", "GIT_DIR", "RUSTC_WRAPPER", "CC"):
            self.assertNotIn(k, env)
        self.assertEqual(env["HOME"], "/home/x")
        self.assertNotIn("ALLOWED_SIGNERS", env)


class Collect(Base):
    # case 5
    def test_wrapper0_valid_records_is_match_with_badge(self):
        r = self.collect(0)
        self.assertEqual(r["execution"], {"status": "COMPLETED", "reason": None})
        self.assertEqual(r["p10"]["outcome"], "BINDING_MATCH")
        self.assertEqual(r["reproduction"]["status"], "MATCH")
        self.assertTrue(r["reproduction"]["badge"])
        self.assertTrue(all(c["ok"] for c in r["reproduction"]["checks"]))

    def test_synthetic_module_never_gets_badge(self):
        r = self.collect(0, mod=S3Module(self.profile, synthetic=True))
        self.assertEqual(r["reproduction"]["status"], "MATCH")
        self.assertFalse(r["reproduction"]["badge"])
        self.assertTrue(r["synthetic"])

    # case 6
    def test_reject_halt_stay_distinct_with_wrapper_exit_1(self):
        for outcome, stage in (("REJECT", "post-s2a"), ("HALT", "s2a")):
            v = fakes.dumps(fakes.good_verdict(outcome=outcome, stage=stage, reason={"code": "X-" + outcome, "rule": "r1"}))
            r = self.collect(1, verdict=v)
            self.assertEqual(r["p10"]["outcome"], outcome)
            self.assertEqual(r["p10"]["reason"], {"code": "X-" + outcome, "rule": "r1"})
            self.assertEqual(r["reproduction"]["status"], "DIFFERENT")
            self.assertFalse(r["reproduction"]["badge"])
            self.assertEqual(r["execution"]["status"], "COMPLETED")
            self.assertEqual(r["wrapper_exit"], 1)
            self.assertIn("failed replay", r["wrapper_exit_meaning"])

    def test_s3_fail_is_preserved_and_not_evaluated(self):
        for outcome in ("S3-FAIL(packaging)", "S3-FAIL(infrastructure)"):
            v = fakes.dumps(fakes.good_verdict(outcome=outcome, stage="snapshot", reason={"code": "SNAP"}))
            r = self.collect(1, verdict=v)
            self.assertEqual(r["p10"]["outcome"], outcome)
            self.assertEqual(r["reproduction"]["status"], "NOT_EVALUATED")
            self.assertEqual(r["execution"]["status"], "COMPLETED")

    def test_binding_match_with_different_bytes_is_different(self):
        v = fakes.dumps(fakes.good_verdict(extra_field=1))
        r = self.collect(1, verdict=v)
        self.assertEqual(r["p10"]["outcome"], "BINDING_MATCH")
        self.assertEqual(r["reproduction"]["status"], "DIFFERENT")
        self.assertFalse(r["reproduction"]["badge"])

    def test_wrapper2_is_blocked_and_p10_not_evaluated(self):
        r = self.collect(2, verdict=None, info=None)
        self.assertEqual(r["execution"]["status"], "BLOCKED")
        self.assertEqual(r["p10"]["state"], "NOT_EVALUATED")
        self.assertEqual(r["reproduction"]["status"], "NOT_EVALUATED")

    def test_wrapper3_and_odd_exits_never_succeed(self):
        for we in (3, 4, 11, 12, 40, 127):
            r = self.collect(we)
            self.assertEqual(r["execution"]["status"], "APP_FAILURE", we)
            self.assertFalse(r["reproduction"]["badge"])
            self.assertIsNone(r["p10"]["outcome"])

    # case 7
    def test_wrapper0_with_bad_records_cannot_show_success(self):
        good_info = fakes.dumps(fakes.good_info())
        cases = {
            "missing verdict": dict(verdict=None),
            "malformed verdict": dict(verdict=b"{not json"),
            "duplicate keys": dict(verdict=b'{"outcome":"BINDING_MATCH","outcome":"BINDING_MATCH","stage":"s","reason":{"code":"c"}}'),
            "NaN": dict(verdict=b'{"outcome":"BINDING_MATCH","stage":"s","reason":{"code":"c"},"x":NaN}'),
            "unknown outcome": dict(verdict=fakes.dumps(fakes.good_verdict(outcome="ACCEPT"))),
            "missing run-info": dict(info=None),
            "malformed run-info": dict(info=b"[]"),
            "isolation false": dict(info=fakes.dumps(fakes.good_info(network_isolated=False))),
            "isolation int": dict(info=fakes.dumps(fakes.good_info(network_isolated=1))),
            "problems": dict(info=fakes.dumps(fakes.good_info(problems=["x"]))),
            "tcb mismatch": dict(info=fakes.dumps(fakes.good_info(tcb_source_mismatch=["f"]))),
            "bad runner hash": dict(info=fakes.dumps(fakes.good_info(runner_source_sha256={"s3c_verify.py": "0" * 64, "s3c_chain.py": "1" * 64}))),
            "bad entry hash": dict(info=fakes.dumps(fakes.good_info(entry_binary_sha256="0" * 64))),
            "pins missing": dict(verdict=fakes.dumps({k: v for k, v in fakes.good_verdict().items() if k != "executables_pinned"})),
            "pin false": dict(verdict=fakes.dumps(fakes.good_verdict(executables_pinned={"entry": True, "g5": False}))),
            "pin int": dict(verdict=fakes.dumps(fakes.good_verdict(executables_pinned={"entry": 1, "g5": 1}))),
            "not matching refs": dict(verdict=fakes.dumps(fakes.good_verdict(outcome="REJECT"))),
        }
        for name, kw in cases.items():
            kw.setdefault("verdict", fakes.VERDICT_BYTES)
            kw.setdefault("info", good_info)
            r = self.collect(0, **kw)
            self.assertFalse(r["reproduction"]["badge"], name)
            self.assertNotEqual(r["reproduction"]["status"], "MATCH", name)
            self.assertEqual(r["execution"]["status"], "APP_FAILURE", name)

    # case 8
    def test_all_pass_text_without_valid_records_is_not_success(self):
        # the textual line is not an input of collect(); with no valid records the result is an application failure
        r = self.collect(0, verdict=None, info=None)
        self.assertEqual(r["execution"]["status"], "APP_FAILURE")
        self.assertFalse(r["reproduction"]["badge"])

    # case 9
    def test_references_are_read_only_by_collect(self):
        self.assertIn("references", self.profile)
        # collect() reads references itself, after the run; command() / inspect() hash them but never pass them on
        cmd = self.mod.command(self.managed, {"lean_bin": self.lean}, os.path.join(self.t, "fresh"), self.ctx())
        self.assertFalse(any(rel.split("/")[-2] in " ".join(cmd["argv"]) for rel in self.profile["references"]))
        os.remove(os.path.join(self.root, "repo", "ref", "runner", "verdict.json"))
        r = self.collect(0)
        ids = {c["id"]: c["ok"] for c in r["reproduction"]["checks"]}
        self.assertFalse(ids["verdict-bytes-equal-runner"])
        self.assertTrue(ids["verdict-bytes-equal-runner-2"])
        self.assertEqual(r["execution"]["status"], "APP_FAILURE")

    def test_interrupted_runs_are_not_promoted(self):
        for ex in ({"wrapper_exit": None, "cancelled": True}, {"wrapper_exit": None, "deadline": True}, {"wrapper_exit": 0, "cancelled": True},
                   {"wrapper_exit": None, "signal": 9}, {"app_failure": "LOG_LIMIT_EXCEEDED"}):
            r = self.collect(ex)
            self.assertFalse(r["reproduction"]["badge"], ex)
            self.assertIsNone(r["p10"]["outcome"], ex)
            self.assertTrue(r["artifacts"]["verdict.json"]["present"], "partial records are still listed")
        self.assertEqual(self.collect({"wrapper_exit": None, "cancelled": True})["execution"]["status"], "CANCELLED")
        self.assertEqual(self.collect({"wrapper_exit": None, "deadline": True})["execution"]["reason"], "deadline")

    def test_original_bytes_are_hashed_not_canonicalised(self):
        raw = b'{"outcome":"BINDING_MATCH",   "stage":"s","reason":{"code":"c"}}'
        r = self.collect(1, verdict=raw)
        self.assertEqual(r["artifacts"]["verdict.json"]["sha256"], fakes.sha(raw))


if __name__ == "__main__":
    unittest.main()
