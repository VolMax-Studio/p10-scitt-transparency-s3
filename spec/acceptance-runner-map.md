# S3-C runner map, S3-owned glue, and supported-runtime contract

Status: DRAFT CANDIDATE, supporting `S3_PREREG_v0.1.md` r5. Not normative, not frozen. Sections 1-7 were derived by reading the frozen sources (S2b `8eaa91c`, S2a `741d56d`); the experimental spike under `spike/` later executed the traced path, and its executed findings are recorded in §8 and in `spike/FEASIBILITY_REPORT.md`, clearly separated from source inspection. Manifest coverage confers no normative authority.

## 1. Implementation acceptance is not capture acceptance

`scripts/verify.sh` (S2b) is the ratified **implementation** acceptance command: 16 steps (frozen tags/hashes, rule conformance, execution manifest, partition checks, locked and offline Rust build/tests, locked Python oracle environment, vector-manifest equality, all vectors through production and the reference oracle, exact `tB` comparison, S2a transcript/outcome differentials, closureAt helper, post-S2a T12–T15/A1–A15 cases, mutation completeness, production partition). Its inputs are S2b's own corpus (`vectors/`) and the ratified S2a checkout. It takes no external capture and writes no verdict for one. Passing it supports trust in the **toolchain and code** that S3-C then uses; it is not evidence about the S3 capture, and S3 does not cite it as such.

## 2. The frozen pieces, as found

| Stage | Frozen entry point | Input | Output |
|---|---|---|---|
| S2b decode | `p10_replay::request::decode_request(&[u8])` | `request.cbor` (`["P10-ReplayRequestV0", frozen-config, material]`) | `ReplayRequest` or decode error |
| S2b replay | `p10_replay::finalize::replay_p0_p9(&ReplayRequest)` | decoded request | `ReplayResult::Verified{transcript_bytes, replay_evidence}` \| `Invalid{reason, diagnostics}` \| `Unavailable{reason, diagnostics}` |
| Composition (S2b result) | prereg r7 §16.6 table | S2b result | non-`Verified` ⇒ HALT (`Invalid(replay)`, `Invalid(request)`, `Unavailable(*)`) or REJECT (`Invalid(binding)`); **no S2a call** without `tB` |
| S2a | `orchestration/launch_s2a_runner.sh <S2A_DIR> <jobs.tsv>` (fresh Lean build of `orchestration/helper/S2aRunner.lean` against the pinned clean S2a checkout) | job lines: `tb <tB>`, `inst <instB>`, `pb <pB>`, `cov <tB> <pB> <instB>`, `e2e <tB> <pB> <iB> <instB>` | one JSON object per job; `cov` ⇒ `{"outcome":"accept"\|"reject"\|"halt", "evidence_digest"?, "repr"}` |
| post-S2a | `orchestration/post_s2a.py::evaluate(PostS2aInputs, ClosureAtProvider)`; real provider `LeanLauncherClosureAt` ⇒ `orchestration/launch_closureat.sh` (fresh build of `helper/ClosureAtHelper.lean`) | `PostS2aInputs` (below) | `Verdict` ∈ {`HALT`, `REJECT`, `BINDING_MATCH`, `NOT_APPLICABLE`} with rule/code; `evidence_record(v)` refuses a verdict not produced by the real Lean helper |

`PostS2aInputs` fields (from `orchestration/post_s2a.py`): `s2a_accepted`, `tb`, `pb`, `ib` (S1 instance bytes), `leaf_index` (Receipt target leaf), `target_statement` (target payload bytes, JCS JSON), `target_protected_sub`, `evidence_digest_of_e` (from the S2a `cov` accept result), `s1_underdetermined` (from the S2a/S1 `e2e` result), `frozen` (`FrozenArtifactDigests`: `codec_digest`, `capability_proof_digest`, `proof_digest`).

## 3. What is missing in the frozen sources: S3-owned glue

There is **no frozen one-shot driver** from `request.cbor` to a final verdict. The pieces above exist, and the assembly of `PostS2aInputs` plus the sequencing exists only in S2b **test tooling** (`tests/s2a/run_post.py` and `run_t11.py`, `tests/s2a/s2a_lib.py`, which also run the production replay through the `cargo test --test differential` harness, not through a production binary). `p10-replay-cli` (`v0.1.0`, commit `90c2706a981b0071bd627278f5a59fb9cdbc9a8c`) wraps `decode_request` + `replay_p0_p9` and writes `tB`; it is a separately versioned adapter, outside the ratified chain, and pins `p10_replay` at `v0.1.1-s2b-public`.

