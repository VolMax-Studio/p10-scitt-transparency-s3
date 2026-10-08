# S3-C reproducibility check (frozen S3 §8; precondition of the key-retirement record)

A second standalone offline replay of the SAME accepted capture and anchor from commit `149953c29780e566b0b23f7a1b975dc93349daf2`, in a fresh output directory, with the frozen configuration and the supplied pinned executables. No lifecycle, key, build or capture action; the capture and `ANCHOR.sha256` are byte-identical to `149953c` (`git diff` empty). `RESULT.md`, the first run (`runner/`), the signed tag `v0.1.0-s3a-frozen` and all 99 frozen files are unchanged (`sha256sum -c deployment/candidate/freeze-set.sha256`: 99 of 99 OK before and after).

Command (as in `deployment/candidate/RUN.md`; no `--no-offline`, no `--pinned`): `python3 -B verifier/runner/s3c_verify.py --capture $OUT/capture --anchor-file $OUT/ANCHOR.sha256 --out <fresh dir> --s1 --s2a --s2b --entry verifier/artifacts/s3-spike-entry --g5 verifier/artifacts/s3-g5 --lean-bin-dir …`. The comparison was made only after this run finished.

| Item | Run 1 (`runner/`) | Run 2 (`runner-2/`) |
|---|---|---|
| Exit / outcome | 0 / `BINDING_MATCH` at `post-s2a` | 0 / `BINDING_MATCH` at `post-s2a` |
| `verdict.json` SHA-256 | `6368022f06cc6ef6e4c9698cd45e71c44db505b4bf8b5812aaf0cbe26f41db22` | `6368022f06cc6ef6e4c9698cd45e71c44db505b4bf8b5812aaf0cbe26f41db22` |
| Byte-for-byte comparison (`cmp`) | — | **identical** |
| Measured isolation | `network_isolated=true` | `network_isolated=true` (interfaces: `lo` only) |
| `executables_pinned` | entry true, g5 true | entry true, g5 true |
| Runner sources | `s3c_verify.py` `7e6c457a…f628`, `s3c_chain.py` `de3450bb…0494` | same |
| Executables | entry `53ba4440…`, G5 `a2b4b1ef…` | same |
| Input hashes (`run-info.json`) | — | equal to run 1 |
| Problems / `tcb_source_mismatch` | none / none | none / none |

`run-info.json` is incidental and recorded, not compared. This is the reproducibility evidence for the same capture and environment only: it says nothing about other hosts. It does not accept the capture and does not retire any key. Machine paths in text files are replaced by `$SP`.
