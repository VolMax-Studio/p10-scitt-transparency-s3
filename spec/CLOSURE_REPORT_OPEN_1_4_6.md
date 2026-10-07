# Evidence-only closure report — OPEN #1, #4, #6

Status: EVIDENCE ONLY. Read-only inspection of the frozen chain. Nothing here is a decision, freeze, or acceptance. Committed in `605030c4fcb20d946d8bac124c4f45cb8b212937`; this file is hashed in `MANIFEST.sha256` for provenance only, which confers no normative authority. It was written before the prereg r2 correction pass and is not edited to track it, except for this status line and the notes below. Where it says the prereg is "not modified" or lists corrections as "NOT applied" (§4), that described the state at that commit; the corrections were applied in the r2 candidate of `S3_PREREG_v0.1.md`.

Post-report verification (r2 pass, read-only): `git diff --name-status 8eaa91c 8e89f9a` shows only license/documentation paths (`LICENSE-APACHE`, `LICENSE-MIT`, `NOTICE.md`, `README.md`, `SECURITY.md`, `docs/INTEGRATION.md`); `replay.rs` and `statement.rs` hash identically at both commits. Section 5's first and second "still unverified" items are thereby resolved for the file set compared; the third and fourth remain open (the S1 profile text was reported by the user as checked and not independently re-read here).

Method: shallow clones of the public/attached upstream repos, read-only; no builds, no test runs, no Lean/Rust execution. Claims below are source-reading claims unless marked "executed" (none are).

## 0. Immutable identifiers (verified against `git ls-remote --tags` and checked-out HEAD)

| Layer | Repository | Tag | Tag object | Peeled commit |
|---|---|---|---|---|
| S1 | VolMax-Studio/p10-underdetermination-lean-s1 | v0.1.0-s1-ratified | 7c3df437de454466b932a5d0dc889b3287c64e05 | e4db3747eaeeb1a07227bb9029f9a9c3b566cdb1 |
| S2a | VolMax-Studio/p10-coverage-lean-s2 | v0.1.0-s2a-ratified | c356cde5295dc82860b70305e3048db8f2717db3 | 741d56d36d7b2bfe2e9e0080a1cba4393e4a47da |
| S2b (ratified) | VolMax-Studio/p10-replay-verifier | v0.1.0-s2b-complete | 83fad0063443aa5d43620d82550dff9cbf3dd3a8 | 8eaa91cad1ffa963158b365c6d0d7316f4965e89 |
| S2b (public, licensed) | same | v0.1.1-s2b-public | (not resolved here) | 8e89f9a4192bdd0ab280556701dc595eb55539d2 (default-branch HEAD inspected) |
| CLI adapter (not part of the frozen chain) | VolMax-Studio/p10-replay-cli | v0.1.0 | 9719a85a26b949dad27fdcb54f670799179616ed | 90c2706a981b0071bd627278f5a59fb9cdbc9a8c |

These match `p10-replay-verifier/frozen/S1_DEPENDENCY.txt`, `S2A_DEPENDENCY.txt` and README "Repository chain".

Inspected-file SHA-256 (S2b at `8e89f9a`, S2a at `741d56d`):

```
d142e636a9a92fdc57bbc49e77e077607ff12e96c19b79ad539b2f6b17b16008  s2b/frozen/LeafEncodeV0_SPEC.md      (== UPSTREAM_HASHES leafencode_spec_sha256)
a28eb8c25904650c76576e80c442590aa14e3380fb8d6e39433bb4da59d05706  s2b/frozen/S2B_PREREG_v0.1_r7.md
7fc847ea66114f87b22e79b5c93f55d80d3e92923b613a9ad8efee17df92a455  s2b/frozen/StatementPayloadSchemaV0_r9.md
ff648f762f7f0b8d4c800575206f720d5cd9a205767f51db84c973b7eef0263a  s2b/frozen/IMPLEMENTATION_SELECTION_v0.md
9d492650647d42348407dd75b1e9d490e1d071232152a7297365b924e107800e  s2b/src/p10_replay/replay.rs
9e73fc15b34e3c23e0c2f6f10563bc50831472e008887c5020d94db1b6f29f21  s2b/src/p10_replay/statement.rs
3ee5cbe0eba7c9ad8a07cc73ca3ceb2d8c0a1915c0374d46917b5bf01c845b7f  s2a/P10S2/Coverage.lean              (== UPSTREAM_HASHES)
a0176b6e191272fd6cb45f0e54eb9a6a137efc0bf4a839ff31c1c5423a4dcbd2  s2a/P10S2/Types.lean                 (== UPSTREAM_HASHES)
```

