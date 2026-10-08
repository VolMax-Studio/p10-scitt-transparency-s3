# S3_PREREG_v0.1 — P10 S3: SCITT Transparency Service Deployment and Offline Capture Verification

Status: **DRAFT CANDIDATE, revision r7 — preparation only.** Not ratified, not frozen, not signed, not tagged, not released. Nothing in this document is verified or accepted. Items marked `[OPEN]` are unresolved and MUST be closed before any freeze. Manifest coverage of this file (or of any file in this repository) confers no normative authority.

Companion candidate documents: `spec/acceptance-runner-map.md` (traced execution path, S3-owned glue, runtime contract), `spec/CLOSURE_REPORT_OPEN_1_4_6.md` (evidence report).

Revision r7 (relative to r6 at `8d154b5`/`dda0116`): a candidate Go facade over Tessera v1.0.4 and a separate HTTP-only capture client were built and exercised (`ts-prototype/`, `ts-prototype/RESULTS.md`): facade/public-read checks are reported apart from the frozen verdict; an exploratory seven-leaf lifecycle (synthetic, unenforced bootstrap statements) was captured through them, anchored, and run through G5 and the unchanged chain. Nothing is adopted; TS selection, bootstrap, policy enforcement, glue, G5 and the acceptance path remain OPEN.

Revision r6 (relative to r5 at `8d154b5`): a bounded TS selection pass was run (`ts-selection/RECOMMENDATION.md`): two candidates pinned, a capability probe executed against Tessera v1.0.4, and a procedure dry run (not acceptance evidence) built `request.cbor` from retained engine bytes. It recommends, as a proposal only, Tessera plus an S3-owned SCITT facade; OPEN item 3 stays OPEN. The mixed-log plan's title and ML-2 row were corrected. Nothing is adopted.

Revision r5 (relative to r4 at `5f73d22`): G5 inventory defect fixed (file names on disk are no longer converted lossily or rewritten; a backslash-named file used to merge with a legitimate path and escape hashing); the host runner gained an anchored capture path (external anchor required, chain inputs taken only from G5-returned paths, kept separate from the direct ratified controls); the mixed-log test ML-1 and the packaging case ML-6 were built and executed (`spec/mixed-log-test-plan.md` §8); the plan's description of ratified fixtures was corrected. Nothing is adopted; bootstrap, policy enforcement and TS selection remain OPEN.

Revision r4 (runner hardening and capture layer, relative to r3 at `23ba96f`): the capture layout, the index format and the exact G5 packaging failure reasons are specified in `spec/capture-format.md`; a candidate G5 implementation exists under `verifier/g5/` with test evidence under `tests/offline/g5/` (candidate acceptance-code evidence, kept separate from the feasibility-spike evidence under `spike/`); the mixed-log test is identified in `spec/mixed-log-test-plan.md`; the spike runner was hardened (`spike/HARDENING_REPORT.md`). Nothing is adopted by this document.

Revision r3 (feasibility-spike pass, relative to r2 at `fcb1efa`): the fixed toy semantics are distinguished from configurable identity/key data (I13); the sentence that post-hoc corruption could only yield `RootMismatch` or `S3-FAIL` is removed and replaced by an accurate statement (Section 7.4); post-S2a target payload and protected `sub` must originate from the authenticated target (Section 6.1a); open items updated. The non-normative spike under `spike/` supports these corrections with executed evidence (`spike/FEASIBILITY_REPORT.md`); nothing in the spike is adopted by this document.

Revision r2 changes (relative to the first candidate commit `ba54cd4`): I2/I4/I10 corrected against the frozen sources; policy non-claim added; negative testing narrowed to new S3 behavior with exact recipes; `request.cbor` made a committed capture artifact with a limited correspondence check; execution path traced; supported-runtime contract replaces "any machine"; S2b baseline pin proposed.

---

## 1. Scope

**Normative deployment model (Option A).** A deployable P10-compatible Transparency Service instance whose Statement Sequence uses the frozen `LeafEncodeV0` and whose captured outputs are accepted unchanged by the already frozen offline P10 verification chain.

**Target claim.** S3 demonstrates that a deployed P10-compatible Transparency Service, using the frozen LeafEncodeV0 and RFC9162_SHA256 receipts, can register and expose an exact Statement Sequence capture sufficient for the unchanged frozen P10 verification chain to independently reproduce and accept the captured instance offline.

**Layers.**

- S3-A — deployment definition: what a P10-compatible TS instance is (Sections 3–4).
- S3-B — live capture: the real registration process and export (Section 5).
- S3-C — offline acceptance: the frozen verifier chain run over the frozen capture (Section 6).

**Boundary.** S3 is a transport / transparency / deployment layer. It adds no P10 semantics. `TargetAdjudicationValidV0` and `AdjudicationBindingV0` are post-S2a stages of the frozen chain and run there unchanged; S3 defines no rule of its own for them.

