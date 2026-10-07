# Offline chain feasibility spike — report

**NON-NORMATIVE FEASIBILITY EVIDENCE.** Not a ratification, freeze, signature, acceptance or verification of S3. The spike code is experimental and is **not** adopted as the S3 acceptance runner; adoption requires explicit review against the completed S3 preregistration. All results below are for the ratified **toy** semantics, not for a live Transparency Service or a real S3 capture.

Environment of all executed items: a Claude Code cloud container (Ubuntu 24.04, Linux x86_64, gcc 13.3.0, Python 3.13.16, rustup-installed Rust 1.82.0), 2026-10-07. This is **not** the maintainer's host and **not** the pinned oracle interpreter (CPython 3.12.3); the maintainer's own run of `spike/host/run_host.sh` remains the authoritative independent execution.

## 1. Scope (what was asked, what was done)

| Item | Status |
|---|---|
| Correct candidate documents (toy semantics vs data; contradictory sentence; G4 provenance) | done (prereg r3, runner map, README) |
| Minimal S3 Rust entry over the unchanged pinned S2b crate | built and run |
| Run `POST-BASE-match` through request → production S2b `tB` → S2a coverage/e2e → post-S2a with the real Lean closureAt helper | **executed**, `BINDING_MATCH` |
| Establish which existing runner controls have complete inputs; exercise the distinct stop paths | **executed** (8 controls) |
| Show whether the same frozen toy semantics support `volmax-owner` with independently generated keys | **executed**, `BINDING_MATCH` |
| Document A12–A14 inputs/recipes/applicability | done, with executed reproduction |
| Use the pinned runtime; report precisely if unavailable | pinned Lean obtained and hash-verified (see §3) |
| Host package | `spike/host/run_host.sh` (executed here end to end) |

## 2. Executed vs inspected

**Executed (commands run, outputs kept under `spike/evidence/2026-10-07-container/`):**

1. `rustup toolchain install 1.82.0`; `cargo build --locked` of the S2b crate at `8eaa91c`; `cargo build --locked --offline` of the spike entry (API accessibility, `API_INVENTORY.md`).
2. Acquisition of conda-forge `lean4-4.33.0-h6c1889d_0` and SHA-256 comparison of `lean`, `lake`, `leanchecker`, `libleanshared.so` with their frozen manifests (`lean-acquisition.txt`).
3. `launch_s2a_runner.sh --build-only`: first attempt failed at `ld: cannot find -luv`; after installing `libuv1-dev` it built (`build-only/`).
4. S1 OPEN-S13 `static` and `run` modes under the pinned toolchain (`s1-open-s13-reproduction/`).
5. `spike/host/run_host.sh` (preflight; entry build; cases; two chain runs under `unshare -n`; run comparison; output hashes) → `container-run-via-run_host/`.
6. A first online chain run and one network-isolated run (`chain-run-online.report.json`, `chain-run-offline.report.json`) and two sensitivity runs (`sensitivity/`).
7. The `volmax-owner` fixture generator (`spike/fixtures/gen_volmax_owner.py`), including its eight sanity checks (re-derivation of the toy `SubjectDeriveV0` subject and `LogIdentityV0` digest from the ratified toy values, unchanged `iB` bytes, only the expected fields changed).
8. Unit tests of the glue helpers (`spike/glue/test_glue.py`).

**Inspected only (not executed):** the S2b `scripts/verify.sh` acceptance command (not run); the S3 correspondence checker G5 (not written); the S3 negative cases N-P1..N-P7 and N-D1 (not written); everything about a live TS, its Receipts and a real capture.

## 3. Pinned runtime

| Prerequisite | Result |
|---|---|
| Rust 1.82.0 (`rust-toolchain.toml`) | installed and used (`rustc 1.82.0 (f6e511eec 2024-10-15)`) |
| Lean `lean` executable | `9842f89b9a1874db969cc58933e4117c397338f795eb8febffeb79edd5272847`: equals the S2a manifest pin and the S1 manifest pin (the two manifests agree) |
| `lake`, `leanchecker`, `libleanshared.so` | equal the S1 manifest pins (`8c57ee92…`, `612915ad…`, `0df64f23…`); only `lean` is used on the S2b launcher path, the others were reported against the S1 pins |
| Native C toolchain | not pinned by the frozen sources; the pinned Conda-built Lean required `cc_wrapper.sh` compiler/library substitutions with Ubuntu's `x86_64-linux-gnu-gcc-13`, libgmp, libssl, libcrypto, all logged (`link-log` lines in the stderr logs) |
| **Undeclared prerequisite found** | a native `libuv` development library (`-luv`); not covered by `cc_wrapper.sh` |
| Python | glue and `post_s2a.py` ran on the standard library only (3.13.16 here); `zstandard` was not installed on the chain interpreter and was not needed |

## 4. Chain results (expected vs actual)

Expected values come from each fixture's own `expected.json` (and, for the S2b-level controls, from the frozen S2b composition table); they were read only after the actual outputs existed. Each fixture is run with its own bound inputs unchanged. `tB` equality with `tB.expected` is a comparison; `tB.expected` never fed a stage.

