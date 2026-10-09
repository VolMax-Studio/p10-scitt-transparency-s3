# Second-host replay on the operator's HP — validation record (additional evidence; recorded separately)

Evidence directory: `packaging/offline-package/evidence/hp-replay-20261008T214835Z/` (the supplied archive and its checksum file as received, plus the three runner records extracted from the archive without modification). Existing validation records (`VALIDATION.md`, `VALIDATION-rev2.md`), the packages, the frozen files, the accepted evidence, binaries, tags and keys are unchanged. Nothing was rerun, rebuilt, signed, tagged or released, and no key was retired.

## What this is, and is not

A **reproduction on a second host**: the operator ran the offline verification of the accepted capture on his HP and returned the runner records. It is **not** an independent operator audit (the same operator runs both hosts and the S3 operator-independence non-claim is unchanged), **not** a universal portability claim (one additional host, one distribution/kernel/Python combination), and **not** a new acceptance. The acceptance remains the operator's signed tag `v0.1.0-s3-accepted`.

## A. Inspected artifacts (verified by Claude from the files received)

| Item | Result |
|---|---|
| Archive `p10-s3-hp-replay-20261008T214835Z.tar.gz` (4,304 bytes) | SHA-256 `903aa55b4bed5c60fc8c84b3993359225eb0539a3e53b4eafc7c05ff0d5ce632`; equals the value in the supplied `.sha256` file (`sha256sum -c`: OK) |
| Archive members | exactly `verdict.json`, `run-info.json`, `preflight.json` (timestamps 2026-10-08 21:48) |
| `verdict.json` | SHA-256 `6368022f06cc6ef6e4c9698cd45e71c44db505b4bf8b5812aaf0cbe26f41db22` = the required value; `cmp`-identical to the accepted `ts-prototype/evidence/s3b-capture/runner/verdict.json` and to `runner-2/verdict.json` (comparison made after the files were received) |
| Outcome | `BINDING_MATCH` at `post-s2a`; `executables_pinned` entry true, g5 true; anchor `2662c2da…00a7` |
| `run-info.json` (runtime details from the supplied record) | host platform `Linux-7.0.0-34-generic-x86_64-with-glibc2.39`, Python `3.12.3`; started `2026-10-08T21:48:36Z`, 16.7 s; `network_isolated=true`, interfaces `['lo']`, launcher label `unshare -rn` (a label, not evidence); Lean directory `…/p10-underdetermination-lean-s1/.toolchain/lean4-4.33.0/bin`; commands `preflight`, `g5`, `s2b-entry`, `s2a-runner`, `closureat-batch` all exit 0; no problems; no `tcb_source_mismatch` |
| Source and binary pins in `run-info.json` | `s3c_verify.py` `7e6c457a…f628`, `s3c_chain.py` `de3450bb…0494`, entry `53ba4440…`, G5 `a2b4b1ef…`, and the five input hashes (`request` `f577f382…9c83`, `profile_artifact` `ac489551…26ec`, …): all equal to the accepted first run's `run-info.json` |
| `preflight.json` | 31 checks, none failed, none required-and-failed; S1/S2a/S2b clean; Lean, Lake, libleanshared and version `4.33.0` match the S1/S2a manifests; `rustc 1.82.0 (f6e511eec 2024-10-15)` in `spike/s3-entry`; native `-luv` link check ok; Python 3.12.3 (informational) |

Compared with the first host (Linux 6.18.44 container, glibc 2.39, Python 3.13.16, 40.6 s), the second host differs in kernel, Python minor version, Lean directory path and wall time; every pinned hash and the verdict are the same.

## B. Operator-reported terminal observations (not inspected)

The terminal transcript itself was **not** among the files received; the following is as reported by the operator in his message and is recorded as a report, not as something Claude saw: Ubuntu 24.04.4; both signed tags (`v0.1.0-s3a-frozen`, `v0.1.0-s3-accepted`) verified successfully; the run ended with `BINDING_MATCH` and exit 0; the new `verdict.json` was byte-identical to the accepted verdicts; network isolation was measured; executable and source pins matched; and `kernel.apparmor_restrict_unprivileged_userns` was restored to `1` afterwards. The records are consistent with these statements (kernel/glibc compatible with Ubuntu 24.04, `unshare -rn` label, `network_isolated=true`) but do not establish them: they contain no tag-verification output, no OS release string and no sysctl value.

## C. Not established by the records

Which package revision (original or rev2) was used and how it was transferred; the package-level checks of `verify_offline.sh` (their output is not in the archive); the validity of the tag signatures (reported, not inspected); the number of replay attempts and any earlier interruption (nothing in the records addresses them and nothing is inferred); anything about other hosts.

## Added files and SHA-256

