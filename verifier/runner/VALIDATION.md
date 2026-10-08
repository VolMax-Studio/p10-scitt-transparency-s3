# Candidate S3-C runner: validation record (exploratory; nothing adopted)

Candidate runner source pinned before the evidence runs: commit `ffeaf5c56f23e0378529e457e5592fbfd3e00380` (clean tree under `verifier/` and `tests/offline/runner/`). Runner source SHA-256: `s3c_verify.py` `e9a56d94…2c66`, `s3c_chain.py` `29773135…8def`, `PINNED_INPUTS.json` `261279b7…c67d`. Binaries used (recorded, not compared; built on this host from the pinned sources): entry `53ba4440…`, G5 `a2b4b1ef…`. Environment of the runs: Linux 6.18 container, Python 3.13.16 (recorded, not pinned), pinned Lean from the S2a/S1 manifests, S1/S2a/S2b checkouts at the pinned commits (clean before and after), every chain run network-isolated (`unshare -n`, tested from inside). Evidence: `evidence/validation-1/` (report, every `verdict.json` and `run-info.json`, harness outputs). The harness is `tests/offline/runner/`; all expectation comparisons are there.

## What was shown

| Check | Result |
|---|---|
| Stage tests (`test_stages.py`, no Lean, fake S2b tree with the real `post_s2a.py`): 14 tests | OK. Entry without/with inconsistent result, unknown status, target failure; S2A runner failure, short or non-JSON output, codec and cov errors, explicit e2e required; closureAt not run, malformed, **unattested** answer; frozen HALT/REJECT at S2b and S2A propagated as such. Infrastructure failures never became HALT, REJECT or a match. |
| Static and command-line tests (`test_runner_static.py`): 7 tests | OK. Reused spike functions textually identical to the spike's; pinned hashes match; the CLI has no expectation/fixture/producer option and no such string constant; usage errors exit 2; a wrong pin, an unavailable network isolation and a wrong anchor end as the contract says (infrastructure 40, infrastructure 40, packaging 30 with only `preflight` and `g5` run). |
| Existing captures through the single command, twice each (`run2`, `run3-ml2`, `detached-closure`) | All six runs `BINDING_MATCH`, exit 0, S2b `Verified` with the expected size and target index, S2a accept / e2e `some`, A1-A15 `match`, closureAt helper hash attested; `tB` equals the independently derived expectation stored beside each capture and the `tB` of the earlier spike-glue chain run; **`verdict.json` byte-identical between the two runs** of each capture (`278ae155…`, `d4798ed3…`, `79f9a368…`). |
| Eight ratified propagation controls (prereg §7.3) | All eight reproduce the fixture's recorded expectation. Seven were packaged as captures (`materialize_control.py`; nothing re-encoded) and run through the single command: C-ACC `BINDING_MATCH`; C-POST-REJ `REJECT` (post-S2a A10, `BindingMismatch`); C-POST-HALT `HALT` (post-S2a T5, `closureAt returned none`, real helper); C-S2A-REJ `REJECT` (`c3_profileAfterFirstAdmission`); C-S2A-HALT `HALT` (`c2_subjectPayloadUnavailable`); C-S2B-REJ `REJECT` (`Invalid(binding, LeafInputDomainViolation)`); C-S2B-HALT `HALT` (`Invalid(replay, RootMismatch)`). **C-S2B-UNAV (`M8`) cannot be packaged**: its request omits index 2, and the capture format requires a complete prefix `0..n-1`, so as a capture it would end as `S3-FAIL(packaging)` before the chain; its propagation (`Unavailable(material, MissingIndex)` ⇒ `HALT` at S2b) was therefore checked through the chain stages directly with the fixture's own request. |
| Packaging cases through the single command (34: BASE, N-P1a..N-P6b, N-P7 a/b for pB, inst, iB, target payload, request, N-D1, and the extra G5 cases) | All as preregistered: every failure is `S3-FAIL(packaging)`, exit 30, with the exact G5 reason, only `preflight` and `g5` in the command list, no S2b/S2A/closureAt/post-S2a output; BASE and N-D1 (permuted delivery order) end `BINDING_MATCH`. |

## Reused spike code (candidate TCB code requiring review; successful execution adopts nothing)

