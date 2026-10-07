# G5 candidate-code test results (executed in the container)

Candidate acceptance-code evidence. The G5 binary under test has SHA-256 `b77e814f4dc347bd24de7cc294dbcdd664de39806396d8249e3b45c2862007cd` (`g5-binary.sha256`; a debug build with Rust 1.82.0 and the locked versions). Test input: the committed materialization `tests/offline/g5/fixtures/volmax-owner-capture` (capture.json SHA-256 `6fb6826c…9a09`), derived from the spike fixture. Harness: `run_g5_tests.py`; full output `g5tests.console`, machine-readable `g5report.json`.

- 31 cases, all as expected (`all_ok: true`): BASE (G5 pass), N-P1a/b, N-P2a/b, N-P3, N-P4, N-P5, N-P6a/b, N-P7 for each of `pB`, `inst`, `iB`, retained target payload and `request.cbor` in variants a (file replaced, index unchanged: `E_FILE_HASH_MISMATCH`) and b (index rewritten, committed anchor unchanged: `E_INDEX_ANCHOR_MISMATCH`), N-D1, and extras X-S1, X-S2, X-P1, X-P2, X-I1, X-I2, X-T1, X-R1, X-D1, X-X1.
- For all 28 G5 failures: exit code 30, the exact expected reason, the chain was not invoked and its output directory was never created.
- Chain invocations: exactly 2 (BASE, N-D1), under `unshare -n`. Both: S2b Verified, S2a accept, S1 e2e `some`, post-S2a `BINDING_MATCH`, code `BindingMatch`, helper hash recorded, no infrastructure failure (`chain-BASE.report.json`, `chain-N-D1.report.json`).
- N-D1 (leaves delivered in permuted order, indices unchanged): G5 pass; `tB` bytes identical to the unpermuted run and equal to the generator's independently built expected `tB` (`nd1-tB-comparison.txt`).

Limits: all files of the materialization derive from one request (mechanics, not source independence); the harness is test scaffolding, not acceptance code; "stages not called" is shown by the driver not spawning the chain and by the absent output directory, not by tracing system calls.
