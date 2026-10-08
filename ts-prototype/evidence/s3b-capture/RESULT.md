# S3-B normative capture and S3-C verification — result record

Run under the frozen S3-A (tag `v0.1.0-s3a-frozen`, tag object `8f0c97f3745131f79936dec71ebe09316332f5ab`, commit `7c3b2d4b919c356a566f8f5d3628d4f546e41afa`), following `deployment/candidate/RUN.md`, with the candidate key set and the committed definition (`install` checked the manifest hashes and the key custody). Operator-authorized run; the anchor is an operator-generated record, not an independent channel. No attempt failed; nothing was repeated.

| Step | Result |
|---|---|
| Freeze set | `sha256sum -c deployment/candidate/freeze-set.sha256`: 99 of 99 OK before and after the run; no frozen file differs from the tag |
| Preconditions | source-pin check, clean tree, Go binaries rebuilt by the recipe = manifest hashes (facade `7c71d861…`, capture `1ecde5e4…`, keygen `fd829bd6…`), `verifier/artifacts/SHA256SUMS` OK |
| `install` / `capture` | OK; 8 leaves; pre-verification record: all expectations true |
| Anchor | `2662c2daf912d2ce4796a26b13464d7bc2df6ba8825fa399fed3a87185d700a7`, committed and pushed in `149953c29780e566b0b23f7a1b975dc93349daf2` before any verification |
| Prototype checks F0–F8 | ALL OK (`facade-checks.out`) |
| G5 | PASS, anchor checked, 8 leaves, 54 files (`g5.json`) |
| Unchanged chain (network-isolated) | PASS (`chain/report.json`) |
| Standalone runner (no `--no-offline`, no `--pinned`) | exit 0, `BINDING_MATCH` at `post-s2a`, A1–A15 hold (`runner/verdict.json`) |
| Acceptance conditions (CONTRACT §4a) | `executables_pinned` entry=true, g5=true; `network_isolated=true` (measured); runner sources `s3c_verify.py` `7e6c457a…f628`, `s3c_chain.py` `de3450bb…0494`; entry `53ba4440…`, G5 `a2b4b1ef…` identity-checked; no `tcb_source_mismatch`; no problems |
| Hashes | `request.cbor` `f577f382607c6956e4c724ff37e19f55581bd4c3a06e075ebb3cb0baed569c83`; `tB` `8711346a69c601b424da736bf890cc627170c1181616d08029f08c132129d14e`; S2b `Verified`, checkpoint size 8, target leaf 7; S2a `accept`, evidence digest `a8cf4ba5…fab0`, e2e `some` |

This record reports results; it does not accept the capture. Final acceptance and key retirement are the operator's actions. No key was deleted, retired or regenerated. The runner's private snapshot and binary copies were pruned from the stored evidence.
