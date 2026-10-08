#!/usr/bin/env python3
"""Packaging tests (not verifier tests): the two checksum checks of verify_offline.sh decide by the EXIT STATUS of `sha256sum -c`.
A synthetic package (fake runner stub, fake rustc/lean, throw-away Git repos) is run through the REAL wrapper in its test mode (expected values replaced via VERIFY_OFFLINE_TEST_EXPECT;
such a run can never report ALL PASS). Cases, for both checks (PACKAGE_SHA256SUMS and the frozen-set list):
  control          checksums fine           -> the runner stub IS reached (exit 3 = test mode), PASS lines
  real mismatch    a listed file differs    -> FAIL with sha256sum's diagnostics, exit 2, runner stub NOT invoked
  silent failure   sha256sum -c exits 7 with no output (simulated) -> FAIL naming the status, exit 2, runner stub NOT invoked
usage: python3 test_verify_offline.py"""
import os, shutil, stat, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "verify_offline.sh")
REAL_SHA = shutil.which("sha256sum")

def sh(cmd, cwd=None, env=None):
    return subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, check=True).stdout.strip()

def write(p, s, mode=None):
    os.makedirs(os.path.dirname(p), exist_ok=True); open(p, "w").write(s)
    if mode: os.chmod(p, mode)

def git_repo(d, files, tags=()):
    for n, s in files.items(): write(os.path.join(d, n), s)
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t", GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null")
    sh(["git", "init", "-q", d], env=env); sh(["git", "-C", d, "add", "-A"], env=env); sh(["git", "-C", d, "commit", "-q", "-m", "x"], env=env)
    for t in tags: sh(["git", "-C", d, "tag", "-a", t, "-m", "-----BEGIN SSH SIGNATURE-----\nsynthetic\n-----END SSH SIGNATURE-----"], env=env)
    return sh(["git", "-C", d, "rev-parse", "HEAD"], env=env)

STUB = """#!/usr/bin/env python3
import json, os, sys
a = sys.argv; out = a[a.index("--out") + 1]; os.makedirs(out, exist_ok=True)
open(os.environ["RUNNER_MARKER"], "w").write("ran")
open(out + "/verdict.json", "w").write("{}"); open(out + "/run-info.json", "w").write("{}")
"""