**Choice of Option A over Option B.** Option A means the "real Transparency Service" is a P10-compatible instance operated for this demonstration (for example an adapted open-source RFC 9162-style SCITT TS), so the claim is feasibility of such a deployment, not compatibility with an independent third-party service. Option B (a third-party TS hashing raw Statement bytes) is incompatible with the frozen `LeafEncodeV0`; adapting to it would be a new profile instance (e.g. `LeafEncodeV1`) and is not S3.

**Pinned baseline (proposed).** Chain components are identified by immutable commits (Section 6.4): S1 `e4db3747eaeeb1a07227bb9029f9a9c3b566cdb1`, S2a `741d56d36d7b2bfe2e9e0080a1cba4393e4a47da`, S2b `8eaa91cad1ffa963158b365c6d0d7316f4965e89` (`v0.1.0-s2b-complete`).

---

## 2. Non-claims

1. The frozen P10 chain authenticates the inclusion of Registration Policy and trust-anchor Statement bytes in the captured prefix, but does not verify their issuer signatures or payload semantics. S3 does not establish that the live Transparency Service enforced the declared Registration Policy.
2. S3 does not establish operator independence or non-equivocation against a malicious operator when the Statement issuer and Transparency Service are controlled by the same party. (A policy Statement at a low leaf index is, in that setting, a claim by the operator, not evidence.)
3. S3 does not claim compatibility with arbitrary RFC 9943 Transparency Services. Exact full-prefix byte export and `LeafEncodeV0` are requirements of this P10 profile instance.
4. S3 does not exercise receipt-key rotation during the committed capture.
5. S3 does not exercise the X.509 identity path. This S3 instance uses the non-X.509 `kid` path with a preregistered public COSE key and `iss = "volmax-owner"` for the instance issuer. The X.509 path is simply outside the frozen identity model exercised here; no claim is made that it is syntactically incompatible with S2a.

Additional non-claims: S3 does not claim that a SCITT TS confirms any P10 verdict; it does not claim byte-identical output from repeated S3-B executions (Section 8); it does not claim that rollback or key-rotation procedures are tested; it does not re-prove the rules of S2b/S2a (Section 7); it does not claim reproducibility outside the declared pinned environment (Section 8).

---

## 3. Deployment invariants (S3-A)

An instance is P10 S3-compatible only if all of the following hold.

