# Candidate S3-C acceptance runner: contract

Status: **DRAFT CANDIDATE contract**, written before the runner code (the code is committed afterwards and must follow this text). Not ratified, not frozen, not adopted; nothing here changes the preregistration (`S3_PREREG_v0.1.md` §6, §8; `spec/acceptance-runner-map.md`). Existence and successful execution of the runner do not adopt it. Manifest coverage confers no normative authority.

**Amended in the r13 correction pass** (after the review of the first validation): isolation is tested inside the process that runs the stages; the capture is snapshotted before G5; stage readers are strict; codec diagnostics are kept per input and never preempt a frozen coverage outcome; executable identity can be pinned. The text below is the amended contract; the first version is in git history (`270c793`).

The runner is S3-owned acceptance code and part of the S3-C trusted computing base (TCB). It adds no P10 rule: it sequences the frozen pieces and the candidate G5 checker, assembles their inputs from actual authenticated outputs, and reports a vocabulary of outcomes. Non-claims of the preregistration are unchanged: no operator independence, no arbitrary RFC 9943 compatibility, no rotation, no X.509, and no claim that policy statements were verified or enforced.

## 1. Command

One command, one capture:

```
python3 verifier/runner/s3c_verify.py --capture DIR (--anchor HEX64 | --anchor-file FILE) --out DIR \
        --s1 DIR --s2a DIR --s2b DIR --entry BIN --g5 BIN [--lean-bin-dir DIR] [--pinned FILE] [--no-offline]
```

