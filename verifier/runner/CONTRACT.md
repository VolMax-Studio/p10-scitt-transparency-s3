# Candidate S3-C acceptance runner: contract

Status: **DRAFT CANDIDATE contract**, written before the runner code (the code is committed afterwards and must follow this text). Not ratified, not frozen, not adopted; nothing here changes the preregistration (`S3_PREREG_v0.1.md` §6, §8; `spec/acceptance-runner-map.md`). Existence and successful execution of the runner do not adopt it. Manifest coverage confers no normative authority.

The runner is S3-owned acceptance code and part of the S3-C trusted computing base (TCB). It adds no P10 rule: it sequences the frozen pieces and the candidate G5 checker, assembles their inputs from actual authenticated outputs, and reports a vocabulary of outcomes. Non-claims of the preregistration are unchanged: no operator independence, no arbitrary RFC 9943 compatibility, no rotation, no X.509, and no claim that policy statements were verified or enforced.

## 1. Command

One command, one capture:

```
python3 verifier/runner/s3c_verify.py --capture DIR (--anchor HEX64 | --anchor-file FILE) --out DIR \
        --s1 DIR --s2a DIR --s2b DIR --entry BIN --g5 BIN [--lean-bin-dir DIR] [--pinned FILE] [--no-offline]
```

