#!/usr/bin/env python3
"""NON-NORMATIVE FEASIBILITY SPIKE. Generates a `volmax-owner` instance on the SAME frozen toy semantics as the ratified S2b fixture
POST-BASE-match (same lifecycle shape, same exact toy iB bytes, same frozen A12-A14 digests), with independently generated test keys.

What changes relative to the ratified fixture: issuer/owner name (`volmax-owner`), all issuer keys, the TS issuer string and key, hence
LogIdentityV0, pB.key_resolution, the instance commitment (issuer_id, instance_owner_iss, SubjectDeriveV0 subject, profile_digest,
log_identity_digest), and every statement/receipt signature. What does not change: S1 iB bytes, claim/evidence/witness data, rule IDs and
descriptor digests, the verifier manifest digest, the admitter set, the lifecycle shape.

It reuses the ratified S2b test-tooling codecs (tests/differential/gen_corpus.py, tests/s2a/scenarios.py, tests/s2a/post_scenarios.py,
orchestration/post_s2a.py) unchanged, read-only, and sets module-level key lookups from this script (no file of S2b/S2a/S1 is modified).

Private keys are generated here, written ONLY to --keys-dir (must be outside the repository), and never to the output directory. Only
public material is written: request.cbor, pB.json, inst.bin, iB.json, target_payload.json, tB.expected (comparison only), expect.json,
public COSE keys and thumbprints, PUBLIC_META.json.

Not reproducible byte-for-byte (random keys); the committed output is the fixture. Needs cryptography and jcs (see spike/README.md).

usage: gen_volmax_owner.py --s2b DIR --s2a DIR --out DIR --keys-dir DIR
"""
import argparse, dataclasses, hashlib, json, os, subprocess, sys, types


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--s2b", required=True)
    ap.add_argument("--s2a", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--keys-dir", required=True)
    a = ap.parse_args()
    out, kdir = os.path.abspath(a.out), os.path.abspath(a.keys_dir)
    here = os.path.dirname(os.path.abspath(__file__))
    top = subprocess.run(["git", "-C", here, "rev-parse", "--show-toplevel"], capture_output=True, text=True).stdout.strip()
    if top and (kdir == top or kdir.startswith(top + os.sep)):
        raise SystemExit("refusing: --keys-dir is inside the repository; private keys must stay outside it")
    for sub in ("tests/differential", "tests/s2a", "orchestration"):
        sys.path.insert(0, os.path.join(a.s2b, sub))
    import jcs
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    import gen_corpus as G
    import scenarios as S
    import post_scenarios as PS
    import post_s2a as P

    H = lambda b: hashlib.sha256(b).digest()
    jd = lambda o: H(jcs.canonicalize(o))
    rd = lambda p: open(p, "rb").read()

    def subject_derive(issuer: bytes, request_id: bytes) -> bytes:
        # SubjectDeriveV0(i, r) = "p10s2sub:" ++ hex(SHA-256(JCS({"issuer_id": i, "request_id": hex(r), "v": "SubjectDeriveV0"})))  (S2a Digests.lean)
        return b"p10s2sub:" + jd({"issuer_id": issuer.decode(), "request_id": request_id.hex(), "v": "SubjectDeriveV0"}).hex().encode()

    def lid(ts_iss, ts_key, spec_hex):
        lp = jd({"rule": "LeafEncodeV0", "spec_digest": spec_hex})
        return H(jcs.canonicalize({"checkpoint_verification_key_fingerprint": G.thumbprint(ts_key).hex(), "leaf_encoding_profile_digest": lp.hex(),
                                   "ts_iss": ts_iss, "vds_algorithm": 1}))

    def decode_inst(b):
        r = P._R(b)
        ic = P.InstanceCommitment(*[r.bytes_() for _ in range(13)])
        assert r.i == len(b) and ic.encode() == b, "instance commitment not canonical"
        return ic

    checks = []

    def check(name, ok, detail=""):
        checks.append({"check": name, "ok": bool(ok), "detail": detail})
        if not ok:
            raise SystemExit(f"generator sanity check failed: {name} {detail}")

    # ---------------- templates (ratified S2b profile material; ratified S2a vector P2 for the toy iB / evidence digest)
    pb_t, ic_t = rd(os.path.join(a.s2b, "profile", "pB.json")), decode_inst(rd(os.path.join(a.s2b, "profile", "inst.bin")))
    pj = json.loads(pb_t)
    p2 = os.path.join(a.s2a, "vectors", "P2")
    ib = rd(os.path.join(p2, "iB.json"))
    T = P.decode_transcript(rd(os.path.join(p2, "tB.bin")))
    evidence_digest = next(d.payload for d in T.detailed if d.payload_tag == "closure").closed_evidence_set_digest
    check("toy iB bytes are the S1 p1.instance.json bytes (sha256 62353069...)", H(ib).hex() == "62353069823aace3a91b37ffabcdf7b2d608134457276b2a5e597ebb49e0e824")
    # sanity: my SubjectDeriveV0 / LogIdentityV0 re-derivations reproduce the ratified toy values
    check("SubjectDeriveV0 re-derivation reproduces the toy instance_subject", subject_derive(ic_t.issuer_id, ic_t.request_id) == ic_t.instance_subject,
          f"{subject_derive(ic_t.issuer_id, ic_t.request_id)!r} vs {ic_t.instance_subject!r}")
    check("LogIdentityV0 re-derivation reproduces the toy log_identity_digest", lid(G.TS_ISS, G.K_TS, pj["leaf_encoding_spec_digest"]) == ic_t.log_identity_digest)

    # ---------------- independent keys (private keys outside the repo)
    os.makedirs(kdir, mode=0o700, exist_ok=True)
    names = ["admitter-one", "admitter-two", "intruder-x", "volmax-owner"]
    keys = {n: ec.generate_private_key(ec.SECP256R1()) for n in names}
    ts_key = ec.generate_private_key(ec.SECP256R1())
    ts_iss = "https://ts.example/volmax-s3-spike"
    for n, k in list(keys.items()) + [("ts", ts_key)]:
        p = os.path.join(kdir, f"{n}.pem")
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))

    # ---------------- profile artifact and instance commitment for volmax-owner
    kr_hex = {n: G.thumbprint(keys[n]).hex() for n in names}
    pj2 = dict(pj)
    pj2["key_resolution"] = kr_hex
    pb = json.dumps(pj2, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    owner = b"volmax-owner"
    subj = subject_derive(owner, ic_t.request_id)
    lid2 = lid(ts_iss, ts_key, pj["leaf_encoding_spec_digest"])
    ic = dataclasses.replace(ic_t, issuer_id=owner, instance_owner_iss=owner, instance_subject=subj, profile_digest=H(pb), log_identity_digest=lid2)
    inst = ic.encode()
    check("only identity-dependent instance fields changed",
          {f.name for f in dataclasses.fields(ic) if getattr(ic, f.name) != getattr(ic_t, f.name)} == {"issuer_id", "instance_owner_iss", "instance_subject", "profile_digest", "log_identity_digest"})
    check("pB differs from the toy pB only in key_resolution", {k for k in pj if pj[k] != pj2[k]} == {"key_resolution"})
    check("authorized admitters unchanged (owner is not an admitter)", pj2["authorized_admitters"] == pj["authorized_admitters"] and "volmax-owner" not in pj2["authorized_admitters"])

    # ---------------- lifecycle (shape of ratified POST-BASE-match): profile(0) instance(1) admission(2) closure(3) adjudication(4)
    S.key_of = lambda iss: keys[iss.decode()]
    S.STD_KEYS = list(names)
    ADM = b"admitter-one"
    prof = types.SimpleNamespace(inst=ic, vmd=pj["verifier_manifest_digest"])
    entries = {
        0: P.Detailed(0, owner, "profileCommit", "verified", "profileCommit", ic.profile_digest),
        1: P.Detailed(1, owner, "instanceCommit", "verified", "instanceCommit", ic),
        2: P.Detailed(2, ADM, "admission", "verified", "admission", ("first", 0)),
    }
    entries[3] = P.Detailed(3, owner, "closure", "verified", "closure",
                            P.ClosurePayload(subj, True, (2,), evidence_digest, PS.preclosure_digest(entries, 3, owner=owner)))
    entries[4] = P.Detailed(4, owner, "adjudication", "verified", "adjudication", (0, 1, 3))
    size, target = 5, 4
    stmts, km = S.build_log(entries, [subj] * size, size, subj, prof, ib)
    rcpt = G.receipt(stmts, target, tskey=ts_key, ts_iss=ts_iss)
    kr = {n: bytes.fromhex(v) for n, v in kr_hex.items()}
    req = G.request(rcpt, stmts[target], list(enumerate(stmts)), receipt_key_bytes=G.cose_key(ts_key), fp=G.thumbprint(ts_key), ts_iss=ts_iss,
                    key_res=kr, key_mat=km, subject=S.sub_str(subj))
    krd = jd({"key_resolution": kr_hex})
    rows = tuple(P.Row(i, subj) for i in range(size))
    tb_exp = P.encode_transcript(P.Transcript(lid2, krd, size, G.mth([G.leaf_hash(s) for s in stmts]), rows, tuple(entries[i] for i in sorted(entries))))
    payload = PS.stmt_payload(stmts[target])

    # A12-A14 applicability: the adjudication wire built by S.adj_wire carries the toy frozen digests. Record them as used.
    a12 = {k: S.FROZEN_A12_A14[k] for k in ("codec_digest", "capability_proof_digest", "proof_digest")}
    wire = json.loads(payload)["predicate"]
    check("adjudication wire carries the frozen A12-A14 digests unchanged", all(wire[k] == a12[k] for k in a12))
    check("adjudication wire instance_subject is the derived volmax-owner subject", wire["instance_subject"] == subj.decode())

    # ---------------- write public material only
    os.makedirs(out, exist_ok=True)
    pub = os.path.join(out, "public")
    os.makedirs(pub, exist_ok=True)
    files = {"request.cbor": req, "pB.json": pb, "inst.bin": inst, "iB.json": ib, "target_payload.json": payload, "tB.expected": tb_exp}
    for n, b in files.items():
        open(os.path.join(out, n), "wb").write(b)
    for n, k in list(keys.items()) + [("ts", ts_key)]:
        open(os.path.join(pub, f"{n}.public.cose_key.cbor"), "wb").write(G.cose_key(k))
    expect = {"s2b": {"status": "Verified"}, "s2a": ".accept", "e2e": "some", "post": {"verdict": "BINDING_MATCH", "rule": None}}
    open(os.path.join(out, "expect.json"), "w").write(json.dumps(expect, indent=1, sort_keys=True) + "\n")
    meta = {
        "status": "NON-NORMATIVE FEASIBILITY SPIKE FIXTURE; test keys only; not S3 live-capture evidence; not a mutation of any S3 capture",
        "identity": {"owner_iss": owner.decode(), "instance_subject": subj.decode(), "ts_iss": ts_iss,
                     "ts_key_thumbprint": G.thumbprint(ts_key).hex(), "log_identity_digest": lid2.hex(), "issuer_key_thumbprints": kr_hex},
        "unchanged_vs_ratified_toy": {"iB_sha256": H(ib).hex(), "a12_a14": a12, "verifier_manifest_digest": pj["verifier_manifest_digest"],
                                      "lifecycle_shape": "profile(0) instance(1) admission(2) closure(3) adjudication(4); target 4"},
        "sources": {"s2b_commit": subprocess.run(["git", "-C", a.s2b, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip(),
                    "s2a_commit": subprocess.run(["git", "-C", a.s2a, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip(),
                    "template_pB_sha256": H(pb_t).hex(), "template_inst_sha256": H(rd(os.path.join(a.s2b, "profile", "inst.bin"))).hex()},
        "generator_environment": {"python": sys.version.split()[0], "note": "NOT the pinned oracle interpreter (CPython 3.12.3); generator output is test input, validated by the pinned chain"},
        "sanity_checks": checks,
        "file_sha256": {n: H(b).hex() for n, b in files.items()},
        "private_keys": "generated outside the repository, not committed, not recorded",
    }
    open(os.path.join(out, "PUBLIC_META.json"), "w").write(json.dumps(meta, indent=1, sort_keys=True) + "\n")
    print(json.dumps({"out": out, "subject": subj.decode(), "log_identity_digest": lid2.hex(), "file_sha256": meta["file_sha256"], "checks": len(checks)}, indent=1))


if __name__ == "__main__":
    main()
