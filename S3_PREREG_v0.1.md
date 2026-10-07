# S3_PREREG_v0.1 — P10 S3: SCITT Transparency Service Deployment and Offline Capture Verification

Status: **DRAFT CANDIDATE — preparation only.** Not ratified, not frozen, not signed, not tagged, not released. Nothing in this document is verified or accepted. Items marked `[OPEN]` are unresolved and MUST be closed before any freeze.

---

## 1. Scope

**Normative deployment model (Option A).** A deployable P10-compatible Transparency Service instance whose Statement Sequence uses the frozen `LeafEncodeV0` and whose captured outputs are accepted unchanged by the already frozen offline P10 verification chain.

**Target claim.** S3 demonstrates that a deployed P10-compatible Transparency Service, using the frozen LeafEncodeV0 and RFC9162_SHA256 receipts, can register and expose an exact Statement Sequence capture sufficient for the unchanged frozen P10 verification chain to independently reproduce and accept the captured instance offline.

**Layers.**

- S3-A — deployment definition: what a P10-compatible TS instance is (Section 3, Section 4).
- S3-B — live capture: the real registration process and export (Section 5).
- S3-C — offline acceptance: the frozen verifier chain run over the frozen capture (Section 6).

**Boundary.** S3 is a transport / transparency / deployment layer. It adds no P10 semantics. `TargetAdjudicationValidV0` and `AdjudicationBindingV0` are separate post-S2a semantic bindings and are out of S3 scope, except insofar as the existing post-S2a checks are run unchanged in the acceptance oracle (Section 6).

**Choice of Option A over Option B.** Option A means the "real Transparency Service" is a P10-compatible instance operated for this demonstration (for example an adapted open-source RFC 9162-style SCITT TS), so the claim is feasibility of such a deployment, not compatibility with an independent third-party service. Option B (a third-party TS hashing raw Statement bytes) is incompatible with the frozen `LeafEncodeV0`; adapting to it would be a new profile instance (e.g. `LeafEncodeV1`) and is not S3.

---

## 2. Non-claims

1. S3 does not establish operator independence or non-equivocation against a malicious operator when the Statement issuer and Transparency Service are controlled by the same party.
2. S3 does not claim compatibility with arbitrary RFC 9943 Transparency Services. Exact full-prefix byte export and `LeafEncodeV0` are requirements of this P10 profile instance.
3. S3 does not exercise receipt-key rotation during the committed capture.
4. S3 does not exercise the X.509 identity path. This S3 instance uses the non-X.509 `kid` path with a preregistered public COSE key and `iss = "volmax-owner"`. The X.509 path is simply outside the frozen identity model exercised here; no claim is made that it is syntactically incompatible with S2a.

Additional non-claims: S3 does not claim that a SCITT TS confirms any P10 verdict; it does not claim byte-identical output from repeated S3-B executions (Section 8); it does not claim that rollback/rotation procedures (RFC 9943 key-management guidance) are tested.

---

## 3. Deployment invariants (S3-A)

An instance is P10 S3-compatible only if all of the following hold.

