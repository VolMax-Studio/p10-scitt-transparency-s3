#!/usr/bin/env python3
"""PRODUCER / CONFIGURATION (candidate, non-normative). Generates the PUBLIC configuration of a fresh `volmax`-style instance on the frozen toy semantics, with fresh keys.

Only configuration is produced: NO lifecycle statement, no request, no Receipt. Statements are created and signed at run time by issuer_tool.py.

Fresh: all issuer keys (owner, admitter-one, admitter-two, intruder-x), the `operator` key (signs the bootstrap declarations and the operator note) (issuer keys dir), and the Receipt key (TS keys dir; a separate
directory so that the issuer tooling never holds the Receipt key). Derived from the new public configuration: pB.key_resolution (and hence the profile digest), the
SubjectDeriveV0 subject (from the owner name and the toy request_id), LogIdentityV0 (from ts_iss, the Receipt key thumbprint and the frozen leaf-encoding profile),
and the instance commitment. Unchanged: the exact toy S1 iB (sha256 62353069...), the frozen A12-A14 digests, the verifier manifest digest, claim/evidence/witness data,
rule IDs, the admitter set and its names, request_id.

Private keys go ONLY to --issuer-keys-dir / --ts-keys-dir (outside the repository, 0600) and are never written to --out.

Also written (public, deterministic bytes): the facade's PRECONFIGURED ISSUER TABLE (public/issuers.json: owner, admitter-one, admitter-two and the operator; intruder-x is
deliberately not registered) and the two bootstrap DECLARATION payloads (bootstrap/policy-declaration.json, bootstrap/verification-material-declaration.json) with their SHA-256.
The declarations are published bytes; they confer no key authority and are not read by the facade.

usage: gen_config.py --s2b DIR --s2a DIR --out DIR --issuer-keys-dir DIR --ts-keys-dir DIR --owner NAME --ts-iss URL --origin ORIGIN --note-vkey VKEY [--operator-iss NAME]
"""
import argparse, base64, dataclasses, hashlib, json, os, subprocess, sys

ap = argparse.ArgumentParser()
for k in ("s2b", "s2a", "out", "issuer-keys-dir", "ts-keys-dir", "owner", "ts-iss", "origin", "note-vkey"): ap.add_argument("--" + k, required=True)
ap.add_argument("--operator-iss", default="volmax-s3-operator", help="iss of the statements signed by the operator (bootstrap declarations, operator note)")
ap.add_argument("--max-leaf-input", type=int, default=65535, help="facade limit on len(LeafEncodeV0(statement)); the statement limit is this minus the 61-byte header")
ap.add_argument("--max-detached-payload", type=int, default=1 << 20)
ap.add_argument("--expect-size", type=int, default=7, help="number of leaves of the configured layout (expectation written BEFORE the run)")
ap.add_argument("--expect-subject-idx", default="2,3,4,5,6", help="log indices of statements about the instance subject in the configured layout")
a = ap.parse_args()
here = os.path.dirname(os.path.abspath(__file__))
top = subprocess.run(["git", "-C", here, "rev-parse", "--show-toplevel"], capture_output=True, text=True).stdout.strip()
kd = [os.path.abspath(a.issuer_keys_dir), os.path.abspath(a.ts_keys_dir)]
for d in kd:
    if top and (d == top or d.startswith(top + os.sep)): sys.exit("refusing: a keys dir is inside the repository")
for sub in ("tests/differential", "tests/s2a", "orchestration"): sys.path.insert(0, os.path.join(a.s2b, sub))
import jcs
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
import gen_corpus as G
import post_s2a as P

H = lambda b: hashlib.sha256(b).digest()
jd = lambda o: H(jcs.canonicalize(o))
rd = lambda p: open(p, "rb").read()
checks = []
def check(name, ok, detail=""):
    checks.append({"check": name, "ok": bool(ok), "detail": detail})
    if not ok: sys.exit(f"sanity check failed: {name} {detail}")
def subject_derive(issuer, request_id): return b"p10s2sub:" + jd({"issuer_id": issuer.decode(), "request_id": request_id.hex(), "v": "SubjectDeriveV0"}).hex().encode()
def lid(ts_iss, ts_key, spec_hex):
    lp = jd({"rule": "LeafEncodeV0", "spec_digest": spec_hex})
    return H(jcs.canonicalize({"checkpoint_verification_key_fingerprint": G.thumbprint(ts_key).hex(), "leaf_encoding_profile_digest": lp.hex(), "ts_iss": ts_iss, "vds_algorithm": 1}))
