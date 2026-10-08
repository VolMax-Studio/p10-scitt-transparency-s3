# ML-1 / ML-6 results (executed in the container, anchored host path)

Input: `tests/offline/ml/fixtures/ml1-capture` (capture.json SHA-256 `420197718e6fbfdab743756d47f08183dc2315866ccec95fdf9dd1e53c06933d`, recorded in `MANIFEST.sha256` and supplied to G5 as the external anchor). Chain inputs were taken only from the paths returned by G5 (`g5-CAP-ML1.json`, `capture-cases.json`); the host runner has no fallback to the source fixture directory (`tests/offline/ml/fixtures/ml1`, used only for expectations).

Result (two consecutive network-isolated runs, identical): G5 PASS with `anchor_checked=true` (7 leaves) -> S2b Verified (checkpoint size 7; subject entries at 2,3,4,5,6; no unreadable row; rows 0-1 are `available` with the two non-target subs) -> S2a accept -> S1 e2e `some` -> post-S2a `BINDING_MATCH`, code `BindingMatch`, closureAt helper binary hash recorded, rows A1-A15 all `match`. The actual `tB` (SHA-256 `e716ad43…db01`, `tB-hashes.txt`) equals the generator's independently built expected `tB`.

Limits: container environment; synthetic leading statements (no policy, no bootstrap, no enforcement); all capture files derive from one request (mechanics, not source independence); ML-2 to ML-5 not built.