- **I1 — Mixed Statement Sequence.** The VDS Statement Sequence is a mixed SCITT/P10 sequence. Registration Policy and trust-anchor Signed Statements are registered on the same VDS (per RFC 9943), so `[0,n)` is a complete SCITT Statement Sequence, not a P10-only log. `LeafEncodeV0` MUST be applied to every registered leaf, including policy and trust-anchor statements.
- **I2 — Subject membership and classifiable leaves.** Subject membership in the frozen chain is exact byte equality of the protected CWT `sub` with `instance_subject`; there is no frozen P10 namespace rule. Registration Policy and trust-anchor statements are non-target leaves: their `sub` MUST be a valid UTF-8 text string not byte-equal to `instance_subject`. **Every** leaf of `[0,n)` MUST satisfy the frozen readability conditions, otherwise it becomes an `unavailable` row and the frozen chain HALTs: the leaf is a tagged `#6.18(COSE_Sign1)`; its protected header is exactly one CBOR map without duplicate labels; label 15 (CWT claims) is a map without duplicate labels containing `iss` (claim 1) and `sub` (claim 2) as valid UTF-8 text strings. `[OPEN]` the concrete non-target `sub` value(s) are an S3 choice.
- **I3 — Bootstrap frozen before execution.** The bootstrap mechanism (Section 4) is chosen and frozen before S3-B runs; the implementation does not select it.
- **I4 — Exact registered-form bytes; empty unprotected header on every leaf.** Every Signed Statement registered into `[0,n)` — P10 lifecycle statements, Registration Policy and trust-anchor statements alike — MUST carry an empty unprotected header (`{}`), the form RFC 9943 requires prior to inclusion in the Statement Sequence. The frozen chain treats any readable leaf with a non-empty unprotected header as a domain violation. The acceptance condition for submitted statements is `submitted_registered_form_bytes == exported_leaf_statement_bytes`; no semantically-equivalent normalization by the TS is accepted. For TS-originated statements (if any), the bytes registered are the bytes exported.
- **I5 — Sequential lifecycle submission.** Log order need not follow submission order in general, and P10 relies on leaf indices for lifecycle ordering. Therefore: submit one statement, obtain its Receipt and committed leaf index, verify the index, and only then submit the next.
- **I6 — Single-writer window.** The committed vector is captured in a single-writer window; no other writer registers leaves during it.
- **I7 — Fixed Receipt-signing key.** One Receipt-signing key is fixed for the entire bounded S3 capture. The demonstration interval MUST NOT cross the selected receipt-key cryptoperiod. Key rotation is not tested. The key's RFC 9679 thumbprint is committed in the frozen configuration and `LogIdentityV0`; the key MUST NOT change beneath a given `LogIdentityV0`.
- **I8 — Original Receipts retained.** The Receipt obtained at the time of each registration is a capture artifact, hashed in the manifest. A later "fresh" Receipt for the same statement (which RFC 9943 permits to be signed with a different key or algorithm) MUST NOT replace it. The Receipt selected for the replay is the one for the target (the adjudication Statement, Section 6).
- **I9 — Full-prefix export is a P10 requirement.** Exact full `[0,n)` Statement byte export is a P10 compatibility requirement, not a generic RFC 9943 requirement (RFC 9943 permits hash-only VDS). A SCITT-compliant TS that cannot export it fails the P10 S3 gate; that is not a statement about its SCITT compliance.
- **I10 — Profile parameters and identity path.** VDS = 1 (`RFC9162_SHA256`); inclusion proof carries `tree_size`, `leaf_index`, `inclusion_path` in a tagged COSE_Sign1 Receipt; ES256 for Receipts and Statements; no X.509 headers. `kid` is the selected SCITT header path for statements (RFC 9943: `kid` is required when neither `x5t` nor `x5chain` is present). The frozen verifier does not read `kid`: it resolves statement-signing keys through the statement's protected `iss`, the frozen-configuration table `key_resolution` (`iss` → key fingerprint) and `key_material` (`iss` → COSE_Key). The instance issuer's `iss` is `volmax-owner`, which the frozen S2a token-alphabet rule (`[A-Za-z0-9_.:-]`, applied to the instance issuer only) accepts. `ts_iss` and the `iss` of non-target leaves are not alphabet-restricted by the frozen chain.
- **I13 — Fixed semantics vs configurable data (frozen toy profile).** Fixed by the frozen semantics and artifacts: the profile-artifact constants (`fixture_id`, `s1_profile_token`, `leaf_encoding`, `log_identity_scheme`, `checkpoint_vds`), the rule identifiers and descriptor digests, the verifier-manifest digest, the S1 instance bytes `iB` (claim, evidence, witnesses), and the A12–A14 composite digests. Read as data from the profile artifact and instance commitment: the authorized-admitter names and the `key_resolution` table in `pB`; and `issuer_id`, `instance_owner_iss`, `request_id`, `instance_subject` (derived by `SubjectDeriveV0`), `profile_digest` and `log_identity_digest` in `inst`; plus the signing keys and the TS issuer string. Changing the instance owner name or any key therefore changes `pB`, `inst`, the derived subject, `LogIdentityV0` and all signatures, but not the S1 artifacts or the A12–A14 digests. The S2a identity constraints remain: owner equals issuer, issuer inside the token alphabet, owner not in the admitter set, subject equal to `SubjectDeriveV0(issuer, request_id)`. That a `volmax-owner` instance with independently generated test keys passes the unchanged chain is feasibility evidence from the non-normative spike (`spike/FEASIBILITY_REPORT.md`); it is not a decision to adopt that profile material.
- **I11 — Keys.** Private issuer and TS keys MUST NOT appear in the capture or the manifest.
- **I12 — Public-material sufficiency.** S3-C MUST succeed using public verification material only. This also serves as a completeness test of the capture.

**Compatibility checklist (pre-integration gate).** A candidate TS implementation is evaluated against I1–I12 before any integration code is written. Because `LeafEncodeV0` is a P10-defined wrapper, no off-the-shelf service is expected to pass; the gate is expected to select an adaptable implementation, not discover a ready-made one. `[OPEN]` TS selection.

---

## 4. Bootstrap

RFC 9943 permits (a) preconfigured Registration Policy and trust anchors, (b) a first policy statement registered without registration checks, or (c) authenticated out-of-band management. S3 MUST NOT leave this choice to the implementation.

`[OPEN]` Select exactly one mechanism and record: the mechanism; the content and hash of the initial Registration Policy and trust anchors; what occupies leaf index 0; and which policy version is active for each P10 statement (derivable from the prefix, since policy statements are leaves and the applicable policy is the last one committed before a registration). Whatever the choice, the policy statements are bytes in the prefix and are subject to I2 and I4. The selection is part of the deployment definition and of capture provenance, and MUST be recorded before S3-B begins. A leading preference for mechanism (b) is recorded in discussion only; it is not a decision. A prototype of that candidate exists (`ts-prototype/`); it does not close the item.

---

## 5. Capture protocol (S3-B)