def decode_inst(b):
    r = P._R(b); ic = P.InstanceCommitment(*[r.bytes_() for _ in range(13)])
    assert r.i == len(b) and ic.encode() == b; return ic

pb_t, ic_t = rd(os.path.join(a.s2b, "profile", "pB.json")), decode_inst(rd(os.path.join(a.s2b, "profile", "inst.bin")))
pj = json.loads(pb_t)
p2 = os.path.join(a.s2a, "vectors", "P2")
ib = rd(os.path.join(p2, "iB.json"))
T = P.decode_transcript(rd(os.path.join(p2, "tB.bin")))
evidence_digest = next(d.payload for d in T.detailed if d.payload_tag == "closure").closed_evidence_set_digest
check("toy iB bytes are the S1 p1.instance.json bytes (sha256 62353069...)", H(ib).hex() == "62353069823aace3a91b37ffabcdf7b2d608134457276b2a5e597ebb49e0e824")
check("SubjectDeriveV0 re-derivation reproduces the toy instance_subject", subject_derive(ic_t.issuer_id, ic_t.request_id) == ic_t.instance_subject)
check("LogIdentityV0 re-derivation reproduces the toy log_identity_digest", lid(G.TS_ISS, G.K_TS, pj["leaf_encoding_spec_digest"]) == ic_t.log_identity_digest)