| Case | Fixture | S2b | S2a | Post-S2a | Expected | Actual |
|---|---|---|---|---|---|---|
| C-ACC | `s2a-post/POST-BASE-match` | Verified | accept (`e2e` some) | `BINDING_MATCH` (A1–A15 all `match`) | same | same, `tB` sha256 `3ad48229…` equals expected |
| C-POST-REJ | `s2a-post/BIND-A10-mismatch` | Verified | accept | `REJECT` A10 | same | same |
| C-POST-HALT | `s2a-post/T13-T5-closureAt-none` | Verified | accept | `HALT` T5 (real helper: closureAt none) | same | same |
| C-S2A-REJ | `s2a-t11/N13b` | Verified | `reject c3_profileAfterFirstAdmission` | not applicable | same | same |
| C-S2A-HALT | `s2a-t11/N7a` | Verified | `halt c2_subjectPayloadUnavailable` | not applicable | same | same |
| C-S2B-REJ | `E/E10-unprotected` | `Invalid(binding, LeafInputDomainViolation)` | not called | REJECT (composition) | same | same |
| C-S2B-HALT | `M/M1` | `Invalid(replay, RootMismatch)` | not called | HALT | same | same |
| C-S2B-UNAV | `M/M8` | `Unavailable(material, MissingIndex)` | not called | HALT | same | same |
| FX-volmax-owner | `spike/fixtures/volmax-owner` | Verified | accept (`e2e` some) | `BINDING_MATCH` (A1–A15 all `match`) | same | same, `tB` equals the generator's independently constructed expected `tB` |

Control input completeness (`cases.inventory.json`): the `s2a-post` vectors carry `request.cbor`, `iB.json`, `target_payload.json`, `tB.expected` and take `pB.json`/`inst.bin` from S2b `profile/`; the `s2a-t11` vectors carry `request.cbor`, `pB.json`, `inst.bin`, `tB.expected`; the `E`/`M` vectors carry only a request (enough for the S2b stop paths, which never reach S2a). All eight were complete for the stop path they exercise. Covered stop paths: S2b REJECT, S2b HALT (replay), S2b HALT (unavailable), S2a REJECT, S2a HALT, post-S2a REJECT, post-S2a HALT, full acceptance path.

Repeatability (two consecutive network-isolated runs): identical verdict projections, identical `tB` bytes for every case, identical S2a-runner and closureAt-helper binary hashes (`repro.json`). Network-isolated vs online run: identical verdict projections and `tB`. Identity of helper binary hashes is within this container only.

Entry artifact hashes: spike entry binary `53ba44408b1de7322010681f45bb4aa576931f0974c448d9e6b7a662683ca863` (debug build, this container); S2a runner `c682d73c0a6c260a1212b3427b1215461b04fd86f8188a99343283adf2fb3651`; closureAt helper `960341c0c137b606fdfe953b5412fc3ee7e82b176ceab8485dcf453bec408702` (both host-dependent builds).

## 5. Target provenance (G4)

The entry parses the exact `target_registered_statement_bytes` of the request with the frozen `parse_cose_sign1` and `read_protected` after S2b returns `Verified`, takes the attached payload (or the exact detached payload from the request material), the protected `sub`, and the authenticated Receipt `leaf_index`, and writes them as `target.payload.bin`, `target.sub.txt`, `target.leaf_index.txt`. The glue builds `PostS2aInputs` from those and from the actual `tB`, S2a `cov`/`e2e` outputs and the frozen A12–A14 digests read from the S2b freeze record. A retained `target_payload.json` is only compared: in all cases with a retained file it equalled the extracted payload; sensitivity run 1 (retained file replaced by a different file) gave entry exit 20 and a failed check, and S2a was not consulted for it. Sensitivity run 2 (wrong expected verdict) was reported as `FAIL`.

## 6. `volmax-owner` on the same toy semantics

Generated with independently generated random P-256 keys (private keys written only outside the repository and not recorded), same lifecycle shape as `POST-BASE-match`, exact toy `iB` bytes. Changed relative to the ratified toy fixture: owner/issuer name, all issuer keys, TS issuer string and key, `pB.key_resolution`, `inst.{issuer_id, instance_owner_iss, instance_subject (p10s2sub:0fe1be11…), profile_digest, log_identity_digest (7dd7aff4…)}`, signatures. Unchanged: `iB`, rule IDs/digests, verifier-manifest digest, admitter set, A12–A14. The ratified S2a decoders accepted `pB`/`inst` (strict decode round-trip `reencode_identical`), S2a returned `accept`, S1 `e2e` returned `some`, and the post-S2a stage matched all fifteen rows. Details: `A12_A14_APPLICABILITY.md`, `fixtures/volmax-owner/PUBLIC_META.json`.

## 7. Findings and remaining blockers

1. **A frozen one-shot driver does not exist**, confirmed by the need for G1–G5; the spike glue is experimental TCB code and is not adopted.
2. **Undeclared prerequisite:** native `libuv` development library for the Lean link step.
3. **Test-tooling coupling:** the S2b fixture builders hard-code toy key seeds and the owner name as module-level constants; the `volmax-owner` fixture therefore monkeypatches two module-level lookups (`scenarios.key_of`, `scenarios.STD_KEYS`) and passes explicit parameters elsewhere. No S2b file was modified, but the generator depends on ratified test tooling internals. The fixture is test input; it is validated by the pinned chain, not by regeneration.
4. **Not exercised:** the S3 correspondence checker and the S3 packaging negatives; a live TS; attached-vs-detached Receipt variants beyond the ratified vectors; a non-toy instance (different `iB`/certificate); `scripts/verify.sh`; execution on the maintainer's host; the pinned oracle interpreter; a bundle-based offline distribution of toolchains.
5. **Environment differences to check on the host:** compiler/library substitution during the Lean link, interpreter versions, and OS.
6. Bootstrap and TS selection remain OPEN, as instructed.

## 8. Host command

```
spike/host/run_host.sh --s1 <S1 checkout at e4db3747…> --s2a <S2a checkout at 741d56d3…> --s2b <S2b checkout at 8eaa91ca…> \
                       --out <empty output dir> [--lean-bin-dir <dir containing the pinned lean>] [--no-offline]
```
The checkouts must be clean and detached at the pinned commits. The script stops at the first failed required prerequisite and prints the exact missing item; it never substitutes an unpinned toolchain and never feeds expected outputs into a stage.