Therefore S3-C needs the following **S3-owned code**, which is part of the S3-C trusted computing base and which must add no rule:

| Glue | Purpose | Constraint |
|---|---|---|
| G1 Rust entry | call `decode_request` then `replay_p0_p9` on `request.cbor`, emit `tB` and the S2b result | `[OPEN]` a thin S3 binary vs `p10-replay-cli` vs a harness; must call the pinned S2b crate unchanged |
| G2 composer | apply prereg r7 §16.6 to the S2b result; stop on non-`Verified` | table-driven copy of the frozen table; no new mapping |
| G3 S2a job writer | write `jobs.tsv` for `tb`, `inst`, `pb`, `cov`, `e2e` over the exact `tB`, `pB`, `inst`, `iB` files | exact-bytes; no re-encoding |
| G4 post-S2a input assembler | build `PostS2aInputs` from the **actual** `tB`, `pB`, `iB`, the authenticated Receipt `leaf_index`, the target payload and protected `sub` extracted from the authenticated target (frozen `parse_cose_sign1` and `read_protected`; detached payloads from the exact request material), the actual S2a `cov`/`e2e` results and the frozen A12–A14 digests (read from the S2b schema freeze record) | does NOT copy the assembly in `tests/s2a/run_post.py`, which uses the expected transcript and generator-known subject/payload values; `[OPEN]` A12–A14 digests for a non-toy instance |
| G5 correspondence checker | prereg §6.1; format and reason codes: `spec/capture-format.md` | limited to artifact correspondence. Candidate implementation: `verifier/g5/` (Rust over the unchanged pinned S2b crate; candidate acceptance code, not adopted); test evidence: `tests/offline/g5/` |

Guardrail proposed for G1–G5: run the same glue over the ratified runner-control fixtures (prereg §7.3) and require each recorded expectation to reproduce unchanged, so any divergence of the glue from the frozen test tooling is visible. This shows consistency on those fixtures; it does not prove the glue adds no rule.

## 4. Runner map for one capture

```
capture/ (committed, manifest-covered)
  request.cbor  pB  inst  iB  target-payload  public-config  provenance  prefix/*.cose  receipts/*  submissions/*  public-keys/*
 │
 ├─ G5  correspondence check (S3-owned)  ── decode_request (pinned S2b) ; byte-compare fields to files ; account for every record ; manifest hashes
 │        └─ any failure ⇒ S3-FAIL(packaging); stop. No P10 verdict.
 │
 ├─ G1  decode_request ──► replay_p0_p9 ──► Verified{tB, evidence} | Invalid | Unavailable
 │        └─ G2  non-Verified ⇒ HALT / REJECT per §16.6; stop. (no S2a call)
 │
 ├─ G3  S2a runner (fresh Lean build, pinned Lean): tb, inst, pb strict round-trip ; cov(tB,pB,inst) ; e2e(tB,pB,iB,inst)
 │        └─ cov = reject / halt ⇒ that is the outcome; stop.
 │
 └─ G4  post-S2a (only when cov = accept): TargetAdjudicationValidV0 T1–T6 (T5 via real closureAt helper, fresh Lean build)
          ─► AdjudicationBindingV0 A1–A15 ─► Verdict {HALT | REJECT | BINDING_MATCH}
```

Recorded outputs: `tB`, S2b result + evidence record, S2a runner JSON lines, post-S2a `Verdict` and `evidence_record`. Reproducibility classification: prereg §8.

## 5. Runtime contract (declared pinned environment)

Verification is supported only inside the environment below. Dependencies were inventoried from the sources; anything not listed here is not claimed to be needed or sufficient.

