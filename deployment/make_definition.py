#!/usr/bin/env python3
"""Assembles the PUBLIC part of a candidate deployment definition from the output of `run_lifecycle.sh prepare` (candidate tooling; nothing is adopted).

Copies config/ and operator-staging/ (public configuration, bootstrap declaration payloads, issuer table, the staged operator note) into the definition directory and writes
definition-manifest.json: the resolved identity, the layout, the payload hashes, the source and executable pins and the SHA-256 of every file. No private key is read or copied.

usage: make_definition.py --prepared DIR --out DIR --repo DIR --facade-commit SHA --go-binaries DIR --entry FILE --g5 FILE
"""
import argparse, hashlib, json, os, shutil, subprocess, sys

ap = argparse.ArgumentParser()
for k in ("prepared", "out", "repo", "facade-commit", "go-binaries", "entry", "g5"): ap.add_argument("--" + k, required=True)
a = ap.parse_args()
H = lambda b: hashlib.sha256(b).hexdigest()
rd = lambda p: open(p, "rb").read()
git = lambda *x: subprocess.run(["git", "-C", a.repo, *x], capture_output=True, text=True, check=True).stdout.strip()

for sub in ("config", "operator-staging"):
    dst = os.path.join(a.out, sub)
    assert not os.path.exists(dst), f"refusing to overwrite {dst}"
    shutil.copytree(os.path.join(a.prepared, sub), dst)
for root, _, files in os.walk(a.out):
    for f in files:
        assert b"PRIVATE KEY" not in rd(os.path.join(root, f)), f"private key material in {f}"

meta = json.load(open(os.path.join(a.out, "config", "PUBLIC_META.json")))
rc = json.load(open(os.path.join(a.prepared, "run-config.json")))
idn = meta["identity"]

# source pin of the facade/producer tooling: the same file list and hashes that run_lifecycle.sh records as producer-source-pin.txt
files = git("ls-files", "--", "ts-prototype/cmd", "ts-prototype/internal", "ts-prototype/producer", "ts-prototype/scripts", "ts-prototype/go.mod", "ts-prototype/go.sum").splitlines()
lines = "".join(f"{H(rd(os.path.join(a.repo, f)))}  {f}\n" for f in files)
runner = {f: H(rd(os.path.join(a.repo, "verifier", "runner", f))) for f in ("s3c_verify.py", "s3c_chain.py", "PINNED_INPUTS.json")}
pinned = json.load(open(os.path.join(a.repo, "verifier", "runner", "PINNED_INPUTS.json")))
exe = {"entry": H(rd(a.entry)), "g5": H(rd(a.g5))}
assert exe["entry"] == pinned["executables"]["entry"]["sha256"] and exe["g5"] == pinned["executables"]["g5"]["sha256"], "supplied executables differ from PINNED_INPUTS.json"
go_bins = {n: H(rd(os.path.join(a.go_binaries, n))) for n in ("s3-facade", "s3-capture", "s3-keygen")}

man = {
    "status": "CANDIDATE DEPLOYMENT DEFINITION (public part). Proposals prepared for review; not adopted, not frozen, not signed. Key-dependent values below belong to the candidate key set only.",
    "identity": {"owner_iss": idn["owner_iss"], "operator_iss": idn["operator_iss"], "ts_iss": idn["ts_iss"], "origin": rc["origin"], "note_vkey": rc["note_vkey"],
                 "instance_subject": idn["instance_subject"], "log_identity_digest": idn["log_identity_digest"], "profile_digest": idn["profile_digest"],
                 "receipt_key_thumbprint": idn["ts_key_thumbprint"], "operator_key_thumbprint": idn["operator_key_thumbprint"], "issuer_key_thumbprints": idn["issuer_key_thumbprints"]},
    "layout": rc["expected_layout"], "receipt_payload": "detached", "log_engine": rc["log_engine"], "facade_configuration": rc["facade"],
    "bootstrap": meta["bootstrap"], "unchanged_frozen_inputs": meta["unchanged_vs_ratified_toy"],
    "pins": {
        "s1": pinned["s1"], "s2a": pinned["s2a"], "s2b": pinned["s2b"], "lean": pinned["lean"], "rust": pinned["rust"], "go": subprocess.run(["go", "version"], capture_output=True, text=True).stdout.strip(),
        "facade_and_tooling_source": {"commit": a.facade_commit, "scope": "ts-prototype/{cmd,internal,producer,scripts,go.mod,go.sum}", "file_list_sha256": H(lines.encode()), "files": len(files),
                                      "check": f"git diff --quiet {a.facade_commit} HEAD -- ts-prototype/cmd ts-prototype/internal ts-prototype/producer ts-prototype/scripts ts-prototype/go.mod ts-prototype/go.sum"},
        "runner_source_sha256": runner, "executables": {"supplied_artifacts": exe, "supplied_in": "verifier/artifacts/", "go_binaries_recipe": "CGO_ENABLED=0 go build -trimpath -buildvcs=false ./cmd/... from the facade source pin",
                                                        "go_binaries_sha256_from_that_recipe": go_bins}},
    "notes": [
        "config/PUBLIC_META.json carries the generator's generic status line ('NON-NORMATIVE EXPLORATORY CONFIGURATION; fresh test keys only; not S3 live-capture evidence'); it is the unmodified output of the pinned gen_config.py and does not describe adoption: nothing here is adopted. The keys it lists are the candidate key set, generated fresh and not used in any run",
        "config/expect.json is an expectation for the test harness only; no stage reads it",
        "the private keys of this candidate set are outside the repository (custody); the thumbprints, bootstrap payload hashes, profile digest, instance commitment, subject and LogIdentityV0 above depend on that exact key set and change if the keys are regenerated",
        "the bootstrap declarations are published bytes; they confer no key authority and are not read by the facade",
    ],
    "file_sha256": {},
}
for root, _, fs in os.walk(a.out):
    for f in sorted(fs):
        p = os.path.join(root, f)
        rel = os.path.relpath(p, a.out)
        if rel != "definition-manifest.json" and rel not in ("RUN.md", "env.example.sh"): man["file_sha256"][rel] = H(rd(p))
man["file_sha256"] = dict(sorted(man["file_sha256"].items()))
open(os.path.join(a.out, "definition-manifest.json"), "w").write(json.dumps(man, indent=1, sort_keys=True) + "\n")
print(json.dumps({"files": len(man["file_sha256"]), "facade_source_files": len(files), "log_identity_digest": idn["log_identity_digest"]}, indent=1))
