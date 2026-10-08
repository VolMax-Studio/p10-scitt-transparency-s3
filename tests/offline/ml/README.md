# tests/offline/ml — mixed-log test ML-1 (and ML-6 packaging)

Test material; not an S3 capture. Plan: `spec/mixed-log-test-plan.md`.

- `gen_ml1.py` — generates ML-1, a NEW authenticated synthetic log for the `volmax-owner` instance: leaves 0-1 are non-target policy-like and trust-anchor-like TEST statements, then profile commitment (2), instance commitment (3), admission (4), closure (5), adjudication / Receipt target (6). All index-bearing items, signatures, the Merkle tree, the Receipt and the request are recomputed for the shifted indices; `pB`, `inst`, `iB`, the instance subject, `LogIdentityV0` and the A12-A14 digests are unchanged. It reuses the external test keys of `spike/fixtures/volmax-owner` when they are available and consistent (they must live outside the repository); see the file header for the fresh-key procedure. Needs `cryptography`, `jcs`, `cbor2`.
- `fixtures/ml1/` — generator output (public material only) and its expectations (`expect.json`, `tB.expected`: comparison only).
- `fixtures/ml1-capture/` — the capture materialized from it by `tests/offline/g5/materialize_capture.py --ts-origin 0,1 --roles ...` (leaves 0-1 recorded `origin="ts"`, no submission files for them: ML-6). Its `capture.json` hash is the external anchor in `MANIFEST.sha256`.
- `evidence/container-run/` — outputs of the anchored host run (container).

The two leading statements are synthetic. They are not a Registration Policy, they select no bootstrap mechanism and nothing about policy enforcement follows from them.