| Dependency | Pin (source) | Needed for | Phase |
|---|---|---|---|
| S2b source | commit `8eaa91cad1ffa963158b365c6d0d7316f4965e89` (`v0.1.0-s2b-complete`); proposed baseline | G1, orchestration scripts, `post_s2a.py`, helpers | prep (obtain/verify), run |
| S2a source | commit `741d56d36d7b2bfe2e9e0080a1cba4393e4a47da`, checkout must be clean and at the commit (`verify.sh` `verify_upstream` enforces this for implementation acceptance) | S2a runner, closureAt helper | prep, run |
| S1 source | commit `e4db3747eaeeb1a07227bb9029f9a9c3b566cdb1`; also vendored inside S2a (`vendor/p10-underdetermination-lean-s1`); S2b records vendored tree `6cdf48c29cd2207243912881c8f38c416ba2026a` | Lean build, `.olean` reproducibility | prep, run |
| Rust toolchain | `1.82.0`, profile minimal (`rust-toolchain.toml`) | G1 build | prep (install), run (build) |
| Rust crates | 53 packages locked in `Cargo.lock`; offline build requires them to be available locally (`verify.sh` step 6 is "clean offline Rust build") | G1 build | prep (fetch/vendor), run |
| Lean toolchain | `leanprover/lean4:v4.33.0` (conda-forge `lean4` 4.33.0 build `h6c1889d_0`). `lean_build_common.sh` selects the `lean` executable by SHA-256 `9842f89b9a1874db969cc58933e4117c397338f795eb8febffeb79edd5272847`, the S2a verifier manifest's `lean_toolchain_artifact_digest` (the S1 manifest records the same value as `lean_toolchain_artifact_sha256`), and refuses an unpinned binary. `lake` (`8c57ee92…d7d2`) and `libleanshared.so` (`0df64f23…c4d`) are used by the launchers (`lake build`) and are pinned only by the **S1** manifest; the host preflight enforces both, plus the version string, as required. `leanchecker` (`612915ad…5f33`, S1 manifest) is not used on this chain. `f8380b19…` is the digest of the S2a verifier manifest file itself, not a Lean pin (an earlier revision of this table wrongly gave it as the Lean pin) | S2a runner, closureAt helper | prep (obtain), run |
| Native C compiler / linker | `cc_wrapper.sh` uses one native `cc` (`$P10_NATIVE_CC` or `command -v cc`) for the pinned Conda-built Lean's native build, logging path and hash | Lean native build | host prerequisite |
| Python 3 | interpreter used by `post_s2a.py` and glue; `[OPEN]` exact version not pinned in the sources inspected | G2–G5, post-S2a | host prerequisite |
| Python package | `zstandard==0.25.0` (listed in S2a `requirements.lock`) | **not required by the spike chain**: the glue and `post_s2a.py` ran on the standard library only, and the chain ran on an interpreter without `zstandard` | none observed |
| Native `libuv` development library (`-luv`) | not named in the frozen scripts; `cc_wrapper.sh` repairs libgmp/libssl/libcrypto but not `-luv` | final link of the Lean runner/helper executables (the first spike build failed at `ld: cannot find -luv` until the Ubuntu package `libuv1-dev` was installed) | host prerequisite, `[OPEN]` whether to declare it |
| `.olean` set | all S1 `olean_digest_set` hashes must reproduce (schema r9 §8.11.11 is an acceptance condition) | A12–A14 composite digests | run |
| Frozen configuration digests | A12–A14 composites `codec_digest c156965f…6dd9`, `capability_proof_digest 9482c3f7…4928`, `proof_digest 30f49843…8696` as used for the **toy** fixture in `tests/s2a/scenarios.py` | G4 | `[OPEN]` for the S3 instance (`proof_digest` is described as toy-fixture-specific) |
| Operating system | the sources inspected do not state one | all | `[OPEN]` |

**Preparation vs S3-C execution.** Preparation obtains inputs and checks their hashes and may use a network (git objects, toolchains, crates, wheels). S3-C execution is run with the network disabled and must not fetch anything: no `git fetch`, no `cargo` network access (offline/locked), no `lake update`, no package installs. `[OPEN]` whether the package carries toolchains and vendored crates or declares them as host prerequisites verified by hash; **a `git bundle` of the three repositories is necessary for source identity but not sufficient for this contract** (it carries neither the Rust/Lean toolchains, nor the crate sources, nor the Python wheel).

**Declared limits.** No claim of reproducibility on other operating systems, toolchain versions, or with unpinned Lean binaries. The frozen scripts themselves refuse an unpinned Lean executable.

## 6. Baseline pin comparison (S2b)

`v0.1.0-s2b-complete` → `8eaa91cad1ffa963158b365c6d0d7316f4965e89` (tree `c9a5d0a2012e0fca3c5952184590c428bc5fc063`); `v0.1.1-s2b-public` → `8e89f9a4192bdd0ab280556701dc595eb55539d2` (tree `92d13c756b8f1bd4e29b2c3681a3e9e9a8d0ee08`).

