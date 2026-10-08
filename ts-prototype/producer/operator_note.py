#!/usr/bin/env python3
"""Operator tool (candidate, non-normative): creates ONE classifiable non-target statement (an operator note) signed with the operator key. Tagged COSE_Sign1, protected CWT
iss/sub as text, sub != instance subject, empty unprotected header: it satisfies only the structural constraints of the frozen classification. It carries no policy.
usage: operator_note.py --s2b DIR --config DIR --issuer-keys DIR --out FILE
"""
import argparse, json, os, sys
ap = argparse.ArgumentParser()
for k in ("s2b", "config", "issuer-keys", "out"): ap.add_argument("--" + k, required=True)
ap.add_argument("--ts-iss", help="unused (kept for the command line of earlier runs)")
a = ap.parse_args()
sys.path.insert(0, os.path.join(a.s2b, "tests", "differential"))
from cryptography.hazmat.primitives import serialization
import gen_corpus as G
meta = json.load(open(os.path.join(a.config, "PUBLIC_META.json")))
sub = meta["bootstrap"]["operator_note_subject"]; op_iss = meta["identity"]["operator_iss"]
assert sub != meta["identity"]["instance_subject"]
key = serialization.load_pem_private_key(open(os.path.join(a.issuer_keys, "operator.pem"), "rb").read(), None)
note = "Operator note. A non-target statement registered by the log operator between lifecycle statements; it carries no policy and concerns no P10 subject."
payload = json.dumps({"kind": "operator-note", "note": note, "version": "1"}, sort_keys=True, separators=(",", ":")).encode()
open(a.out, "wb").write(G.signed_statement(payload, key=key, iss=op_iss, sub=sub, ct="application/json"))
print("wrote", a.out)
