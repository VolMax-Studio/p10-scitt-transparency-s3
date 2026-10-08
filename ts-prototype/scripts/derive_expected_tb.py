#!/usr/bin/env python3
"""Derive the EXPECTED transcript tB for a log that differs from ML-1 only in the bytes of some leaves (e.g. the detached-closure variant).

Independent derivation (nothing from the chain's output is read; the chain-output directory is refused as an input):
  1. the new RFC 9162 root is computed from the RETAINED EXPORTED BYTES of that log (run/export/*.leaf_input, the public export), with two separate
     implementations of the leaf hash (the S2b test helper and hashlib directly on 0x00 || leaf_input) and the S2b test helper's recursive MTH;
  2. it is cross-checked against the root in the retained final PUBLIC checkpoint (signature not re-verified here; s3check does that);
  3. the reference transcript model (S2b orchestration/post_s2a.py: decode_transcript / encode_transcript) decodes the independently generated ML-1
     expectation (gen_ml1.py's tB.expected), the round trip is required to be byte-identical, and ONLY the root_digest field is replaced; every other field
     (log identity, key-resolution digest, size, rows, detailed payload entries) does not depend on the byte form of any statement: a detached payload
     is the same payload, and the entries come from the decoded payloads. The size must equal the number of exported leaves.
usage: derive_expected_tb.py --s2b DIR --base-expect DIR(with tB.expected and expect.json) --run DIR(s3-capture run) --out DIR
"""
import argparse, base64, dataclasses, hashlib, json, os, shutil, sys
ap = argparse.ArgumentParser()
for k in ("s2b", "base-expect", "run", "out"): ap.add_argument("--" + k, required=True)
a = ap.parse_args()
if "chain" in os.path.abspath(a.run).split(os.sep)[-1:] or os.path.exists(os.path.join(a.run, "tB.bin")):
    sys.exit("refusing: --run must be the capture run directory, not chain output")
for sub in ("tests/differential", "tests/s2a", "orchestration"): sys.path.insert(0, os.path.join(a.s2b, sub))
import gen_corpus as G
import post_s2a as P
rd = lambda p: open(p, "rb").read()
sha = lambda b: hashlib.sha256(b).hexdigest()
HDR = 61
names = sorted(os.listdir(os.path.join(a.run, "export")))
li = [rd(os.path.join(a.run, "export", n)) for n in names]
stm = []
for i, (n, e) in enumerate(zip(names, li)):
    assert n == f"{i:06d}.leaf_input"
    assert e[:HDR - 8] == b"P10-LeafEncodeV0\x00" + (32).to_bytes(4, "big") + b"application/scitt-statement+cose" and int.from_bytes(e[HDR - 8:HDR], "big") == len(e) - HDR
    stm.append(e[HDR:])
h1 = [G.leaf_hash(s) for s in stm]
h2 = [hashlib.sha256(b"\x00" + e).digest() for e in li]
assert h1 == h2, "the two leaf-hash implementations disagree"
root = G.mth(h1)
cp = rd(os.path.join(a.run, "public", "checkpoint")).decode().split("\n")
cp_root = base64.b64decode(cp[2]); cp_size = int(cp[1])
assert cp_size == len(li) and cp_root == root, "the retained public checkpoint does not match the root computed from the exported bytes"
base_b = rd(os.path.join(a.base_expect, "tB.expected"))
T = P.decode_transcript(base_b)
assert P.encode_transcript(T) == base_b, "reference transcript model does not round-trip the base expectation"
assert T.size == len(li)
T2 = dataclasses.replace(T, root_digest=root)
new_b = P.encode_transcript(T2)
assert P.decode_transcript(new_b) == T2
# structure check: the two encodings differ ONLY in the encoded root field (enc_bytes(root_digest); its length depends on the value in this model)
fb_old, fb_new = P.enc_bytes(T.root_digest), P.enc_bytes(root)
k = base_b.index(fb_old); assert base_b.count(fb_old) == 1
prefix, suffix = base_b[:k], base_b[k + len(fb_old):]
assert new_b == prefix + fb_new + suffix, "encodings differ outside the root field"
os.makedirs(a.out, exist_ok=True)
open(os.path.join(a.out, "tB.expected"), "wb").write(new_b)
shutil.copy(os.path.join(a.base_expect, "expect.json"), os.path.join(a.out, "expect.json"))
d = {"inputs": {"export_leaf_inputs": {n: sha(e) for n, e in zip(names, li)}, "base_tB_expected_sha256": sha(base_b), "base_expect_json_sha256": sha(rd(os.path.join(a.base_expect, "expect.json")))},
     "root_from_exported_bytes": root.hex(), "root_in_retained_public_checkpoint": cp_root.hex(), "base_root_digest": T.root_digest.hex(),
     "tB_expected_sha256": sha(new_b), "encoding_differs_only_in_root_field": {"prefix_len": len(prefix), "suffix_len": len(suffix), "base_total": len(base_b), "new_total": len(new_b), "old_field_len": len(fb_old), "new_field_len": len(fb_new)},
     "chain_output_read": False}
json.dump(d, open(os.path.join(a.out, "derivation.json"), "w"), indent=1)
print(json.dumps(d, indent=1))
