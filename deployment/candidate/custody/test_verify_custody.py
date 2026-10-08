#!/usr/bin/env python3
"""Focused tests for verify_custody.py (dummy keys only; no real key material is read).

  * a package-hash mismatch (either package) invokes NEITHER `age` NOR `tar` and exits nonzero (fake age/tar on PATH record every call);
  * positive run with a real age identity passes; a wrong identity fails (needs `age`, `openssl` and the `cryptography` package; skipped otherwise).
usage: python3 deployment/candidate/custody/test_verify_custody.py
"""
import base64, hashlib, json, os, shutil, stat, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "verify_custody.py")
sha = lambda b: hashlib.sha256(b).hexdigest()

def have(*tools): return all(shutil.which(t) for t in tools)
try:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec, ed25519
    HAVE_CRYPTO = True
except Exception:
    HAVE_CRYPTO = False

class Base(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.mkdtemp(prefix="vc-test-")
        self.addCleanup(shutil.rmtree, self.t, True)
        self.pk1, self.pk2 = os.path.join(self.t, "issuers.tar.age"), os.path.join(self.t, "one.tar.age")
        open(self.pk1, "wb").write(b"package one bytes"); open(self.pk2, "wb").write(b"package two bytes")
        self.identity = os.path.join(self.t, "id.txt"); open(self.identity, "w").write("not used by the fakes\n")
        self.manifest = os.path.join(self.t, "manifest.json")
        json.dump({"identity": {"issuer_key_thumbprints": {}, "operator_key_thumbprint": "", "receipt_key_thumbprint": "", "note_vkey": ""}}, open(self.manifest, "w"))
    def record(self, h1, h2):
        p = os.path.join(self.t, "record.json")
        json.dump({"packages": {"issuer-archive": {"sha256": h1, "files": []}, "one-use-receipt-checkpoint": {"sha256": h2, "files": []}}}, open(p, "w")); return p
    def run_script(self, rec, env=None):
        return subprocess.run([sys.executable, SCRIPT, "--identity", self.identity, "--issuers", self.pk1, "--one-use", self.pk2, "--manifest", self.manifest, "--record", rec],
                              capture_output=True, text=True, env=env)

class HashMismatchFailsClosed(Base):
    def fakes(self):
        d = os.path.join(self.t, "fakebin"); os.mkdir(d); self.calls = os.path.join(self.t, "calls.log")
        for n in ("age", "tar", "openssl"):
            p = os.path.join(d, n); open(p, "w").write(f'#!/bin/sh\necho "{n} $*" >> "{self.calls}"\nexit 0\n'); os.chmod(p, 0o755)
        env = dict(os.environ); env["PATH"] = d + os.pathsep + env["PATH"]; return env
    def check(self, h1, h2):
        env = self.fakes(); r = self.run_script(self.record(h1, h2), env)
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse(os.path.exists(self.calls), "age/tar/openssl was invoked: " + (open(self.calls).read() if os.path.exists(self.calls) else ""))
        self.assertIn("FAIL", r.stdout); self.assertNotIn("decrypt issuer-archive with", r.stdout); self.assertNotIn("ALL PASS", r.stdout)
        return r
    def test_first_hash_wrong(self): self.check("0" * 64, sha(open(self.pk2, "rb").read()))
    def test_second_hash_wrong(self): self.check(sha(open(self.pk1, "rb").read()), "0" * 64)
    def test_both_wrong(self): self.check("0" * 64, "f" * 64)
    def test_matching_hashes_do_reach_age(self):
        env = self.fakes(); r = self.run_script(self.record(sha(open(self.pk1, "rb").read()), sha(open(self.pk2, "rb").read())), env)
        self.assertTrue(os.path.exists(self.calls) and "age" in open(self.calls).read())   # control: the fakes do record calls when hashes match

@unittest.skipUnless(have("age", "age-keygen", "openssl", "tar") and HAVE_CRYPTO, "needs age, openssl, tar and cryptography")
class Positive(unittest.TestCase):
    def test_positive_and_wrong_identity(self):
        t = tempfile.mkdtemp(prefix="vc-test-"); self.addCleanup(shutil.rmtree, t, True)
        src = os.path.join(t, "src"); thumbs = {}
        def ec_key(path):
            k = ec.generate_private_key(ec.SECP256R1())
            open(path, "wb").write(k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
            n = k.public_key().public_numbers(); x, y = n.x.to_bytes(32, "big"), n.y.to_bytes(32, "big")
            return sha(bytes([0xA4, 0x01, 0x02, 0x20, 0x01, 0x21, 0x58, 0x20]) + x + bytes([0x22, 0x58, 0x20]) + y)
        for d in ("candidate-issuers", "candidate-receipt", "candidate-checkpoint"): os.makedirs(os.path.join(src, d))
        for n in ("volmax-owner", "admitter-one", "admitter-two", "intruder-x", "operator"): thumbs[n] = ec_key(os.path.join(src, "candidate-issuers", n + ".pem"))
        rk = ec_key(os.path.join(src, "candidate-receipt", "ts.pem"))
        seed = os.urandom(32); sk = ed25519.Ed25519PrivateKey.from_private_bytes(seed)
        pub = sk.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw); name = "test/log"
        vkey = name + "+" + sha(name.encode() + b"\n" + b"\x01" + pub)[:8] + "+" + base64.b64encode(b"\x01" + pub).decode()
        open(os.path.join(src, "candidate-checkpoint", "note.vkey"), "w").write(vkey + "\n")
        open(os.path.join(src, "candidate-checkpoint", "note.skey"), "w").write("PRIVATE+KEY+" + name + "+00000000+" + base64.b64encode(b"\x01" + seed).decode() + "\n")
        idf, idf2 = os.path.join(t, "id.txt"), os.path.join(t, "id2.txt")
        recipient = lambda f: [l for l in subprocess.run(["age-keygen", "-y", f], capture_output=True, text=True).stdout.split() if l.startswith("age1")][0]
        subprocess.run(["age-keygen", "-o", idf], capture_output=True); subprocess.run(["age-keygen", "-o", idf2], capture_output=True)
        pk1, pk2 = os.path.join(t, "issuers.tar.age"), os.path.join(t, "one.tar.age")
        for pk, dirs in ((pk1, ["candidate-issuers"]), (pk2, ["candidate-receipt", "candidate-checkpoint"])):   # streamed: no plaintext archive
            tr = subprocess.Popen(["tar", "--sort=name", "--owner=0", "--group=0", "--numeric-owner", "-C", src, "-cf", "-"] + dirs, stdout=subprocess.PIPE)
            subprocess.run(["age", "-r", recipient(idf), "-o", pk], stdin=tr.stdout, check=True); tr.wait()
        files = lambda *ds: sorted(os.path.join(d, f) for d in ds for f in os.listdir(os.path.join(src, d)))
        rec = os.path.join(t, "record.json")
        json.dump({"packages": {"issuer-archive": {"sha256": sha(open(pk1, "rb").read()), "files": files("candidate-issuers")},
                                "one-use-receipt-checkpoint": {"sha256": sha(open(pk2, "rb").read()), "files": files("candidate-receipt", "candidate-checkpoint")}}}, open(rec, "w"))
        man = os.path.join(t, "manifest.json")
        json.dump({"identity": {"issuer_key_thumbprints": {k: v for k, v in thumbs.items() if k != "operator"}, "operator_key_thumbprint": thumbs["operator"], "receipt_key_thumbprint": rk, "note_vkey": vkey}}, open(man, "w"))
        run = lambda ident: subprocess.run([sys.executable, SCRIPT, "--identity", ident, "--issuers", pk1, "--one-use", pk2, "--manifest", man, "--record", rec], capture_output=True, text=True)
        r = run(idf); self.assertEqual(r.returncode, 0, r.stdout); self.assertIn("ALL PASS", r.stdout)
        self.assertNotIn("PRIVATE", r.stdout + r.stderr); self.assertNotIn("BEGIN", r.stdout + r.stderr)
        r = run(idf2); self.assertNotEqual(r.returncode, 0); self.assertIn("FAIL decrypt issuer-archive", r.stdout)

if __name__ == "__main__":
    unittest.main(verbosity=2)
