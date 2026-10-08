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

## D. Public-read timeout correction (r8)

**Defect (found by source review, then reproduced).** The facade read its public log through `NewHTTPFetcher(u, nil)` (default HTTP client, no timeout) after `context.WithoutCancel`
(no deadline), and `PublishTimeout` was only compared between calls. A public endpoint that accepts a request and withholds the response therefore held the registration mutex without bound.
Reproduced on the unfixed build (commit `a7958d9`, which adds only the `--public-read-url` test hook; `scripts/stall_proxy.py` + `scripts/timeout_tests.py --mode pre`,
`evidence/timeout-defect/before-fix/`), with `--publish-timeout 3s`:

| Stalled resource | Registration (client waits 12 s) | Resubmission of an already registered statement (needs only the mutex) | Receipt stored |
|---|---|---|---|
| checkpoint | no answer in 12 s | no answer in 12 s | no |
| hash tile | no answer in 12 s | no answer in 12 s | no |
| entry bundle | no answer in 12 s | no answer in 12 s | no |

`s3-capture export` against a stalled checkpoint took 40.1 s (two 20 s per-request timeouts; no overall deadline).

**Correction.** `finalizeBounded` creates a new bounded context after `WithoutCancel` (client disconnects still do not abort a half-done registration, but the operation now ends at `--publish-timeout`);
every public read of the finalization (checkpoint, hash tiles, entry bundle) runs under it, and each single read also has `--fetch-timeout` (default 10 s). Read failures are recorded by a tracker
and answered as 504 `E_PUBLIC_READ_TIMEOUT` / `E_PUBLIC_READ_FAILED`; only a checkpoint that was read and then failed signature/origin verification is `E_CHECKPOINT_UNVERIFIED`.
Failure releases the mutex, stores nothing, journals `finalize-failed`, and leaves the entry in the log, so the same statement finalizes at its existing index on retry.
`WaitCheckpointSize` now runs under a real context deadline; `s3-capture` has `--timeout` for `submit` and `export`.
The first post-fix run of the new tests **failed** (a single stalled read was reported as 502 `E_CHECKPOINT_UNVERIFIED` for the checkpoint and as 500 `E_PROOF`/`E_PUBLIC_ENTRY_MISMATCH` for tiles and bundle,
because the library wraps read errors without their cause); the read tracker fixed that, and the results below are from the corrected build.

**After the fix** (`scripts/timeout_tests.py --mode post`, `evidence/timeout-defect/after-fix/`; publish-timeout 3 s, fetch-timeout 1 s):

| Scenario | Result |
|---|---|
| checkpoint stalled | 504 `E_PUBLIC_READ_TIMEOUT` after 3.0 s; no Receipt/checkpoint/meta stored; a stored-Receipt resubmission sent 1 s into the stall is answered 200 as soon as the mutex is released (2.0 s: it waited for the bounded period, not forever); after restoring the endpoint the real client retries the same statement: index 1, `duplicate:true, recovered:true`, intents before = after (no second append), independent checks F0-F8 all OK |
| hash tile stalled | 504 `E_PUBLIC_READ_FAILED` after 1.1 s; same storage, mutex and retry results |
| entry bundle stalled | same as tile |
| client disconnects after 1 s (checkpoint stalled) | the facade keeps going to its own deadline (`integrated` to `finalize-failed` 3.0 s, `E_PUBLIC_READ_TIMEOUT`), stores nothing, and the next request is answered in 0.0 s |
| `s3-capture export --timeout 3s`, checkpoint stalled | exit 1 after 3.0 s |

Re-run of the affected facade tests on the corrected build (`evidence/after-timeout-fix/`): unit tests, T1-T6, T5 seeds 2 and 3: all PASS (the earlier evidence directories are unchanged).
Not changed: the Tessera append and its future are not under a deadline; tile/bundle reads fail at the first failed read (no retry inside the deadline), so a caller must retry.

**Detached-closure chain re-run.** The original report (`evidence/exploratory-ml1-detached-closure/`, glue FAIL on the comparison-only `tB == tB.expected`) is preserved byte-for-byte.
The corrected run is stored apart in `evidence/exploratory-ml1-detached-closure-corrected/`; only G5 and the chain were re-run, over the same capture and the same recorded anchor
(`a21ced91…`, committed in `98bb726`), with a detached-specific expectation:

- `scripts/derive_expected_tb.py` computes the root from the log's **retained exported bytes** (two independent leaf-hash implementations, the S2b recursive MTH), cross-checks it against the
  root in the retained final public checkpoint (`c4b0417b…1b43`), decodes the independently generated ML-1 expectation with the reference transcript model (`post_s2a.decode_transcript`, byte-identical round trip)
  and replaces only `root_digest`. The result differs from the ML-1 expectation only inside the encoded root field (`enc_bytes(root)`; in this model its length depends on the value: 34 vs 33 bytes,
  prefix 87 and suffix 1145 bytes identical). `tB.actual` is not an input (the script refuses chain output). Derived expectation: `tB.expected` sha256 `019ad3aae8b3acd9…`; files and `derivation.json` in `expected/`.
- Result: G5 PASS (anchor checked, 7 leaves, 50 files); unchanged chain: S2b Verified, S2a accept, S1 e2e `some`, `BINDING_MATCH`/`BindingMatch`, A1-A15 `match`, and the exact comparison
  `tB.actual == tB.expected` holds (`019ad3aae8b3acd9` both); run PASS. The frozen-chain verdicts were already identical in the original run; only the expectation was wrong there.