- **I1 — Mixed Statement Sequence.** The VDS Statement Sequence is a mixed SCITT/P10 sequence. Registration Policy and trust-anchor Signed Statements are registered on the same VDS (per RFC 9943), so `[0,n)` is a complete SCITT Statement Sequence, not a P10-only log. `LeafEncodeV0` MUST be applied to every registered leaf, including policy and trust-anchor statements.
- **I2 — Non-target leaves are classifiable.** Registration Policy / trust-anchor statements are non-target leaves. Each MUST carry a protected CWT `iss` and `sub` (required by RFC 9943), and its `sub` MUST lie outside the target P10 subject namespace so the frozen verifier classifies it deterministically as a non-target row. **All** leaves in `[0,n)` MUST remain parsable and classifiable by the frozen verifier; an unparsable leaf is a failed capture, not something to be tolerated by S3 tooling. `[OPEN]` the concrete non-target `sub` value(s) and the exact namespace rule must be taken from the frozen S1/S2 specification.
- **I3 — Bootstrap frozen before execution.** The bootstrap mechanism (Section 4) is chosen and frozen before S3-B runs; the implementation does not select it.
- **I4 — Exact registered-form bytes.** Signed Statements are submitted with an empty unprotected header (`{}`), the form RFC 9943 requires prior to inclusion in the Statement Sequence. The acceptance condition is `submitted_registered_form_bytes == exported_leaf_statement_bytes`. No semantically-equivalent normalization by the TS is accepted.
- **I5 — Sequential lifecycle submission.** Log order need not follow submission order in general, and P10 relies on leaf indices for lifecycle ordering. Therefore: submit one statement, obtain its Receipt and committed leaf index, verify the index, and only then submit the next.
- **I6 — Single-writer window.** The committed vector is captured in a single-writer window; no other writer registers leaves during it.
- **I7 — Fixed Receipt-signing key.** One Receipt-signing key is fixed for the entire bounded S3 capture. The demonstration interval MUST NOT cross the selected receipt-key cryptoperiod. Key rotation is not tested. The key's RFC 9679 thumbprint enters `LogIdentityV0`; the key MUST NOT change beneath a given `LogIdentityV0`.
- **I8 — Original Receipts retained.** The Receipt obtained at the time of each registration is a capture artifact, hashed in the manifest. A later "fresh" Receipt for the same statement (which RFC 9943 permits to be signed with a different key or algorithm) MUST NOT replace it.
- **I9 — Full-prefix export is a P10 requirement.** Exact full `[0,n)` Statement byte export is a P10 compatibility requirement, not a generic RFC 9943 requirement (RFC 9943 permits hash-only VDS). A SCITT-compliant TS that cannot export it fails the P10 S3 gate; that is not a statement about its SCITT compliance.
- **I10 — Profile parameters.** VDS = 1 (`RFC9162_SHA256`); inclusion proof carries `tree_size`, `leaf_index`, `inclusion_path` in a tagged COSE_Sign1 Receipt; ES256 for Receipts and Statements; identity by `kid` with `iss = "volmax-owner"`; no X.509 headers.
- **I11 — Keys.** Private issuer and TS keys MUST NOT appear in the capture or the manifest.
- **I12 — Public-material sufficiency.** S3-C MUST succeed using public verification material only. This also serves as a completeness test of the capture.

**Compatibility checklist (pre-integration gate).** A candidate TS implementation is evaluated against I1–I12 before any integration code is written. Because `LeafEncodeV0` is a P10-defined wrapper, no off-the-shelf service is expected to pass; the gate is expected to select an adaptable implementation, not discover a ready-made one.

---

## 4. Bootstrap

RFC 9943 permits (a) preconfigured Registration Policy and trust anchors, (b) a first policy statement registered without registration checks, or (c) authenticated out-of-band management. S3 MUST NOT leave this choice to the implementation.

`[OPEN]` Select exactly one mechanism and record: the mechanism; the content and hash of the initial Registration Policy and trust anchors; what occupies leaf index 0; and which policy version is active for each P10 statement (derivable from the prefix, since policy statements are leaves and the applicable policy is the last one committed before a registration). The selection is part of the deployment definition and of capture provenance, and MUST be recorded before S3-B begins.

---

## 5. Capture protocol (S3-B)

1. Freeze the deployment definition (Sections 3–4) and record TS implementation identity and version, configuration, and the active Registration Policy.
2. Generate issuer and TS keys outside the repository. Publish only public keys (COSE public key, thumbprint).
3. Perform the frozen bootstrap (Section 4).
4. For each Signed Statement in the controlled P10 lifecycle sequence, in order: build the registered-form bytes (empty unprotected header); submit; obtain the Receipt; verify the committed leaf index; record the submitted bytes and the Receipt; only then submit the next statement (I5).
5. Export the complete prefix `[0,n)` with exact Statement bytes (I9).
6. Assemble the capture: submitted bytes, original Receipts (I8), exported prefix, public keys, bootstrap and policy records, provenance metadata. No private keys (I11).
7. Hash all artifacts into the manifest and freeze the capture.