1. Freeze the deployment definition (Sections 3–4) and record TS implementation identity and version, configuration, and the active Registration Policy.
2. Generate issuer and TS keys outside the repository. Publish only public keys (COSE public key, thumbprint).
3. Perform the frozen bootstrap (Section 4).
4. For each Signed Statement in the controlled P10 lifecycle sequence, in order: build the registered-form bytes (empty unprotected header); submit; obtain the Receipt; verify the committed leaf index; record the submitted bytes and the Receipt; only then submit the next statement (I5). The sequence MUST end with the owner's adjudication Statement, which is the Receipt target of the replay.
5. Export the complete prefix `[0,n)` with exact Statement bytes (I9).
6. Assemble the capture: submitted bytes, original Receipts (I8), exported prefix, public keys, bootstrap and policy records, the exact `pB` (profile artifact) and `inst` (instance commitment) bytes, the S1 instance bytes `iB`, the target adjudication payload bytes, declared public configuration, provenance metadata. No private keys (I11).
7. Assemble `request.cbor` (Section 6.1) from the exported files, before S3-C and after the capture is complete.
8. Hash all artifacts into the manifest and freeze the capture.

`[OPEN]` The lifecycle sequence content (statement count, which P10 statements), the capture file layout (`spec/capture-format.md`, not yet written), and the provenance of `pB`/`inst`/`iB` for this instance. The ratified toy profile (`profile/pB.json`, `profile/inst.bin` in S2b) binds fixed issuer names and keys; whether S3 uses a new profile artifact for `volmax-owner` and whether S2a's strict `pB` decoder accepts it was not established.

---

## 6. Acceptance oracle (S3-C)

```
captured material -> request.cbor -> frozen S2b (decode_request -> replay_p0_p9 -> exact tB)
                  -> pinned frozen S2a coverage runner -> existing post-S2a orchestration
```

The chain runs unchanged over the frozen capture, offline, using public material only. The step-by-step runner map (entry points, inputs, which pieces are frozen code and which are S3-owned glue) is in `spec/acceptance-runner-map.md`.

The acceptance path MUST NOT contain: S3-specific semantic assistance, transformations of captured bytes, fallback parsing, identity translation, or network lookup.

**Implementation acceptance is distinct from capture acceptance.** `scripts/verify.sh` of S2b (16 steps, ratified) checks the S2b implementation against its own corpus and fixtures; it does not take a new capture as input. Passing it, even in the pinned environment, says nothing about the S3 capture. S3-C MUST show that this capture's own `request.cbor` passes through the chain, with its own outputs recorded.

### 6.1 `request.cbor` as a committed capture artifact

`request.cbor` (the `ReplayRequestV0` of S2b `frozen/IMPLEMENTATION_SELECTION_v0.md` §4.1) is assembled at S3-B and committed and manifest-covered. It is not rebuilt inside S3-C.

**Correspondence checker (S3-owned acceptance code).** It does exactly the following and nothing else:

1. Decode `request.cbor` through the pinned frozen S2b `decode_request`. A second CBOR parser is not introduced; decode failure is an S3-C failure of the packaging layer, not a P10 verdict.
2. Compare, byte for byte, each decoded raw-byte field with the corresponding capture file: every `leaves` record `[index, statement-bytes]` against `prefix/NNNNNN.cose`; `selected_receipt_bytes` against the retained original Receipt; `target_registered_statement_bytes` against the target prefix file; every `detached_statement_payloads` record against its capture file.
3. Account for every supplied record: records are matched one-to-one with capture files; duplicate indices, extra records, extra files and missing records are failures; nothing is silently deduplicated, reordered into a different assignment, or discarded. (Delivery order of `leaves` carries no meaning in S2b, so order alone is not a failure.)
4. Verify manifest hashes of `request.cbor`, `pB`, `inst`, `iB`, the target payload, and the declared public configuration and provenance files.

It does not re-encode any signed object, and it does not check configuration, identity, fingerprint, lifecycle, or coverage rules: `key_resolution`, `ts_iss`, `LogIdentityV0` against the commitment and `pB`, and key-fingerprint binding are checked by the frozen chain (S2b phases P0/P7, S2a C1/C1b), and re-implementing them would create a second implementation of the same rules. This delegation is deliberate.

The checker is S3-owned code in the acceptance path and therefore part of the trusted computing base of S3-C. Its role is artifact correspondence, not P10 semantics. The capture layout, the `capture.json` index, the ordered checks and the exact failure reasons are specified in `spec/capture-format.md`; the check that `capture.json` itself is the committed one uses an external anchor (the hash recorded in the repository manifest) supplied to the checker. A candidate implementation (`verifier/g5/`, Rust over the unchanged pinned S2b crate) exists and has been exercised (`tests/offline/g5/`); it is not adopted. On any checker failure the S2b replay, the S2a runner, the closureAt helper and the post-S2a stage MUST NOT be called. The chain inputs of an accepted capture are the paths returned by the checker for the capture it checked (request, `pB`, `inst`, `iB`, retained target payload) and nothing else: there is no fallback to a source or fixture directory, and the external anchor (`anchor_checked=true`) is required. Direct runs of the ratified runner controls (Section 7.3) are a separate path with their own bound inputs. `[OPEN]` where the checker runs relative to the chain in the final runner, and the review of its code.

