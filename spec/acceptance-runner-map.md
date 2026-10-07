# S3-C runner map, S3-owned glue, and supported-runtime contract

Status: DRAFT CANDIDATE, supporting `S3_PREREG_v0.1.md` r2. Not normative, not frozen. Derived by reading the frozen sources (S2b `8eaa91c`, S2a `741d56d`); **nothing in this document was executed**. Manifest coverage confers no normative authority.

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
| G4 post-S2a input assembler | build `PostS2aInputs` from `tB`, `pB`, `iB`, the S2b evidence (`leaf_index`), the target payload bytes, the target's protected `sub`, the S2a `cov`/`e2e` results and the frozen A12–A14 digests | mirrors the assembly in `tests/s2a/run_post.py`; `[OPEN]` source of the target's protected `sub` and of the A12–A14 digests for a non-toy instance |
| G5 correspondence checker | prereg §6.1 | limited to artifact correspondence |

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
| Lean toolchain | `leanprover/lean4:v4.33.0`; `lean_build_common.sh` selects the Lean executable by SHA-256 pinned in the S2a verifier manifest (`f8380b19b43334925e7f7621e1f7d7912f36c789199d3f8d069b87f5ea176d46`) and refuses an unpinned binary | S2a runner, closureAt helper | prep (obtain), run |
| Native C compiler / linker | `cc_wrapper.sh` uses one native `cc` (`$P10_NATIVE_CC` or `command -v cc`) for the pinned Conda-built Lean's native build, logging path and hash | Lean native build | host prerequisite |
| Python 3 | interpreter used by `post_s2a.py` and glue; `[OPEN]` exact version not pinned in the sources inspected | G2–G5, post-S2a | host prerequisite |
| Python package | `zstandard==0.25.0` (listed in S2a `requirements.lock`) | role on the S3-C path not established `[OPEN]` | prep |
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
