#!/usr/bin/env python3
"""TEST HARNESS (not acceptance code): infrastructure faults inside the runner's inner process must end as S3-FAIL(infrastructure), exit 40, with verdict.json and a diagnostic
in run-info.json (when OUT is writable) and never as BINDING_MATCH, REJECT, HALT or an unclassified crash. The fault is injected in-process (no Lean, no chain run):
  * copying the entry or G5 executable fails with OSError;
  * the chain invocation raises an unexpected exception.
A control with a fake successful chain shows the harness itself can produce BINDING_MATCH. Usage errors keep exit 2.
usage: test_runner_faults.py"""
import json, os, shutil, sys, tempfile, unittest
from unittest import mock

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(REPO, "verifier", "runner"))
import s3c_verify as V
C = V.C


class Faults(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, self.t, True)
        self.cap = os.path.join(self.t, "cap"); os.makedirs(self.cap)
        for n in ("s1", "s2a", "s2b"): os.makedirs(os.path.join(self.t, n))
        for n in ("entry", "g5"): open(os.path.join(self.t, n), "wb").write(b"#!/bin/sh\n")
        self.pinned = os.path.join(self.t, "pinned.json"); open(self.pinned, "w").write("{}")
        self.out = os.path.join(self.t, "out"); self.calls = []
        self.args = V.parse_args(["--capture", self.cap, "--anchor", "0" * 64, "--out", self.out, "--s1", os.path.join(self.t, "s1"), "--s2a", os.path.join(self.t, "s2a"),
                                  "--s2b", os.path.join(self.t, "s2b"), "--entry", os.path.join(self.t, "entry"), "--g5", os.path.join(self.t, "g5"), "--pinned", self.pinned])

    def fake_run(self, log, argv, name, env=None, cwd=None):
        self.calls.append(name)
        if name == "preflight":
            json.dump({"selected_lean_bin_dir": "/lean"}, open(os.path.join(self.out, "preflight.json"), "w")); return 0, "", ""
        assert name == "g5", name
        snap = os.path.join(self.out, "snapshot")
        g = {"g5": "PASS", "anchor_checked": True, "root": snap}
        for k in ("request", "profile_artifact", "instance_commitment", "s1_instance"): g[k] = os.path.join(snap, k)
        return 0, json.dumps(g), ""

    def snapshot(self, src, dst):
        os.makedirs(dst)
        for k in ("request", "profile_artifact", "instance_commitment", "s1_instance"): open(os.path.join(dst, k), "wb").write(b"x")

    def run_inner(self, chain=None, copy_fault=False):
        real_copy = shutil.copyfile
        def copy(src, dst, *a, **k):
            if copy_fault and dst.endswith(os.sep + os.path.join("bin", "entry")): raise OSError(28, "No space left on device")
            return real_copy(src, dst, *a, **k)
        with mock.patch.object(V, "isolation_here", return_value=(True, "test")), mock.patch.object(V, "check_pins", return_value=None), \
             mock.patch.object(C.Log, "run", lambda log, argv, name, env=None, cwd=None: self.fake_run(log, argv, name)), mock.patch.object(V, "snapshot_capture", self.snapshot), \
             mock.patch.object(V.shutil, "copyfile", copy), mock.patch.object(C, "run_chain", chain or mock.Mock()):
            with mock.patch("sys.stdout"):
                return V.inner(self.args, "0" * 64, "test")

    def verdict(self): return json.load(open(os.path.join(self.out, "verdict.json"))), json.load(open(os.path.join(self.out, "run-info.json")))

    def assert_infra(self, rc, code, stage):
        self.assertEqual(rc, 40)
        v, info = self.verdict()
        self.assertEqual((v["outcome"], v["stage"], v["reason"]), ("S3-FAIL(infrastructure)", stage, {"code": code}))
        self.assertNotIn(v["outcome"], ("BINDING_MATCH", "REJECT", "HALT"))
        self.assertTrue(info["problems"] and code not in ("BindingMatch",))
        return info

    def test_control_fake_successful_chain_is_binding_match(self):
        ok = {"outcome": "BINDING_MATCH", "stage": "post-s2a", "reason": {"code": "BindingMatch", "rule": None}}
        rc = self.run_inner(chain=mock.Mock(return_value=ok)); self.assertEqual(rc, 0); self.assertEqual(self.verdict()[0]["outcome"], "BINDING_MATCH")

    def test_executable_copy_failure_is_infrastructure(self):
        info = self.assert_infra(self.run_inner(copy_fault=True), "EXECUTABLE_COPY", "preflight")
        self.assertIn("No space left", info["problems"][0]); self.assertEqual(self.calls, ["preflight"])   # G5 and the chain never ran

    def test_unexpected_chain_exception_is_infrastructure_without_a_p10_reason(self):
        info = self.assert_infra(self.run_inner(chain=mock.Mock(side_effect=RuntimeError("boom"))), "UNEXPECTED_EXCEPTION", "chain")
        self.assertIn("RuntimeError: boom", info["problems"][0])
        v, _ = self.verdict(); self.assertIsNone(v["post"]); self.assertIsNone(v["s2b"])

    def test_unexpected_oserror_from_the_chain_is_infrastructure(self):
        self.assert_infra(self.run_inner(chain=mock.Mock(side_effect=OSError(5, "Input/output error"))), "UNEXPECTED_EXCEPTION", "chain")

    def test_usage_error_keeps_exit_2(self):
        with self.assertRaises(SystemExit) as cm, mock.patch("sys.stderr"):
            V.main(["--capture", os.path.join(self.t, "absent"), "--anchor", "0" * 64, "--out", self.out, "--s1", self.t, "--s2a", self.t, "--s2b", self.t, "--entry", os.path.join(self.t, "entry"), "--g5", os.path.join(self.t, "g5")])
        self.assertEqual(cm.exception.code, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
