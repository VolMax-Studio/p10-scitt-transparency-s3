# TS implementation selection pass: recommendation (candidate, non-normative)

Status: **REVIEWABLE RECOMMENDATION, not a decision.** Evidence baseline: repository commit `8d154b566b27fd643343c61ec95a72b5151f6c1e`. Nothing here ratifies the TS, bootstrap, glue, G5 or acceptance path. Selection (prereg OPEN item 3) stays OPEN until the reviewer closes it.

## 1. Candidates (pinned)

| Candidate | Pin | Notes |
|---|---|---|
| A. `microsoft/scitt-api-emulator` | `6e6776070a1adf7298c9427871f15a8f087be73d` (2024-11-22; tag `pre-archive` = `cfebeee…`) | archived, README banner |
| B. `transparency-dev/tessera` | tag `v1.0.4` = `6bca8e8d5e23c9941f2b8a08f512b373f7131730` | Go; tlog-tiles; RFC 6962/9162 hashing; module-proxy checksum in `probe/go.sum` |

Not inspected beyond a document check (not candidates): `microsoft/scitt-ccf-ledger` (the COSE Receipts CCF profile says CCF trees are not plain RFC 9162 trees) and `scitt-cose` (a verifier library, not a log).

Method: A and B were read at the pinned revisions. For B, a Go probe (`probe/main.go`, sha256 `96b97268…2a31`, go.sum `c8fe14a2…cb593`) was **executed** against Tessera v1.0.4 (Go 1.24.7, POSIX storage) and its output checked against the frozen S2b helpers. For A, nothing was executed; findings are from source.

## 2. Capability matrix

Legend: **I** implemented, **C** configurable, **R** requires adaptation, **U** unsupported.