owner = a.owner.encode()
admitters = ["admitter-one", "admitter-two"]
names = admitters + ["intruder-x", a.owner]
check("owner name is not an admitter name", a.owner not in admitters + ["intruder-x"])
for d in kd: os.makedirs(d, mode=0o700, exist_ok=True)
def newkey(dirpath, n):
    k = ec.generate_private_key(ec.SECP256R1()); p = os.path.join(dirpath, n + ".pem")
    assert not os.path.exists(p), f"refusing to overwrite {p}"
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f: f.write(k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    return k
keys = {n: newkey(kd[0], n) for n in names}
operator_key = newkey(kd[0], "operator")
check("operator iss is neither an instance name, an admitter name nor the Receipt issuer string", a.operator_iss not in names + [a.ts_iss])
ts_key = newkey(kd[1], "ts")

kr_hex = {n: G.thumbprint(keys[n]).hex() for n in names}
pj2 = dict(pj); pj2["key_resolution"] = kr_hex
pb = json.dumps(pj2, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
subj = subject_derive(owner, ic_t.request_id)
lid2 = lid(a.ts_iss, ts_key, pj["leaf_encoding_spec_digest"])
ic = dataclasses.replace(ic_t, issuer_id=owner, instance_owner_iss=owner, instance_subject=subj, profile_digest=H(pb), log_identity_digest=lid2)
inst = ic.encode()
check("only identity-dependent instance fields changed", {f.name for f in dataclasses.fields(ic) if getattr(ic, f.name) != getattr(ic_t, f.name)} == {"issuer_id", "instance_owner_iss", "instance_subject", "profile_digest", "log_identity_digest"})
check("pB differs from the toy pB only in key_resolution", {k for k in pj if pj[k] != pj2[k]} == {"key_resolution"})
check("authorized admitters unchanged and the owner is not one", pj2["authorized_admitters"] == pj["authorized_admitters"] and a.owner not in pj2["authorized_admitters"])
seen = set()
for root, _, files in os.walk(top or "."):
    if ".git" in root.split(os.sep): continue
    for f in files:
        if f in ("PUBLIC_META.json",) or f.endswith("pB.json"):
            try: seen |= {x for x in json.dumps(json.load(open(os.path.join(root, f)))).replace('"', " ").split() if len(x) == 64}
            except Exception: pass
check("fresh keys: no key thumbprint (issuers, operator, TS) occurs in any committed fixture meta or profile", not ({G.thumbprint(k).hex() for k in list(keys.values()) + [operator_key, ts_key]} & seen))

os.makedirs(a.out, exist_ok=True); pub = os.path.join(a.out, "public"); os.makedirs(pub, exist_ok=True)
for n, b in (("pB.json", pb), ("inst.bin", inst), ("iB.json", ib)): open(os.path.join(a.out, n), "wb").write(b)
for n, k in list(keys.items()) + [("ts", ts_key)]: open(os.path.join(pub, f"{n}.public.cose_key.cbor"), "wb").write(G.cose_key(k))
open(os.path.join(pub, "operator.public.cose_key.cbor"), "wb").write(G.cose_key(operator_key))
# ---- preconfigured issuer table (the facade's only source of issuer trust) and the two bootstrap declaration payloads
CANON = lambda o: json.dumps(o, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
table_issuers = [(a.owner, "volmax instance owner (signs the profile, instance, closure and adjudication statements)", keys[a.owner], a.owner + ".public.cose_key.cbor"),
                 ("admitter-one", "P10 admitter (signs the admission statement)", keys["admitter-one"], "admitter-one.public.cose_key.cbor"),
                 ("admitter-two", "P10 admitter (configured, not used in the lifecycle sequence)", keys["admitter-two"], "admitter-two.public.cose_key.cbor"),
                 (a.operator_iss, "log operator (signs the two bootstrap declarations and the operator note)", operator_key, "operator.public.cose_key.cbor")]
issuers_json = {"format": "S3-ISSUER-TABLE-V0", "issuers": [{"iss": i, "key_thumbprint": G.thumbprint(k).hex(), "cose_key_file": f} for i, _, k, f in table_issuers]}
open(os.path.join(pub, "issuers.json"), "wb").write(CANON(issuers_json) + b"\n")
STATEMENT_MAX = a.max_leaf_input - 61
policy_decl = {"kind": "s3-policy-declaration", "version": "1",
  "status": "candidate deployment declaration, generated by the log operator; not ratified; it confers no authority and is not read by the facade",
  "log": {"origin": a.origin, "receipt_issuer": a.ts_iss, "engine": "transparency-dev/tessera v1.0.4 (6bca8e8d5e23c9941f2b8a08f512b373f7131730), POSIX storage, antispam off, no witnesses",
          "leaf_encoding": "P10 LeafEncodeV0: 61-byte header followed by the statement bytes, registered unchanged"},
  "registration": {
    "structural_admission": "tagged COSE_Sign1 of four elements; protected header is one CBOR map without duplicate labels whose CWT claims (label 15) hold text iss and sub; empty unprotected header; payload a byte string or null; signature a byte string",
    "issuer_authentication": "ES256 (alg -7) signature over the COSE Sig_structure built from the submitted protected-header bytes and the signed payload, verified against the key preconfigured in the facade for the statement's iss; protected labels are limited to 1, 3, 4 and 15; a kid, if present, must equal the thumbprint of that key; the issuer table is operator configuration supplied out of band and is never read from the log",
    "detached_statement_payloads": "when the COSE payload slot is null the signed payload must accompany the registration request; it is used for verification only and is not logged",
    "size_limits": {"leaf_input_max_bytes": a.max_leaf_input, "statement_max_bytes": STATEMENT_MAX, "detached_payload_max_bytes": a.max_detached_payload},
    "duplicates": "byte-identical statements are registered once; a resubmission is authenticated again, returns the original index and the stored Receipt and appends nothing; the duplicate index is rebuilt from the log at start",
    "ordering": "one writer, sequential registration",
    "receipts": "issued only after a published checkpoint covering the entry is verified with the pinned checkpoint key; COSE_Sign1, ES256, low-S, detached payload (RFC 9942 form); one Receipt key for the whole capture"},
  "not_done": ["no authorization of issuers for particular subjects or statement types", "no payload parsing and no P10 semantic check",
               "no Registration Policy beyond the rules above", "no witnesses, no key rotation, no X.509 identity path",
               "no operator independence: one operator controls the log, the facade, the issuer table and every key",
               "no claim of RFC 9943 or SCRAPI compliance"],
  "declarations": "this statement and the verification-material declaration are published bytes; neither establishes key authority and neither is evidence that a rule was enforced beyond what the registration section states"}
cose_hex = lambda k: G.cose_key(k).hex()
vm_decl = {"kind": "s3-verification-material-declaration", "version": "1",
  "status": "candidate deployment declaration, generated by the log operator; not ratified; it confers no authority and is not read by the facade",
  "receipt_and_checkpoint_keys": {
    "receipt_key": {"role": "signs Receipts (COSE_Sign1, ES256); the only key that may sign Receipts under this log identity", "receipt_issuer": a.ts_iss,
                    "cose_key_thumbprint_sha256": G.thumbprint(ts_key).hex(), "cose_key_hex": cose_hex(ts_key)},
    "checkpoint_key": {"role": "signs log checkpoints (note format, Ed25519)", "origin": a.origin, "note_verifier_key": a.note_vkey}},
  "declared_issuer_keys": [{"iss": i, "role": r, "cose_key_thumbprint_sha256": G.thumbprint(k).hex(), "cose_key_hex": cose_hex(k)} for i, r, k, _ in table_issuers],
  "notes": ["the declared issuer keys are the entries of the facade's preconfigured issuer table; this listing is a declaration, not the source of that configuration",
            "the P10 key resolution used by the frozen verification chain is the key_resolution table of the profile artifact, committed separately",
            "Receipt and checkpoint keys are not issuer keys and no issuer key is a Receipt key"]}
bd = os.path.join(a.out, "bootstrap"); os.makedirs(bd, exist_ok=True)
open(os.path.join(bd, "policy-declaration.json"), "wb").write(CANON(policy_decl))
open(os.path.join(bd, "verification-material-declaration.json"), "wb").write(CANON(vm_decl))
bootstrap_meta = {"policy_declaration_sha256": H(CANON(policy_decl)).hex(), "verification_material_declaration_sha256": H(CANON(vm_decl)).hex(), "issuer_table_sha256": H(rd(os.path.join(pub, "issuers.json"))).hex(),
                  "policy_subject": "urn:volmax:s3:policy-declaration", "verification_material_subject": "urn:volmax:s3:verification-material-declaration", "operator_note_subject": "urn:volmax:s3:operator-note"}
meta = {"status": "NON-NORMATIVE EXPLORATORY CONFIGURATION; fresh test keys only; not S3 live-capture evidence",
        "identity": {"owner_iss": a.owner, "instance_subject": subj.decode(), "ts_iss": a.ts_iss, "ts_key_thumbprint": G.thumbprint(ts_key).hex(), "log_identity_digest": lid2.hex(),
                     "issuer_key_thumbprints": kr_hex, "operator_iss": a.operator_iss, "operator_key_thumbprint": G.thumbprint(operator_key).hex(), "profile_digest": H(pb).hex()},
        "unchanged_vs_ratified_toy": {"iB_sha256": H(ib).hex(), "verifier_manifest_digest": pj["verifier_manifest_digest"], "request_id": ic_t.request_id.hex(),
                                      "a12_a14": {"codec_digest": "c156965f810643b115b6bbe720c87e874522bfff298490713be5874677346dd9", "capability_proof_digest": "9482c3f775e78a72dd9b8290c67a59bf00716ac0adb86d5b7b0d8eb4045a4928",
                                                  "proof_digest": "30f498438473d39566d951b75dd5ce7326d9c368da3cda4868635a3e422a8696"}},
        "closed_evidence_set_digest": evidence_digest.hex(),
        "sources": {"s2b_commit": subprocess.run(["git", "-C", a.s2b, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip(),
                    "s2a_commit": subprocess.run(["git", "-C", a.s2a, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip(),
                    "template_pB_sha256": H(pb_t).hex(), "template_inst_sha256": H(rd(os.path.join(a.s2b, "profile", "inst.bin"))).hex()},
        "sanity_checks": checks, "file_sha256": {n: H(rd(os.path.join(a.out, n))).hex() for n in ("pB.json", "inst.bin", "iB.json")},
        "bootstrap": bootstrap_meta, "note_vkey": a.note_vkey, "private_keys": "generated outside the repository, not committed, not recorded"}
open(os.path.join(a.out, "PUBLIC_META.json"), "w").write(json.dumps(meta, indent=1, sort_keys=True) + "\n")
# expectation fixed BEFORE the run from the configured layout
expect = {"s2b": {"status": "Verified"}, "s2a": ".accept", "e2e": "some", "post": {"verdict": "BINDING_MATCH", "rule": None},
          "s2b_detail": {"checkpoint_size": a.expect_size, "subject_idx": [int(x) for x in a.expect_subject_idx.split(",")], "unreadable": []}}
open(os.path.join(a.out, "expect.json"), "w").write(json.dumps(expect, indent=1, sort_keys=True) + "\n")
print(json.dumps({"subject": subj.decode(), "log_identity_digest": lid2.hex(), "profile_digest": H(pb).hex(), "ts_key_thumbprint": G.thumbprint(ts_key).hex(), "checks": len(checks)}, indent=1))
