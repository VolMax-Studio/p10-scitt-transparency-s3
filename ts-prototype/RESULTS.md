# ts-prototype: what was executed (candidate, non-normative)

Source: commit `e7fafc4eedcc9ec994369d1e1926b01784030827` (binaries built from it; source and binary hashes are in `evidence/exploratory-*/extra/prototype-*-sha256.txt`).
Toolchain: Go 1.24.7; Tessera `v1.0.4` (`6bca8e8d5e23c9941f2b8a08f512b373f7131730`); Python venv with `cbor2`, `cryptography` for the independent checks.
Frozen S1 `e4db3747…`, S2a `741d56d3…`, S2b `8eaa91ca…` checkouts were clean before and after. Nothing frozen was modified.

**Two kinds of result are kept apart.** Section A reports checks of this prototype (facade, public read path). They are **not** frozen-chain verdicts, and they add no
P10 rule. Section B reports what the unchanged frozen chain said about a capture assembled from the retained bytes. Checkpoint correspondence and policy
enforcement are **not** acceptance rules of the frozen chain.

## A. Facade and public-read checks (executed)

Go unit tests (`evidence/go-test.out`): CBOR strictness, LeafEncodeV0 (header 61 bytes, statement limit 65474), structural admission (all committed fixture
statements are admitted), Receipt shape: the Go-issued Receipt equals the ratified S2b-tooling Receipt for the ML-1 target **in every byte except the signature**; low-S.

`scripts/facade_tests.py` against real `s3-facade` processes (`evidence/facade-tests/facade-tests.json`; Tessera log directories, bulk tile dumps and per-process klog files of the chaos runs were pruned from the copied evidence):

| Test | What was exercised | Result |
|---|---|---|
| T1 size limit | statement of 65474 bytes (leaf input 65535) accepted and exported byte-exact; 65475 refused 413 `E_TOO_LARGE`; a 70000-byte body refused; nothing appended on refusal | PASS |
| T2 admission | 6 structural refusals (400 with `E_*` codes) append nothing | PASS |
| T3 duplicates + public read | same bytes twice: same index, same stored Receipt bytes, nothing appended; same after a clean restart (index rebuilt from the log); public endpoint serves checkpoint/tiles/entry bundles only: `.state`, directory listing, `/`, traversal 404, POST 405; registration endpoint serves no log data | PASS |
| T4 abrupt termination | self-SIGKILL at `pre-add`, `submitted` (entry not yet integrated, 100-entry/1 s batching), `integrated` (before checkpoint/Receipt), `receipt-stored`, `pre-response`; restart; the real capture client continues and retries | PASS for all five: exactly one leaf per statement, indices contiguous; before-integration crashes (`pre-add`, `submitted`) left 2 entries and the retry appended once; after-integration crashes (`integrated`, `receipt-stored`, `pre-response`) left 3 entries and the retry appended nothing (`duplicate:true`; `recovered:true` when the Receipt had to be issued after the crash); the returned Receipt equals the stored one; independent checks F0-F8 pass on each resulting run |
| T5 chaos | external SIGKILL at random times while the client submits; seed 1/30 statements (25 kills), seed 2/60 (42 kills), seed 3/60 (48 kills) | PASS: each statement exactly once, in order; 9, 16 and 20 recoveries after integration; no restart failure |
| T6 pins | wrong pinned note key, wrong origin, wrong Receipt-key thumbprint: facade refuses to start; client with a wrong (well-formed) key, wrong origin or wrong expected size fails; a forged checkpoint (right origin and format, other key) on the public endpoint: registration answers 502 `E_CHECKPOINT_UNVERIFIED` and no Receipt is stored | PASS |

`scripts/s3check.py` (independent Python, S2b test helpers read-only) checks every run: F0 contiguous entries; F1 public export == `LeafEncodeV0(submitted statement)` byte for byte;
F2 no duplicate leaf; F3 each retained public checkpoint: signature under the pinned key, origin, size == index+1, root == RFC 9162 MTH of the exported leaves; F4 checkpoint returned with
the registration == checkpoint fetched from the public endpoint; F5 each Receipt: detached payload, expected protected header, proof == RFC 9162 for that state, ES256 signature under the committed
TS key over the public checkpoint root; F6 response fields; F7 submit log; F8 export result. `scripts/s3check_mutations.py` tampers with a run in 8 ways: every one is detected (`evidence/s3check-mutations.out`).

## B. Exploratory seven-leaf lifecycle through the facade, then the unchanged chain

Bootstrap: leaves 0 and 1 are the ML-1 **synthetic TEST statements** (`urn:volmax:s3-test:registration-policy`, `…:trust-anchor`), operator-submitted, no policy, not enforced.
Sources kept separate: submissions and returned Receipts (and the original public checkpoint after each registration) by `s3-capture submit`; the export by `s3-capture export`, HTTP only, with no storage path and no submission input.
The anchor (SHA-256 of `capture.json`) was written to `ANCHOR.sha256` and committed (`4bc0df1`, `98bb726`) before G5 and the chain were run. Caveat: the same session and repository produced it; it is a recorded, timestamped anchor, not an independent channel.

| Run | Facade/public-read checks | G5 | Frozen chain |
|---|---|---|---|
| `evidence/exploratory-ml1` (attached payloads) | F0-F8 ALL OK | PASS, anchor checked, 7 leaves, 49 files | S2b Verified (continue), S2a accept, S1 e2e `some`, post-S2a `BINDING_MATCH`/`BindingMatch`, A1-A15 `match`; actual `tB` == the generator's independently built expected `tB`; run PASS |
| `evidence/exploratory-ml1-detached-closure` (statement 5 submitted in detached form, payload kept by the issuer as `detached/000005.payload`, passed to `detached_statement_payloads[5]`, frozen schema unchanged) | F0-F8 ALL OK | PASS, 50 files | same verdicts and `BINDING_MATCH`, A1-A15 `match`; the glue's comparison-only check `tB == tB.expected` is **FAIL**, as expected: that expectation is the ML-1 attached-form log, and the log root differs because a leaf's bytes changed (the only difference found in `tB` is the root field). The run is therefore reported as glue FAIL on that one comparison, not as PASS; no variant-specific expected `tB` was built. |

Receipts are issued with Go's randomized ECDSA, so `request.cbor` differs from the fixture generator's request (which uses RFC 6979); the verdicts do not depend on it.

## C. Not shown

- Durability beyond SIGKILL: no power loss, no fsync fault injection, no disk-full; the Tessera POSIX driver's own crash guarantees are relied on. 115 random kills (25 + 42 + 48) and 5 targeted ones produced no violation, which is not a proof.
- Issuer signatures are not verified by the facade; no trust anchors; no Registration Policy beyond structure; the bootstrap statements are synthetic and unenforced.
- Single process, single writer; duplicate detection rebuilds from a full scan at start (O(n)); a second facade over the same storage is not supported.
- A Receipt issued after recovery covers the first verified checkpoint larger than its index; the sequential client makes that size `index+1`, and `s3check` requires it.
- No witnesses; no rotation; no X.509; no operator independence; no SCRAPI/RFC 9943 compliance claim. RFC 9943 requires registration before a Receipt is issued; binding the Receipt to a verified, published Tessera checkpoint is this prototype's additional operational invariant.
- Receipt payload form: detached, as in the frozen S2b form (consistent with RFC 9942's recommendation); whether S3 adopts it is still OPEN item 9.
