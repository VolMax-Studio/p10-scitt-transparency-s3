#!/usr/bin/env python3
"""TEST TOOLING (not acceptance code). Generates ML-1: a NEW authenticated synthetic mixed log for the `volmax-owner` instance.

Layout (7 leaves; see spec/mixed-log-test-plan.md):
    0  registration-policy TEST statement     (non-target, TS-originated)
    1  trust-anchor TEST statement            (non-target, TS-originated)
    2  profile commitment      3  instance commitment      4  admission
    5  closure                 6  adjudication  (Receipt target)

It is NOT the existing five-leaf fixture with leaves prepended. Every index-bearing item is recomputed for the new positions: the closure's
`ordered_admission_refs`, its PreclosureDigestV0 (over the shifted view), the adjudication refs and its wire members
(profile_commitment_ref=2, instance_commitment_ref=3, evidence_closure_ref=5, evidence_admission_refs=[4], preclosure_transcript_digest),
every signature that covers a changed payload, the Merkle tree, the Receipt (tree_size 7, leaf_index 6, proof path, signed root), the request.
Unchanged by construction: pB, inst, iB (the exact toy bytes), the instance subject, LogIdentityV0, the A12-A14 frozen digests.

Keys: the external test keys of spike/fixtures/volmax-owner are REUSED when they are available in --keys-dir (outside the repository) and their
thumbprints match the fixture's pB.key_resolution and the fixture's LogIdentityV0; otherwise the generator stops. To use fresh keys, first run
spike/fixtures/gen_volmax_owner.py with a new --keys-dir (it derives a new pB/inst/LogIdentityV0 consistently) and pass that output directory
as --fixture. One further key, `policy-test`, signs the two leading TEST statements and is generated into --keys-dir when absent; it appears in
no key table, because the frozen chain does not verify non-target statements. Private keys are never written to the output.

The two leading statements are synthetic test statements. Their content is not a Registration Policy, no bootstrap mechanism is selected, and
nothing about policy enforcement follows from them. They satisfy only the structural constraints of the frozen classification: tagged
COSE_Sign1, protected CWT iss/sub as UTF-8 text with sub != instance_subject, empty unprotected header.

usage: gen_ml1.py --s2b DIR --s2a DIR --fixture spike/fixtures/volmax-owner --keys-dir DIR --out DIR
"""
import argparse, dataclasses, hashlib, json, os, subprocess, sys, types