| File | SHA-256 |
|---|---|
| `evidence/hp-replay-20261008T214835Z/p10-s3-hp-replay-20261008T214835Z.tar.gz` | `903aa55b4bed5c60fc8c84b3993359225eb0539a3e53b4eafc7c05ff0d5ce632` |
| `evidence/hp-replay-20261008T214835Z/p10-s3-hp-replay-20261008T214835Z.tar.gz.sha256` | `d919267596ab820102d4b7b712511fd67f3be5ada992c7b1504fbb5b0f28f898` |
| `evidence/hp-replay-20261008T214835Z/verdict.json` | `6368022f06cc6ef6e4c9698cd45e71c44db505b4bf8b5812aaf0cbe26f41db22` |
| `evidence/hp-replay-20261008T214835Z/run-info.json` | `4c82c728e1b9bfeedbd1c66445e8c728fae3903c7893b945b29ac3227b1d8a3b` |
| `evidence/hp-replay-20261008T214835Z/preflight.json` | `1c3ba055f0724a77eb03859fc8728376a9e30040702004c11a45fd96f398fd9f` |
| `VALIDATION-hp-replay.md` (this record) | recorded in the commit's `MANIFEST.sha256` |

## Addendum — terminal transcript received and inspected

The operator then supplied the terminal transcript as a file: `evidence/hp-replay-20261008T214835Z/s3-hp-terminal-20261008.txt` (10,993 bytes, 177 lines), SHA-256 `a8d66981b10fdeec353da0bee75fec9e1d497d6ff88d5b191d156208294e2c68`, equal to the checksum the operator gave; stored byte-identical to what was received (`cmp`). It supersedes Section B's statement that the transcript was not inspected: Claude has now read it. It remains **operator-supplied evidence** (pasted terminal text), not something Claude produced or observed running. Nothing was rerun.

**Transcript observations (what the pasted text shows).**

- Wrapper output of the package's `verify_offline.sh`: `PASS PACKAGE_SHA256SUMS: all 5997 listed files match`; repo HEAD `e56d3ea8…`; both tag objects (`v0.1.0-s3a-frozen` `8f0c97f3…` → `7c3b2d4b…`, `v0.1.0-s3-accepted` `4148a740…` → `5acc277a…`) with signature blocks present; **`PASS signature of v0.1.0-s3a-frozen verifies against ALLOWED_SIGNERS` and the same for `v0.1.0-s3-accepted`** (the allowed-signers file is named in the pasted text by path; Claude has not seen its contents); S1/S2a/S2b at the pins and clean; `frozen set (deployment/candidate/freeze-set.sha256): all 99 listed files match`; anchor `2662c2da…00a7`; accepted-verdict hash `6368022f…db22`.
- Runner: `BINDING_MATCH stage=post-s2a`, `runner exit code: 0`; the comparison section, printed after the run, shows `verdict.json` byte-identical to the accepted `runner/` and `runner-2/` verdicts (SHA-256 `6368022f…db22`), `executables_pinned entry and g5`, `network_isolated true (measured)`, no problems, no `tcb_source_mismatch`, runner source hashes and both binary hashes; the last wrapper line is `ALL PASS: the offline replay reproduced the accepted verdict on this host`, with output directory `…/out/run-20261008T214835Z`.
- Prerequisites shown: `rustc 1.82.0 (f6e511eec 2024-10-15)`; an apt step reporting `libuv1-dev` and `build-essential` already the newest versions (0 newly installed); an `unshare -rn` check passing.
- Kernel setting: `kernel.apparmor_restrict_unprivileged_userns = 0` is printed before the checks (followed by `Namespace preduslov: OK`) and **`kernel.apparmor_restrict_unprivileged_userns = 1` is printed after `ALL PASS`**, i.e. the value shown at the end is `1`.
- The wording of the two checksum lines (`all N listed files match`) is the output format of the revised wrapper (`VALIDATION-rev2.md`); that is a reading of the printed text, since the transcript does not name the tarball used.

**Runner-record checks (unchanged, from Section A).** The archived `verdict.json`, `run-info.json` and `preflight.json` were inspected as files: hashes, 31 preflight checks, pins, isolation and host details come from those records, not from the transcript. The transcript and the records agree: run directory `run-20261008T214835Z` matches the archive name and the record's start time, and the verdict hash is the same.

**Limits.** The command section of the pasted text is partly garbled by the paste (line 23 interleaves fragments of several commands), so the exact command line cannot be reconstructed from it and none is inferred. The transcript contains the operator's host name and local paths, and an `apt` listing of the machine's package sources; it is stored unmodified at the operator's request. It does not establish independent operator validation (the same operator ran both hosts), and nothing in it or in the records is used to infer the cause of the earlier desktop-session interruption or the number of replay attempts. This remains a reproduction on a second host, not a universal portability claim.

| Added file | SHA-256 |
|---|---|
| `evidence/hp-replay-20261008T214835Z/s3-hp-terminal-20261008.txt` | `a8d66981b10fdeec353da0bee75fec9e1d497d6ff88d5b191d156208294e2c68` |
