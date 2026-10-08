#!/usr/bin/env python3
"""Sanity: the independent facade/public-read checker must FAIL on tampered runs. Copies a run dir, applies one mutation, expects the named check to fail.
usage: s3check_mutations.py --run DIR --py PYTHON --s2b DIR --note-vkey V --origin O --ts-pub F --ts-iss I --work DIR"""
import argparse, json, os, shutil, subprocess, sys
ap = argparse.ArgumentParser()
for k in ("run", "py", "s2b", "note-vkey", "origin", "ts-pub", "ts-iss", "work"): ap.add_argument("--" + k, required=True)
a = ap.parse_args(); H = os.path.dirname(os.path.abspath(__file__))
def flip(p, off=-1):
    b = bytearray(open(p, "rb").read()); b[off] ^= 1; open(p, "wb").write(bytes(b))
def checkpoint_sig(p):
    b = bytearray(open(p, "rb").read()); b[-5] = ord("A") if b[-5] != ord("A") else ord("B"); open(p, "wb").write(bytes(b))   # inside the base64 signature
def drop_export(r): os.remove(os.path.join(r, "export", "000003.leaf_input"))
def dup_export(r): shutil.copy(os.path.join(r, "export", "000002.leaf_input"), os.path.join(r, "export", "000003.leaf_input"))
def wrong_root_resp(r):
    p = os.path.join(r, "returned", "000002.response.json"); j = json.load(open(p)); j["root"] = "00" * 32; json.dump(j, open(p, "w"))
M = {
 "receipt signature byte flipped": ("F5", lambda r: flip(os.path.join(r, "returned", "000004.receipt.cbor"))),
 "receipt proof path byte flipped": ("F5", lambda r: flip(os.path.join(r, "returned", "000004.receipt.cbor"), 60)),
 "public checkpoint signature altered": ("F3", lambda r: checkpoint_sig(os.path.join(r, "public-checkpoints", "000003.checkpoint"))),
 "export entry byte flipped": ("F1", lambda r: flip(os.path.join(r, "export", "000002.leaf_input"))),
 "export entry replaced by a duplicate of another": ("F2", dup_export),
 "facade-returned checkpoint differs from the public one": ("F4", lambda r: flip(os.path.join(r, "returned", "000001.facade-checkpoint"), 3)),
 "response root field wrong": ("F6", wrong_root_resp),
 "export entry missing": ("F0", drop_export),
}
allok = True
for name, (want, fn) in M.items():
    d = os.path.join(a.work, want + "-" + str(abs(hash(name)) % 10000)); shutil.copytree(a.run, d); fn(d)
    r = subprocess.run([a.py, "-B", os.path.join(H, "s3check.py"), "--run", d, "--s2b", a.s2b, "--note-vkey", a.note_vkey, "--origin", a.origin, "--ts-pub", a.ts_pub, "--ts-iss", a.ts_iss, "--out", os.path.join(d, "o.json")], capture_output=True, text=True)
    failed = [l.split()[1] for l in r.stdout.splitlines() if l.startswith("FAIL")]
    ok = r.returncode != 0 and want in failed
    allok &= ok
    print(("ok   " if ok else "FAIL ") + f"mutation '{name}': expected {want} to fail; failed checks = {failed}")
print("CHECKER MUTATIONS:", "ALL DETECTED" if allok else "SOME MISSED"); sys.exit(0 if allok else 1)
