#!/usr/bin/env python3
"""Independent FACADE / PUBLIC-READ checks of a capture-client run directory (Python, using the ratified S2b test helpers read-only).
These are checks of the PROTOTYPE (facade and public read path). They are NOT frozen-chain verdicts and add no P10 rule.

usage: s3check.py --run DIR --s2b DIR --note-vkey VKEY --origin ORIGIN --ts-pub FILE.cose_key.cbor --ts-iss ISS --out report.json [--expect N]

Run layout (written by s3-capture): issuer|operator/submissions, returned/, public-checkpoints/, export/, public/.
Checks (F1-F8) are reported one by one; exit 0 only if all pass.
"""
import argparse, base64, hashlib, json, os, sys
import cbor2
from cryptography.hazmat.primitives.asymmetric import ec, ed25519
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

ap = argparse.ArgumentParser()
for k in ("run", "s2b", "note-vkey", "origin", "ts-pub", "ts-iss", "out"):
    ap.add_argument("--" + k, required=True)
ap.add_argument("--expect", type=int)
ap.add_argument("--allow-retry", action="store_true", help="crash tests: accept duplicate/recovered flags in the submit log (retries after a facade crash)")
a = ap.parse_args()
sys.path.insert(0, os.path.join(a.s2b, "tests", "differential"))
import gen_corpus as G

rd = lambda p: open(p, "rb").read()
R = a.run
report, ok_all = [], True
def chk(cid, name, cond, detail=""):
    global ok_all
    ok_all &= bool(cond)
    report.append({"id": cid, "check": name, "ok": bool(cond), **({"detail": detail} if detail and not cond else {})})
    print(("ok   " if cond else "FAIL ") + cid + " " + name + ((" :: " + str(detail)) if detail and not cond else ""))

# ---- pinned note key (name+hash8+base64(0x01||ed25519 pub))
name, h8, b64 = a.note_vkey.split("+", 2)
kb = base64.b64decode(b64); assert kb[0] == 1 and len(kb) == 33
pub = ed25519.Ed25519PublicKey.from_public_bytes(kb[1:])
keyhash = hashlib.sha256(name.encode() + b"\n" + kb).digest()[:4]
assert keyhash.hex() == h8, "vkey hash field does not match the key"

def open_note(raw):
    """returns (origin, size, root) if the note carries a valid signature by the pinned key, else raises"""
    text, sep, sigs = raw.partition(b"\n\n")
    assert sep, "no signature block"
    text += b"\n"
    good = False
    for line in sigs.decode().strip().split("\n"):
        assert line.startswith("— "), "bad signature line"
        n, s64 = line[2:].rsplit(" ", 1)
        blob = base64.b64decode(s64)
        if n == name and blob[:4] == keyhash:
            pub.verify(blob[4:], text); good = True
    assert good, "no signature by the pinned key"
    lines = text.decode().split("\n")
    return lines[0], int(lines[1]), base64.b64decode(lines[2])

ents = lambda d: sorted(os.listdir(os.path.join(R, d))) if os.path.isdir(os.path.join(R, d)) else []
subs = {}
for role in ("issuer", "operator"):
    for f in ents(role + "/submissions"):
        i = int(f.split(".")[0]); assert i not in subs; subs[i] = (role, rd(os.path.join(R, role, "submissions", f)))
exp = [rd(os.path.join(R, "export", f)) for f in ents("export")]
n = len(exp)
chk("F0", f"export holds {a.expect if a.expect else n} entries (indices contiguous)", n > 0 and (a.expect is None or n == a.expect) and sorted(subs) == list(range(n)), f"n={n} submissions={sorted(subs)}")
# F1 preservation: the public export holds exactly LeafEncodeV0(submitted statement) for every index
bad = [i for i in range(n) if exp[i] != G.leaf_input(subs[i][1])]
chk("F1", "public export[i] == LeafEncodeV0(submitted statement[i]) byte for byte (registered bytes preserved)", not bad, bad)
chk("F2", "no two exported leaves are identical (no duplicate append)", len(set(exp)) == n)
hs = [hashlib.sha256(b"\x00" + e).digest() for e in exp]
# F3 public checkpoints retained before the next registration
cps, bad = {}, []
for i in range(n):
    try:
        raw = rd(os.path.join(R, "public-checkpoints", f"{i:06d}.checkpoint"))
        o, sz, root = open_note(raw)
        cps[i] = (raw, o, sz, root)
        if o != a.origin or sz != i + 1 or root != G.mth(hs[: i + 1]):
            bad.append((i, o, sz))
    except Exception as e:
        bad.append((i, repr(e)))
