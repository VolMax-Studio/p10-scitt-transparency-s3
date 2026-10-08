#!/usr/bin/env python3
"""Make a variant of a statement prefix in which ONE statement is submitted in detached form: the COSE payload is replaced by null, everything else
(protected header, empty unprotected header, signature) is untouched. The signature covers the payload either way (RFC 9052 Sig_structure), so the
issuer's signature stays valid; the payload is kept as a separate file for the issuer to retain. Test tooling only; the frozen payload schema is unchanged.
usage: make_detached_variant.py --s2b DIR --prefix DIR --index N --out DIR --detached-out DIR
"""
import argparse, os, sys, cbor2
ap = argparse.ArgumentParser()
for k in ("s2b", "prefix", "index", "out", "detached-out"): ap.add_argument("--" + k, required=True)
a = ap.parse_args()
sys.path.insert(0, os.path.join(a.s2b, "tests", "differential"))
import gen_corpus as G
os.makedirs(a.out); os.makedirs(a.detached_out)
for f in sorted(os.listdir(a.prefix)):
    raw = open(os.path.join(a.prefix, f), "rb").read()
    if f == f"{int(a.index):06d}.cose":
        t = cbor2.loads(raw); prot, unprot, payload, sig = t.value
        assert t.tag == 18 and unprot == {} and isinstance(payload, bytes)
        new = G.tag(18, G.arr([G.bstr(prot), G.cmap([]), G.NULL, G.bstr(sig)]))
        open(os.path.join(a.detached_out, f.replace(".cose", ".payload")), "wb").write(payload)
        raw = new
        print("detached statement", f, "payload bytes", len(payload))
    open(os.path.join(a.out, f), "wb").write(raw)
