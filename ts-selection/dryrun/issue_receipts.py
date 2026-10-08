#!/usr/bin/env python3
"""REFERENCE SKETCH of the one component Tessera does not provide: the COSE Receipt issuer (RFC 9942 style, VDS 1). NON-NORMATIVE.

It turns what the log engine returned for each registration (leaf index, checkpoint tree size, root, RFC 9162 inclusion path) into a
tagged COSE_Sign1 Receipt in the shape the frozen S2b verifier consumes: protected {1: -7 (ES256), 395: 1 (VDS RFC9162_SHA256),
15: {1: ts_iss}}; unprotected {396: {-1: [[tree_size, leaf_index, [path...]]]}}; DETACHED payload (the signed root is reconstructed by
the verifier from the proof); signature over Sig_structure(protected, root). It reuses the byte encoders of the ratified S2b test
tooling (read-only) and holds the Receipt-signing private key, which is read from --keys-dir (outside the repository) and never written.

The Receipt is issued per registration, right after the log engine confirms integration, and is retained as issued (never re-requested).

usage: issue_receipts.py --s2b DIR --fixture DIR --keys-dir DIR --retained DIR
  reads  <retained>/receipt-inputs/NNNNNN.json   writes <retained>/receipts/NNNNNN.receipt.cbor
"""
import argparse, glob, json, os, sys
from cryptography.hazmat.primitives import serialization

ap = argparse.ArgumentParser()
for k in ("s2b", "fixture", "keys_dir", "retained"):
    ap.add_argument("--" + k.replace("_", "-"), required=True)
a = ap.parse_args()
sys.path.insert(0, os.path.join(a.s2b, "tests", "differential"))
import gen_corpus as G

meta = json.load(open(os.path.join(a.fixture, "PUBLIC_META.json")))
ts_iss = meta["identity"]["ts_iss"]
tskey = serialization.load_pem_private_key(open(os.path.join(a.keys_dir, "ts.pem"), "rb").read(), None)
assert G.thumbprint(tskey).hex() == meta["identity"]["ts_key_thumbprint"], "the Receipt-signing key is not the key committed in the instance"
os.makedirs(os.path.join(a.retained, "receipts"), exist_ok=True)
for f in sorted(glob.glob(os.path.join(a.retained, "receipt-inputs", "*.json"))):
    r = json.load(open(f))
    path = [bytes.fromhex(h) for h in (r["inclusion_path"] or [])]
    root = bytes.fromhex(r["root"])
    prot = G.cmap([(G.uint(1), G.integer(-7)), (G.uint(395), G.uint(1)), (G.uint(15), G.cmap([(G.uint(1), G.tstr(ts_iss))]))])
    sig = G.sign(tskey, G.sig_structure(prot, root))
    proof = G.arr([G.uint(r["tree_size"]), G.uint(r["index"]), G.arr([G.bstr(h) for h in path])])
    # each inclusion proof is a bstr that WRAPS the CBOR array [tree_size, leaf_index, path] (RFC 9942 inclusion-proof encoding; found by running
    # the frozen verifier: an unwrapped array is ReceiptMalformed ProofEntryNotBstr)
    unprot = G.cmap([(G.uint(396), G.cmap([(G.nint(-1), G.arr([G.bstr(proof)]))]))])
    rec = G.tag(18, G.arr([G.bstr(prot), unprot, G.NULL, G.bstr(sig)]))
    open(os.path.join(a.retained, "receipts", f"{r['index']:06d}.receipt.cbor"), "wb").write(rec)
print("issued", len(glob.glob(os.path.join(a.retained, "receipts", "*.cbor"))), "receipts")