chk("F3", "each retained public checkpoint: pinned-key signature valid, expected origin, size == index+1, root == RFC 9162 MTH of the exported leaves", not bad and len(cps) == n, bad)
# F4 checkpoints returned by the facade == the public ones
diff = [i for i in range(n) if rd(os.path.join(R, "returned", f"{i:06d}.facade-checkpoint")) != cps[i][0]]
chk("F4", "checkpoint returned with each registration == original signed checkpoint fetched from the public endpoint (same bytes)", not diff, diff)
# F5 Receipts
tsk = cbor2.loads(rd(a.ts_pub))
tspub = ec.EllipticCurvePublicNumbers(int.from_bytes(tsk[-2], "big"), int.from_bytes(tsk[-3], "big"), ec.SECP256R1()).public_key()
badr, thumbs = [], set()
for i in range(n):
    try:
        rec = rd(os.path.join(R, "returned", f"{i:06d}.receipt.cbor"))
        t = cbor2.loads(rec); assert t.tag == 18 and len(t.value) == 4
        prot_b, unprot, payload, sig = t.value
        assert payload is None, "payload not detached"
        prot = cbor2.loads(prot_b)
        assert prot == {1: -7, 395: 1, 15: {1: a.ts_iss}}, prot
        proofs = unprot[396][-1]; assert len(proofs) == 1 and isinstance(proofs[0], bytes)
        size, leaf_index, path = cbor2.loads(proofs[0])
        assert (size, leaf_index) == (i + 1, i), (size, leaf_index)
        assert path == G.path(i, hs[: i + 1]), "inclusion path differs from RFC 9162"
        root = cps[i][3]
        r, s = int.from_bytes(sig[:32], "big"), int.from_bytes(sig[32:], "big")
        tspub.verify(encode_dss_signature(r, s), G.sig_structure(prot_b, root), ec.ECDSA(hashes.SHA256()))
        thumbs.add(hashlib.sha256(rd(a.ts_pub)).hexdigest())
    except Exception as e:
        badr.append((i, repr(e)))
chk("F5", "each returned Receipt: tagged COSE_Sign1, detached payload, expected protected header, proof (size,index,path) == RFC 9162 for that log state, ES256 signature verifies under the committed TS key over the PUBLIC checkpoint root", not badr, badr)
# F6 responses
bad = []
for i in range(n):
    j = json.loads(rd(os.path.join(R, "returned", f"{i:06d}.response.json")))
    if j["index"] != i or j["tree_size"] != i + 1 or j["leaf_hash"] != hs[i].hex() or j["root"] != cps[i][3].hex():
        bad.append(i)
chk("F6", "facade response fields (index, tree_size, leaf_hash, root) agree with the independently recomputed values", not bad, bad)
sl = json.loads(rd(os.path.join(R, "submit-log.json"))) if os.path.exists(os.path.join(R, "submit-log.json")) else []
chk("F7", "submit log: " + ("registrations may be retries (duplicate/recovered flags allowed); " if a.allow_retry else "every registration was fresh (no duplicate/recovered flag); ") + "public checkpoint size == index+1 at retention time",
    all((a.allow_retry or ((not x["duplicate"]) and (not x["recovered"]))) and x["public_checkpoint_size"] == x["index"] + 1 for x in sl) and len(sl) == n)
er = json.loads(rd(os.path.join(R, "export-result.json")))
chk("F8", "capture client export result: size, root and per-entry proof count agree with the retained final checkpoint", er["size"] == n and er["root"] == cps[n - 1][3].hex() and er["entries_proved_into_checkpoint_root"] == n)
open(a.out, "w").write(json.dumps({"scope": "facade/public-read checks (NOT a frozen-chain verdict)", "n": n, "all_ok": ok_all, "checks": report}, indent=1) + "\n")
print("FACADE/PUBLIC-READ CHECKS:", "ALL OK" if ok_all else "FAILURES")
sys.exit(0 if ok_all else 1)
