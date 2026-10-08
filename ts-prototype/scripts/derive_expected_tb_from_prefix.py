#!/usr/bin/env python3
"""Expected transcript tB for a run, derived from the RETAINED AUTHENTICATED PREFIX (the public export, cross-checked with the retained final public checkpoint) with the
reference transcript model of the ratified S2b test tooling (orchestration/post_s2a.py Transcript/encode_transcript). The chain's own output is never read (and refused as input).
Per statement: row subject from the CWT `sub`; for statements about the instance subject a detailed entry whose kind and payload come from the DECODED payload and whose signature
status comes from verifying the signature with the public issuer key. Root: S2b helper MTH over the exported bytes. Independence is that of the ratified S2b test tooling's model.
usage: derive_expected_tb_from_prefix.py --s2b DIR --config DIR --run DIR --out DIR   (writes tB.expected, expect.json (copied from config), derivation.json)
"""
import argparse, base64, hashlib, json, os, shutil, sys
import cbor2
ap = argparse.ArgumentParser()
for k in ("s2b", "config", "run", "out"): ap.add_argument("--" + k, required=True)
a = ap.parse_args()
if os.path.exists(os.path.join(a.run, "tB.bin")): sys.exit("refusing: --run must be the capture run directory")
for sub in ("tests/differential", "tests/s2a", "orchestration"): sys.path.insert(0, os.path.join(a.s2b, sub))
import jcs
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
import gen_corpus as G
import post_s2a as P
rd = lambda p: open(p, "rb").read()
H = lambda b: hashlib.sha256(b).digest()
pj = json.loads(rd(os.path.join(a.config, "pB.json")))
r = P._R(rd(os.path.join(a.config, "inst.bin"))); ic = P.InstanceCommitment(*[r.bytes_() for _ in range(13)])
subj = ic.instance_subject.decode()
names = list(pj["key_resolution"])
pub = {n: cbor2.loads(rd(os.path.join(a.config, "public", n + ".public.cose_key.cbor"))) for n in names}
PT_INV = {v: k for k, v in G.PT.items()}
def verify(iss, prot_b, payload, sig):
    k = pub.get(iss)
    if k is None or payload is None: return False
    pk = ec.EllipticCurvePublicNumbers(int.from_bytes(k[-2], "big"), int.from_bytes(k[-3], "big"), ec.SECP256R1()).public_key()
    try: pk.verify(encode_dss_signature(int.from_bytes(sig[:32], "big"), int.from_bytes(sig[32:], "big")), G.sig_structure(prot_b, payload), ec.ECDSA(hashes.SHA256())); return True
    except Exception: return False
names_ = sorted(os.listdir(os.path.join(a.run, "export")))
li = [rd(os.path.join(a.run, "export", n)) for n in names_]
stm = [e[61:] for e in li]
assert all(e[:17] == b"P10-LeafEncodeV0\x00" and int.from_bytes(e[53:61], "big") == len(e) - 61 for e in li)
root = G.mth([G.leaf_hash(s) for s in stm])
cp = rd(os.path.join(a.run, "public", "checkpoint")).decode().split("\n")
assert int(cp[1]) == len(li) and base64.b64decode(cp[2]) == root, "retained public checkpoint does not match the exported prefix"
rows, det = [], []
for i, st in enumerate(stm):
    t = cbor2.loads(st); prot_b, _, payload, sig = t.value; claims = cbor2.loads(prot_b)[15]
    rows.append(P.Row(i, claims[2].encode()))
    if claims[2] != subj: continue
    j = json.loads(payload); kind = PT_INV[j["predicateType"]]; pr = j["predicate"]; iss = claims[1]
    sg = "verified" if verify(iss, prot_b, payload, sig) else "badSignature"
    if kind == "profile": assert pr["profile_digest"] == ic.profile_digest.hex(); tag, pl = "profileCommit", bytes.fromhex(pr["profile_digest"])
    elif kind == "instance":
        assert pr["profile_digest"] == ic.profile_digest.hex() and pr["log_identity_digest"] == ic.log_identity_digest.hex() and pr["instance_subject"] == subj and pr["issuer_id"] == ic.issuer_id.decode()
        tag, pl = "instanceCommit", ic
    elif kind == "admission": tag, pl = "admission", (pr["item"]["kind"], int(bool(pr["item"]["value"])))
    elif kind == "closure":
        tag, pl = "closure", P.ClosurePayload(pr["instance_subject"].encode(), bool(pr["terminal"]), tuple(int(x) for x in pr["ordered_admission_refs"]), bytes.fromhex(pr["closed_evidence_set_digest"]),
                                              bytes.fromhex(pr["checkpoint_preclosure_transcript_digest"]))
    else: tag, pl = "adjudication", (int(pr["profile_commitment_ref"]), int(pr["instance_commitment_ref"]), int(pr["evidence_closure_ref"]))
    det.append(P.Detailed(i, iss.encode(), tag, sg, tag, pl))
kr_hex = pj["key_resolution"]
T = P.Transcript(ic.log_identity_digest, H(jcs.canonicalize({"key_resolution": kr_hex})), len(stm), root, tuple(rows), tuple(det))
b = P.encode_transcript(T); assert P.decode_transcript(b) == T
os.makedirs(a.out, exist_ok=True)
open(os.path.join(a.out, "tB.expected"), "wb").write(b); shutil.copy(os.path.join(a.config, "expect.json"), os.path.join(a.out, "expect.json"))
d = {"root_from_exported_bytes": root.hex(), "size": len(stm), "rows": len(rows), "detailed_indices": [x.idx for x in det], "detailed_kinds": [x.kind for x in det], "signature_status": [x.sig for x in det],
     "tB_expected_sha256": H(b).hex(), "chain_output_read": False, "export_leaf_input_sha256": {n: H(e).hex() for n, e in zip(names_, li)}}
json.dump(d, open(os.path.join(a.out, "derivation.json"), "w"), indent=1); print(json.dumps(d, indent=1)[:900])
