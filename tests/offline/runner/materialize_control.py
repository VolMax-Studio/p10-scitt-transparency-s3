#!/usr/bin/env python3
"""TEST TOOLING (not acceptance code). Packages a RATIFIED S2b/S2a fixture vector (request.cbor with its own bound inputs) as a capture directory
(spec/capture-format.md) WITHOUT re-encoding any signed object, so that the candidate runner command can be exercised on it. Nothing in the vector is changed.

The request is read with `cbor2` (an independent decoder). Prefix, submission, Receipt and detached-payload files are the decoded byte strings of the request itself
(mechanics only: this is a packaging of a fixture, not independent S3-B sources). pB/inst/iB/retained target payload are the vector's own when it has them; otherwise the
ratified S2b profile pB/inst and the S2a P2 toy iB are supplied as FILLER (recorded in provenance/CONTROL.json); the chain stops before it could read filler for the controls
that need it, which the harness checks through the expected outcome. If the vector cannot be packaged (no Receipt/target, non-contiguous or duplicate leaf indices that the
capture format forbids), the result says so and no directory is produced.

usage (library): materialize(vector_dir, out_dir, s2b, s2a, control_id) -> dict
"""
import hashlib, json, os, shutil
import cbor2

sha = lambda b: hashlib.sha256(b).hexdigest()


def materialize(vec, out, s2b, s2a, cid):
    req = open(os.path.join(vec, "request.cbor"), "rb").read()
    obj = cbor2.loads(req)
    magic, frozen, material = obj
    receipt, target, leaves, detached = material[1], material[2], material[3], material[4]
    if receipt is None or target is None:
        return {"packaged": False, "why": "request has no selected Receipt or no target"}
    pairs = sorted(((i, b) for i, b in leaves), key=lambda t: t[0])
    if [i for i, _ in pairs] != list(range(len(pairs))):
        return {"packaged": False, "why": f"leaf indices {[i for i, _ in pairs]} are not 0..n-1 (the capture format requires a complete prefix)"}
    ti = [i for i, b in pairs if b == target]
    if len(ti) != 1:
        return {"packaged": False, "why": "target bytes do not match exactly one leaf"}
    ti = ti[0]
    os.makedirs(out)
    def w(rel, data):
        p = os.path.join(out, rel); os.makedirs(os.path.dirname(p), exist_ok=True); open(p, "wb").write(data)
        return {"path": rel, "sha256": sha(data)}
    filler = []
    def pick(name, fallback):
        p = os.path.join(vec, name)
        if os.path.exists(p):
            return open(p, "rb").read()
        filler.append(name)
        return open(fallback, "rb").read()
    pb = pick("pB.json", os.path.join(s2b, "profile", "pB.json"))
    inst = pick("inst.bin", os.path.join(s2b, "profile", "inst.bin"))
    ib = pick("iB.json", os.path.join(s2a, "vectors", "P2", "iB.json"))
    idx = {"format": "P10-S3-CaptureIndex-v0-candidate", "request": w("request.cbor", req), "prefix": [], "submissions": []}
    for i, b in pairs:
        idx["prefix"].append({"index": str(i), **w(f"prefix/{i:06d}.cose", b), "origin": "issuer", "role": "p10-target" if i == ti else "p10-lifecycle"})
        idx["submissions"].append({"index": str(i), **w(f"submissions/{i:06d}.cose", b)})
    idx["receipts"] = [{"index": str(ti), **w(f"receipts/{ti:06d}.receipt.cbor", receipt), "selected": True}]
    idx["detached_payloads"] = [{"index": str(i), **w(f"detached/{i:06d}.payload", b)} for i, b in sorted(detached)]
    idx["target"] = {"index": str(ti)}
    rtp = os.path.join(vec, "target_payload.json")
    idx["material"] = {"profile_artifact": w("material/pB.json", pb), "instance_commitment": w("material/inst.bin", inst), "s1_instance": w("material/iB.json", ib),
                       "retained_target_payload": [w("material/target_payload.json", open(rtp, "rb").read())] if os.path.exists(rtp) else []}
    idx["public_keys"] = []
    idx["provenance"] = [w("provenance/CONTROL.json", (json.dumps({"control": cid, "source_vector": vec, "filler_inputs": filler,
                                                                  "note": "test packaging of a ratified fixture vector; not an S3 capture"}, sort_keys=True, indent=1) + "\n").encode())]
    data = (json.dumps(idx, sort_keys=True, indent=1, ensure_ascii=False) + "\n").encode()
    open(os.path.join(out, "capture.json"), "wb").write(data)
    return {"packaged": True, "capture": out, "anchor": sha(data), "filler": filler, "leaves": len(pairs), "target_index": ti}