Caveat: `replay.rs`/`statement.rs` hashes are for the `8e89f9a` tree. README states manifest-covered implementation files are identical between `v0.1.0-s2b-complete` and `v0.1.1-s2b-public`; I did not diff the two tags myself.

## 1. OPEN #1 — non-target leaf (`sub`) rule

Source of truth: S2b prereg r7 §13.4 (line ~548), `statement.rs::read_protected`, `replay.rs`, S2a `Coverage.lean::matchIdxs`.

Findings (source-read):

1. **There is no "P10 subject namespace" in the frozen verifier.** Subject membership is exact byte equality `row.sub == frozen.instance_subject` (prereg I-9; S2a `matchIdxs`: `s = sub`). Anything else is non-target. The instance subject has the ratified-fixture form `"p10s2sub:" ++ 64 lowercase hex` (schema r9 §3 rule 2), but the wire rule is byte equality. A non-target `sub` only has to be a valid UTF-8 text string that is not byte-equal to `instance_subject`.
2. **To be classified as a non-target row (not `unavailable`), a leaf MUST be:** a conformant tagged `#6.18(COSE_Sign1)` (untagged ⇒ `unavailable`, vector E2-untagged: `Verified`, `unreadable:[0]`); with a protected header that is exactly one CBOR map with no duplicate labels; containing label 15 (CWT claims) as a map with no duplicate labels; with claim 1 (`iss`) and claim 2 (`sub`) both present and both valid-UTF-8 text strings. Failure modes (`ProtectedUnreadable`): NotOneCborItem, NotAMap, DuplicateProtectedLabel, CwtClaimsAbsent, CwtClaimsNotAMap, DuplicateCwtLabel, IssAbsent, IssNotText, SubAbsent, SubNotText. Vectors E4-protected-notmap/-trunc, E5-iss-missing, E5-sub-notstr, E6-dup-cwt, E12-sub-badutf8 all `Verified` with the leaf listed in `unreadable`.
3. **An unreadable leaf becomes an `unavailable` row, and S2a then HALTs** (`Coverage.lean` C2 `c2_rowUnavailable`; prereg §13.4 rationale). So a single unparsable policy/trust-anchor leaf anywhere in `[0,n)` forces HALT for the whole instance. This confirms I2 ("all leaves must be parsable/classifiable") is load-bearing, and shows the RFC 9943 mandatory `iss`/`sub` are not optional for S3.
4. **Non-target leaves get no signature/alg/payload processing** (§13.4 row 2; vectors E3-nonsubject, S11d, S14, M26): a bad signature, forbidden `alg`, or garbage/`nil` payload on a non-target leaf is `Verified`. Consequence for S3: S2b/S2a place no verification weight on Registration Policy leaf signatures; their authenticity is outside the frozen chain (TB boundary).
5. **Unprotected-header domain rule applies to EVERY leaf in the authenticated prefix, including non-target ones.** `replay.rs::leaf_violates_domain`: if the COSE array is readable (4 items, tag 18 or untagged) and the unprotected map is non-empty ⇒ `Invalid(binding, LeafInputDomainViolation)` ⇒ composed **REJECT** (E10, M4-in-log). Policy/trust-anchor statements registered by the TS must therefore also have `{}` unprotected. This is stronger than I4 currently states ("Signed Statements"); it should say every leaf. An empty map (`a0`, and `bf ff`) is accepted (E10b-empty-unprotected: `Verified`).
6. **Alphabet correction (affects how the prereg and the discussion justified `iss`).** The S2a token alphabet (`allTokB`, `[A-Za-z0-9_.:-]`) is enforced only on `inst.issuerId` (C1a `c1a_issuerNotToken`, vector X10) — i.e. the instance owner/issuer. S2b places **no alphabet restriction on `ts_iss`** (prereg §12: "No `ts_iss` alphabet restriction"; vector I6b-slash-uri is `Verified`) and reads non-target `iss` as any text string. So: `iss="volmax-owner"` matters for the instance issuer; policy-statement `iss` and TS `iss` are unconstrained by S2a/S2b. The earlier phrase "S2a rejects every S3 instance because of `iss`" applies only to the owner/issuer identity.
7. **`kid` is not read by the frozen verifier.** `grep -w kid src/` finds only a comment in `thumbprint.rs`. Statement-signer key resolution is by `iss` via the frozen-config tables `key_resolution` (`[iss, fingerprint]`) and `key_material` (`[iss, COSE_Key]`) (IMPLEMENTATION_SELECTION §4.1 labels 7–8). `kid` presence is an RFC 9943 header requirement of the TS, not something S2b exercises. Prereg I10 ("identity by `kid`") is therefore imprecise: identity as far as the frozen chain is concerned is `iss` + the frozen tables.
8. Ratified-fixture S2a also constrains `owner == issuer` (C1a `c1a_ownerNotIssuer`) and `owner ∉ admitters` (`c1_ownerInAdmitters`).