The capture itself was made by the pre-fix build (binary hashes in its `extra/`); it was not regenerated, because the corrected path under test is G5 + chain over that capture.

## E. Fresh exploratory lifecycle with runtime issuer tooling (run2; exploratory, not acceptance evidence)

Reported in three separate parts: producer/configuration changes (E1), prototype checks (E2), frozen-chain verdicts (E3).

### E1. Producer and configuration (what changed; not verifier results)

- **Producer source pinned before execution:** commit `0905dfb88bdfa19fd69b9c260f8917f8805c9b81` (tree clean under `ts-prototype/`, enforced by `run_lifecycle.sh capture`; the pin, all source hashes and binary hashes are in `evidence/lifecycle-run2/extra/`). New in that commit: `producer/gen_config.py`, `producer/issuer_tool.py`, `s3-capture submit --producer`, `scripts/run_lifecycle.sh`, `scripts/derive_expected_tb_from_prefix.py`, an assembler option for a retained target payload. One unpinned development dry run with other throwaway keys (same code, scratch directory, `ALLOW_DIRTY`) passed end to end before pinning; it is not evidence and was discarded.
- **Fresh keys** (outside the repository, 0600; issuers and the Receipt key in separate directories, the issuer tool refuses to run if the Receipt key is reachable): owner, admitter-one, admitter-two, intruder-x, policy-test, Receipt key, and a new Tessera note key. A sanity check confirmed that no thumbprint occurs in any committed fixture meta or profile.
- **Derived from the new public configuration:** owner `s3-owner-run2`, `ts_iss` `https://ts.example/volmax-s3-run2`, origin `s3-proto/run2`; `pB.key_resolution` and profile digest `733512cb…de50`; subject `p10s2sub:dfef11ff…f501` (SubjectDeriveV0 of owner and the unchanged toy `request_id`; the same owner name always yields the same subject); LogIdentityV0 `204b17c8…1405`; instance commitment (`inst.bin` sha256 `81238e49…7221`). **Unchanged:** the exact toy `iB` (sha256 `62353069…`), the frozen A12-A14 digests (`c156965f…`, `9482c3f7…`, `30f49843…`), the verifier manifest digest, claim/evidence/witness data, rule IDs, admitter names, `request_id`.
- **Candidate run configuration:** `evidence/lifecycle-run2/run-config.json` (Tessera v1.0.4 POSIX, antispam off, no witnesses, batch 1/10 ms, checkpoint interval 200 ms, publish timeout 30 s, fetch timeout 10 s, entry limit 65535, detached Receipts, sequence of seven roles, non-claims). Bootstrap leaves 0 and 1 are **explicitly experimental** synthetic statements (operator-submitted through the facade, signed by a key in no key table); no policy exists and none is enforced.
- **Runtime issuance:** the issuer tool created and signed each statement just before its registration from the authenticated prefix it fetched over the public endpoint (checkpoint verified, every entry proved), after checking it against the retained submissions and the returned indices (`run/producer/steps.jsonl`). Closure: admission refs `[4]` and preclosure digest `c4e189d1…d24c` over the decoded view `[(2, profile), (3, instance), (4, admission by admitter-one)]` with the ratified S2b reference definition. Adjudication: refs profile 2, instance 3, closure 5 recovered from the decoded prefix. In this single-writer sequential run the returned indices equal the planned positions, so the run cannot distinguish tool-derived from hard-coded indices; a run with a diverging index (for example an extra non-target leaf between lifecycle statements, the unexecuted ML-2 shape) was not executed.
- **Sources kept separate:** issuer/operator submissions and returned Receipts/checkpoints (`run/issuer`, `run/operator`, `run/returned`, `run/public-checkpoints`), and the HTTP public export (`run/export`, `run/public`), read by a client invocation with no storage or submission input. The capture and `request.cbor` were assembled from those retained bytes. The retained target payload was taken from the retained exported target statement.
- **Anchor recorded before verification:** `2ca34344ff01c64e754c702873671810442a82babab515f49833d82833b15b75`, committed in `30374f4` before the checks, G5 and the chain ran (same repository and session; a timestamped record, not an independent channel).
- **Regression of the changed client** (before the run; `evidence/regression-before-run2/`): unit tests, facade tests T1-T6 (seed 1) and the timeout tests all PASS on the pinned build.

### E2. Prototype checks (facade/public read; not a frozen-chain verdict)

F0-F8 all OK over the retained run (`facade-checks.out`): public export equals `LeafEncodeV0(submitted statement)` byte for byte for all 7 leaves; no duplicates; each retained public checkpoint verified with the pinned key, expected origin, size == index+1, root == RFC 9162 MTH of the exported leaves; each returned Receipt (detached, ES256 under the committed key, proof == RFC 9162 for that state) verified against the public checkpoint root; every registration fresh (no retry).

### E3. Unchanged frozen chain

G5 PASS (anchor checked, 7 leaves, 49 files). Chain on G5-returned paths, network-isolated: S2b Verified (continue), S2a accept, S1 e2e `some`, post-S2a `BINDING_MATCH`/`BindingMatch`, A1-A15 `match`; `tB.actual == tB.expected` exactly (`31df5d55c2a69036…`), where the expectation was derived independently from the retained authenticated prefix with the reference transcript model of the ratified S2b test tooling (`expected/derivation.json`; the chain output is not an input); run PASS. Receipts use Go's randomized ECDSA; verdicts do not depend on it.

Not shown: issuer signatures are not verified by the facade (the producer verifies them for its own derivations); no policy is enforced; the single-writer run does not exercise index divergence; no witnesses, rotation, X.509 or operator independence.
