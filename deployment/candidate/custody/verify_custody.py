#!/usr/bin/env python3
"""Local custody verification (run by the key custodian on his own machine; standard library + `age` + `openssl` only).

Decrypts the two transit packages with the custodian's age identity, streaming `age -d | tar -x` into a private temporary directory (removed at the end), recomputes the PUBLIC
fingerprints of the keys inside and compares them with the candidate definition. It prints ONLY package hashes, public fingerprints and PASS/FAIL lines. It never prints,
copies or keeps key material, and it deletes nothing but its own temporary directory. Exit status 0 only if every check passes.

usage: verify_custody.py --identity AGE_IDENTITY_FILE --issuers issuer-archive.tar.age --one-use one-use-receipt-checkpoint.tar.age
                         [--manifest definition-manifest.json] [--record transit-record.json]
"""
import argparse, base64, hashlib, json, os, shutil, subprocess, sys, tempfile

ap = argparse.ArgumentParser()
ap.add_argument("--identity", required=True); ap.add_argument("--issuers", required=True); ap.add_argument("--one-use", required=True)
here = os.path.dirname(os.path.abspath(__file__))
ap.add_argument("--manifest", default=os.path.join(here, "..", "definition-manifest.json")); ap.add_argument("--record", default=os.path.join(here, "transit-record.json"))
a = ap.parse_args()
ok = True
def report(good, msg):
    global ok
    ok &= bool(good); print(("PASS " if good else "FAIL ") + msg)
sha = lambda b: hashlib.sha256(b).hexdigest()
man = json.load(open(a.manifest)); idn = man["identity"]; rec = json.load(open(a.record))

# FAIL CLOSED: both package hashes are checked before `age` or `tar` is ever invoked; any mismatch exits nonzero with nothing decrypted or extracted.
hash_ok = True
for label, path in (("issuer-archive", a.issuers), ("one-use-receipt-checkpoint", a.one_use)):
    h = sha(open(path, "rb").read())
    good = h == rec["packages"][label]["sha256"]; hash_ok &= good
    report(good, f"package {label} sha256 {h}")
if not hash_ok:
    print("FAILURES (package hash mismatch: nothing was decrypted or extracted)")
    sys.exit(1)

def run(cmd, stdin=None):
    return subprocess.run(cmd, input=stdin, capture_output=True)   # stderr captured, never echoed: it could quote paths or key text
def extract(pkg, dest):
    ag = subprocess.Popen(["age", "-d", "-i", a.identity, pkg], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    tr = subprocess.run(["tar", "-x", "-C", dest, "--no-same-owner", "--no-same-permissions", "-f", "-"], stdin=ag.stdout, stderr=subprocess.DEVNULL)
    ag.stdout.close(); return ag.wait() == 0 and tr.returncode == 0

P256_SPKI = bytes.fromhex("3059301306072a8648ce3d020106082a8648ce3d030107034200")
def ec_thumbprint(pem):
    r = run(["openssl", "pkey", "-in", pem, "-pubout", "-outform", "DER"])
    d = r.stdout
    if r.returncode or len(d) != 91 or d[:26] != P256_SPKI or d[26] != 4: return None
    x, y = d[27:59], d[59:91]
    return sha(bytes([0xA4, 0x01, 0x02, 0x20, 0x01, 0x21, 0x58, 0x20]) + x + bytes([0x22, 0x58, 0x20]) + y)
def note_check(skey_path, vkey_expected):
    s = open(skey_path).read().strip().split("+", 4)     # PRIVATE+KEY+<name>+<hash>+<base64(0x01||seed)>
    if len(s) != 5 or s[:2] != ["PRIVATE", "KEY"]: return None
    raw = base64.b64decode(s[4])
    if len(raw) != 33 or raw[0] != 1: return None
    r = run(["openssl", "pkey", "-inform", "DER", "-pubout", "-outform", "DER"], bytes.fromhex("302e020100300506032b657004220420") + raw[1:])
    if r.returncode or len(r.stdout) != 44: return None
    pub = r.stdout[-32:]; name = s[2]
    nl, one = b"\n", b"\x01"
    v = name + "+" + sha(name.encode() + nl + one + pub)[:8] + "+" + base64.b64encode(one + pub).decode()
    return v == vkey_expected

tmp = tempfile.mkdtemp(prefix="s3-custody-", dir="/dev/shm" if os.path.isdir("/dev/shm") else None)
os.chmod(tmp, 0o700)
try:
    d1, d2 = os.path.join(tmp, "a"), os.path.join(tmp, "b"); os.mkdir(d1); os.mkdir(d2)
    report(extract(a.issuers, d1), "decrypt issuer-archive with the supplied identity")
    report(extract(a.one_use, d2), "decrypt one-use-receipt-checkpoint with the supplied identity")
    for label, base in (("issuer-archive", d1), ("one-use-receipt-checkpoint", d2)):
        found = sorted(os.path.relpath(os.path.join(r, f), base) for r, _, fs in os.walk(base) for f in fs)
        report(found == sorted(rec["packages"][label]["files"]), f"{label} file inventory matches the record ({len(found)} files)")
    want = dict(idn["issuer_key_thumbprints"]); want["operator"] = idn["operator_key_thumbprint"]
    fname = {"volmax-owner": "volmax-owner", "admitter-one": "admitter-one", "admitter-two": "admitter-two", "intruder-x": "intruder-x", "operator": "operator"}
    for n, w in sorted(want.items()):
        got = ec_thumbprint(os.path.join(d1, "candidate-issuers", fname[n] + ".pem"))
        report(got == w, f"issuer key {n} fingerprint {got}")
    got = ec_thumbprint(os.path.join(d2, "candidate-receipt", "ts.pem"))
    report(got == idn["receipt_key_thumbprint"], f"Receipt key fingerprint {got}")
    vk = open(os.path.join(d2, "candidate-checkpoint", "note.vkey")).read().strip()
    report(vk == idn["note_vkey"], f"checkpoint verifier key {vk}")
    report(note_check(os.path.join(d2, "candidate-checkpoint", "note.skey"), idn["note_vkey"]) is True, "checkpoint signing key matches the verifier key")
except Exception as e:
    report(False, f"unexpected {type(e).__name__}")
finally:
    shutil.rmtree(tmp, ignore_errors=True)
print("ALL PASS" if ok else "FAILURES")
sys.exit(0 if ok else 1)
