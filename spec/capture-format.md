# Capture format and G5 correspondence checks (candidate)

Status: **DRAFT CANDIDATE**, supporting `S3_PREREG_v0.1.md` r4 §6.1. Not ratified, not frozen, not adopted. Manifest coverage confers no normative authority. This document defines the layout of a capture directory and the checks of the S3-owned correspondence checker "G5". The candidate implementation is `verifier/g5/`; its test evidence is under `tests/offline/g5/` and is separate from the feasibility-spike evidence under `spike/`.

G5 is S3-owned acceptance code and part of the S3-C trusted computing base. Its role is **artifact correspondence only**. It implements no P10 rule: no configuration, identity, fingerprint, lifecycle, coverage, signature, Receipt or Merkle check, and it never parses or re-encodes a signed object. Those are checked by the frozen chain.

## 1. Principles

1. Raw bytes are primary. `capture.json` is an index; it never contains or reconstructs a COSE object, Receipt or payload.
2. Nothing is normalized. The bytes in `submissions/` (as submitted, registered form), `prefix/` (as exported from the Statement Sequence), `receipts/` (as received at registration) and `request.cbor` are compared byte for byte.
3. Every file in the capture directory is indexed, every indexed file exists and has the indexed SHA-256, and every record in `request.cbor` is matched to exactly one file. Nothing is silently deduplicated, reordered into a different assignment, or discarded.
4. `request.cbor` is decoded only by the pinned frozen S2b `decode_request`. `capture.json` is read by the frozen duplicate-aware JSON type of the same crate (`p10_replay::statement::Json`: objects, arrays, strings and booleans only; duplicate member names rejected at every depth; numbers and `null` rejected).
5. The external anchor: the SHA-256 of `capture.json` is recorded outside the capture (for the committed capture, in the repository's `MANIFEST.sha256`) and supplied to G5 as `--index-sha256`. It prevents a repackager from rewriting the index and the files consistently. Acceptance MUST supply it; a run without it is reported `anchor_checked=false` and is not acceptance.

## 2. Directory layout

```
<capture>/
  capture.json                       index (see §3); the only file not listed in the index
  request.cbor                       ReplayRequestV0, assembled at S3-B after the capture is complete
  prefix/NNNNNN.cose                 exact exported leaf bytes of [0,n), one file per leaf index, zero-padded decimal
  submissions/NNNNNN.cose            exact submitted registered-form bytes, for issuer-originated leaves
  receipts/NNNNNN.receipt.cbor       original Receipts obtained at registration; exactly one is the selected Receipt
  detached/NNNNNN.payload            exact detached payload bytes (only if a leaf's COSE payload is detached)
  material/                          pB.json, inst.bin, iB.json, optional retained target payload
  public-keys/                       public COSE keys and declared public configuration (public material only)
  provenance/                        TS identity and version, bootstrap and policy records, tool versions, capture log
```
Private keys and secrets MUST NOT appear anywhere in the capture. A capture contains no symbolic links.

## 3. `capture.json` (format id `P10-S3-CaptureIndex-v0-candidate`)

A JSON object with exactly these members, in any order:

| Member | Value |
|---|---|
| `format` | the string `P10-S3-CaptureIndex-v0-candidate` |
| `request` | file reference `{"path","sha256"}` |
| `prefix` | array of `{"index","path","sha256","origin","role"}`; `origin` is `"issuer"` (statement submitted by the issuer) or `"ts"` (statement originated by the TS, e.g. a bootstrap policy statement); `role` is informational text and is not interpreted |
| `submissions` | array of `{"index","path","sha256"}` |
| `receipts` | array of `{"index","path","sha256","selected"}`; `selected` is a boolean |
| `detached_payloads` | array of `{"index","path","sha256"}` |
| `target` | `{"index"}`, the leaf index of the Receipt target |
| `material` | `{"profile_artifact","instance_commitment","s1_instance","retained_target_payload"}`; the first three are file references, the last is an array holding zero or one file reference |
| `public_keys` | array of `{"name","path","sha256"}` |
| `provenance` | array of `{"path","sha256"}` |

`index` values are canonical decimal strings (`0` or no leading zero, at most 19 digits) because the JSON domain has no numbers. `sha256` is 64 lowercase hex characters. Paths are relative, use `/`, contain no empty, `.` or `..` component, no backslash or NUL, are unique across the index, and are not `capture.json`.

## 4. Ordered checks and reason codes

G5 runs the checks in this order and reports the first failure. A failure is an S3 acceptance failure of the packaging layer, `S3-FAIL(packaging)`, **not a P10 verdict**. G5 exit code: 0 pass, 30 fail, 2 usage error.

| # | Check | Reason code |
|---|---|---|
| C0 | external anchor (when supplied): SHA-256 of `capture.json` equals the anchor | `E_INDEX_ANCHOR_MISMATCH` |
| C0 | `capture.json` / the capture directory cannot be read | `E_CAPTURE_UNREADABLE` |
| C1 | `capture.json` parses with the frozen JSON type and has the exact shape of §3 (members, types, canonical indices, hex hashes, `origin` values, format id; duplicate members and numbers rejected) | `E_INDEX_MALFORMED` |
| C2 | path policy for every indexed path; no symbolic link or special file anywhere in the capture | `E_PATH_UNSAFE`; `E_PATH_DUPLICATE` for a path indexed twice |
| C3 | inventory: every indexed file exists; every regular file on disk (other than `capture.json`) is indexed | `E_FILE_MISSING`; `E_FILE_NOT_INDEXED` |
| C4 | every indexed file's SHA-256 equals the indexed value | `E_FILE_HASH_MISMATCH` |
| C5 | index structure: prefix indices unique and exactly `0..n-1`; submissions unique and for known indices; every `origin="issuer"` leaf has a submission; target index in the prefix; receipts unique per index and exactly one selected, for the target index; detached payloads unique | `E_PREFIX_DUPLICATE_INDEX`, `E_PREFIX_NOT_CONTIGUOUS`, `E_SUBMISSION_INDEX_UNKNOWN`, `E_SUBMISSION_DUPLICATE`, `E_SUBMISSION_MISSING`, `E_TARGET_INDEX_UNKNOWN`, `E_RECEIPT_DUPLICATE`, `E_RECEIPT_SELECTION`, `E_DETACHED_DUPLICATE` |
| C6 | `request.cbor` decodes with the pinned frozen `decode_request` | `E_REQUEST_DECODE` |
| C7 | correspondence of every decoded record with the files: request carries at most one record per index (`E_REQUEST_LEAF_DUPLICATE`); every request record has a prefix file (`E_REQUEST_LEAF_UNMATCHED`); every prefix file has a request record (`E_PREFIX_FILE_UNMATCHED`); record bytes equal file bytes (`E_LEAF_BYTES_MISMATCH`); the selected Receipt is present and equals the selected receipt file (`E_RECEIPT_ABSENT`, `E_RECEIPT_BYTES_MISMATCH`); the target statement is present and equals the prefix file at the target index (`E_TARGET_ABSENT`, `E_TARGET_BYTES_MISMATCH`); detached payload records and files correspond one to one and byte for byte (`E_DETACHED_UNMATCHED`, `E_DETACHED_FILE_UNMATCHED`, `E_DETACHED_BYTES_MISMATCH`) | as listed |
| C8 | each submission's bytes equal the exported leaf bytes at the same index (`submitted_registered_form_bytes == exported_leaf_statement_bytes`) | `E_SUBMISSION_MISMATCH` |

Delivery order of the `leaves` array in `request.cbor` carries no meaning (S2b); G5 does not treat order as a failure.

**What G5 deliberately does not check** (left to the frozen chain): that the Receipt's `leaf_index` is the target (S2b P3/P5); that signatures verify; that the root matches the Receipts; that `ts_iss`, key fingerprints, `LogIdentityV0`, `key_resolution` and `key_material` are consistent with `pB`/`inst` (S2b P0/P7, S2a C1/C1b); lifecycle and coverage (S2a); that the retained target payload equals the payload extracted from the authenticated target (done after S2b `Verified` by the target-extraction step, `S3_PREREG` §6.1a); and the content of `provenance/`.

## 5. Stages that must not be called after a G5 failure

On any G5 failure none of the following may be invoked: the S2b replay (`replay_p0_p9`), the S2a runner (`launch_s2a_runner.sh`), the closureAt helper (`launch_closureat.sh`) and the post-S2a evaluation. G5's own use of `decode_request` (C6) is not a replay. Only after G5 passes may the chain run; a G5 pass is not acceptance.

## 6. Mapping to the preregistered packaging cases

| Case (prereg §7.2) | Variants executed | Expected G5 reason |
|---|---|---|
| N-P1 prefix file byte flipped | a: index unchanged; b: index re-anchored | a `E_FILE_HASH_MISMATCH`; b `E_LEAF_BYTES_MISMATCH` |
| N-P2 request leaf byte altered in place | a: index unchanged; b: re-anchored | a `E_FILE_HASH_MISMATCH`; b `E_LEAF_BYTES_MISMATCH` |
| N-P3 leaf record removed from `request.cbor` | re-anchored | `E_PREFIX_FILE_UNMATCHED` |
| N-P4 leaf record duplicated in `request.cbor` | re-anchored | `E_REQUEST_LEAF_DUPLICATE` |
| N-P5 extra file in `prefix/` | — | `E_FILE_NOT_INDEXED` |
| N-P6 retained Receipt byte flipped | a: index unchanged; b: re-anchored | a `E_FILE_HASH_MISMATCH`; b `E_RECEIPT_BYTES_MISMATCH` |
| N-P7 `pB` / `inst` / `iB` / retained target payload / `request.cbor` replaced by another valid object | a: file replaced, index unchanged; b: index rewritten, committed anchor unchanged | a `E_FILE_HASH_MISMATCH`; b `E_INDEX_ANCHOR_MISMATCH` |
| N-D1 delivery order permuted, indices unchanged (positive control) | re-anchored derived request | G5 pass; the chain result and `tB` bytes are identical to the unpermuted run |

"Re-anchored" means the index (and the anchor handed to G5) were rewritten to match the altered file, simulating a packaging layer that is internally consistent; it isolates the correspondence layer from the hash layer. Additional cases (submission mismatch/missing, symlink, path traversal, duplicate/number in `capture.json`, wrong target, absent Receipt, unmatched detached record, undecodable request) are listed with their results in `tests/offline/g5/`.

## 7. Open points

- The `role` values and the provenance file set are not specified beyond "informational".
- Whether `origin="ts"` statements (bootstrap policy) are required to have a recorded TS-side source file is not decided.
- Real S3-B capture tooling (an independent source for submissions, exports and Receipts) does not exist yet; the tested materialization derives all files from one request and therefore exercises mechanics, not source independence.
- Reason-code stability and the exit-code contract are candidate.