Unresolved after reading: the concrete non-target `sub` string(s) is a free S3 choice subject only to "≠ instance_subject, valid UTF-8 tstr". The previously assumed "S1/S2 rule" does not exist as a namespace; the choice is a new S3 decision, constrained by item 2.

## 2. OPEN #4 — mutation expectations from the existing taxonomy

Composition table (S2b prereg §16.6): `Invalid(replay)` and `Invalid(request)` and `Unavailable(*)` ⇒ **HALT**; `Invalid(binding)` ⇒ **REJECT**; `Verified` ⇒ S2a decides.

| S3 ID | Intended mutation | Existing S2b vector(s) | Expected S2b result | Composed |
|---|---|---|---|---|
| M1 | one registered Statement byte changed, log/Receipt unchanged | M1 | `Invalid(replay, RootMismatch)` | HALT |
| M2 | incorrect Receipt / inclusion proof | M11 (root changed, re-signed), M12 (sig bit flipped: detached ⇒ `ReceiptTargetAuthenticationFailure`, attached ⇒ `ReceiptBadSignature`), M27 (valid Receipt for a different leaf ⇒ `ReceiptTargetAuthenticationFailure`/`ReceiptTargetBindingFailure`) | `Invalid(replay, …)` (reason depends on mutation and on attached/detached Receipt payload) | HALT |
| M3 | missing prefix leaf | M8 (idx 2 omitted), M8b (last omitted), M10 (`tree_size=n+1`) | `Unavailable(material, MissingIndex, idx)` | HALT |
| M4 | reordered lifecycle, ordering semantically invalid | S2b: M7 (leaf contents swapped, indices unchanged) ⇒ `RootMismatch`. S2a: N13b (`c3_profileAfterFirstAdmission`), X3 (`c4_commitmentAfterFirstAdmission`), N5 (`c10_relevantAdmissionAfterClosure`) — all `.reject` | **depends on how the mutation is built — see below** | HALT (byte-swap) or REJECT (consistent log) |
| M5 | substituted Receipt-signing public key / LogIdentity mismatch | M13 (supplied `receipt_key` fingerprint ≠ committed) ⇒ `Invalid(request, KeyMaterialFingerprintMismatch)`; M14/I2 (Receipt TS iss ≠ `frozen.ts_iss`) ⇒ `Invalid(binding, TsIssuerMismatch)`; I3 (other TS key) | key swap: `Invalid(request, …)` ⇒ HALT (§16.6: a rotated key "cannot be authenticated" ⇒ HALT, not REJECT); `ts_iss` mismatch: REJECT | HALT or REJECT |
| M6 | non-empty / byte-altered registered form | non-empty unprotected in an authenticated leaf: E10, M4-in-log ⇒ `Invalid(binding, LeafInputDomainViolation)`; byte-altered registered bytes with unchanged log: M1/M3/M4-transport ⇒ `RootMismatch`; tagged↔untagged: M2-tagged-logged / E2 | see rows | REJECT (log hashed it) or HALT (transport only) |