| Capability S3 needs | A. emulator | B. Tessera v1.0.4 |
|---|---|---|
| Exact LeafEncodeV0 bytes as the leaf | **U**. CCF leaf is `sha256(internal_hash ‖ sha256(entry_id) ‖ sha256(countersign_tbi))` (`scitt_emulator/ccf.py:119-124`); `tree_algs.py` has only `CCF` and `RKVST` (SaaS). | **R** (small). `NewEntry(data)` hashes `data` with `rfc6962.DefaultHasher.HashLeaf` (`entry.go`), so submitting the 61-byte LeafEncodeV0 header plus the statement gives exactly `SHA-256(0x00‖leaf_input)`. **Executed:** Tessera leaf hash == S2b `leaf_hash` for 5/5 and 7/7 leaves. The wrapper is front-end code. |
| RFC 9162 Merkle tree (roots, paths) | **U**. Padded fake tree of `range(63)` dummy leaves and a "Simplification" proof (`ccf.py:128-143`). | **I**. **Executed:** checkpoint roots == S2b MTH of the first i+1 leaves; inclusion path == S2b path (`client.NewProofBuilder.InclusionProof`). |
| Preserve already-conformant submissions | **U**. Stores `{entry_id}.cose`, but re-wraps with its own countersign structure and does not verify claim signatures (`scitt.py` ~226). | **R** (front-end policy). The engine stores whatever bytes it is given; it never parses them. The front-end must register the submitted bytes unchanged and reject (not normalize) non-empty unprotected headers. **Executed:** statement recovered from the export == submitted bytes. |
| Full ordered-prefix export | **U**. No tile or entry export. | **I**. Entry bundles (`api/layout.EntriesPath`, `api.EntryBundle.UnmarshalText`). **Executed:** 5 and 7 exported entries == LeafEncodeV0(submitted) byte for byte. Exporter stripping the 61-byte header is S3 code. |
| Registration Receipt with usable index and size | **U**. Own non-standard Receipt (temporary labels from draft-birkholz-scitt-receipts, `scitt.py:18`; CCF-style `[signature, node_cert, proof, leaf_info]`). | **R**. `PublicationAwaiter.Await` returns the `Index` plus a checkpoint committing to it; **Executed:** index == position and tree_size == index+1 for sequential registration. The RFC 9942/9162 COSE Receipt (protected `{1:-7, 395:1, 15:{1:iss}}`, unprotected `{396:{-1:[bstr(CBOR [size, index, path])]}}`) must be issued by S3 code; Tessera signs checkpoints as notes, not COSE. |
| Stable Receipt signing key for the run | **U**. Fresh ad-hoc node key per Receipt (`ccf.py:98`). | **R**. Not a Tessera concept; the COSE key is held by the Receipt issuer, fixed before the instance commitment. (Tessera's own checkpoint `note.Signer` is a separate key; see §6.) |
| Persistent log state | **C/R**. File storage, but the emulator creates a new ad-hoc node key on each receipt, so state alone does not give stable receipts. | **I/C**. POSIX driver persists. **Executed:** shutdown and reopen of the same directory before the 4th registration; indices and roots continued unchanged. Crash (unclean) consistency **not tested**. |
| Entry size | Not assessed. | **C**. `DefaultEntrySizeLimit = 1<<16 - 1` (`append_lifecycle.go:62`). **Executed:** 65474-byte statement (leaf_input 65535) accepted, 65475 rejected. Limit applies to leaf_input including the 61-byte header. |
| Duplicate handling | n/a | **C**. Antispam is off by default; **executed:** identical bytes got indices 0 and 1, `IsDup=false`. S2b would HALT with `ReceiptTargetAmbiguous` if target bytes appeared twice, so the front-end must prevent a second append of the same bytes, also across restarts (r7: antispam is best-effort and not sufficient; see `ts-prototype/`). |
| Registration-policy enforcement / signature verification | **U** (documented as not applied). | **U**, by design: a log engine. Front-end work. |
| Garbage collection | n/a | **C**. `WithGarbageCollectionInterval` (0 disables); GC removes obsolete partial tiles only, not entries. |

## 3. Verdict per candidate

- **A.** Four of the capabilities are unsupported at the level of core design (leaf form, tree, Receipt, key). Adapting it means replacing `ccf.py`, the receipt format and key handling, i.e. a rewrite of the parts that matter, on an archived codebase with no maintenance. Not recommended.
- **B.** The engine layer is implemented and was executed against the frozen helpers. The SCITT layer (front-end, COSE Receipt issuer, exporter) does not exist and must be written; it is the smallest part of the system but it is also where all non-engine risk sits.

## 4. Recommendation

Select **B (Tessera v1.0.4, `6bca8e8d…`) plus a purpose-built S3 front-end**, as a proposal. Honest characterization: this is "a log engine with an S3-owned SCITT facade", not an off-the-shelf SCITT Transparency Service. It supports the prereg's Option A (a P10-compatible instance operated for the demonstration) and does not support any claim of RFC 9943 / SCRAPI compliance (non-claim 3 stands).

### Smallest required patch list (B)

1. **Front-end register path**: accept a COSE_Sign1 over a transport the S3 profile fixes; parse enough to apply the I2/I4 rules (tagged, readable protected `iss`/`sub`, **empty** unprotected header, reject rather than normalize); build `leaf_input = "P10-LeafEncodeV0\0" ‖ uint32_be(32) ‖ "application/scitt-statement+cose" ‖ uint64_be(len) ‖ statement`; call `Add(NewEntry(leaf_input))`.
2. **Serialize registrations** (I5/I6): one statement in flight; wait for the awaited index before accepting the next. Refuse byte-identical resubmission persistently, including after a restart (**amended in r7: Tessera's antispam is best-effort and is not a deduplication guarantee; the prototype derives duplicate state from the log itself**).
3. **Publication wait**: use `PublicationAwaiter` and obtain index and the checkpoint that commits to it; build the inclusion proof with `client.NewProofBuilder`; check `index == expected position` and `tree_size == index+1` (or record the actual values).
4. **COSE Receipt issuer** with one stable ES256 key, its thumbprint and `ts_iss` fixed before the instance commitment (I7); Receipt issued at registration time and retained as issued (I8). Reference sketch: `dryrun/issue_receipts.py` (uses the S2b test encoders; **not production code**, and the sketch signs with a key supplied by `--keys-dir`).
5. **Exporter**: read entry bundles for `[0,n)`, strip the 61-byte header, write `prefix/NNNNNN.cose`; independent of the submission files.
6. **Persisted configuration** that fixes the batching/checkpoint interval, entry limit, antispam, GC and storage directory for the run; recorded in the capture provenance.
7. **Bootstrap writer** (§5.1) for the leading statements.

Not patched in Tessera itself: no change to the pinned Tessera source is needed for any capability measured here.

## 5. Provisional bootstrap and capture procedure (proposal)

### 5.1 Bootstrap (proposal; prereg §4 and OPEN item 2 stay OPEN)

RFC 9943 mechanism (b): the operator registers a first Registration Policy statement at leaf 0 and a trust-anchor statement at leaf 1, before any issuer statement, through the same facade (same LeafEncodeV0, same empty-unprotected rule). The leaves are non-target, classifiable, and are authenticated as prefix members (the shape exercised by ML-1/ML-6). Contents, `sub` values and signer of those two statements are not chosen here.

**Publication vs enforcement are separate.** Publication = the two statements are bytes in the authenticated prefix. Enforcement = front-end behaviour, an operator-side claim; the frozen chain verifies neither the signatures nor the payload of those statements, so enforcement is **not** established by any acceptance result and is not a soundness premise (prereg non-claim 1). Optionally, the S2b prereg §2.5 content could be added as defence in depth; that is a content choice for the reviewer.

### 5.2 Capture procedure (collect from actual interfaces)

1. Start the facade on a fresh storage directory; record pins (Tessera tag and commit, Go toolchain, facade source hash, configuration).
2. Operator registers the bootstrap statements (leaves 0, 1).
3. Issuers submit the lifecycle statements sequentially (profile, instance, admission, closure, adjudication). The **submission files** are the bytes each issuer sent, retained at submission time.
4. After each registration the facade returns the Receipt, which is retained **as issued**.
5. After the last registration, **export** `[0,n)` from the entry bundles (not from the submission files).
6. Build `request.cbor` from the retained exported leaves, retained Receipts and public configuration only (`dryrun/assemble_capture.py`); expected artifacts are never fed in.
7. Write the capture index; the anchor is the `capture.json` hash recorded from an external channel (the prereg's `MANIFEST.sha256` mechanism).
8. G5 (candidate) checks capture correspondence against the anchor; then the unchanged chain runs on the paths G5 returns (anchored host path).
9. Private keys stay outside the repository.

### 5.3 Procedure dry run (executed, not acceptance evidence)

`dryrun/run_dryrun.sh` ran steps 3-8 against Tessera v1.0.4 for two logs, with a **reference Receipt-issuer sketch** and a **self-anchored** G5. Not a live TS, no real issuers, no external anchor.

| Run | Log | Result |
|---|---|---|
| dry1 | `volmax-owner` 5 leaves | probe all registrations match the S2b helpers; `request.cbor` built from retained bytes is byte-identical to the fixture generator's; G5 PASS (5 leaves, 24 files); chain `BINDING_MATCH`, A1-A15 `match` |
| dry2 | ML-1 shape, 7 leaves (`--ts-origin 0,1`) | same; G5 PASS (7 leaves, 27 files); `BINDING_MATCH`, A1-A15 `match` |

The Receipts are byte-identical to the fixture generator's because ES256 signing is deterministic (RFC 6979) with the same key; that shows equality of encodings, nothing about key governance. A first dry-run request was `Invalid(replay, ReceiptMalformed, ProofEntryNotBstr)`: each inclusion proof must be a bstr wrapping the CBOR array; fixed in the sketch. That is the kind of encoding detail a facade must get right; it was found by the frozen decoder, not by inspection.

Evidence: `evidence/dry1`, `evidence/dry2` (retained submissions, exported leaves, receipt inputs, Receipts, capture dir, G5 and chain reports, `probe-result.json`); `evidence/probe-direct` is an earlier plain probe run (5 leaves, no restart step) with the `verify_probe.py` output (29 checks, 0 FAIL).

## 6. Unresolved choices (all OPEN; recommendation does not close them)

1. Whether B is selected at all (OPEN item 3); whether "engine plus facade" is acceptable as the Option A TS.
2. Facade language (Go in-process with Tessera vs a separate process); who reviews it.
3. Tessera checkpoint-note key vs the COSE Receipt key: two keys with two roles; which is published, and how each is governed.
4. Checkpoint interval and batching (`WithBatching`, `WithCheckpointInterval`) and its effect on registration latency; antispam on/off; GC setting.
5. Storage driver: POSIX tested; others untested. Crash consistency is untested.
6. Who originates the policy leaves and signs them; their `sub` values (OPEN item 1) and content.
7. Receipt payload form, attached vs detached (OPEN item 9). The sketch uses the S2b detached form.
8. Time claims in the Receipt, if any, and `ts_iss` value.
9. Witnessing/TB3 and anything about operator independence: not addressed (non-claim 2).
10. Whether the facade's transport follows SCRAPI (not claimed).
11. Whether the capture tooling (submission/export/Receipt collection) is independent code from the facade (OPEN item 13).
12. Legal/licence review of Tessera (Apache-2.0 is stated upstream; not checked beyond that) and its dependency tree.

## 7. What was not done

No Receipt was issued by a production issuer; no external anchor was used; no unclean-crash test; no multi-writer or load test; candidate A was not executed; no SCRAPI conformance check; the Lean/S2a pins were used as before and re-verified by the existing runner only.

## 8. Amendment (r7): prototype follow-up

A candidate Go facade and capture client over the pinned Tessera were built and exercised (`ts-prototype/`, results in `ts-prototype/RESULTS.md`). Refinements carried into it:
the checkpoint is verified (pinned note key, expected origin), not only parsed, and the Receipt signs only the root reconstructed from a proof for that checkpoint's size
(an operational invariant of this prototype, beyond RFC 9943's registration-before-Receipt rule); the limit is 65535 for `LeafEncodeV0(statement)` (statement 65474);
detached statement payloads are retained as separate exact files and enter `detached_statement_payloads[idx]`; duplicate prevention is persistent and not based on antispam.
The selection (OPEN item 3), bootstrap, glue, G5 and acceptance path remain OPEN.