| Input | Meaning |
|---|---|
| `--capture` | the capture directory (`spec/capture-format.md`). Read only through G5. |
| `--anchor` / `--anchor-file` | the external anchor: SHA-256 of `capture.json` (64 lowercase hex) taken from a record outside the capture (for a committed capture, the repository manifest). Exactly one is required; there is no unanchored mode. A file holds the hex, optionally followed by whitespace. |
| `--out` | new or empty output directory. |
| `--s1`, `--s2a`, `--s2b` | checkouts of the frozen S1, S2a, S2b sources (clean, detached at the pinned commits). |
| `--entry` | the S2b entry binary (§7). |
| `--g5` | the G5 binary (`verifier/g5`). |
| `--lean-bin-dir` | directory holding the pinned `lean` (else `P10_LEAN_BIN_DIR` or the launchers' own selection by SHA-256). |
| `--pinned` | the pinned-inputs file (default `PINNED_INPUTS.json` beside the runner). |
| `--no-offline` | permit a connected run; the run is then labelled `network_isolated=false` in `run-info.json`. |

**The runner has no input for, and never reads:** an expected verdict, an expected `tB`, an expected S2b/S2a/post-S2a result, a fixture directory, a producer or issuer tool, `PUBLIC_META.json`-style generator metadata, or the manifest. Every datum that reaches a stage is either a byte of the capture (via G5-returned paths), an actual output of an earlier stage, or a frozen value read from the pinned S2b freeze record (A12–A14). Expectation comparison belongs to test harnesses (§8), outside the runner.

## 2. Stages and boundaries

```
P  preflight + isolation   pins (preflight.py, PINNED_INPUTS.json), TCB source hashes, network isolation test
G5 correspondence          s3-g5 --capture DIR --index-sha256 ANCHOR     (success required before ANY later stage)
S2B entry                  request.cbor -> decode_request -> replay_p0_p9 ; target sub/payload from the authenticated target
CMP composition            frozen S2b prereg r7 §16.6 table (copied, table-driven)
S2A runner                 jobs tb, inst, pb, cov, e2e on the exact tB, pB, inst, iB files (fresh Lean build)
POST post-S2a              orchestration/post_s2a.py evaluate, real closureAt helper (fresh Lean build)
```

1. **P** precedes everything. A failed pin, TCB hash or isolation test is an infrastructure failure; no stage runs.
2. **G5** runs next, alone. Any G5 failure ends the run as `S3-FAIL(packaging)`; the S2b entry, S2a runner, closureAt helper and post-S2a stage are not called (the run-info command list proves it). A G5 PASS is accepted only if `anchor_checked` is `true` and every returned path lies under the checked capture root (symlinks resolved).
3. **S2B** receives only the G5-returned `request.cbor` and (if present) the G5-returned retained target payload for the equality check. Its outputs: `result.json`, and on `Verified`: `tB.bin`, `target.leaf_index.txt`, `target.sub.txt`, `target.payload.bin`.
4. **CMP** maps the S2b result: `Verified` continues; `Invalid(binding)` ⇒ REJECT; `Invalid(replay|request)` and `Unavailable(*)` ⇒ HALT. The run ends there for non-`Verified`.
5. **S2A** is called only after `Verified`. Inputs: the exact `tB.bin` written by S2B, and the G5-returned `pB`, `inst`, `iB` files. Parsing of runner output is strict (§5).
6. **POST** is called only after S2A `cov = accept` with the S1 end-to-end result established. `PostS2aInputs` is assembled from: the actual `tB` bytes; the G5-returned `pB` and `iB` bytes; the S2B Receipt `leaf_index`; the target payload and protected `sub` extracted by S2B from the authenticated target; the S2A evidence digest and the end-to-end result from the S2A output; the A12–A14 digests read from the S2b freeze record. The real closureAt helper runs (one fresh build); no substitute is accepted.

## 3. Pinned dependencies

`PINNED_INPUTS.json` (candidate) records: S1 `e4db3747…`, S2a `741d56d3…`, S2b `8eaa91ca…` commits; the Lean hashes already used by the frozen scripts (`lean` `9842f89b…`, and the S1-manifest values for `lake`, `leanchecker`, `libleanshared`); Rust `1.82.0`; Python 3 (interpreter version recorded, not pinned: OPEN); and the **reused-code table** (§7) with SHA-256 of each TCB source file. At start the runner checks the git HEAD and cleanliness of the three checkouts against the pins, runs the reused `spike/host/preflight.py` (which carries its own copies of the pins and checks frozen file hashes, the S1 manifest, the Lean directory and the `-luv` link prerequisite), and compares the hashes of the reused TCB sources with the table. Binary hashes (entry, G5, Lean launchers' helper binaries) are recorded, not compared: build reproducibility is not claimed.

Preparation (obtaining checkouts and toolchains, building the entry and G5) may use a network and is outside the command; the command runs network-isolated by default (`unshare -n`, else `unshare -rn`; the isolation is tested from inside and the run stops if it cannot be established, unless `--no-offline`).

## 4. Output vocabulary

`verdict.json` carries `outcome` (and `stage`, `reason`). Exit code follows the outcome.

| Outcome | Exit | Meaning |
|---|---|---|
| `BINDING_MATCH` | 0 | G5 PASS, S2b `Verified`, S2a accept, post-S2a `BINDING_MATCH`. The only accepting outcome. |
| `REJECT` | 11 | a frozen REJECT: S2b `Invalid(binding)`, S2a `reject`, or post-S2a `REJECT`. `stage` and the frozen reason/rule are recorded. |
| `HALT` | 12 | a frozen HALT: S2b `Invalid(replay\|request)` or `Unavailable`, S2a `halt`, or post-S2a `HALT` (with a P10 rule, e.g. T5 `closureAt returned none`). |
| `S3-FAIL(packaging)` | 30 | G5 failure (its reason code is recorded), or the target extraction / retained-payload equality failure of the S2b entry (exit 20, reason `TARGET_EXTRACTION`). Not a P10 verdict. |
| `S3-FAIL(infrastructure)` | 40 | a stage could not run or produced output that the strict reader rejects; pin, TCB hash or isolation failure; Lean unavailable; closureAt unavailable or inconsistent; malformed or short runner output; an S2a codec round-trip failure (candidate classification, OPEN). Never converted into HALT, REJECT or a match. |
| (usage) | 2 | invalid command line; no output directory content other than a note on stderr. |

Only `BINDING_MATCH` means that the S3-C oracle accepted the capture. HALT, REJECT and both S3-FAIL classes are non-accepting and distinct.

## 5. Strictness and failure handling

- Stage output is read strictly: the S2B `result.json` must be one JSON object with a known `status`; S2A output must be exactly one JSON line per job, each an object with the expected `op`, with no `error` member; `tb`/`inst`/`pb` need `decode` and `reencode_identical` both `true`; `cov` needs an outcome in `accept|reject|halt`, a string repr and, for `accept`, a 64-hex evidence digest; `e2e` needs an explicit `some` (with evidence repr) or `none`. Any deviation is `S3-FAIL(infrastructure)`; an unreadable `e2e` is never turned into a false value.
- post-S2a codes `ClosureAtUnavailable`, `ClosureAtInconsistent` and `NOT_EVIDENCE` are infrastructure failures; a post-S2a HALT with a P10 rule is a HALT.
- A missing launcher, missing pinned Lean, failed build or non-zero exit of the S2A runner or closureAt batch is `S3-FAIL(infrastructure)` with the stderr tail recorded.
- No retry, no fallback parser, no substitution of expected or retained outputs. A failed run still writes `verdict.json` and `run-info.json` (when `--out` is usable).

## 6. Reproducible fields

`verdict.json` is canonical JSON (sorted keys, no insignificant whitespace variation) and MUST be byte-identical across repeated runs of the same capture, anchor and pinned environment. It holds only: format id; outcome, stage, reason; anchor and `capture.json` hash; G5 result; SHA-256 of `request.cbor`, of the exact `tB`, and of the S2A per-job result lines; S2b result status/class/reason; S2A outcome, reason token, evidence digest, end-to-end result; the post-S2a verdict, rule, code and the A1–A15 row statuses; the frozen A12–A14 digests. `run-info.json` holds everything incidental and is **recorded, not compared**: command lines and exit codes, stdout/stderr hashes, durations, timestamps, absolute paths, host/OS/Python/Rust versions, binary hashes (entry, G5, helper binaries), the Lean selection, the isolation status, runner source hashes. The exact list of recorded-but-not-compared fields remains OPEN (prereg §8).

## 7. Candidate TCB inventory and review status

| Component | Origin | Status |
|---|---|---|
| `verifier/runner/s3c_verify.py`, `s3c_chain.py` | new in this candidate | candidate TCB code; needs review against this contract |
| `verifier/g5/` (G5) | candidate (r4/r5) | candidate TCB code; reviewed only by its own tests |
| `spike/s3-entry/` (S2b entry, Rust) | **reused from the spike unchanged** | candidate TCB code requiring review; its source hashes are in `PINNED_INPUTS.json` |
| stage logic and strict readers in `s3c_chain.py` (composer, `parse_*`, `norm_s2a`, A12–A14 reader, closureAt batching, post assembly) | **adapted from `spike/glue/s3_spike_chain.py`** with comparison code removed; each reused function is marked and its source text is hash-compared with the spike's by the harness | candidate TCB code requiring review |
| `spike/host/preflight.py` | **reused from the spike unchanged** | candidate TCB code requiring review |
| S2b launchers, `post_s2a.py`, S2a/S1 sources | frozen | unchanged, pinned |

Reuse is reported here so that review can find it. Successful execution of any of it adopts nothing.

## 8. Validation (harness, not part of the runner)

`tests/offline/runner/` holds the harness. It runs the runner over existing captures and compares outcomes with expectations it reads itself; it reuses the eight ratified propagation controls (prereg §7.3) through the chain stages with each fixture's own bound inputs and, where a control can be packaged as a capture, through the full command; and it reuses the applicable packaging cases (N-P1..N-P7, N-D1 and the extra G5 cases) through the command. It creates no new live logs and no new semantic test families, and its expectation comparisons are never visible to the runner.

## 9. Open points

Python version and OS pins; whether an S2A strict-codec failure is infrastructure or a P10 HALT; the exact recorded-not-compared list; whether the entry and G5 are adopted in this form; carriage of toolchains vs host prerequisites; the exit-code numbers (candidate); whether `--no-offline` should exist in an adopted runner.