### 6.1a Provenance of post-S2a inputs

The inputs of the post-S2a stage are derived from actual outputs of the preceding stages, never from expected artifacts or from values known to a fixture generator:

- the transcript `tB` is the exact byte string produced by S2b for this capture; it is not a retained or expected copy;
- the Receipt target `leaf_index` is the authenticated checkpoint's `leaf_index` established by S2b;
- the target payload and the target's protected `sub` are taken from the **authenticated target** itself: after S2b returns `Verified`, parse the exact `target_registered_statement_bytes` with the frozen `parse_cose_sign1` and read the protected header with the frozen `read_protected`; an attached payload is used as is, and a detached payload is taken from the corresponding exact request material (`detached_statement_payloads` at that index). No new CBOR/COSE parser is introduced;
- a separately retained target-payload file, if kept, is not an input: it MUST equal the extracted payload byte for byte, and any difference is an S3 acceptance failure of the packaging layer (`S3-FAIL`), not a P10 verdict;
- the S2a evidence digest and the S1 end-to-end result come from the actual S2a runner output for this capture; the A12–A14 digests are the frozen values read from the S2b schema freeze record.

The S2b test tooling (`tests/s2a/run_post.py`) assembles these inputs from the expected transcript and generator-known subject and payload values; that assembly is not acceptable in S3-C.

### 6.2 Outputs recorded

The exact `tB` bytes produced by S2b; the S2b result and evidence record (Section 8 defines which parts must reproduce byte for byte); the S2a runner output; the post-S2a verdict record. These are derived outputs and are not committed as normative.

### 6.3 Composed outcomes

Composition of S2b results into HALT/REJECT is the frozen table of S2b prereg r7 §16.6, not an S3 rule. S3 only requires that the runner propagates it faithfully (Section 7, runner controls).

### 6.4 Supported runtime contract

Verification is supported within the declared pinned environment only. `spec/acceptance-runner-map.md` §5 inventories the dependencies and separates **preparation** (obtaining and hash-checking pinned inputs, toolchains and crates; may use a network) from **S3-C execution** (network disabled). `[OPEN]` whether toolchains are carried in the package or declared host prerequisites verified by hash.

Proposed S2b baseline pin: commit `8eaa91cad1ffa963158b365c6d0d7316f4965e89` (`v0.1.0-s2b-complete`). Comparison with the licensed public tag `v0.1.1-s2b-public` (`8e89f9a4192bdd0ab280556701dc595eb55539d2`): the trees differ only in `LICENSE-APACHE`, `LICENSE-MIT`, `NOTICE.md`, `README.md`, `SECURITY.md`, `docs/INTEGRATION.md` (verified by `git diff --name-status` between the two commits; the manifest-covered implementation files inspected, `replay.rs` and `statement.rs`, are byte-identical at both). Pinning to `8eaa91c` is a proposal, not a freeze.

---

## 7. Mutations

### 7.1 Principle

S3 negative testing covers only behavior that is new in S3:

- (a) capture packaging and the correspondence between capture files and `request.cbor`;
- (b) runner propagation of HALT and REJECT through the traced path;
- (c) delivery-order invariance with unchanged leaf indices.

Coverage of the rules inside S2b and S2a is by reference to the ratified S2b vectors at the baseline pin, by name (Section 7.4). S3 does not regenerate those families and does not build semantic mutations of the committed capture. Each mandatory negative case MUST produce its preregistered non-accepting outcome; a case that produces a different non-accepting outcome, or acceptance, is a failure of the case.

Outcome vocabulary: `S3-FAIL(layer)` is an S3-owned packaging failure and is not a P10 verdict; HALT/REJECT are the composed outcomes of the frozen chain.

### 7.2 S3-owned negative cases (new behavior)

Each case is applied to a copy of the committed capture; the committed capture is never modified. The exact `S3-FAIL(packaging)` reasons are the G5 reason codes of `spec/capture-format.md` §4, and the variants executed for each case (index unchanged vs re-anchored) are listed in §6 of that document.