Findings that bear on the prereg:

1. **M1 and M6 can be kept separate with existing, distinct codes**, but only for the *authenticated-log* flavour of M6. A post-hoc byte alteration of a frozen capture (what M1 does) is always `RootMismatch` ⇒ HALT, for M1 and for a byte-altered M6 alike. The only path to REJECT `LeafInputDomainViolation` is a log whose tree actually hashes a leaf with a non-empty unprotected header — i.e. the live TS (or a test log) must have registered it.
2. **M4 and the REJECT flavour of M6 cannot be produced by mutating the frozen capture bytes.** Swapping/reordering leaves of the captured prefix breaks the Merkle root against the retained Receipt (⇒ `RootMismatch`, HALT, not the semantic S2a REJECT). To reach S2a's `c3/c4/c10` REJECTs (or E10's REJECT) the mutated log needs a consistent tree **and** a freshly signed Receipt, which requires the TS Receipt private key — and the prereg forbids private keys in the capture. Therefore the REJECT-class mutations need either (a) separate negative live captures (a second S3-B run submitted in a bad order / with a non-empty unprotected header, if the TS allows it — an RFC 9943-conformant TS may normalize the header to `{}`), or (b) a test-only mutation harness using a disposable test TS key that is explicitly not the S3 capture key. This is an open design decision, not resolved by existing sources.
3. **Mutation expectation granularity**: S2b prereg §16.6 itself notes the profile does not define REJECT vs HALT for root mismatch/bad Receipt signature (G-10) — HALT there is a prereg choice (confirmed by the independent G5 review). S3 should cite §16.6 rather than re-derive.
4. S2a REJECT/HALT enums are in `Types.lean` lines ~132–180 (REJECT: 32 reasons incl. `c1_rowsNotContiguous`, `c1_detailedMismatch`, `c1_logIdentity`, `c3_*`…`c13_*`; HALT: `c2_rowUnavailable`, `c2_subjectPayloadUnavailable`, `c2_keyUnavailable`, `c3_noProfileCommitment`, `c4_noInstanceCommitment`, `c6_noValidClosure`, `c11_noAdjudicationAfterClosure`, `tb5_checkpointMaterialUnavailable`).
5. Post-S2a (after S2a ACCEPT): `TargetAdjudicationValidV0` failure ⇒ HALT; `AdjudicationBindingV0` A1–A15 mismatch ⇒ REJECT (prereg §16.6 second table).

Not executed: no vector was run; the expected values are the frozen `expected.json`/`expected.txt` contents and prereg tables, read as written.

## 3. OPEN #6 — what the frozen chain needs in order to run offline

Findings (source-read):