`[OPEN]` The lifecycle sequence content (statement count, which P10 statements) and the capture file layout (`spec/capture-format.md`) are not yet specified.

---

## 6. Acceptance oracle (S3-C)

```
captured material -> frozen S2b -> frozen S2a -> existing post-S2a checks
```

The frozen chain runs unchanged over the frozen capture, using public material only, offline.

The acceptance path MUST NOT contain: S3-specific semantic assistance, transformations of captured bytes, fallback parsing, identity translation, or network lookup.

Acceptance requires, in addition to the chain accepting: `submitted_registered_form_bytes == exported_leaf_statement_bytes` for every submitted statement (I4), and manifest hashes matching.

S3's claim remains limited to transport/deployment: the chain's acceptance shows the captured material is sufficient for existing P10 semantics, not that S3 adds or confirms any.

---

## 7. Mutations

Preregistered negative tests, each applied to a copy of the frozen capture and run through the unchanged oracle (Section 6). Each MUST be rejected. `[OPEN]` the exact expected failing stage and failure code for each mutation must be preregistered from the frozen S2b/S2a error taxonomy before execution.

| ID | Mutation | Expected outcome |
|----|----------|------------------|
| M1 | One changed registered Statement byte | Reject `[OPEN: stage/code]` |
| M2 | Incorrect Receipt / inclusion proof | Reject `[OPEN: stage/code]` |
| M3 | Missing prefix leaf | Reject `[OPEN: stage/code]` |
| M4 | Reordered lifecycle capture where ordering is semantically invalid | Reject `[OPEN: stage/code]` |
| M5 | Substituted Receipt-signing public key / `LogIdentityV0` mismatch | Reject `[OPEN: stage/code]` |
| M6 | Non-empty or byte-altered registered-form representation (where applicable) | Reject `[OPEN: stage/code]` |

---

## 8. Reproducibility boundary

- S3-B is a live, one-time capture event. It is not required to reproduce identical bytes across repeated executions: ES256 signatures are randomized unless deterministic nonces (RFC 6979) are used, Receipts may carry time-dependent claims, and the TS assigns indices.
- A repeated S3-B demonstrates procedural repeatability only: another conforming capture should independently satisfy the acceptance oracle. It is not byte-reproduction.
- The frozen S3 capture is the reproducible object.
- S3-C verification over the frozen capture MUST be byte-reproducible and network-independent, on any machine.
- Private keys never enter the capture; S3-C passing without them is the completeness test (I11, I12).

---

## 9. Committed artifacts

Planned (none of the S3-B outputs exist at this stage):

- `S3_PREREG_v0.1.md`, `README.md`
- `spec/` — `deployment-profile.md`, `registration-policy.md`, `capture-format.md` (not yet written)
- `ts/` — deployment configuration for the selected TS (not yet chosen)
- `capture/` — frozen live capture (not yet produced)
- `vectors/` — committed S3 vectors derived from the capture (not yet produced)
- `verifier/` — thin runner for the frozen chain, e.g. `run_s2_chain.sh` (not yet written)
- `tests/live/`, `tests/offline/`, `tests/mutations/`
- `MANIFEST.sha256` — hashes of committed artifacts; the current one covers only the candidate documents.

Excluded from the repository and manifest: private keys, secrets, and any artifact not yet produced.

---

## Unresolved items (`[OPEN]` summary)

1. Non-target `sub` namespace value(s) (I2).
2. Bootstrap mechanism and index-0 content (Section 4).
3. Lifecycle sequence and capture format (Section 5).
4. Expected failing stage/code per mutation (Section 7).
5. Selection of the TS implementation to adapt (Option A).
6. How the frozen S1/S2a/S2b specifications and verifier are referenced (vendored, pinned by hash, or external) — they are not present in this repository.