| ID | Input artifact | Change | Unchanged | Expected phase / outcome |
|---|---|---|---|---|
| N-P1 | one `prefix/NNNNNN.cose` file | one byte flipped | `request.cbor`, manifest of `request.cbor` | correspondence step 2 (content mismatch) ⇒ `S3-FAIL(packaging)`; the chain is not consulted |
| N-P2 | `request.cbor` | one `leaves` record's bytes altered consistently with its manifest hash | capture files | correspondence step 2 ⇒ `S3-FAIL(packaging)` |
| N-P3 | `request.cbor` | one leaf record removed | capture files | correspondence step 3 (unmatched file) ⇒ `S3-FAIL(packaging)` |
| N-P4 | `request.cbor` | one leaf record duplicated (same index) | capture files | correspondence step 3 (duplicate not deduplicated) ⇒ `S3-FAIL(packaging)` |
| N-P5 | capture directory | an extra file added in `prefix/` | `request.cbor` | correspondence step 3 ⇒ `S3-FAIL(packaging)` |
| N-P6 | retained Receipt file | one byte flipped | `request.cbor` | correspondence step 2 ⇒ `S3-FAIL(packaging)` (this is a packaging mismatch; Receipt authentication faults are covered by S2b references) |
| N-P7 | `pB`, `inst`, `iB`, target payload or `request.cbor` | file replaced by another consistent file whose hash is not in the manifest | other files | correspondence step 4 ⇒ `S3-FAIL(packaging)` |
| N-D1 (positive control) | a derived request built from the same capture files | `leaves` records delivered in a permuted order, indices unchanged | all bytes | frozen chain result `Verified` with `tB` byte-identical to the committed run (analogue of S2b `M7b`) |

For N-P1..N-P7 the case fails closed before the chain (the S2b replay, S2a runner, closureAt helper and post-S2a stage are not called); none of them produces a P10 verdict. They exist to show the S3 checker cannot be bypassed by a stale or edited packaging layer, not to test P10 rules.

### 7.3 Runner propagation controls (existing fixtures)

The S3 runner (Section 6; `spec/acceptance-runner-map.md`) MUST be exercised on ratified fixtures that already exist, run with each fixture's own bound profile inputs, not S3's:

| Control | Ratified fixture (S2b `8eaa91c`) | Frozen expectation (as recorded in the fixture) | Path exercised |
|---|---|---|---|
| C-ACC | `vectors/s2a-post/POST-BASE-match` | S2b Verified; S2a accept; post-S2a `BINDING_MATCH` | full path |
| C-POST-REJ | `vectors/s2a-post/BIND-A10-mismatch` | S2a accept; post-S2a `REJECT` (rule A10) | post-S2a REJECT |
| C-POST-HALT | `vectors/s2a-post/T13-T5-closureAt-none` | S2a accept; post-S2a `HALT` (rule T5) | post-S2a HALT incl. closureAt helper |
| C-S2A-REJ | `vectors/s2a-t11/N13b` | S2a `.reject .c3_profileAfterFirstAdmission` | S2a REJECT |
| C-S2A-HALT | `vectors/s2a-t11/N7a` | S2a `.halt .c2_subjectPayloadUnavailable` | S2a HALT |
| C-S2B-REJ | `vectors/E/E10-unprotected` | `Invalid(binding, LeafInputDomainViolation)` ⇒ REJECT | S2b REJECT, no S2a call |
| C-S2B-HALT | `vectors/M/M1` | `Invalid(replay, RootMismatch)` ⇒ HALT | S2b HALT, no S2a call |
| C-S2B-UNAV | `vectors/M/M8` | `Unavailable(material, MissingIndex)` ⇒ HALT | S2b HALT, no S2a call |

The runner MUST reproduce each fixture's recorded expectation unchanged. `[OPEN]` fixture adequacy: the above are candidates and must be confirmed against the actual runner interface (some fixture directories hold only a request, the S2a vectors hold bound `pB`/`inst`). A minimal disposable-key fixture is created only if a required runner path cannot be exercised by an existing ratified fixture. Such a fixture has its own TS key, its own `LogIdentityV0` and its own instance; it is not a mutation of the committed S3 capture; only public material enters it; its keys are generated outside the repository and never committed; it is labelled as test infrastructure and is not S3 live-capture evidence.

### 7.4 Rule coverage by reference (not regenerated)

The six categories originally preregistered map to ratified S2b vectors. The recipe column records what the ratified vector does, from its generator (`tests/differential/gen_corpus.py`) and prereg r7 §17.6; the reason depends on that recipe, so no family is assigned a single generic reason.

