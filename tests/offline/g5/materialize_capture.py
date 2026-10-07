#!/usr/bin/env python3
"""TEST TOOLING for candidate G5 (not acceptance code). Materializes a capture directory (spec/capture-format.md) from the committed
spike fixture `spike/fixtures/volmax-owner`, WITHOUT re-encoding any signed object.

Independence: the request is read here with `cbor2` (an independent decoder), not with the frozen Rust decoder that G5 uses, so a
decoder disagreement would surface as a G5 failure. Every signed object, Receipt and payload is written byte for byte from the decoded
byte strings. Precondition checked: re-encoding the decoded request with cbor2 reproduces the original bytes (this is only used by the
mutation tests, never for materialization).

LIMITATION: in this materialization the submitted bytes, exported prefix bytes and request leaves all originate from the one request,
so it exercises the checker's mechanics, not the independence of real submission/export sources. It is NOT the S3 capture.

usage: materialize_capture.py --fixture DIR --out DIR
"""
import argparse, hashlib, json, os, shutil, sys
import cbor2


def sha(b): return hashlib.sha256(b).hexdigest()


def w(root, rel, data):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as f:
        f.write(data)
    return {"path": rel, "sha256": sha(data)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixture", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    req = open(os.path.join(a.fixture, "request.cbor"), "rb").read()
    obj = cbor2.loads(req)
    assert cbor2.dumps(obj) == req, "cbor2 round trip does not reproduce the request bytes"
    magic, frozen, material = obj
    assert magic == "P10-ReplayRequestV0"
    receipt, target, leaves, detached = material[1], material[2], material[3], material[4]
    assert receipt is not None and target is not None
    out = os.path.abspath(a.out)
    assert not os.path.exists(out) or not os.listdir(out), "output directory must be empty"
    os.makedirs(out, exist_ok=True)

    idx = {}
    idx["format"] = "P10-S3-CaptureIndex-v0-candidate"
    idx["request"] = w(out, "request.cbor", req)
    pairs = sorted(((i, b) for i, b in leaves), key=lambda t: t[0])
    target_index = next(i for i, b in pairs if b == target)
    idx["prefix"], idx["submissions"] = [], []
    for i, b in pairs:
        ref = w(out, f"prefix/{i:06d}.cose", b)
        idx["prefix"].append({"index": str(i), **ref, "origin": "issuer", "role": "p10-target" if i == target_index else "p10-lifecycle"})
        idx["submissions"].append({"index": str(i), **w(out, f"submissions/{i:06d}.cose", b)})
    idx["receipts"] = [{"index": str(target_index), **w(out, f"receipts/{target_index:06d}.receipt.cbor", receipt), "selected": True}]
    idx["detached_payloads"] = [{"index": str(i), **w(out, f"detached/{i:06d}.payload", b)} for i, b in sorted(detached)]
    idx["target"] = {"index": str(target_index)}
    cp = lambda src, rel: w(out, rel, open(os.path.join(a.fixture, src), "rb").read())
    idx["material"] = {"profile_artifact": cp("pB.json", "material/pB.json"), "instance_commitment": cp("inst.bin", "material/inst.bin"),
                       "s1_instance": cp("iB.json", "material/iB.json"), "retained_target_payload": [cp("target_payload.json", "material/target_payload.json")]}
    idx["public_keys"] = [{"name": n[:-len(".public.cose_key.cbor")], **cp(os.path.join("public", n), "public-keys/" + n)}
                          for n in sorted(os.listdir(os.path.join(a.fixture, "public")))]
    prov = [cp("PUBLIC_META.json", "provenance/PUBLIC_META.json"),
            w(out, "provenance/MATERIALIZATION.json", (json.dumps({"tool": "tests/offline/g5/materialize_capture.py", "source_fixture": "spike/fixtures/volmax-owner",
                                                                     "request_sha256": sha(req), "note": "test materialization of a spike fixture; not an S3 capture"}, sort_keys=True, indent=1) + "\n").encode())]
    idx["provenance"] = prov
    data = (json.dumps(idx, sort_keys=True, indent=1, ensure_ascii=False) + "\n").encode("utf-8")
    open(os.path.join(out, "capture.json"), "wb").write(data)
    print(json.dumps({"capture": out, "capture_json_sha256": sha(data), "prefix_leaves": len(pairs), "target_index": target_index}))


if __name__ == "__main__":
    main()