class Wrapper(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.mkdtemp(prefix="vo-test-"); self.addCleanup(shutil.rmtree, self.t, True)
        self.pkg = os.path.join(self.t, "pkg"); os.makedirs(self.pkg)
        shutil.copy(SCRIPT, os.path.join(self.pkg, "verify_offline.sh")); os.chmod(os.path.join(self.pkg, "verify_offline.sh"), 0o755)
        self.marker = os.path.join(self.t, "RUNNER_RAN")
        repo = os.path.join(self.pkg, "repo")
        head = git_repo(repo, {"spike/s3-entry/x": "x", "verifier/runner/s3c_verify.py": STUB, "frozen.txt": "frozen\n", "verifier/artifacts/s3-spike-entry": "e", "verifier/artifacts/s3-g5": "g",
                               "ts-prototype/evidence/s3b-capture/ANCHOR.sha256": "ab\n", "ts-prototype/evidence/s3b-capture/runner/verdict.json": "{}",
                               "ts-prototype/evidence/s3b-capture/runner-2/verdict.json": "{}"}, tags=("v0.1.0-s3a-frozen", "v0.1.0-s3-accepted"))
        self.sums_freeze = os.path.join(repo, "deployment/candidate/freeze-set.sha256")
        write(self.sums_freeze, sh([REAL_SHA, "frozen.txt"], cwd=repo) + "\n")
        deps = {n: git_repo(os.path.join(self.pkg, "deps", n), {"f": n}) for n in ("s1", "s2a", "s2b")}
        tag = lambda t: sh(["git", "-C", repo, "rev-parse", t])
        vsha = sh([REAL_SHA, os.path.join(repo, "ts-prototype/evidence/s3b-capture/runner/verdict.json")]).split()[0]
        self.expect = os.path.join(self.t, "expect.env")
        write(self.expect, f"EXPECT_HEAD={head}\nEXPECT_TAG_S3A={tag('v0.1.0-s3a-frozen')}\nEXPECT_TAG_ACC={tag('v0.1.0-s3-accepted')}\nEXPECT_VERDICT_SHA={vsha}\nEXPECT_ANCHOR=ab\n"
                              f"S1={deps['s1']}\nS2A={deps['s2a']}\nS2B={deps['s2b']}\n")
        self.fake = os.path.join(self.t, "fakebin"); write(os.path.join(self.fake, "rustc"), "#!/bin/sh\necho 'rustc 1.82.0 (synthetic)'\n", 0o755)
        self.lean = os.path.join(self.t, "lean"); [write(os.path.join(self.lean, n), "#!/bin/sh\n", 0o755) for n in ("lean", "lake")]
        write(os.path.join(self.pkg, "NOTE.txt"), "listed in the package manifest, not tracked by Git\n"); self.manifest()

    def manifest(self):   # PACKAGE_SHA256SUMS over every file except .git, itself and out/
        files = []
        for r, ds, fs in os.walk(self.pkg):
            ds[:] = [d for d in ds if d not in (".git", "out")]
            files += [os.path.relpath(os.path.join(r, f), self.pkg) for f in fs if f != "PACKAGE_SHA256SUMS"]
        write(os.path.join(self.pkg, "PACKAGE_SHA256SUMS"), sh([REAL_SHA] + sorted(files), cwd=self.pkg) + "\n")

    def silent_failure_for(self, name):   # sha256sum that exits 7 without any output when asked to check `name`, real otherwise
        write(os.path.join(self.fake, "sha256sum"), f'#!/bin/sh\ncase "$*" in *{name}*) exit 7;; esac\nexec {REAL_SHA} "$@"\n', 0o755)

    def run_wrapper(self):
        if os.path.exists(self.marker): os.remove(self.marker)
        env = dict(os.environ, PATH=self.fake + os.pathsep + os.environ["PATH"], LEAN_BIN=self.lean, VERIFY_OFFLINE_TEST_EXPECT=self.expect, RUNNER_MARKER=self.marker)
        return subprocess.run(["./verify_offline.sh", os.path.join(self.t, "out")], cwd=self.pkg, env=env, capture_output=True, text=True)

    def stopped(self, r, label):
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr); self.assertFalse(os.path.exists(self.marker), "the runner was invoked")
        self.assertIn("FAIL " + label, r.stdout); self.assertIn("STOP:", r.stdout); self.assertNotIn("ALL PASS:", r.stdout)

    # ---- control
    def test_control_reaches_the_runner(self):
        r = self.run_wrapper()
        self.assertTrue(os.path.exists(self.marker), r.stdout)                           # the synthetic package passes every check, so the runner stub runs
        self.assertEqual(r.returncode, 3, r.stdout)                                      # test mode never reports success
        for l in ("PASS PACKAGE_SHA256SUMS: all", "PASS frozen set (deployment/candidate/freeze-set.sha256): all 1 listed files match"): self.assertIn(l, r.stdout)
        self.assertNotIn("ALL PASS:", r.stdout)
    # ---- package manifest
    def test_package_manifest_real_mismatch(self):
        write(os.path.join(self.pkg, "NOTE.txt"), "tampered\n")
        r = self.run_wrapper(); self.stopped(r, "PACKAGE_SHA256SUMS: sha256sum -c exited with status 1"); self.assertIn("FAILED", r.stdout)
        self.assertIn("PASS frozen set", r.stdout)                                       # the other check is unaffected
    def test_package_manifest_silent_nonzero(self):
        self.silent_failure_for("PACKAGE_SHA256SUMS"); r = self.run_wrapper()
        self.stopped(r, "PACKAGE_SHA256SUMS: sha256sum -c exited with status 7"); self.assertIn("PASS frozen set", r.stdout)
    # ---- frozen set
    def test_frozen_set_real_mismatch(self):
        write(os.path.join(self.pkg, "repo/frozen.txt"), "changed\n"); self.manifest()    # keep the package manifest consistent so only the frozen-set check fails
        r = self.run_wrapper(); self.stopped(r, "frozen set (deployment/candidate/freeze-set.sha256): sha256sum -c exited with status 1"); self.assertIn("PASS PACKAGE_SHA256SUMS", r.stdout)
    def test_frozen_set_silent_nonzero(self):
        self.silent_failure_for("freeze-set.sha256"); r = self.run_wrapper()
        self.stopped(r, "frozen set (deployment/candidate/freeze-set.sha256): sha256sum -c exited with status 7"); self.assertIn("PASS PACKAGE_SHA256SUMS", r.stdout)

if __name__ == "__main__":
    unittest.main(verbosity=2)