| Category | Ratified vector | Recipe in the ratified vector | Phase / reason / composed |
|---|---|---|---|
| one changed registered Statement byte | `M1` | one byte of the leaf at index 1 changed; selected target leaf and Receipt unchanged | P6 `Invalid(replay, RootMismatch)` ⇒ HALT |
| same, but the **selected target** leaf altered | (no ratified vector of this exact shape identified; behavior read from `replay.rs`, phase P5) | target leaf bytes differ from `target_registered_statement_bytes` | P5 `TargetStatementMismatch` is established before P6 and is the reported reason; composed HALT. A "changed byte" recipe MUST therefore state whether the target or a non-selected leaf is altered |
| incorrect Receipt / inclusion proof | `M11` (Receipt root changed, re-signed); `C5-attached`/`C5-detached`, `C6-attached`/`C6-detached` (bad Receipt signature); `M27-attached`/`M27-detached` (validly signed Receipt for a different leaf) | as named | `M11` `Invalid(replay, RootMismatch)`; `C5`/`C6` `-attached` `ReceiptBadSignature`, `-detached` `ReceiptTargetAuthenticationFailure`; `M27-attached` `ReceiptTargetBindingFailure`, `M27-detached` `ReceiptTargetAuthenticationFailure`; all composed HALT. Which of the attached/detached variants applies depends on the Receipt payload form of the selected TS `[OPEN]` |
| missing prefix leaf | `M8` (index 2 omitted), `M8b` (last leaf omitted), `C2` (Receipt `tree_size` larger than the delivered leaves) | as named | P4 `Unavailable(material, MissingIndex)` ⇒ HALT |
| reordered lifecycle: transport-level | `M7` (contents of two leaves swapped, indices unchanged) | changed content-to-index assignment | `RootMismatch` ⇒ HALT (transport corruption) |
| reordered lifecycle: delivery order only | `M7b` | permuted delivery, indices correct | `Verified`, identical `tB` (positive invariance control; S3 analogue N-D1) |
| reordered lifecycle: semantically invalid but authenticated | S2a `N13b`, `X3`, `N5` mirrored as S2b logs in `vectors/s2a-t11` | an authenticated log in which profile commitment / instance commitment follows the first admission, or a relevant admission follows the closure | S2a `.reject .c3_profileAfterFirstAdmission` / `.c4_commitmentAfterFirstAdmission` / `.c10_relevantAdmissionAfterClosure` ⇒ REJECT (semantic negative; needs a consistent tree and a validly signed Receipt) |
| substituted Receipt key | `M13` | supplied `receipt_key` fingerprint ≠ committed | P0 `Invalid(request, KeyMaterialFingerprintMismatch)` ⇒ HALT |
| `ts_iss` / LogIdentity mismatch | `I2-ts-iss` | Receipt TS identity ≠ `frozen.ts_iss` | P7 `Invalid(binding, TsIssuerMismatch)` ⇒ REJECT |
| non-empty unprotected header in the log | `E10-unprotected`, `M4` (in-log flavour) | an authenticated leaf with a non-empty unprotected map | P7 `Invalid(binding, LeafInputDomainViolation)` ⇒ REJECT |
| same registered bytes altered after the fact | `M1`, `M3`, `M4` (transport flavour) | bytes changed with an unchanged log | `RootMismatch` ⇒ HALT |
| empty unprotected header | `E10b-empty-unprotected` | unprotected map is `{}` | `Verified` (positive control for I4) |

Consequences recorded for S3:

- The outcome of a post-hoc alteration of the committed capture depends on what is altered, and the recipe MUST say which object is changed: a non-selected prefix leaf gives P6 `RootMismatch`; the selected target leaf gives P5 `TargetStatementMismatch` (established before P6 and reported as the reason; `RootMismatch` may appear among the diagnostics); a missing leaf gives `MissingIndex`; Receipt, key or configuration alterations give the P0/P2/P3/P7 reasons listed above; all of these compose to HALT except `Invalid(binding)` reasons, which compose to REJECT. Alteration of `request.cbor` or a capture file relative to the other is an S3 packaging failure caught before the chain. A semantic S2a REJECT (lifecycle order) or a `LeafInputDomainViolation` REJECT cannot be reached by altering the committed capture bytes, because that requires a log that actually hashes the offending leaf under a validly signed Receipt; those paths are covered by the ratified vectors above.
- A conformant TS may normalize or reject a statement with a non-empty unprotected header (RFC 9943 requires it empty before inclusion); S3 does not ask a live TS to violate that rule to produce a negative log.
- M1 (byte-level binding of the registered bytes) and the unprotected-header domain boundary stay distinct in intent: M1 tests cryptographic binding of the registered bytes to the root; `E10`/`E10b` test the registered-form boundary.

---

## 8. Reproducibility boundary

