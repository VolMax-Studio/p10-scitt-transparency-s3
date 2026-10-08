#!/usr/bin/env python3
"""RUNTIME ISSUER TOOLING (candidate, non-normative). Called by `s3-capture submit --producer` once per statement, BEFORE that statement is registered.

For step N it creates and signs statement N from what the log has actually registered so far:
  * the authenticated prefix [0,N) is obtained from the PUBLIC read endpoint (`s3-capture export`, HTTP only, checkpoint verified with the pinned key and every
    entry proved into its root) and cross-checked against the retained submissions and the returned registration indices;
  * every index used in a statement (admission refs, adjudication refs) is the index the facade ACTUALLY returned, recovered from that prefix by decoding
    the retained statements (signature verified with the public issuer keys), never an assumed constant;
  * the closure's preclosure digest is PreclosureDigestV0 over the view of that decoded prefix, computed with the ratified S2b reference definition
    (tests/s2a/post_scenarios.preclosure_digest), and statements are built and signed with the ratified S2b test builders (scenarios.statement_for).
Issuer private keys are read from --issuer-keys (outside the repository); the Receipt key is never available to this tool.

usage (by the client): issuer_tool.py --config RUN_CONFIG.json --step N --run RUN
prints one JSON line: {"file","origin"} or {"done":true}. Staged files and a derivation log are written under RUN/producer/.
"""
import argparse, hashlib, json, os, subprocess, sys, types
import cbor2

ap = argparse.ArgumentParser()
ap.add_argument("--config", required=True); ap.add_argument("--step", type=int, required=True); ap.add_argument("--run", required=True)
a = ap.parse_args()
cfg = json.load(open(a.config))
for sub in ("tests/differential", "tests/s2a", "orchestration"): sys.path.insert(0, os.path.join(cfg["s2b"], sub))
import jcs
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
import gen_corpus as G
import scenarios as S
import post_scenarios as PS
import post_s2a as P

H = lambda b: hashlib.sha256(b).digest()
rd = lambda p: open(p, "rb").read()
CD = cfg["config_dir"]
seq = cfg["sequence"]
if a.step >= len(seq):
    print(json.dumps({"done": True})); sys.exit(0)
role = seq[a.step]

owner_name = cfg["owner"]; owner = owner_name.encode()
pj = json.loads(rd(os.path.join(CD, "pB.json"))); ib = rd(os.path.join(CD, "iB.json"))
r = P._R(rd(os.path.join(CD, "inst.bin"))); ic = P.InstanceCommitment(*[r.bytes_() for _ in range(13)])
meta = json.load(open(os.path.join(CD, "PUBLIC_META.json")))
subject = ic.instance_subject; subj = subject.decode()
assert subj == meta["identity"]["instance_subject"] and ic.issuer_id == owner
evidence_digest = bytes.fromhex(meta["closed_evidence_set_digest"])
names = ["admitter-one", "admitter-two", "intruder-x", owner_name]
keys = {n: serialization.load_pem_private_key(rd(os.path.join(cfg["issuer_keys"], n + ".pem")), None) for n in names}
policy_key = serialization.load_pem_private_key(rd(os.path.join(cfg["issuer_keys"], "policy-test.pem")), None)
assert not os.path.exists(os.path.join(cfg["issuer_keys"], "ts.pem")), "the Receipt key must not be reachable from the issuer tooling"
S.key_of = lambda iss: keys[iss.decode()]
S.STD_KEYS = list(names)
prof = types.SimpleNamespace(inst=ic, vmd=pj["verifier_manifest_digest"])
pub = {n: cbor2.loads(rd(os.path.join(CD, "public", n + ".public.cose_key.cbor"))) for n in names}
PT_INV = {v: k for k, v in G.PT.items()}
TOKEN = {"profile": "profileCommit", "instance": "instanceCommit", "admission": "admission", "closure": "closure", "adjudication": "adjudication"}

def verify_sig(iss, prot_b, payload, sig):
    k = pub.get(iss)
    if k is None or payload is None: return False
    pk = ec.EllipticCurvePublicNumbers(int.from_bytes(k[-2], "big"), int.from_bytes(k[-3], "big"), ec.SECP256R1()).public_key()
    try:
        pk.verify(encode_dss_signature(int.from_bytes(sig[:32], "big"), int.from_bytes(sig[32:], "big")), G.sig_structure(prot_b, payload), ec.ECDSA(hashes.SHA256())); return True
    except Exception: return False

def decode(i, st):
    t = cbor2.loads(st); prot_b, _, payload, sig = t.value; prot = cbor2.loads(prot_b); claims = prot[15]
    d = {"idx": i, "iss": claims[1], "sub": claims[2], "sig_ok": verify_sig(claims[1], prot_b, payload, sig), "kind": None, "pred": None}
    try:
        j = json.loads(payload); d["kind"] = PT_INV.get(j["predicateType"]); d["pred"] = j["predicate"]
    except Exception: pass
    return d

