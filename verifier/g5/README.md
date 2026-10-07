# verifier/g5 — candidate G5 capture-correspondence checker

**CANDIDATE acceptance-layer code. Not ratified, not frozen, not adopted.** It is S3-owned code in the future S3-C trusted computing base, kept separate from the feasibility spike (`spike/`). Specification: `spec/capture-format.md`. Test evidence: `tests/offline/g5/`.

Role: artifact correspondence between a capture directory and its `request.cbor`. It decodes the request only through the pinned frozen `p10_replay::request::decode_request`, reads `capture.json` through the frozen duplicate-aware JSON type of the same crate, compares raw bytes, and accounts for every record and every file. It implements no P10 rule and never parses or re-encodes a signed object.

```
s3-g5 --capture <dir> [--index-sha256 <hex>]
```
stdout: one JSON line, `{"g5":"PASS",...}` or `{"g5":"FAIL","reason":"E_...","detail":"..."}`. Exit: 0 pass, 30 fail, 2 usage. On failure the S2b replay, the S2a runner, the closureAt helper and the post-S2a stage must not be called. The anchor is the hash of `capture.json` recorded outside the capture; acceptance must supply it.

Build (Rust 1.82.0, locked versions identical to the S2b `Cargo.lock`; `p10_replay` is linked from the pinned S2b checkout at `verifier/.deps/s2b`, a symlink created by `spike/host/run_host.sh`, not committed):
```
cd verifier/g5 && cargo build --locked --offline && cargo test --locked --offline --lib
```
Dependencies: `p10_replay` (path), `sha2 =0.10.8`, `serde_json =1.0.132` (both already locked by S2b). `spike/host/preflight.py` checks the lock against the S2b lock.