| Input | Meaning |
|---|---|
| `--capture` | the capture directory (`spec/capture-format.md`). Read once, by the snapshot copy; G5 and every later stage use the copy. |
| `--anchor` / `--anchor-file` | the external anchor: SHA-256 of `capture.json` (64 lowercase hex) taken from a record outside the capture (for a committed capture, the repository manifest). Exactly one is required; there is no unanchored mode. A file holds the hex, optionally followed by whitespace. |
| `--out` | new or empty output directory, separate from the capture: its resolved path (symlinks resolved, also in the parents of a not-yet-existing output) must not equal, lie inside or contain the resolved capture, else exit 2 before anything is written. |
| `--s1`, `--s2a`, `--s2b` | checkouts of the frozen S1, S2a, S2b sources (clean, detached at the pinned commits). |
| `--entry` | the S2b entry binary (§7). |
| `--g5` | the G5 binary (`verifier/g5`). |
| `--lean-bin-dir` | directory holding the pinned `lean` (else `P10_LEAN_BIN_DIR` or the launchers' own selection by SHA-256). |
| `--pinned` | the pinned-inputs file (default `PINNED_INPUTS.json` beside the runner). |
| `--no-offline` | permit a run whose isolation test fails; `run-info.json` always records the *measured* `network_isolated`. |

**The runner has no input for, and never reads:** an expected verdict, an expected `tB`, an expected S2b/S2a/post-S2a result, a fixture directory, a producer or issuer tool, `PUBLIC_META.json`-style generator metadata, or the manifest. Every datum that reaches a stage is either a byte of the capture (via G5-returned paths), an actual output of an earlier stage, or a frozen value read from the pinned S2b freeze record (A12–A14). Expectation comparison belongs to test harnesses (§8), outside the runner.

## 2. Stages and boundaries

```
P  isolation test (this process) + pins + preflight + executable identity
SN snapshot                private copy of the capture, made once; every later stage sees only the copy
G5 correspondence          s3-g5 --capture SNAPSHOT --index-sha256 ANCHOR     (success required before ANY later stage)
S2B entry                  request.cbor -> decode_request -> replay_p0_p9 ; target sub/payload from the authenticated target
CMP composition            frozen S2b prereg r7 §16.6 table (copied, table-driven)
S2A runner                 jobs tb, inst, pb, cov, e2e on the exact tB, pB, inst, iB files (fresh Lean build)
POST post-S2a              orchestration/post_s2a.py evaluate, real closureAt helper (fresh Lean build)
```

1. **P** precedes everything and runs **inside the process that executes the stages** (children inherit its network namespace). Network isolation is *measured there*: any interface other than loopback, or a successful external connection, means "not isolated". The result is what `run-info.json` records as `network_isolated`; no argument, launcher label or earlier test is accepted as evidence (`--_inner` is only a recorded label, `launcher_claim_not_evidence`). Not isolated and not `--no-offline` ⇒ `S3-FAIL(infrastructure)` `NETWORK_ISOLATION`, no stage runs. The outer process still starts the inner one under `unshare -n` (else `-rn`) as a convenience. A failed pin, TCB hash, preflight or executable-identity check is an infrastructure failure; no stage runs. The empty-`--out` requirement and the separate-from-capture requirement are applied by every invocation path, including a direct `--_inner` call and `--no-offline`; `snapshot_capture()` independently refuses a destination that overlaps its source (`SNAPSHOT_DESTINATION_OVERLAPS_SOURCE`).
2. **Executables.** The entry and G5 binaries are copied into `OUT/bin/` and the copies run. If `PINNED_INPUTS.json` pins an executable's SHA-256, the copy must match before it runs (`EXECUTABLE_HASH` otherwise). This is **executable identity, not reproducible compilation**: the pin is specific to the build that was validated.
3. **SN** copies the capture directory once, without interpreting it: regular files byte for byte, directories, symlinks recreated as symlinks (never followed), FIFOs recreated as FIFOs (never opened), names handled as raw bytes so that unsafe names survive for G5 to reject. A socket or device file cannot be reproduced and ends as `S3-FAIL(packaging)` `SNAPSHOT_SPECIAL_FILE` (such a capture could never pass G5); an I/O failure is `SNAPSHOT_IO` (infrastructure). The original directory is never read again.
4. **G5** runs next, alone, on the snapshot. G5 verifies the external anchor against the snapshot's `capture.json` and every indexed file hash, so the bytes it checks are the bytes the chain uses. Any G5 failure ends the run as `S3-FAIL(packaging)`; the S2b entry, S2a runner, closureAt helper and post-S2a stage are not called (the run-info command list proves it). A G5 PASS is accepted only if `anchor_checked` is `true`, its `root` is the snapshot, and every returned path is a regular file under that root (symlinks resolved).
5. **S2B** receives only the G5-returned `request.cbor` and (if present) the G5-returned retained target payload for the equality check. Its outputs: `result.json`, and on `Verified`: `tB.bin`, `target.leaf_index.txt`, `target.sub.txt`, `target.payload.bin`.
6. **CMP** maps the validated S2b result: `Verified` continues; `Invalid(binding)` ⇒ REJECT; `Invalid(replay|request)` and `Unavailable(material|capability)` ⇒ HALT. The run ends there for non-`Verified`.
7. **S2A** is called only after `Verified`. Inputs: the exact `tB.bin` written by S2B, and the G5-returned `pB`, `inst`, `iB` files. Reading is strict (§5).
8. **POST** is called only after S2A `cov = accept` with the S1 end-to-end result established. `PostS2aInputs` is assembled from: the actual `tB` bytes; the G5-returned `pB` and `iB` bytes; the S2B Receipt `leaf_index`; the target payload and protected `sub` extracted by S2B from the authenticated target; the S2A evidence digest and the end-to-end result from the S2A output; the A12–A14 digests read from the S2b freeze record. The real closureAt helper runs (one fresh build); no substitute is accepted.

## 3. Pinned dependencies

`PINNED_INPUTS.json` (candidate) records: S1 `e4db3747…`, S2a `741d56d3…`, S2b `8eaa91ca…` commits; the Lean hashes already used by the frozen scripts (`lean` `9842f89b…`, and the S1-manifest values for `lake`, `leanchecker`, `libleanshared`); Rust `1.82.0`; Python 3 (interpreter version recorded, not pinned: OPEN); and the **reused-code table** (§7) with SHA-256 of each TCB source file. At start the runner checks the git HEAD and cleanliness of the three checkouts against the pins, runs the reused `spike/host/preflight.py` (which carries its own copies of the pins and checks frozen file hashes, the S1 manifest, the Lean directory and the `-luv` link prerequisite), and compares the hashes of the reused TCB sources with the table. Executable identity: `PINNED_INPUTS.json` carries SHA-256 pins for the entry and G5 binaries of the validated build; the runner checks the private copies it runs (§2.2). **Implemented as a mechanism and enabled in this candidate; it is not a claim that the binaries can be rebuilt bit-for-bit.** How adopted binaries are produced and pinned (reproducible build, vendored binary, attested builder) is an explicit adoption prerequisite and remains OPEN. The Lean launchers' helper binary hashes are recorded, not compared.

Preparation (obtaining checkouts and toolchains, building the entry and G5) may use a network and is outside the command; the command runs network-isolated by default (`unshare -n`, else `unshare -rn`; the isolation is tested from inside and the run stops if it cannot be established, unless `--no-offline`).

## 4. Output vocabulary

`verdict.json` carries `outcome` (and `stage`, `reason`). Exit code follows the outcome.

| Outcome | Exit | Meaning |
|---|---|---|
| `BINDING_MATCH` | 0 | G5 PASS, S2b `Verified`, S2a accept, post-S2a `BINDING_MATCH`. The only accepting outcome. |
| `REJECT` | 11 | a frozen REJECT: S2b `Invalid(binding)`, S2a `reject`, or post-S2a `REJECT`. `stage` and the frozen reason/rule are recorded. |
| `HALT` | 12 | a frozen HALT: S2b `Invalid(replay\|request)` or `Unavailable`, S2a `halt`, or post-S2a `HALT` (with a P10 rule, e.g. T5 `closureAt returned none`). |
| `S3-FAIL(packaging)` | 30 | G5 failure (its reason code is recorded), a capture the snapshot cannot reproduce (`SNAPSHOT_SPECIAL_FILE`), or the target extraction / retained-payload equality failure of the S2b entry (exit 20, reason `TARGET_EXTRACTION`). Not a P10 verdict. |
| `S3-FAIL(infrastructure)` | 40 | a stage could not run or produced output that the strict reader rejects; pin, TCB hash or isolation failure; Lean unavailable; closureAt unavailable or inconsistent; malformed or short runner output; an S2a codec round-trip failure (candidate classification, OPEN). Never converted into HALT, REJECT or a match. |
| (usage) | 2 | invalid command line; no output directory content other than a note on stderr. |

Only `BINDING_MATCH` means that the S3-C oracle accepted the capture. HALT, REJECT and both S3-FAIL classes are non-accepting and distinct.

## 5. Strictness and failure handling

Readers validate **interface structure** only: closed member sets, types, duplicate JSON keys, known enumerations and the internal consistency of one stage's outputs. They contain no P10 rule and no list of P10 reasons.

- **All stage JSON is strict**: duplicate object keys and non-finite numbers are rejected (a duplicate key would let the last member silently win).
- **S2b `result.json`**: `status` is `Verified|Invalid|Unavailable`; `Invalid`/`Unavailable` need a `reason` object with a non-empty `reason` and a `class` from the frozen `ResultClass` set (`Request|Replay|Binding|Material|Capability`); the combinations must be the ones the frozen composition table lists (`Invalid`: Request, Replay, Binding; `Unavailable`: Material, Capability). Unknown class ⇒ `S2B_UNKNOWN_CLASS`; missing reason ⇒ `S2B_REASON_MISSING`; unlisted combination ⇒ `S2B_UNLISTED_COMBINATION`; all infrastructure. `Verified` needs an integer `checkpoint_size` and a 64-hex `transcript_sha256`, and `tB.bin` must hash to it (`ENTRY_TB_MISMATCH`). The entry's exit code must belong to its status (`ENTRY_EXIT_MISMATCH`).
- **S2A output**: exactly one strict-JSON line per job, objects with the expected `op` and closed member sets. Codec jobs (`tb`, `inst`, `pb`) report `decode` (bool) and, only when decoding succeeded, `reencode_identical` (bool); a job-level `error` means the job did not run. `cov` has exactly one of `result` and `error`; a `result` has `outcome` in `accept|reject|halt`, a `repr` that agrees with the outcome (`P10S2.CoverageOutcome.<outcome> (...)`), for `reject`/`halt` a recognizable `P10S2.RejectReason.<token>` / `P10S2.HaltReason.<token>` of the matching type (token *shape* only), and for `accept` a 64-hex evidence digest and no token. `e2e` needs an explicit `some` (with `evidence_repr`) or `none`. Anything else is infrastructure.
- **Codec diagnostics are kept per input and stage and never preempt an established frozen outcome.** The `pb` decode result is a diagnostic: S2a itself reports `c1_profileDigest`/`c1_profileDecode` as a coverage REJECT, and that REJECT is the outcome. A `reencode_identical=false` is recorded; with a REJECT/HALT it does not change the outcome. `s2a.codec` in `verdict.json` carries the three diagnostics.
- **Transcript and instance decode failures.** The S2a `cov` job needs a decoding transcript and a decoding instance commitment; when the runner reports `tB does not strict-decode` or `instB does not strict-decode` (consistently with the failing `tb`/`inst` job) the frozen entry point produced **no outcome**. The runner reports `S3-FAIL(infrastructure)` `S2A_TRANSCRIPT_DECODE` or `S2A_INSTANCE_DECODE`. It does **not** invent a P10 HALT or REJECT reason for it. (A transcript is produced by S2b itself, so a transcript the frozen S2a decoder rejects is an inconsistency between frozen components, not a statement about the instance; an undecodable instance commitment has no frozen coverage reason.) Whether the preregistration should define a composed outcome for these cases is OPEN.
- **Contradictions** are `S2A_CONTRADICTION`: a `cov` error that disagrees with the codec job of the same input; an outcome although `tb` or `inst` did not decode; `accept` although any of `tb`, `inst`, `pb` did not decode or does not re-encode identically.
- post-S2a codes `ClosureAtUnavailable`, `ClosureAtInconsistent` and `NOT_EVIDENCE` are infrastructure failures; a post-S2a HALT with a P10 rule is a HALT. A closureAt answer is accepted only if the launcher attested a 64-hex helper binary hash on its stderr (`CLOSUREAT_UNATTESTED` otherwise): the real helper must have run.
- A missing launcher, missing pinned Lean, failed build or non-zero exit of the S2A runner or closureAt batch is `S3-FAIL(infrastructure)` with the stderr tail recorded. No retry, no fallback parser, no substitution of expected or retained outputs. A failed run still writes `verdict.json` and `run-info.json` (when `--out` is usable).

## 6. Reproducible fields

`verdict.json` is canonical JSON (sorted keys, no insignificant whitespace variation) and MUST be byte-identical across repeated runs of the same capture, anchor and pinned environment. It holds only: format id; outcome, stage, reason; anchor and `capture.json` hash; G5 result; SHA-256 of `request.cbor`, of the exact `tB`, and of the S2A per-job result lines; S2b result status/class/reason; S2A outcome, reason token, evidence digest, end-to-end result and the three codec diagnostics; whether the executables were identity-pinned; the post-S2a verdict, rule, code and the A1–A15 row statuses; the frozen A12–A14 digests. `run-info.json` holds everything incidental and is **recorded, not compared**: command lines and exit codes, stdout/stderr hashes, durations, timestamps, absolute paths, host/OS/Python/Rust versions, binary hashes (entry, G5, helper binaries), the Lean selection, the isolation status, runner source hashes. The exact list of recorded-but-not-compared fields remains OPEN (prereg §8).

## 7. Candidate TCB inventory and review status

| Component | Origin | Status |
|---|---|---|
| `verifier/runner/s3c_verify.py`, `s3c_chain.py` | new in this candidate | candidate TCB code; needs review against this contract |
| `verifier/g5/` (G5) | candidate (r4/r5) | candidate TCB code; reviewed only by its own tests |
| `spike/s3-entry/` (S2b entry, Rust) | **reused from the spike unchanged** | candidate TCB code requiring review; its source hashes are in `PINNED_INPUTS.json` |
| `Log`, `compose_s2b`, `frozen_a12_a14`, hashing helpers, `INFRA_POST_CODES` in `s3c_chain.py` | **copied verbatim from `spike/glue/s3_spike_chain.py`** (marked `REUSED`; the harness compares the source text with the spike's) | candidate TCB code requiring review |
| stage sequencing, closureAt batching, post assembly, and all stage-output readers in `s3c_chain.py` | adapted from the spike glue with comparison code removed; **the spike's lenient readers (`parse_*_job`, `norm_s2a`) were replaced in r13 by the strict readers of §5** | candidate TCB code requiring review |
| snapshot, isolation test, executable copies and pins in `s3c_verify.py` | new in the r13 pass | candidate TCB code requiring review |
| `spike/host/preflight.py` | **reused from the spike unchanged** | candidate TCB code requiring review |
| S2b launchers, `post_s2a.py`, S2a/S1 sources | frozen | unchanged, pinned |

Reuse is reported here so that review can find it. Successful execution of any of it adopts nothing.

## 8. Validation (harness, not part of the runner)

`tests/offline/runner/` holds the harness. It runs the runner over existing captures and compares outcomes with expectations it reads itself; it reuses the eight ratified propagation controls (prereg §7.3) through the chain stages with each fixture's own bound inputs and, where a control can be packaged as a capture, through the full command; and it reuses the applicable packaging cases (N-P1..N-P7, N-D1 and the extra G5 cases) through the command. It creates no new live logs and no new semantic test families, and its expectation comparisons are never visible to the runner.

## 9. Open points

Python version and OS pins; whether the preregistration should define a composed outcome for a transcript or instance commitment that the S2a runner cannot decode (currently infrastructure, §5); the exact recorded-not-compared list; whether the entry and G5 are adopted in this form, and how adopted executables are produced and pinned (§3); carriage of toolchains vs host prerequisites; the exit-code numbers (candidate); whether `--no-offline` should exist in an adopted runner.

Remaining limits of the stable-input measures: the snapshot is private to the run but not a security boundary against a hostile process of the same user; the S1/S2a/S2b checkouts and the Lean directory are checked by preflight and then used in place (not snapshotted); the S2b and S2a launchers are frozen scripts that build and run from those checkouts.