# ---- authenticated prefix from the PUBLIC read endpoint
prefix, derived = [], {"step": a.step, "role": role}
if a.step > 0:
    od = os.path.join(a.run, "producer", f"prefix-{a.step:06d}")
    rc = subprocess.run([os.path.join(cfg["bin"], "s3-capture"), "export", "--public", cfg["public_url"], "--note-vkey", cfg["note_vkey"], "--origin", cfg["origin"],
                         "--expect-size", str(a.step), "--out", od], capture_output=True, text=True)
    if rc.returncode: sys.exit("authenticated prefix export failed: " + rc.stdout + rc.stderr)
    for i in range(a.step):
        le = rd(os.path.join(od, "export", f"{i:06d}.leaf_input")); assert le[:17] == b"P10-LeafEncodeV0\x00" and int.from_bytes(le[53:61], "big") == len(le) - 61
        st = le[61:]
        resp = json.load(open(os.path.join(a.run, "returned", f"{i:06d}.response.json")))
        who = "operator" if os.path.exists(os.path.join(a.run, "operator", "submissions", f"{i:06d}.cose")) else "issuer"
        assert resp["index"] == i, f"facade returned index {resp['index']} for step {i}"
        assert rd(os.path.join(a.run, who, "submissions", f"{i:06d}.cose")) == st, f"authenticated prefix differs from the retained submission at {i}"
        prefix.append(decode(i, st))
    derived["prefix_root"] = json.load(open(os.path.join(od, "export-result.json")))["root"]
    derived["returned_indices_equal_positions"] = True
    derived["prefix_summary"] = [{"idx": d["idx"], "iss": d["iss"], "kind": d["kind"], "subject": d["sub"] == subj, "sig_ok": d["sig_ok"]} for d in prefix]

subj_entries = [d for d in prefix if d["sub"] == subj]
def idx_of(kind):
    m = [d["idx"] for d in subj_entries if d["kind"] == kind and d["iss"] == owner_name and d["sig_ok"]]
    assert len(m) == 1, f"expected exactly one verified owner {kind} statement in the authenticated prefix, found {m}"
    return m[0]
def detailed_view(k):
    out = {}
    for d in subj_entries:
        if d["idx"] >= k: continue
        tok = TOKEN.get(d["kind"])      # predicate kind -> reference-model token (None: not a P10 lifecycle statement)
        out[d["idx"]] = P.Detailed(d["idx"], d["iss"].encode(), tok, "verified" if d["sig_ok"] else "badSignature", tok, None)
    return out

def build(det, closures=None):
    return S.statement_for(det, subj, subject, closures or {}, {}, prof, ib, None)

if role in ("bootstrap-policy", "bootstrap-trust-anchor"):
    def jb(o): return json.dumps(o, sort_keys=True, separators=(",", ":")).encode()
    note = "SYNTHETIC EXPERIMENTAL S3 TEST STATEMENT. Not a Registration Policy; no bootstrap mechanism is selected; nothing is enforced."
    if role == "bootstrap-policy":
        st = G.signed_statement(jb({"kind": "registration-policy-test-statement", "note": note, "version": "1"}), key=policy_key, iss=cfg["ts_iss"], sub="urn:volmax:s3-test:registration-policy", ct="application/json")
    else:
        st = G.signed_statement(jb({"kind": "trust-anchor-test-statement", "note": note, "anchors": [{"name": n, "thumbprint": G.thumbprint(keys[n]).hex()} for n in names]}),
                                key=policy_key, iss=cfg["ts_iss"], sub="urn:volmax:s3-test:trust-anchor", ct="application/json")
    origin = "operator"
else:
    origin = "issuer"
    n = a.step   # the index this statement will be registered at (checked by the client against the facade's answer)
    if role == "profile":
        det = P.Detailed(n, owner, "profileCommit", "verified", "profileCommit", ic.profile_digest)
    elif role == "instance":
        det = P.Detailed(n, owner, "instanceCommit", "verified", "instanceCommit", ic)
    elif role == "admission":
        det = P.Detailed(n, b"admitter-one", "admission", "verified", "admission", ("first", 0))
    elif role == "closure":
        adm = sorted(d["idx"] for d in subj_entries if d["kind"] == "admission" and d["iss"] in ("admitter-one", "admitter-two") and d["sig_ok"])
        assert adm, "no verified admission in the authenticated prefix"
        view = detailed_view(n)
        pre = PS.preclosure_digest(view, n, owner=owner)
        derived.update({"ordered_admission_refs": adm, "preclosure_view_entries": [[str(i), d.kind, d.iss.decode()] for i, d in sorted(view.items())], "preclosure_digest": pre.hex(),
                        "closed_evidence_set_digest": evidence_digest.hex()})
        det = P.Detailed(n, owner, "closure", "verified", "closure", P.ClosurePayload(subject, True, tuple(adm), evidence_digest, pre))
    elif role == "adjudication":
        pi, ii, ci = idx_of("profile"), idx_of("instance"), idx_of("closure")
        cp = [d for d in subj_entries if d["idx"] == ci][0]["pred"]
        closure = P.ClosurePayload(subject, True, tuple(int(x) for x in cp["ordered_admission_refs"]), bytes.fromhex(cp["closed_evidence_set_digest"]), bytes.fromhex(cp["checkpoint_preclosure_transcript_digest"]))
        derived.update({"profile_commitment_ref": pi, "instance_commitment_ref": ii, "evidence_closure_ref": ci, "ordered_admission_refs": list(closure.ordered_admission_refs)})
        det = P.Detailed(n, owner, "adjudication", "verified", "adjudication", (pi, ii, ci))
        st = build(det, {ci: closure})
    else:
        sys.exit("unknown role " + role)
    if role != "adjudication": st = build(det)
sd = os.path.join(a.run, "producer", "staged"); os.makedirs(sd, exist_ok=True)
f = os.path.join(sd, f"{a.step:06d}.cose"); open(f, "wb").write(st)
derived.update({"statement_sha256": H(st).hex(), "statement_len": len(st), "origin": origin})
with open(os.path.join(a.run, "producer", "steps.jsonl"), "a") as lg: lg.write(json.dumps(derived, sort_keys=True) + "\n")
print(json.dumps({"file": f, "origin": origin}))
