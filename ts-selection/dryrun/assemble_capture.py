#!/usr/bin/env python3
"""S3-B capture assembly sketch (NON-NORMATIVE). Builds a capture directory (spec/capture-format.md) from bytes retained at the ACTUAL interfaces,
and builds request.cbor FROM THOSE RETAINED BYTES:

  submissions/NNNNNN.cose   what the issuer submitted (registered form)         <- retained/submissions   (issuer side)
  prefix/NNNNNN.cose        leaf bytes exported from the log engine's entry bundles, LeafEncodeV0 header removed   <- retained/export
  receipts/NNNNNN.receipt.cbor  Receipts as issued at registration              <- retained/receipts      (Receipt issuer)
  request.cbor              assembled here from the exported leaves, the retained target statement, the retained selected Receipt, the
                            public configuration (ts_iss, Receipt public key + thumbprint, instance subject, key tables)

The request is never decoded to produce capture files; nothing is re-encoded except the request envelope itself. Only public material is read.
Every leaf not marked --ts-origin is issuer-originated and needs a submission file; the exported bytes must equal it (checked later by G5).

usage: assemble_capture.py --s2b DIR --fixture DIR --retained DIR --out DIR [--ts-origin 0,1] [--roles 0=..,1=..] [--issuers a,b]
"""
import argparse, hashlib, json, os, shutil, sys
import cbor2

ap = argparse.ArgumentParser()
for k in ("s2b", "fixture", "retained", "out"):
    ap.add_argument("--" + k, required=True)
ap.add_argument("--ts-origin", default="")
ap.add_argument("--roles", default="")
ap.add_argument("--issuers", default="volmax-owner,admitter-one")
a = ap.parse_args()
sys.path.insert(0, os.path.join(a.s2b, "tests", "differential"))
import gen_corpus as G

sha = lambda b: hashlib.sha256(b).hexdigest()
rd = lambda p: open(p, "rb").read()
meta = json.load(open(os.path.join(a.fixture, "PUBLIC_META.json")))
pj = json.loads(rd(os.path.join(a.fixture, "pB.json")))
ts_iss, subject = meta["identity"]["ts_iss"], meta["identity"]["instance_subject"]
ts_pub = rd(os.path.join(a.fixture, "public", "ts.public.cose_key.cbor"))
k = cbor2.loads(ts_pub)
fp = G.H(G.cmap([(G.uint(1), G.uint(2)), (G.nint(-1), G.uint(1)), (G.nint(-2), G.bstr(k[-2])), (G.nint(-3), G.bstr(k[-3]))]))
assert fp.hex() == meta["identity"]["ts_key_thumbprint"]
HDR = 17 + 4 + 32 + 8          # LeafEncodeV0 header length for the single admitted format id (frozen spec s2)
pre = b"P10-LeafEncodeV0\x00" + (32).to_bytes(4, "big") + b"application/scitt-statement+cose"

export = sorted(os.listdir(os.path.join(a.retained, "export")))
leaves = []
for i, name in enumerate(export):
    le = rd(os.path.join(a.retained, "export", name))
    assert name == f"{i:06d}.leaf_input" and le[:len(pre)] == pre, "unexpected export entry"
    ln = int.from_bytes(le[len(pre):HDR], "big")
    assert ln == len(le) - HDR, "LeafEncodeV0 length field does not match the entry"
    leaves.append(le[HDR:])
n = len(leaves)
target = n - 1
receipt = rd(os.path.join(a.retained, "receipts", f"{target:06d}.receipt.cbor"))
key_res = {nm: bytes.fromhex(v) for nm, v in pj["key_resolution"].items()}
key_mat = {nm: rd(os.path.join(a.fixture, "public", f"{nm}.public.cose_key.cbor")) for nm in a.issuers.split(",")}
req = G.request(receipt, leaves[target], list(enumerate(leaves)), receipt_key_bytes=ts_pub, fp=fp, ts_iss=ts_iss, key_res=key_res, key_mat=key_mat, subject=subject)

ts_origin = {int(x) for x in a.ts_origin.split(",") if x}
roles = {int(x.split("=", 1)[0]): x.split("=", 1)[1] for x in a.roles.split(",") if x}
out = os.path.abspath(a.out)
assert not os.path.exists(out) or not os.listdir(out), "output directory must be empty"
def w(rel, data):
    p = os.path.join(out, rel); os.makedirs(os.path.dirname(p), exist_ok=True); open(p, "wb").write(data)
    return {"path": rel, "sha256": sha(data)}
idx = {"format": "P10-S3-CaptureIndex-v0-candidate", "request": w("request.cbor", req), "prefix": [], "submissions": []}
for i, s in enumerate(leaves):
    ref = w(f"prefix/{i:06d}.cose", s)
    idx["prefix"].append({"index": str(i), **ref, "origin": "ts" if i in ts_origin else "issuer", "role": roles.get(i, "p10-target" if i == target else "p10-lifecycle")})
    if i not in ts_origin:
        idx["submissions"].append({"index": str(i), **w(f"submissions/{i:06d}.cose", rd(os.path.join(a.retained, "submissions", f"{i:06d}.cose")))})
idx["receipts"] = [{"index": str(target), **w(f"receipts/{target:06d}.receipt.cbor", receipt), "selected": True}]
idx["detached_payloads"] = []
idx["target"] = {"index": str(target)}
cp = lambda src, rel: w(rel, rd(os.path.join(a.fixture, src)))
idx["material"] = {"profile_artifact": cp("pB.json", "material/pB.json"), "instance_commitment": cp("inst.bin", "material/inst.bin"),
                   "s1_instance": cp("iB.json", "material/iB.json"), "retained_target_payload": [cp("target_payload.json", "material/target_payload.json")]}
idx["public_keys"] = [{"name": f[:-len(".public.cose_key.cbor")], **cp(os.path.join("public", f), "public-keys/" + f)} for f in sorted(os.listdir(os.path.join(a.fixture, "public")))]
prov = []
for f in sorted(os.listdir(os.path.join(a.retained, "provenance"))):
    prov.append(w("provenance/" + f, rd(os.path.join(a.retained, "provenance", f))))
idx["provenance"] = prov
data = (json.dumps(idx, sort_keys=True, indent=1, ensure_ascii=False) + "\n").encode()
open(os.path.join(out, "capture.json"), "wb").write(data)
print(json.dumps({"capture": out, "capture_json_sha256": sha(data), "request_sha256": sha(req), "leaves": n}))
