#!/usr/bin/env python3
"""Operator tool (candidate, non-normative): creates ONE classifiable non-target TEST statement (a note) signed with the operator's policy-test key. Tagged COSE_Sign1, protected CWT
iss/sub as text, sub != instance subject, empty unprotected header: it satisfies only the structural constraints of the frozen classification. Synthetic and experimental; no policy.
usage: operator_note.py --s2b DIR --config DIR --issuer-keys DIR --ts-iss URL --out FILE
"""
import argparse, json, os, sys
ap = argparse.ArgumentParser()
for k in ("s2b", "config", "issuer-keys", "ts-iss", "out"): ap.add_argument("--" + k, required=True)
a = ap.parse_args()
sys.path.insert(0, os.path.join(a.s2b, "tests", "differential"))
from cryptography.hazmat.primitives import serialization
import gen_corpus as G
meta = json.load(open(os.path.join(a.config, "PUBLIC_META.json")))
sub = "urn:volmax:s3-test:note"
assert sub != meta["identity"]["instance_subject"]
key = serialization.load_pem_private_key(open(os.path.join(a.issuer_keys, "policy-test.pem"), "rb").read(), None)
note = "SYNTHETIC EXPERIMENTAL S3 TEST NOTE. Non-target statement registered by the operator between lifecycle statements to shift later log indices; not a policy; nothing is enforced."
payload = json.dumps({"kind": "non-target-test-note", "note": note, "version": "1"}, sort_keys=True, separators=(",", ":")).encode()
open(a.out, "wb").write(G.signed_statement(payload, key=key, iss=a.ts_iss, sub=sub, ct="application/json"))
print("wrote", a.out)