`spike/s3-entry` (Rust entry, unchanged); `spike/host/preflight.py` (unchanged); the functions marked `REUSED` in `s3c_chain.py` (copied verbatim from `spike/glue/s3_spike_chain.py`: `Log`, `compose_s2b`, `norm_s2a`, `frozen_a12_a14`, `_job`, `parse_codec_job`, `parse_cov_job`, `parse_e2e_job`, hashing helpers, `INFRA_POST_CODES`); `verifier/g5` (candidate G5). The harness reuses `spike/host/make_cases.py`, the spike's comparison helpers and `tests/offline/g5/` mutators for expectations only.

## Not shown / limits

- Candidate classification and exit codes are not reviewed; whether an S2A strict-codec failure is infrastructure or a P10 HALT is open.
- No snapshot of the capture between G5 and the later stages: a concurrent writer to the capture directory is not detected (open point added to the contract).
- Binary-to-source reproducibility of the entry and G5 builds is not shown (binary hashes are recorded only); no OS or Python pin; one host, one run environment.
- The controls prove propagation on ratified fixtures, not S3 live behavior; seven were packaged by mechanics (all files derived from the one request), so they exercise the runner, not source independence. Filler pB/inst/iB (recorded in each control's `provenance/CONTROL.json`) were supplied where a vector carries none; the chain stops before they matter, as the outcomes show.
- Nothing here changes the preregistration's non-claims: no operator independence, no claim about policy verification or enforcement, no rotation, no X.509.

---

# r13 correction pass: reviewed defects, regressions and re-validation

Review of `7b4d466` found four defects. The corrected source was pinned at commit `300417156f1518fcf5e3322155d0ba2a4937b799` before the evidence runs below (clean tree under `verifier/` and `tests/offline/runner/`); runner source SHA-256 `s3c_verify.py` `45e5b96c…5677`, `s3c_chain.py` `de3450bb…0494`, `PINNED_INPUTS.json` `3a1550f8…c991`. The first validation record above is unchanged. Evidence: `evidence/validation-2-r13/` (report, every `verdict.json`/`run-info.json`, harness outputs, and `defects/before|after`). `before` is the runner source of `7b4d466` exercised by `tests/offline/runner/repro_defects.py`; `after` is the pinned corrected source. Expectations stay in the harness.

## Before / after behaviour

| Defect | Before (`7b4d466`) | After (`3004171`) |
|---|---|---|
| 1a. direct `--_inner "unshare -n"` call without isolation (harness process has `eth0`) | ran, G5 reached, `run-info`: `network_isolated=true` | `S3-FAIL(infrastructure)` `NETWORK_ISOLATION`, exit 40, no stage run, `network_isolated=false` (measured in the stage process; the argument is recorded as `launcher_claim_not_evidence`) |
| 1b. direct `--_inner` call with a non-empty `--out` | accepted, ran preflight and G5 into the stale directory | exit 2 (usage), nothing written; normal path and `--no-offline` also exit 2 |
| 2. the supplied capture directory modified after G5 returned (wrapper G5 swaps `material/iB.json` in the original) | chain used the swapped bytes: `REJECT` post-S2a A8; the S1 instance hash used ≠ the anchored one | `BINDING_MATCH`; every input hash used equals the anchored index hash; the original directory is no longer read after the snapshot |
| 3a. S2b `Invalid` with class `Typo` | `HALT` | infrastructure `S2B_UNKNOWN_CLASS` |
| 3b. S2b `Unavailable` without reason | `HALT` | infrastructure `S2B_REASON_MISSING` |
| 3c. duplicate JSON key in `result.json` (`Verified`, then `Invalid`) | last member won: `REJECT` | infrastructure `ENTRY_RESULT` |
| 3d. S2A `reject` with `repr="garbage"` | `REJECT` with an empty token | infrastructure `S2A_COV_MALFORMED` |
| 4a. `pb decode=false` with the frozen coverage REJECT `c1_profileDecode` | infrastructure `S2A_CODEC` | `REJECT` stage `s2a`, token `c1_profileDecode`; the `pb` diagnostic is kept in `s2a.codec` |
| 4b. `tb decode=false`, `cov` error "tB does not strict-decode" | infrastructure `S2A_CODEC` | infrastructure `S2A_TRANSCRIPT_DECODE` |
| 4c. `inst decode=false`, `cov` error "instB does not strict-decode" | infrastructure `S2A_CODEC` | infrastructure `S2A_INSTANCE_DECODE` |

## What changed

1. **Isolation** is tested inside the process that executes the stages; the result is recorded as measured. The empty-`--out` rule is applied by every invocation path.
2. **Private snapshot**: the capture is copied once (regular files byte for byte, symlinks and FIFOs recreated not followed, names as raw bytes), G5 runs on the copy against the external anchor, and only G5-returned snapshot paths feed the chain. Symlink and unsafe-name rejection are preserved (packaging cases X-P1..X-P5 below). A socket/device file ends as `S3-FAIL(packaging)` `SNAPSHOT_SPECIAL_FILE`. A post-chain G5 re-check was not used as a substitute.
3. **Strict readers**: duplicate keys and non-finite numbers rejected; S2b classes checked against the frozen `ResultClass` set and the combinations of the frozen composition table; non-empty reasons; `tB.bin` must hash to the `transcript_sha256` of `result.json`; S2A lines have closed schemas; `cov` repr must agree with the outcome and carry a recognizable `RejectReason`/`HaltReason` token of the matching type (token shape only; no list of P10 reasons).
4. **Codec diagnostics per input and stage**; a frozen coverage outcome is never preempted. Transcript and instance decode failures (no frozen outcome exists) are their own infrastructure codes, documented in `CONTRACT.md` §5 without inventing a P10 HALT/REJECT reason; contradictory helper outputs are `S2A_CONTRADICTION`. Whether the preregistration should define a composed outcome for these two cases is OPEN.
5. **Executable identity** (implemented, enabled): the entry and G5 binaries are copied into `OUT/bin/` and checked against SHA-256 pins in `PINNED_INPUTS.json` before the copies run (`EXECUTABLE_HASH` otherwise; verified by a regression test that G5 never runs on a mismatch). The pins are the hashes of the builds used in validation: `entry` `53ba4440…`, `g5` `a2b4b1ef…` (unchanged from the first validation). **This is identity, not reproducible compilation**: how adopted binaries are produced and pinned is an explicit adoption prerequisite and remains OPEN.

## Regressions and re-validation (all pass)

| Check | Result |
|---|---|
| `test_stages.py` (22 tests; was 14) | OK: unknown/unlisted/missing S2b classes and reasons, duplicate keys, `tB` hash mismatch, closed S2A schemas, outcome/reason representation consistency, profile decode with frozen REJECT, transcript/instance decode failures, contradictions, e2e, closureAt |
| `test_runner_static.py` (11; was 7) | OK: adds the isolation bypass, `--no-offline` measurement, non-empty `--out` on all paths, executable-pin mismatch; the reused-function list is now exactly `HEX64`, `sha256_file`, `sha256_bytes`, `Log`, `compose_s2b`, `frozen_a12_a14`, `INFRA_POST_CODES` |
| `test_snapshot.py` (5) | OK |
| three existing captures, twice each | all `BINDING_MATCH`; `tB`, request hash and S2A result lines identical to the first validation; `verdict.json` byte-identical between the two runs of each capture (the verdict gained `s2a.codec` and `executables_pinned`, so its hash differs from the first validation) |
| eight ratified propagation controls | all reproduce the fixture's recorded expectation (seven through the command, `M8` through the chain stages as before) |
| 34 packaging cases through the command | all as preregistered, including unsafe-name and symlink rejection through the snapshot |

## Remaining limits

- The snapshot is private to the run but not a security boundary against a hostile process of the same user; the S1/S2a/S2b checkouts and the Lean directory are verified by preflight and then used in place.
- Executable identity pins bind the validated builds only; no reproducible-build claim, no OS/Python pin.
- The S2A/closureAt launchers and the Lean build remain the frozen scripts; the harness's stub-based tests do not authenticate the real helper.
- Transcript/instance decode failure handling (infrastructure) is a candidate classification pending a preregistered decision.
- Nothing is adopted; the first-validation limits that this pass did not touch still apply.
