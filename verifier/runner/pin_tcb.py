#!/usr/bin/env python3
"""Writes verifier/runner/PINNED_INPUTS.json (candidate): static pins of the frozen sources plus SHA-256 of the REUSED/pinned TCB source files.
usage: pin_tcb.py   (run from anywhere; regenerate after any change to a listed file, then review the diff)"""
import argparse, hashlib, json, os
ap = argparse.ArgumentParser()
ap.add_argument("--entry", help="entry binary whose SHA-256 becomes the executable identity pin (omit: unpinned)")
ap.add_argument("--g5", help="G5 binary whose SHA-256 becomes the executable identity pin (omit: unpinned)")
A = ap.parse_args()
HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.dirname(os.path.dirname(HERE))
TCB = ["spike/s3-entry/src/main.rs", "spike/s3-entry/Cargo.toml", "spike/s3-entry/Cargo.lock", "spike/s3-entry/rust-toolchain.toml",
       "spike/host/preflight.py", "spike/glue/s3_spike_chain.py",
       "verifier/g5/src/lib.rs", "verifier/g5/src/main.rs", "verifier/g5/Cargo.toml", "verifier/g5/Cargo.lock"]
sha = lambda p: hashlib.sha256(open(os.path.join(REPO, p), "rb").read()).hexdigest()
spike = json.load(open(os.path.join(REPO, "spike", "PINS.json")))
doc = {"status": "CANDIDATE pinned inputs for the candidate S3-C runner (non-normative; not a freeze)",
       "s1": {"commit": spike["s1"]["peeled_commit"], "tag": spike["s1"]["tag"], "verifier_manifest_sha256": spike["s1"]["verifier_manifest_sha256"]},
       "s2a": {"commit": spike["s2a"]["peeled_commit"], "tag": spike["s2a"]["tag"]},
       "s2b": {"commit": spike["s2b"]["peeled_commit"], "tag": spike["s2b"]["tag"]},
       "lean": spike["lean"], "rust": {"toolchain": "1.82.0"}, "python": "interpreter version recorded in run-info.json, not pinned (OPEN)",
       "a12_a14_source": "S2b frozen/StatementPayloadSchemaV0_r9_FREEZE.txt (read at run time; not duplicated here)",
       "tcb_sources": {p: sha(p) for p in TCB},
       "executables": {lab: {"sha256": hashlib.sha256(open(path, "rb").read()).hexdigest() if path else None,
                             "meaning": "EXECUTABLE IDENTITY of the binary the candidate was validated with, checked before the binary runs (the runner executes a private copy). This is not a claim of reproducible compilation: the pin is host/build specific; deciding how adopted binaries are produced and pinned (reproducible build, vendored binary or attested builder) is an adoption prerequisite."}
                       for lab, path in (("entry", A.entry), ("g5", A.g5))},
       "reuse": {"spike/s3-entry": "reused unchanged (candidate TCB, requires review)", "spike/host/preflight.py": "reused unchanged (candidate TCB, requires review)",
                 "spike/glue/s3_spike_chain.py": "functions copied verbatim into s3c_chain.py (marked REUSED); this file is pinned so the harness can compare source text",
                 "verifier/g5": "candidate G5 (candidate TCB)"}}
open(os.path.join(HERE, "PINNED_INPUTS.json"), "w").write(json.dumps(doc, indent=1, sort_keys=True) + "\n")
print("wrote", os.path.join(HERE, "PINNED_INPUTS.json"))
