# tests/offline/g5 — tests of the candidate G5 checker

Candidate-code test evidence; kept separate from the feasibility-spike evidence in `spike/evidence/`. Nothing here is an S3 capture.

- `materialize_capture.py` — materializes a capture directory from the committed spike fixture `spike/fixtures/volmax-owner`, reading the request with `cbor2` (an independent decoder) and writing every signed object byte for byte. Needs `cbor2` (the S2b oracle lock pins 6.1.5).
- `fixtures/volmax-owner-capture/` — the committed output of that tool (test input). Its `capture.json` hash is the anchor recorded in `MANIFEST.sha256`; `spike/host/run_host.sh` runs G5 on it with that anchor and needs no `cbor2`.
- `run_g5_tests.py` — 34 cases (r5; 31 in r4): the preregistered N-P1..N-P7 (with index-unchanged and re-anchored variants), the N-D1 delivery-order control, and extra cases. For each G5 failure it asserts the exact reason, exit code 30, and that the gate-then-chain driver did not invoke the chain (the chain output directory is never created). For the two passing cases it runs the traced chain (spike glue) and checks `BINDING_MATCH` with code `BindingMatch`; N-D1 additionally requires `tB` bytes identical to the unpermuted run.
- `evidence/container-run/` — the r4 run (31 cases); `evidence/regression-r5/` — the r5 run (34 cases) and the reproduction of the inventory defect fixed in r5.

```
python run_g5_tests.py --g5 verifier/g5/target/debug/s3-g5 --glue spike/glue/s3_spike_chain.py --entry spike/s3-entry/target/debug/s3-spike-entry \
   --s2a <S2a> --s2b <S2b> --fixture spike/fixtures/volmax-owner --work <empty dir> --out report.json --runner "unshare -n" [--no-chain]
```
`P10_LEAN_BIN_DIR` must name the pinned Lean directory unless `--no-chain` is given.

Limitation: in this materialization the submitted bytes, the exported prefix and the request leaves all come from one request, so the tests exercise the checker's mechanics, not the independence of real submission/export sources.
