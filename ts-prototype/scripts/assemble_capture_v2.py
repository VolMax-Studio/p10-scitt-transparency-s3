#!/usr/bin/env python3
"""S3-B capture assembly (candidate, NON-NORMATIVE) from a s3-capture RUN directory. Builds the capture directory of spec/capture-format.md and
request.cbor FROM THE RETAINED BYTES; nothing is re-derived from expected artifacts and no private key is read.

Sources (three independent retentions plus public configuration):
  run/issuer/submissions     what issuers submitted (registered form)        -> capture submissions/   (issuer-originated leaves only)
  run/issuer/detached        detached statement payloads held by the issuer  -> capture detached/ and request detached_statement_payloads
  run/export                 PUBLIC export (HTTP) with LeafEncodeV0 header removed -> capture prefix/
  run/returned               Receipts as returned by the facade               -> capture receipts/ (all; the target's is selected)
  run/public-checkpoints, run/public, run/submit-log.json, run/export-result.json, facade checks, facade /config, journal -> capture provenance/
  fixture                    PUBLIC configuration only: ts_iss, TS public COSE key + thumbprint, instance subject, key tables, pB/inst/iB, public keys

usage: assemble_capture_v2.py --s2b DIR --fixture DIR --run DIR --out DIR --extra DIR [--ts-origin 0,1] [--roles 0=..] [--issuers a,b]
  --extra: directory of additional provenance files to index (e.g. facade-config.json, s3check.json, journal)
"""
import argparse, hashlib, json, os, sys
import cbor2

ap = argparse.ArgumentParser()
for k in ("s2b", "fixture", "run", "out", "extra"):
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
HDR = 61
pre = b"P10-LeafEncodeV0\x00" + (32).to_bytes(4, "big") + b"application/scitt-statement+cose"
R = a.run

names = sorted(os.listdir(os.path.join(R, "export")))
leaves = []
for i, name in enumerate(names):
    le = rd(os.path.join(R, "export", name))
    assert name == f"{i:06d}.leaf_input" and le[:len(pre)] == pre, "unexpected export entry"
    assert int.from_bytes(le[len(pre):HDR], "big") == len(le) - HDR, "LeafEncodeV0 length field does not match the entry"
    leaves.append(le[HDR:])
n, target = len(leaves), len(leaves) - 1
receipts = {i: rd(os.path.join(R, "returned", f"{i:06d}.receipt.cbor")) for i in range(n)}
det_dir = os.path.join(R, "issuer", "detached")
detached = {int(f.split(".")[0]): rd(os.path.join(det_dir, f)) for f in sorted(os.listdir(det_dir))} if os.path.isdir(det_dir) else {}
key_res = {nm: bytes.fromhex(v) for nm, v in pj["key_resolution"].items()}
key_mat = {nm: rd(os.path.join(a.fixture, "public", f"{nm}.public.cose_key.cbor")) for nm in a.issuers.split(",")}
req = G.request(receipts[target], leaves[target], list(enumerate(leaves)), receipt_key_bytes=ts_pub, fp=fp, ts_iss=ts_iss, key_res=key_res, key_mat=key_mat, subject=subject,
                detached=detached or None)

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
        idx["submissions"].append({"index": str(i), **w(f"submissions/{i:06d}.cose", rd(os.path.join(R, "issuer", "submissions", f"{i:06d}.cose")))})
idx["receipts"] = [{"index": str(i), **w(f"receipts/{i:06d}.receipt.cbor", receipts[i]), "selected": i == target} for i in range(n)]
idx["detached_payloads"] = [{"index": str(i), **w(f"detached/{i:06d}.payload", p)} for i, p in sorted(detached.items())]
idx["target"] = {"index": str(target)}
cp = lambda src, rel: w(rel, rd(os.path.join(a.fixture, src)))
idx["material"] = {"profile_artifact": cp("pB.json", "material/pB.json"), "instance_commitment": cp("inst.bin", "material/inst.bin"),
                   "s1_instance": cp("iB.json", "material/iB.json"), "retained_target_payload": [cp("target_payload.json", "material/target_payload.json")]}
idx["public_keys"] = [{"name": f[:-len(".public.cose_key.cbor")], **cp(os.path.join("public", f), "public-keys/" + f)} for f in sorted(os.listdir(os.path.join(a.fixture, "public")))]
prov = []
def addtree(srcdir, dstprefix):
    for root, _, files in os.walk(srcdir):
        for f in sorted(files):
            full = os.path.join(root, f); rel = os.path.relpath(full, srcdir).replace(os.sep, "/")
            data = rd(full)
            assert b"PRIVATE KEY" not in data, f"private key material in {full}"
            prov.append(w(f"{dstprefix}/{rel}", data))
addtree(os.path.join(R, "public-checkpoints"), "provenance/public-checkpoints")
addtree(os.path.join(R, "public"), "provenance/public-http-responses")
for f in ("submit-log.json", "export-result.json"):
    prov.append(w("provenance/" + f, rd(os.path.join(R, f))))
addtree(a.extra, "provenance")
idx["provenance"] = sorted(prov, key=lambda x: x["path"])
data = (json.dumps(idx, sort_keys=True, indent=1, ensure_ascii=False) + "\n").encode()
open(os.path.join(out, "capture.json"), "wb").write(data)
print(json.dumps({"capture": out, "capture_json_sha256": sha(data), "request_sha256": sha(req), "leaves": n, "detached": sorted(detached)}))