1. **The chain's entry is a `ReplayRequestV0`, not a capture directory.** S2b consumes exactly one CBOR item `["P10-ReplayRequestV0", frozen-config-map(labels 1–8), ts-material-map(labels 1–5)]` (IMPLEMENTATION_SELECTION §4.1). The integration guide says the integrator "builds the exact `ReplayRequestV0`" (adapter explicitly out of scope of S2b; README diagram). Hence **a capture→request packaging step exists and is not frozen S2b code**. It is a pure serialization step but it is S3-owned bytes: the prereg's "no S3-specific transformation in the acceptance path" needs an explicit treatment — either the request CBOR is produced at S3-B and committed/hashed as a capture artifact (acceptance then starts at the frozen decoder), or the encoder is itself frozen and tested for byte-exactness. Either way this is a new open question.
2. The request's frozen-config carries `ts_iss`, `receipt_key` (COSE_Key), `checkpoint_verification_key_fingerprint`, `vds_algorithm=1`, `leaf_encoding_spec_digest`, `instance_subject`, and the statement-issuer tables `key_resolution`/`key_material`. So the public-keys part of the capture must supply these; and S2a additionally needs `pB` (profile artifact) and `inst` (instance commitment) bytes (`coverageCheck π inst pB T`).
3. **Reproducing the chain needs far more than the three repos' commits:**
   - Rust `1.82.0` toolchain (`rust-toolchain.toml`) and **53 locked crates** (`Cargo.lock`) for S2b (and the CLI), which a bare git bundle does not contain (no vendored crates in the tree).
   - Lean `leanprover/lean4:v4.33.0` toolchain for S2a and the post-S2a `ClosureAtHelper`; the S2b orchestration selects Lean **by SHA-256 of the executable** pinned in the S2a verifier manifest and refuses other builds (`orchestration/lean_build_common.sh`), and uses a `cc_wrapper.sh` workaround for the pinned Conda-built Lean. The helper is built fresh per run (`launch_closureat.sh`), never from cache.
   - S1 is vendored inside S2a (`vendor/p10-underdetermination-lean-s1`); S2b records `Vendored S1 git tree: 6cdf48c29cd2207243912881c8f38c416ba2026a`. `.olean` reproducibility is an acceptance condition (schema r9 §8.11.11).
   - Python 3 (`orchestration/post_s2a.py`) with `zstandard==0.25.0` (S2a `requirements.lock`).
   - The normative acceptance entry is `scripts/verify.sh` (16 steps), evidence under `evidence/g16-s2b-final/`.
   So a `git bundle` per repo is necessary but not sufficient for "network-independent on any machine". The toolchains (Rust, Lean, vendored crates, Python wheel) need to be pinned by hash and carried or declared as host prerequisites. Whether S3-C "byte-reproducible and network-independent" means "given the pinned toolchains already installed" or "self-contained bundle including toolchains" is an open decision.
4. Bundle/identity mechanics are consistent with the existing pins: tag→commit mappings in §0 are verifiable offline from a bundle that contains the tag; the S2b repo's own pins (`UPSTREAM_HASHES.txt`, `S1_DEPENDENCY.txt`, `S2A_DEPENDENCY.txt`) are inside the S2b tree, so a bundle of S2b already carries the S1/S2a commit IDs but not their contents.
5. There are two S2b tags: ratified `v0.1.0-s2b-complete` (no license file) and public `v0.1.1-s2b-public`; README says manifest-covered artifacts are identical. S3 `PINNED_INPUTS.json` must choose one explicitly; I did not verify the "identical" claim by diff.
6. The S2b Rust path (`p10-replay-cli`) is an adapter, not part of the frozen chain; the chain's post-S2a orchestration (`post_s2a.py`) is Python+Lean, so `run_frozen_chain.sh` must cover Rust (S2b) → Lean (S2a runner, `launch_s2a_runner.sh`) → Python/Lean (post-S2a). The exact way these are chained in `scripts/verify.sh` was not traced to line level here.

## 4. Corrections this implies for the committed candidate (NOT applied)

For discussion, not edits:

- I2: replace "namespace rule taken from frozen S1/S2" with: frozen rule is byte-inequality to `instance_subject` plus readability conditions (§1 items 1–2).
- I4: extend the empty-unprotected requirement from "Signed Statements" to every leaf of `[0,n)`, incl. Registration Policy / trust-anchor (§1 item 5).
- I10: "identity by `kid`" should be reworded: the frozen chain resolves statement keys by `iss` through frozen tables and does not read `kid` (§1 item 7).
- Section 7/M4, M6: add the production constraint of §2 findings 1–2.
- Section 6: add the capture→`ReplayRequestV0` question (§3 item 1).
- Open #6: "git bundles" alone are insufficient (§3 item 3).

## 5. Still unverified

- That `v0.1.0-s2b-complete` and `v0.1.1-s2b-public` have byte-identical manifest-covered files.
- Exact chaining order/commands inside `scripts/verify.sh` and `launch_s2a_runner.sh`.
- Whether an RFC 9943-conformant TS can be configured to register a non-empty-unprotected statement (relevant to M6 live-negative option).
- Whether any other source (e.g. S1 profile text §2.4) adds constraints on non-target leaves beyond S2b/S2a; S1 repo was not cloned and the vendored profile document was not read.