def main():
    ap = argparse.ArgumentParser()
    for k in ("s2b", "s2a", "fixture", "keys_dir", "out"):
        ap.add_argument("--" + k.replace("_", "-"), required=True)
    a = ap.parse_args()
    out, kdir, fx = os.path.abspath(a.out), os.path.abspath(a.keys_dir), os.path.abspath(a.fixture)
    here = os.path.dirname(os.path.abspath(__file__))
    top = subprocess.run(["git", "-C", here, "rev-parse", "--show-toplevel"], capture_output=True, text=True).stdout.strip()
    if top and (kdir == top or kdir.startswith(top + os.sep)):
        raise SystemExit("refusing: --keys-dir is inside the repository")
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
    checks = []

    def check(name, ok, detail=""):
        checks.append({"check": name, "ok": bool(ok), "detail": detail})
        if not ok:
            raise SystemExit(f"generator sanity check failed: {name} {detail}")

    # ---- the volmax-owner instance material, byte for byte
    pb, inst_b, ib = rd(os.path.join(fx, "pB.json")), rd(os.path.join(fx, "inst.bin")), rd(os.path.join(fx, "iB.json"))
    meta = json.load(open(os.path.join(fx, "PUBLIC_META.json")))
    r = P._R(inst_b)
    ic = P.InstanceCommitment(*[r.bytes_() for _ in range(13)])
    check("inst decodes canonically", r.i == len(inst_b) and ic.encode() == inst_b)
    check("iB is the exact toy S1 instance", H(ib).hex() == "62353069823aace3a91b37ffabcdf7b2d608134457276b2a5e597ebb49e0e824")
    pj = json.loads(pb)
    ts_iss = meta["identity"]["ts_iss"]

    # ---- keys: reuse the external test keys when available and consistent with the fixture, else stop
    names = ["admitter-one", "admitter-two", "intruder-x", "volmax-owner"]
    load = lambda n: serialization.load_pem_private_key(rd(os.path.join(kdir, n + ".pem")), None)
    try:
        keys = {n: load(n) for n in names}
        ts_key = load("ts")
    except FileNotFoundError as e:
        raise SystemExit(f"external test keys not available in {kdir} ({e}). Regenerate the base fixture with spike/fixtures/gen_volmax_owner.py "
                         "(fresh keys and consistent bindings) and pass it as --fixture.")
    for n in names:
        check(f"key {n} matches pB.key_resolution", G.thumbprint(keys[n]).hex() == pj["key_resolution"][n])
    lp = jd({"rule": "LeafEncodeV0", "spec_digest": pj["leaf_encoding_spec_digest"]})
    lid = H(jcs.canonicalize({"checkpoint_verification_key_fingerprint": G.thumbprint(ts_key).hex(), "leaf_encoding_profile_digest": lp.hex(), "ts_iss": ts_iss, "vds_algorithm": 1}))
    check("TS key and ts_iss reproduce inst.log_identity_digest", lid == ic.log_identity_digest)
    pkp = os.path.join(kdir, "policy-test.pem")
    if not os.path.exists(pkp):
        k = ec.generate_private_key(ec.SECP256R1())
        fd = os.open(pkp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    policy_key = load("policy-test")

    owner, ADM, subj = ic.issuer_id, b"admitter-one", ic.instance_subject
    p2 = os.path.join(a.s2a, "vectors", "P2")
    T = P.decode_transcript(rd(os.path.join(p2, "tB.bin")))
    evidence_digest = next(d.payload for d in T.detailed if d.payload_tag == "closure").closed_evidence_set_digest

    # ---- leading non-target TEST statements (structure only)
    def jb(o): return json.dumps(o, sort_keys=True, separators=(",", ":")).encode()
    sub0, sub1 = "urn:volmax:s3-test:registration-policy", "urn:volmax:s3-test:trust-anchor"
    note = "SYNTHETIC S3 TEST STATEMENT. Not a Registration Policy; no bootstrap mechanism is selected; nothing is enforced."
    pay0 = jb({"kind": "registration-policy-test-statement", "note": note, "version": "1"})
    pay1 = jb({"kind": "trust-anchor-test-statement", "note": note, "anchors": [{"name": n, "thumbprint": G.thumbprint(keys[n]).hex()} for n in names]})
    st0 = G.signed_statement(pay0, key=policy_key, iss=ts_iss, sub=sub0, ct="application/json")
    st1 = G.signed_statement(pay1, key=policy_key, iss=ts_iss, sub=sub1, ct="application/json")
    import cbor2
    for st in (st0, st1):
        c = cbor2.loads(st)
        check("leading statement is a tagged COSE_Sign1 with an empty unprotected map", getattr(c, "tag", None) == 18 and c.value[1] == {} and len(c.value) == 4)
    check("leading subs differ from the instance subject", subj.decode() not in (sub0, sub1))

    # ---- the lifecycle at shifted indices
    S.key_of = lambda iss: keys[iss.decode()]
    S.STD_KEYS = list(names)
    prof = types.SimpleNamespace(inst=ic, vmd=pj["verifier_manifest_digest"])
    entries = {
        2: P.Detailed(2, owner, "profileCommit", "verified", "profileCommit", ic.profile_digest),
        3: P.Detailed(3, owner, "instanceCommit", "verified", "instanceCommit", ic),
        4: P.Detailed(4, ADM, "admission", "verified", "admission", ("first", 0)),
    }
    entries[5] = P.Detailed(5, owner, "closure", "verified", "closure", P.ClosurePayload(subj, True, (4,), evidence_digest, PS.preclosure_digest(entries, 5, owner=owner)))
    entries[6] = P.Detailed(6, owner, "adjudication", "verified", "adjudication", (2, 3, 5))
    size, target = 7, 6
    placeholder = b"p10s2sub:" + b"%064x" % 1
    rows_sub = [placeholder, placeholder + b"x"] + [subj] * 5      # indices 0,1: replaced below
    stmts, km = S.build_log(entries, rows_sub, size, subj, prof, ib)
    stmts[0], stmts[1] = st0, st1
    rcpt = G.receipt(stmts, target, tskey=ts_key, ts_iss=ts_iss)
    kr_hex = pj["key_resolution"]
    kr = {n: bytes.fromhex(v) for n, v in kr_hex.items()}
    req = G.request(rcpt, stmts[target], list(enumerate(stmts)), receipt_key_bytes=G.cose_key(ts_key), fp=G.thumbprint(ts_key), ts_iss=ts_iss,
                    key_res=kr, key_mat=km, subject=S.sub_str(subj))
    rowobjs = tuple(P.Row(i, (sub0.encode() if i == 0 else sub1.encode() if i == 1 else subj)) for i in range(size))
    tb_exp = P.encode_transcript(P.Transcript(lid, jd({"key_resolution": kr_hex}), size, G.mth([G.leaf_hash(s) for s in stmts]), rowobjs, tuple(entries[i] for i in sorted(entries))))
    payload = PS.stmt_payload(stmts[target])

    wire = json.loads(payload)["predicate"]
    a12 = {k: S.FROZEN_A12_A14[k] for k in ("codec_digest", "capability_proof_digest", "proof_digest")}
    check("adjudication wire refs are the shifted indices", (wire["profile_commitment_ref"], wire["instance_commitment_ref"], wire["evidence_closure_ref"], wire["evidence_admission_refs"]) == ("2", "3", "5", ["4"]))
    check("adjudication wire preclosure digest equals the shifted closure digest", wire["preclosure_transcript_digest"] == entries[5].payload.checkpoint_preclosure_transcript_digest.hex())
    check("frozen A12-A14 digests carried unchanged", all(wire[k] == a12[k] for k in a12))
    old = [x for _, x in sorted(cbor2.loads(rd(os.path.join(fx, "request.cbor")))[2][3], key=lambda t: t[0])]
    check("profile/instance/admission statements carry no index, so they equal the base fixture's leaves 0-2 byte for byte", stmts[2:5] == old[0:3])
    check("closure and adjudication statements were re-signed for the shifted indices", stmts[5] != old[3] and stmts[6] != old[4])
    check("the log is not the base fixture with leaves prepended: its root differs from every prefix-extension of the old leaf list", G.mth([G.leaf_hash(x) for x in stmts]) != G.mth([G.leaf_hash(x) for x in [st0, st1] + old]))

    os.makedirs(out, exist_ok=True)
    pub = os.path.join(out, "public")
    os.makedirs(pub, exist_ok=True)
    files = {"request.cbor": req, "pB.json": pb, "inst.bin": inst_b, "iB.json": ib, "target_payload.json": payload, "tB.expected": tb_exp}
    for n, b in files.items():
        open(os.path.join(out, n), "wb").write(b)
    for n in os.listdir(os.path.join(fx, "public")):
        open(os.path.join(pub, n), "wb").write(rd(os.path.join(fx, "public", n)))
    open(os.path.join(pub, "policy-test.public.cose_key.cbor"), "wb").write(G.cose_key(policy_key))
    expect = {"s2b": {"status": "Verified"}, "s2b_detail": {"checkpoint_size": 7, "subject_idx": [2, 3, 4, 5, 6], "unreadable": []},
              "s2a": ".accept", "e2e": "some", "post": {"verdict": "BINDING_MATCH", "rule": None}}
    open(os.path.join(out, "expect.json"), "w").write(json.dumps(expect, indent=1, sort_keys=True) + "\n")
    m = {
        "status": "NON-NORMATIVE TEST FIXTURE ML-1 (synthetic authenticated mixed log); test keys only; not an S3 capture; the leading statements are synthetic and select no bootstrap",
        "layout": {"0": "registration-policy TEST statement (non-target, sub " + sub0 + ")", "1": "trust-anchor TEST statement (non-target, sub " + sub1 + ")",
                   "2": "profile commitment", "3": "instance commitment", "4": "admission", "5": "closure", "6": "adjudication (Receipt target)"},
        "identity": meta["identity"], "policy_test_key_thumbprint": G.thumbprint(policy_key).hex(),
        "leading_statement_sha256": [H(st0).hex(), H(st1).hex()],
        "unchanged_vs_volmax_owner_fixture": {"pB_sha256": H(pb).hex(), "inst_sha256": H(inst_b).hex(), "iB_sha256": H(ib).hex(), "a12_a14": a12},
        "sources": {"base_fixture": "spike/fixtures/volmax-owner", "s2b_commit": subprocess.run(["git", "-C", a.s2b, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip(),
                    "s2a_commit": subprocess.run(["git", "-C", a.s2a, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()},
        "generator_environment": {"python": sys.version.split()[0], "note": "not the pinned oracle interpreter; output is test input validated by the pinned chain"},
        "sanity_checks": checks, "file_sha256": {n: H(b).hex() for n, b in files.items()},
        "private_keys": "kept outside the repository, not recorded",
    }
    open(os.path.join(out, "PUBLIC_META.json"), "w").write(json.dumps(m, indent=1, sort_keys=True) + "\n")
    print(json.dumps({"out": out, "file_sha256": m["file_sha256"], "checks": len(checks)}, indent=1))


if __name__ == "__main__":
    main()
