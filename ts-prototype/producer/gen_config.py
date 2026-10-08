#!/usr/bin/env python3
"""PRODUCER / CONFIGURATION (candidate, non-normative). Generates the PUBLIC configuration of a fresh `volmax`-style instance on the frozen toy semantics, with fresh keys.

Only configuration is produced: NO lifecycle statement, no request, no Receipt. Statements are created and signed at run time by issuer_tool.py.

Fresh: all issuer keys (owner, admitter-one, admitter-two, intruder-x), the bootstrap `policy-test` key (issuer keys dir), and the Receipt key (TS keys dir; a separate
directory so that the issuer tooling never holds the Receipt key). Derived from the new public configuration: pB.key_resolution (and hence the profile digest), the
SubjectDeriveV0 subject (from the owner name and the toy request_id), LogIdentityV0 (from ts_iss, the Receipt key thumbprint and the frozen leaf-encoding profile),
and the instance commitment. Unchanged: the exact toy S1 iB (sha256 62353069...), the frozen A12-A14 digests, the verifier manifest digest, claim/evidence/witness data,
rule IDs, the admitter set and its names, request_id.

Private keys go ONLY to --issuer-keys-dir / --ts-keys-dir (outside the repository, 0600) and are never written to --out.

usage: gen_config.py --s2b DIR --s2a DIR --out DIR --issuer-keys-dir DIR --ts-keys-dir DIR --owner NAME --ts-iss URL --origin ORIGIN
"""
import argparse, dataclasses, hashlib, json, os, subprocess, sys

ap = argparse.ArgumentParser()
for k in ("s2b", "s2a", "out", "issuer-keys-dir", "ts-keys-dir", "owner", "ts-iss", "origin"): ap.add_argument("--" + k, required=True)
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
policy_key = newkey(kd[0], "policy-test")
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
check("fresh keys: no key thumbprint (issuers, policy-test, TS) occurs in any committed fixture meta or profile", not ({G.thumbprint(k).hex() for k in list(keys.values()) + [policy_key, ts_key]} & seen))

os.makedirs(a.out, exist_ok=True); pub = os.path.join(a.out, "public"); os.makedirs(pub, exist_ok=True)
for n, b in (("pB.json", pb), ("inst.bin", inst), ("iB.json", ib)): open(os.path.join(a.out, n), "wb").write(b)
for n, k in list(keys.items()) + [("ts", ts_key)]: open(os.path.join(pub, f"{n}.public.cose_key.cbor"), "wb").write(G.cose_key(k))
open(os.path.join(pub, "policy-test.public.cose_key.cbor"), "wb").write(G.cose_key(policy_key))
meta = {"status": "NON-NORMATIVE EXPLORATORY CONFIGURATION; fresh test keys only; not S3 live-capture evidence",
        "identity": {"owner_iss": a.owner, "instance_subject": subj.decode(), "ts_iss": a.ts_iss, "ts_key_thumbprint": G.thumbprint(ts_key).hex(), "log_identity_digest": lid2.hex(),
                     "issuer_key_thumbprints": kr_hex, "policy_test_key_thumbprint": G.thumbprint(policy_key).hex(), "profile_digest": H(pb).hex()},
        "unchanged_vs_ratified_toy": {"iB_sha256": H(ib).hex(), "verifier_manifest_digest": pj["verifier_manifest_digest"], "request_id": ic_t.request_id.hex(),
                                      "a12_a14": {"codec_digest": "c156965f810643b115b6bbe720c87e874522bfff298490713be5874677346dd9", "capability_proof_digest": "9482c3f775e78a72dd9b8290c67a59bf00716ac0adb86d5b7b0d8eb4045a4928",
                                                  "proof_digest": "30f498438473d39566d951b75dd5ce7326d9c368da3cda4868635a3e422a8696"}},
        "closed_evidence_set_digest": evidence_digest.hex(),
        "sources": {"s2b_commit": subprocess.run(["git", "-C", a.s2b, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip(),
                    "s2a_commit": subprocess.run(["git", "-C", a.s2a, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip(),
                    "template_pB_sha256": H(pb_t).hex(), "template_inst_sha256": H(rd(os.path.join(a.s2b, "profile", "inst.bin"))).hex()},
        "sanity_checks": checks, "file_sha256": {n: H(rd(os.path.join(a.out, n))).hex() for n in ("pB.json", "inst.bin", "iB.json")},
        "private_keys": "generated outside the repository, not committed, not recorded"}
open(os.path.join(a.out, "PUBLIC_META.json"), "w").write(json.dumps(meta, indent=1, sort_keys=True) + "\n")
# expectation fixed BEFORE the run from the configured layout
expect = {"s2b": {"status": "Verified"}, "s2a": ".accept", "e2e": "some", "post": {"verdict": "BINDING_MATCH", "rule": None},
          "s2b_detail": {"checkpoint_size": a.expect_size, "subject_idx": [int(x) for x in a.expect_subject_idx.split(",")], "unreadable": []}}
open(os.path.join(a.out, "expect.json"), "w").write(json.dumps(expect, indent=1, sort_keys=True) + "\n")
print(json.dumps({"subject": subj.decode(), "log_identity_digest": lid2.hex(), "profile_digest": H(pb).hex(), "ts_key_thumbprint": G.thumbprint(ts_key).hex(), "checks": len(checks)}, indent=1))