`git diff --name-status 8eaa91c 8e89f9a`: `A LICENSE-APACHE`, `A LICENSE-MIT`, `A NOTICE.md`, `M README.md`, `A SECURITY.md`, `A docs/INTEGRATION.md`. No other path differs. The proposed S3 baseline is `8eaa91c`; the public tag differs by documentation and license files only. Both ids are recorded so a reviewer can re-run the comparison.

## 7. Open items specific to this document

G1 form; G4 input sources for a non-toy instance; whether `zstandard` is on the S3-C path; Python version and OS pins; toolchain carriage; the runner-control fixtures' interface adequacy.

## 8. Executed findings of the feasibility spike (separate from the source inspection above)

Executed in a Claude Code cloud container (Ubuntu 24.04, x86_64, gcc 13.3.0, Python 3.13.16, Rust 1.82.0 via rustup), network-isolated chain runs via `unshare -n`. Detail, commands, outputs and hashes: `spike/FEASIBILITY_REPORT.md` and `spike/evidence/`. Nothing here adopts the spike code.

- The public items needed (`request::decode_request`, `finalize::replay_p0_p9`, `cose::parse_cose_sign1`, `statement::read_protected`) and the supporting types compile and link from an external crate against `8eaa91c` under Rust 1.82.0. The spike lock was started from the S2b `Cargo.lock`; cargo dropped the eight packages that only the dev-dependencies need (ciborium, ciborium-io, ciborium-ll, coset, crunchy, half, zerocopy, zerocopy-derive) and added the entry itself; every remaining package is identical (name, version, checksum) to the S2b lock, which `spike/host/preflight.py` checks.
- The pinned Lean executable was obtained and matched: conda-forge `lean4-4.33.0-h6c1889d_0`, `lean` SHA-256 `9842f89b…2847` equal to the S2a manifest pin and the S1 manifest pin; `lake`, `leanchecker` and `libleanshared.so` equal to the S1 manifest pins. The S2b launchers then built the S2a runner and the closureAt helper fresh and accepted the executable by hash.
- All eight runner controls and the `volmax-owner` fixture passed with their recorded expectations in two consecutive network-isolated runs, with identical verdict projections, `tB` bytes and helper-binary hashes.
- The S1 OPEN-S13 reproduction (run mode) under the pinned toolchain reproduced the three frozen composite digests used as A12–A14.

## 9. Runner hardening after the feasibility baseline (executed in the container; see `spike/HARDENING_REPORT.md`)

- The host script now stops if network isolation cannot be established or fails its own test (loopback-only interface list, no external TCP connection); a connected run requires the explicit `--no-offline` and is labelled.
- `lake`, `libleanshared.so` and the version string of the Lean directory actually used are required against the S1 manifest.
- The glue reads S2a runner output strictly; an error object, malformed result or missing `evidence_repr` is an infrastructure failure, never a semantic `false` or an A15 REJECT.
- Post-S2a controls compare result, code and rule exactly (and the T5 detail text and the presence of the real helper's binary hash where the helper is required).

## 10. Anchored capture path (r5; `spike/host/run_host.sh` step 6)

Candidate G5 runs on each capture listed in `spike/host/anchored_captures.json` with the external anchor taken from `MANIFEST.sha256`; the runner stops if the anchor is absent, if G5 fails (the chain is not called for that capture), or if the G5 result is not a PASS with `anchor_checked=true`. `make_capture_cases.py` then builds the chain inputs from the paths G5 returned for the capture it checked, refuses a path outside that capture root and an expectation file inside it, and has no fallback to any fixture directory (expectations are read for comparison only). The ratified runner controls are run directly in a separate step with their own bound inputs. Executed: both test captures (`volmax-owner` five leaves; ML-1 seven leaves) pass the whole chain; a deliberately tampered ML-1 capture stopped the host run at G5 with `E_FILE_HASH_MISMATCH` before any capture chain run. Evidence: `spike/evidence/anchored-capture-container/`.

## 8. Candidate runner (added in the r12 pass)

A candidate standalone runner implementing the map of §4 exists under `verifier/runner/` (contract `CONTRACT.md`, validation record `VALIDATION.md`). It adapts the spike glue (reused functions are marked and hash-compared), takes only a capture and an external anchor, and reports `BINDING_MATCH | REJECT | HALT | S3-FAIL(packaging) | S3-FAIL(infrastructure)`. Existence and successful execution do not adopt it; the open items of §3 remain open.

The r13 pass amended the candidate runner (measured isolation, capture snapshot before G5, strict stage readers, per-input codec diagnostics, optional executable identity pins); see `verifier/runner/CONTRACT.md` and `VALIDATION.md`.
