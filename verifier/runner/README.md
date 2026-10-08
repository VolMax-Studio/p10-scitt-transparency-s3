# verifier/runner: candidate standalone S3-C runner

Candidate only; not adopted. The contract (`CONTRACT.md`) was written before the code and the code follows it.

- `s3c_verify.py`: the one command (preflight and network isolation, G5 with the external anchor, then the chain from G5-returned paths only).
- `s3c_chain.py`: the chain stages (S2b entry, composition, S2a runner, post-S2a with the real closureAt helper). Functions marked `REUSED` are copied verbatim from `spike/glue/s3_spike_chain.py` and are candidate TCB code requiring review.
- `PINNED_INPUTS.json`: pins of the frozen sources and SHA-256 of the reused/pinned TCB sources; regenerate with `pin_tcb.py` after any change to a listed file (and review the diff).
- Outputs: `verdict.json` (canonical, byte-reproducible fields only), `run-info.json` (incidental, recorded not compared), `logs/`, stage directories.

Validation harness (expectations live there, never in the runner): `tests/offline/runner/`.

Preparation (outside the command): clean checkouts of S1/S2a/S2b at the pinned commits, the pinned Lean, `cargo build --locked --offline` of `spike/s3-entry` and `verifier/g5` against the S2b crate (see `spike/host/run_host.sh` steps 2 and 2b for the build commands used so far).