- S3-B is a live, one-time capture event. It is not required to reproduce identical bytes across repeated executions: ES256 signatures are randomized unless deterministic nonces (RFC 6979) are used, Receipts may carry time-dependent claims, and the TS assigns indices.
- A repeated S3-B demonstrates procedural repeatability only: another conforming capture should independently satisfy the acceptance oracle. It is not byte-reproduction.
- The frozen S3 capture is the reproducible object.
- S3-C verification over the frozen capture MUST be byte-reproducible and network-independent **within the declared pinned environment** (Section 6.4); no claim is made outside it.
- Byte-reproducible outputs (MUST be identical across runs in the pinned environment): the exact `tB` bytes; the S2a runner's per-job result lines (outcome, evidence digest and repr); the post-S2a verdict and its rule/code; the correspondence checker's pass/fail result; the SHA-256 of each of these outputs.
- Excluded from the byte-reproducibility requirement: log text, timestamps, temporary or build directory paths, build progress output, and any other incidental output. Build-identity facts that the frozen tooling itself records and that depend on the host (e.g. compiler or link substitution logs) are recorded, not compared. `[OPEN]` the exact list of recorded-but-not-compared fields once the glue exists.
- Private keys never enter the capture; S3-C passing without them is the completeness test (I11, I12).

---

## 9. Committed artifacts

Candidate documents present now (`MANIFEST.sha256` hashes every tracked file except `.gitkeep` placeholders and itself; manifest coverage is provenance only, not normative authority): `S3_PREREG_v0.1.md`, `README.md`, `spec/acceptance-runner-map.md`, `spec/CLOSURE_REPORT_OPEN_1_4_6.md`. The directory `spike/` holds a non-normative feasibility spike (experimental entry, glue, host script, public fixture, executed evidence); it is not an S3 artifact in the sense of this section, and its adoption requires explicit review against the completed preregistration.

Planned (none of the S3-B outputs exist at this stage):

- `spec/` — `deployment-profile.md`, `registration-policy.md`, `capture-format.md` (not yet written)
- `ts/` — deployment configuration for the selected TS (not yet chosen)
- `capture/` — frozen live capture, including `request.cbor`, `pB`, `inst`, `iB`, target payload, public configuration, provenance (not yet produced)
- `vectors/` — committed S3 vectors derived from the capture (not yet produced)
- `verifier/` — `PINNED_INPUTS.json`, runner and correspondence-checker glue (not yet written; see `spec/acceptance-runner-map.md` §3)
- `tests/live/`, `tests/offline/`, `tests/mutations/` (Section 7.2–7.3 cases)
- `MANIFEST.sha256`

Excluded from the repository and manifest: private keys, secrets, and any artifact not yet produced.

---

## Remaining OPEN items

1. Non-target `sub` value(s) (I2).
2. Bootstrap mechanism and index-0 content (Section 4).
3. TS implementation selection (Option A). A recommendation exists (`ts-selection/RECOMMENDATION.md`, Tessera v1.0.4 plus an S3-owned facade; unresolved choices listed there); it is not a decision.
4. Lifecycle sequence and capture format (Section 5). Provenance of `pB`/`inst`/`iB` for the S3 instance: a `volmax-owner` fixture with generated test keys was accepted by the unchanged chain in the spike (feasibility only); whether S3 adopts this profile material, and how its keys are governed, is not decided.
5. Form of the Rust entry: the spike uses a thin S3-owned binary over the unchanged pinned S2b crate; adoption versus the separately versioned `p10-replay-cli` adapter is not decided (`spec/acceptance-runner-map.md` §3).
6. The S3-owned glue (post-S2a input assembly, composer, correspondence checker): the spike contains experimental code; form, review against this preregistration, and how it is shown to add no rule are not decided. G4 inputs for a non-toy instance (A12–A14 digests) remain open; for the toy semantics the frozen values were reproduced by the spike (`spike/A12_A14_APPLICABILITY.md`).
7. Toolchain carriage vs declared host prerequisites (Section 6.4); the spike found one prerequisite not covered by the frozen scripts (a native `libuv` development library for the Lean link step).
8. Reason codes: candidate set in `spec/capture-format.md` (executed against the candidate checker); stability and review not decided. Exact recorded-but-not-compared field list (Section 8).
9. Receipt payload form (attached vs detached) of the selected TS (the prototype issues detached Receipts, the frozen S2b form; not adopted), which fixes the reason codes for Receipt-fault references (Section 7.4).
10. Adequacy of the runner-control fixtures (Section 7.3): the eight candidates were exercised in the spike with their own bound inputs; whether they suffice for the adopted runner is not decided.
11. Python version and operating system pins for S3-C (the spike glue used only the standard library).
12. Mixed-log test: ML-1 (two leading synthetic non-target test statements, then the lifecycle at shifted indices) and ML-6 (its capture packaging with `origin="ts"` leaves) were built and executed through the anchored path and the unchanged chain (`spec/mixed-log-test-plan.md` §8); they say nothing about Registration Policy content, bootstrap, enforcement or a live TS. ML-2 to ML-5 are not built (ML-3 to ML-5 are optional rule-coverage checks that reuse ratified vectors).
13. Real capture tooling with independent sources for submissions, exports and Receipts; the tested materialization derives all files from one request.
