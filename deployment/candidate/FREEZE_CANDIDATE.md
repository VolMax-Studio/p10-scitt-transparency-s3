# FREEZE CANDIDATE — S3-A (P10 Transparency Log Deployment and Offline Capture Verification)

Prepared from commit `5d58b67bcdb4643d5fd3a8c5817a6718aca59b42` (the head of `claude/upbeat-allen-pmvtze` before this file; the commit that adds this file is reported separately, because a file cannot contain the hash of its own commit). **This document authorizes nothing.** It identifies exactly what the operator (Ivan) would adopt and freeze, after reviewing the final diff. **Every adoption below is pending Ivan's explicit approval.** Nothing is frozen, ratified or signed by this document or by Claude; the normative S3-B capture has not started.

## 1. Three things that must not be confused

| Class | What it is | Status |
|---|---|---|
| **A. Definition proposed for freezing (S3-A)** | The files listed in §9 (`deployment/candidate/freeze-set.sha256`): preregistration, deployment definition, registration interface, capture format, runner contract and sources, reviewed TCB sources, executable pins, facade and tooling sources, test harness | Candidate; adoption pending Ivan's approval |
| **B. Historical exploratory evidence** | Everything under `*/evidence/` (run2, run3/ML-2, detached-closure, `qualification-auth-ml2`, `auth-regression`, `validation-1`, `validation-2-r13`, `path-guard`, `fault-guard`), the spike, the TS selection pass, throwaway-key runs | Preserved unchanged; supports the proposal; **not acceptance evidence** and **not part of the freeze set** |
| **C. Future normative S3-B capture** | One live lifecycle with the candidate key set through `deployment/candidate/RUN.md`, followed by the runner acceptance | **Has not started.** Starts only after Ivan freezes A with his own key; produces the frozen capture |

## 2. Preregistration and revision

`S3_PREREG_v0.1.md` revision r19, sha256 `1faf4841289e7e33b618ff96a52c9ff88d4940dc534a014096cec29e7578196b`. Target claim (operator-supplied, verbatim): "S3 tests whether a P10 lifecycle registered through an issuer-authenticating COSE registration front-end over a Tessera transparency log can be captured from its public read interface and replayed offline through the frozen P10 chain with BINDING_MATCH." The RFC 9943 / SCRAPI non-claims are a separate paragraph of §1 and §2; none is weakened. Policy enforcement, authorization of issuers, operator independence, witnesses, rotation and X.509 remain non-claims.

## 3. Deployment definition

- Narrative and decisions D1–D13: `spec/deployment-profile.md` `8aafd3fb5ee7def671b5327262d7426af37c25f48b4bd4678813925fed328589`
- Machine-readable definition: `deployment/candidate/definition-manifest.json` `c13a79013e91736a84eee4e6470d7fecc7e9f658198b1641c141e0bd998e7ff1` (every file of `config/` and `operator-staging/` hashed there; checked by the `install` phase)
- Registration interface (authentication rules, written before implementation): `spec/registration-interface.md` `a319211f6f81ccdab907b98c790193338264f4665782224a9544cf2364e13c05`
- Identity: owner `volmax-owner`, operator `volmax-s3-operator`, Receipt issuer `https://ts.example/volmax-s3`, origin `volmax-s3/ts`, instance subject `p10s2sub:0fe1be115beb770330930911e69e4f2026c80809c64ada16e87fe63e7f9150d2`, `LogIdentityV0` `6a510bcf3a122ae9af2714939d60a6a4e997ff9751836024dd480ebd60cd37c9`, profile digest `ac4895511c903e6836c471d197507793566f7d822c49aa5a02a6e0581e7a26ec`, Receipt key thumbprint `6bc5b0ae47f8726379ffbfb0e0858fe10ef74ba5b8801edeba0b3d3b89944056`.
- Bootstrap (preconfigured declarations published as leaves 0 and 1, authenticated like any statement): policy declaration `c9ac82ddc94da80f87c68547e5ca84b0f0c98da80264614b8df9fb169818763e`, verification-material declaration `c09e60ab6d7f36107245e3f8d5fa272eb8859b3f64c4f9cd39f26eaec8f27e68`, issuer table `e1fffa936136135da54c518328b55cb4915cf858dadd73860ff3c3f77d03d1ba`. The declarations are published bytes: they establish neither key authority nor policy enforcement.
- Layout: 8 leaves (0 policy declaration, 1 verification-material declaration, 2 profile, 3 operator note, 4 instance, 5 admission, 6 closure, 7 adjudication). Receipts: detached payload, ES256, low-S.
- Key custody (D8): packages and the operator's identity are kept; the one-use retirement of the Receipt and checkpoint keys is manual, by the operator, **after** the real capture and acceptance. The operator's local custody verification is reported as `ALL PASS` (operator-reported; not a chain execution). Nothing is deleted.

## 4. Capture format and runner contract

- Capture format: `spec/capture-format.md` `c8d8e71447cabd2e61ce46c2416c9d85c7844e6e8376c3e38919e5798f01935e` (candidate reason codes included).
- Runner contract, incl. §4a normative invocation: `verifier/runner/CONTRACT.md` `1ef9566a1073208f35b6ade9854b72d8c3fc4dcf1260d166fa9d7b545c7943b2`
- Validation record (r12–r18): `verifier/runner/VALIDATION.md` `d31d892ddf23b0dd2a7a662bcb2cc9f053633e065c0b02b09a67e40113e2da2f`
- Acceptance map: `spec/acceptance-runner-map.md` `c70d4ce956d2325bec4047369c9ba814c5171a51854850fb81bea87bcdbf0e8e`; mixed-log plan: `spec/mixed-log-test-plan.md` `f28540ec790ccaa3a5e2910680d6bb0dc07ede061e153fd30126083cacf0ac9c`.
- Normative offline invocation (`RUN.md`, checked in this revision): no `--no-offline`; no `--pinned` override; measured `network_isolated=true`; both executable pins present and matched; reviewed `PINNED_INPUTS.json`; `--out` outside the capture; the runner is followed by the checks listed in `RUN.md`. Anything else is a diagnostic run.

## 5. Reviewed source hashes

Runner: `s3c_verify.py` `7e6c457a6cc54e7a5c05610f80361201aa958022e44d8aa303a982ffbe95f628`; `s3c_chain.py` `de3450bbb1b6268773bbee9eb7bc2d5e86d2ad433d59985b8ccf05b56bd50494`; `PINNED_INPUTS.json` `3a1550f8230a70431ca8c7d4905db9d486b2ca7fc6cde1bbc66265ced7ec9912`.
Reused candidate TCB sources: `spike/host/preflight.py` `8b95eadbedc42ce53c303514962601fa6ae630da123208a0a9464bc8c2b83c5d`; `spike/glue/s3_spike_chain.py` `0f8a8788a6c67cf520ba80539817273517d982155ab555f45e2d71286f8f79ea`; `spike/s3-entry/src/main.rs` `a6bb33d4456ff86ac5c0d10d19f0afcfabe9c10a21ab4eef7371322bf2be4ec8`; `verifier/g5/src/lib.rs` `ab5634a8e30a3d10de49a30639559e389fedaf5e32d22f34ef8eb3d9d318692f`; `verifier/g5/src/main.rs` `c63b9bf9209aa2ce66511fe263fda65537cee7b27728afde759bb277666ec96d`; lock files `spike/s3-entry/Cargo.lock` `d0283512f34ae0c49de4b80b86e25f77ad58735b619dc34f43478d155fef11eb`, `verifier/g5/Cargo.lock` `1551158b9ed9969674b7d8c022c98ae339d5852d287dba81240baf651fbafe99`.
Facade and tooling source: commit `10638c239b27d7c87b238a6f387c95882162c4dc` (34 files, file-list digest `c360a25068c652b345b6325695cb16414b47afbe59c7b9ed0f3791992952a7d8`; `git diff --quiet` check in the definition manifest). "Reviewed" means: covered by the operator-reported external source review below and by the retained tests; **the formal TCB review of the glue remains pending (open item 6).**

## 6. Executable pins

`verifier/artifacts/s3-spike-entry` `53ba44408b1de7322010681f45bb4aa576931f0974c448d9e6b7a662683ca863`; `verifier/artifacts/s3-g5` `a2b4b1efeda26302ec5f0710905c46f7c180ad862035959d47ba1e33305ee0bd` (debug builds, supplied as the exact validated bytes; build record `verifier/artifacts/BUILD_RECORD.md` `a03760fbbddddc2f4b45fe7f0608b0543e8e2249a9ffb2f8518eee9b4ec3bb1e`). Identity pinning only: **no reproducible-compilation claim** (builds in different directories differed in the recorded experiment). Go binaries by recipe, from the facade source pin: facade `7c71d8615bc3d46152943e47bf0c7555bc310e93ba9f67b69fd7bfb9e3a0ec40`, capture `1ecde5e4bc10ad8587782f9ab74b070aed0665c800c261972bab5e69cc1fab4d`, keygen `fd829bd6e250b1c9294dd952d59bc1e7db2adaed9e028e41b2ee116c684e7532` (equal in two builds on one host; no broader claim). Toolchains: Rust 1.82.0 (a current runner prerequisite), Go 1.24.7, Lean `leanprover/lean4:v4.33.0` (hashes in `PINNED_INPUTS.json`).

## 7. Frozen upstream commits

S1 `e4db3747eaeeb1a07227bb9029f9a9c3b566cdb1` (`v0.1.0-s1-ratified`); S2a `741d56d36d7b2bfe2e9e0080a1cba4393e4a47da` (`v0.1.0-s2a-ratified`); S2b `8eaa91cad1ffa963158b365c6d0d7316f4965e89` (`v0.1.0-s2b-complete`). Tessera `v1.0.4` `6bca8e8d5e23c9941f2b8a08f512b373f7131730`. None is modified by anything in this repository.

## 8. The 13 OPEN items: proposed resolutions and retained limitations (adoption pending Ivan's approval; none is closed by this document)

| # | OPEN item | Proposed resolution | Retained limitation (explicit scope exclusion) |
|---|---|---|---|
| 1 | Non-target `sub` values (I2) | `urn:volmax:s3:policy-declaration`, `urn:volmax:s3:verification-material-declaration`, `urn:volmax:s3:operator-note`; `iss` `volmax-s3-operator` | Exercised with throwaway keys only; no P10 namespace rule is introduced or implied; the candidate key set has not been run |
| 2 | Bootstrap mechanism and index-0 content | Preconfigured declarations: issuer table supplied out of band, policy declaration at leaf 0 and verification-material declaration at leaf 1, both authenticated like any statement | Not RFC 9943 mechanism (b); declarations establish neither key authority nor policy enforcement; nothing reads them |
| 3 | TS implementation selection | Tessera v1.0.4 + the S3-owned facade at `10638c2` (issuer authentication, detached-payload transport) | Authentication only, not authorization; no claim of RFC 9943 Transparency Service status or SCRAPI compliance; no witnesses, rotation, X.509 or operator independence |
| 4 | Lifecycle sequence, capture format, provenance of `pB`/`inst`/`iB` | 8-leaf ML-2 layout; capture format as in `spec/capture-format.md`; `pB`/`inst` derived by `gen_config.py` for `volmax-owner`; toy `iB` and A12–A14 digests unchanged | Toy semantics only (no G4 inputs for a non-toy instance); key governance is the custody plan in D8; capture format stays a candidate |
| 5 | Form of the Rust entry | Keep the thin S3-owned entry over the unchanged pinned S2b crate, supplied as the exact validated bytes | No adoption of `p10-replay-cli`; no reproducible-compilation claim (builds in different directories differed in the recorded experiment); TCB review pending |
| 6 | S3-owned glue / correspondence checker | The candidate standalone runner and G5 as they are, with the recorded contract and validation | TCB review against the preregistration is not done; **TCB review of the glue is pending and explicit (an external source review reported by the operator at `fa0baf2`, recorded in `verifier/runner/VALIDATION.md` r18, is not that review): successful tests (including the static reuse-identity test) do not establish that the glue adds no rule;** G4 inputs for non-toy instances remain open |
| 7 | Toolchain carriage vs declared prerequisites | Declared host prerequisites verified by hash/version, not carried: Linux x86_64 with network namespaces, CPython 3.13, **Rust 1.82.0 (current preflight requirement)**, pinned Lean 4.33.0 with native `libuv` development library, clean S1/S2a/S2b | `libuv` is not covered by the frozen scripts; the runner is not yet usable from the package alone (expects the repository layout); other hosts untested |
| 8 | Reason codes; recorded-but-not-compared fields | Candidate G5/capture reason codes as in `spec/capture-format.md`; the recorded-but-not-compared set is the keys of `run-info.json` (the 17 top-level keys written by the current runner on a completed run: `capture`, `chain_info`, `commands`, `entry_binary_sha256`, `g5_binary_sha256`, `g5_output`, `host`, `input_sha256`, `isolation_test`, `launcher_claim_not_evidence`, `lean_bin_dir`, `network_isolated`, `problems`, `runner_source_sha256`, `seconds`, `started`, `tcb_source_mismatch`), while `verdict.json` is the canonical compared object | Code stability and review not decided; the field list is descriptive of the current runner (a failed run may write fewer keys), not a frozen schema |
| 9 | Receipt payload form | Detached payload, ES256, low-S, one key per capture | Attached form not exercised against the live facade (covered by fixtures C5/C6 by reference only); fixes the detached reason codes for Receipt-fault references (§7.4) |
| 10 | Adequacy of runner-control fixtures | The eight ratified propagation controls as already exercised; M8 through the chain stages | No new semantic corpus; adequacy for an adopted runner is not decided; M8 cannot be packaged as a capture |
| 11 | Python and OS pins | Declare the tested environment as supported (CPython 3.13.16, Linux 6.18 x86_64) and record, rather than enforce, the host in `run-info.json` | The runner does not refuse other versions; only one version and one kernel were tried |
| 12 | Mixed-log tests | ML-1, ML-2, ML-6 as executed, plus the 8-leaf qualification run with the real declaration payloads; ML-3–ML-5 stay optional and unbuilt | They say nothing about enforcement or a third-party TS; ML-3–ML-5 not built; the qualification used throwaway keys |
| 13 | Capture tooling with independent sources | Keep the existing separation: submission/Receipt/checkpoint retention by `s3-capture submit`, HTTP-only public export by `s3-capture export`, assembly from the retained sources | Independence from the facade's own code is not established (same repository, same operator); G5 test materialization still derives all files from one request |

Full table with supporting artifacts: `spec/open-items-resolution.md` `d2e719691803debfc20b6c2921ac9768cc4a885c23f3d20bb550037aa5cb383a`.

### Evidence supporting adoption (not a formal proof)

- **External source review (operator-reported).** The operator reported a review (ChatGPT) of the entry, G5, runner, preflight, glue and the frozen interfaces they call at `fa0baf2`, with the conclusion that the main data flow matches the documented separation: G5 checks packaging, the entry extracts the authenticated target, the glue passes real stage outputs to the frozen stages. Claude did not independently perform or verify this review, and it is not the pending TCB review.
- **Corrected infrastructure finding.** The review found that an `OSError` while copying an executable escaped without writing `verdict.json`. It was corrected (executable-copy failure and unexpected chain exceptions end as `S3-FAIL(infrastructure)`, exit 40, with a diagnostic; no P10 reason), covered by new fault tests (three fail on the pre-fix runner) and followed by two byte-identical offline runs of an existing anchored capture (`BINDING_MATCH`): `verifier/runner/evidence/fault-guard/`, `verifier/runner/VALIDATION.md` r18.
- Regression of the authenticating facade (`ts-prototype/evidence/auth-regression/`), one exploratory eight-leaf qualification run with throwaway keys through the public capture path, G5, the unchanged chain and the runner (`ts-prototype/evidence/qualification-auth-ml2/`), the runner validation records, and the operator-reported custody confirmation.
- These are tests and reviews, not a formal proof; passing them does not establish that the glue adds no rule, that the facade is RFC 9943 / SCRAPI compliant, or anything about the candidate key set, which has not been run.

## 9. Exact files proposed for freezing

`deployment/candidate/freeze-set.sha256` lists them (`sha256sum -c` from the repository root). 99 files; sha256 of that list file is recorded in the commit's `MANIFEST.sha256`. Companion files, deliberately not in the list because they carry the list or the hashes: `deployment/candidate/FREEZE_CANDIDATE.md` (this file), `deployment/candidate/freeze-set.sha256`, `MANIFEST.sha256`. The whole tree is also covered by `MANIFEST.sha256` (provenance only; it confers no normative authority).

| File | sha256 |
|---|---|
| `README.md` | `34f4aa9d5ad0d592a49c8b40732a7d4ff691dbc174736c027d6f040b364f3245` |
| `S3_PREREG_v0.1.md` | `1faf4841289e7e33b618ff96a52c9ff88d4940dc534a014096cec29e7578196b` |
| `deployment/README.md` | `8bc7daa8d386ca44195b5002545586221d6b66801dbc87fb4b9a8fc06b52df81` |
| `deployment/candidate/RUN.md` | `590f7ed2039acf02dcd2f301b31d4a620ee51ca1e6e6327722374b30ba8f936c` |
| `deployment/candidate/config/PUBLIC_META.json` | `1317859e9fd3fd2e5418a1109d72235b0144035d2e5f5ff3f7804e6e499e9f88` |
| `deployment/candidate/config/bootstrap/policy-declaration.json` | `c9ac82ddc94da80f87c68547e5ca84b0f0c98da80264614b8df9fb169818763e` |
| `deployment/candidate/config/bootstrap/verification-material-declaration.json` | `c09e60ab6d7f36107245e3f8d5fa272eb8859b3f64c4f9cd39f26eaec8f27e68` |
| `deployment/candidate/config/expect.json` | `cf03db9faa8051f4644b76911728e4b1becbb65eea7d39e956259bd9bcbbabd7` |
| `deployment/candidate/config/iB.json` | `62353069823aace3a91b37ffabcdf7b2d608134457276b2a5e597ebb49e0e824` |
| `deployment/candidate/config/inst.bin` | `7f38622b51abebfed5374c3aefd7ded77f169f04cf6e02c00ecdad4d39d6eaaf` |
| `deployment/candidate/config/pB.json` | `ac4895511c903e6836c471d197507793566f7d822c49aa5a02a6e0581e7a26ec` |
| `deployment/candidate/config/public/admitter-one.public.cose_key.cbor` | `d670cdd06104880626929398bb2bfad40103801a7ba156393ef9d1cac6172f62` |
| `deployment/candidate/config/public/admitter-two.public.cose_key.cbor` | `43e39148af008041703b0ab2f5cd86071e94b3bc1364d319bfff9a4ea8bd9ac1` |
| `deployment/candidate/config/public/intruder-x.public.cose_key.cbor` | `17b4ef8d400dc85b201f3ecf489a451e1216b155d88f601048ed67c29ef1f25d` |
| `deployment/candidate/config/public/issuers.json` | `e1fffa936136135da54c518328b55cb4915cf858dadd73860ff3c3f77d03d1ba` |
| `deployment/candidate/config/public/operator.public.cose_key.cbor` | `f7cae36222deeaccc01ed6cf2508d7d5f9e7d8e323c17ab2f3a70a264620a45e` |
| `deployment/candidate/config/public/ts.public.cose_key.cbor` | `6bc5b0ae47f8726379ffbfb0e0858fe10ef74ba5b8801edeba0b3d3b89944056` |
| `deployment/candidate/config/public/volmax-owner.public.cose_key.cbor` | `63759d03f57a34801b4405f54c6dd9a2ab6bf47e120fa8660f548e202dbce512` |
| `deployment/candidate/custody/README.md` | `69d3114ac8a5551022ae8c55d3295da0f08efad9c1142efdc82d8940968f42eb` |
| `deployment/candidate/custody/test_verify_custody.py` | `9fe3afbb76c755a4acdc116252ef822862e74ecd81351a3533e67fe3fb0eccdd` |
| `deployment/candidate/custody/transit-record.json` | `a9a99af66b343e7b2a6988edb2306ec4599431a666874d7372b1995dc47a28c3` |
| `deployment/candidate/custody/verify_custody.py` | `6e08b068050af3acf4176749c6102c39892f3be4a84ba206b52a741f283e072c` |
| `deployment/candidate/definition-manifest.json` | `c13a79013e91736a84eee4e6470d7fecc7e9f658198b1641c141e0bd998e7ff1` |
| `deployment/candidate/env.example.sh` | `1583d08265e8cf8b82be0fa2b4bd2be3163c5963016c101beec4ac724393c747` |
| `deployment/candidate/operator-staging/note.cose` | `7cd73a51bb2baaa7773cd2eaed2c99869598500f641c5d2905b316ec949979cb` |
| `deployment/make_definition.py` | `35841b4e3ac1493736a68d71f97ba5a5714143603ff0240bcc6de1ae2211aa35` |
| `spec/acceptance-runner-map.md` | `c70d4ce956d2325bec4047369c9ba814c5171a51854850fb81bea87bcdbf0e8e` |
| `spec/capture-format.md` | `c8d8e71447cabd2e61ce46c2416c9d85c7844e6e8376c3e38919e5798f01935e` |
| `spec/deployment-profile-evidence/build-repro.txt` | `f4a2460b4e997f22b098140c9a7dfd1889aa03432535976d9b039b79919fa8ae` |
| `spec/deployment-profile.md` | `8aafd3fb5ee7def671b5327262d7426af37c25f48b4bd4678813925fed328589` |
| `spec/mixed-log-test-plan.md` | `f28540ec790ccaa3a5e2910680d6bb0dc07ede061e153fd30126083cacf0ac9c` |
| `spec/open-items-resolution.md` | `d2e719691803debfc20b6c2921ac9768cc4a885c23f3d20bb550037aa5cb383a` |
| `spec/operator-record-receipt-key-retirement.md` | `312c6d16e4eb84b96f814db5daab12b14b48057317062fa3dfaef02bd70ae5d0` |
| `spec/registration-interface.md` | `a319211f6f81ccdab907b98c790193338264f4665782224a9544cf2364e13c05` |
| `spike/glue/s3_spike_chain.py` | `0f8a8788a6c67cf520ba80539817273517d982155ab555f45e2d71286f8f79ea` |
| `spike/host/preflight.py` | `8b95eadbedc42ce53c303514962601fa6ae630da123208a0a9464bc8c2b83c5d` |
| `spike/s3-entry/Cargo.lock` | `d0283512f34ae0c49de4b80b86e25f77ad58735b619dc34f43478d155fef11eb` |
| `spike/s3-entry/Cargo.toml` | `b729e1f4b1d9d1d785fd093dca02b89256ef02b598347c327bc430e0958d64b4` |
| `spike/s3-entry/rust-toolchain.toml` | `8e0c5bd6d955bff9fcb7d2028bc78d6cd5c66c74ea8586a9a56afe4c03939af4` |
| `spike/s3-entry/src/main.rs` | `a6bb33d4456ff86ac5c0d10d19f0afcfabe9c10a21ab4eef7371322bf2be4ec8` |
| `tests/offline/runner/README.md` | `4a1dd2a35a7eeb0d26a8369d420b1aa5654044515f6fe78cf1f9e900c0dedf1d` |
| `tests/offline/runner/materialize_control.py` | `150897854520998f36d732e74151edfd1d61bcd2e5fd87be91083cc187299579` |
| `tests/offline/runner/repro_defects.py` | `187401d56c8e6fcb2a7a8ca9d8416e051db789c34a7402b77f2193c458ae5e08` |
| `tests/offline/runner/run_validation.py` | `abfcd70f7c1a597c80cce455df017cd53737c6fa4948d15b2526063d1e82890d` |
| `tests/offline/runner/test_runner_faults.py` | `059c7785c2d119971910d90b8277948524dba81907bde96f72b8f6bd411ab8ae` |
| `tests/offline/runner/test_runner_static.py` | `acf54049f01630f2b0445b922aa6230818a5c60705cc9d390ec31f05e574b66f` |
| `tests/offline/runner/test_snapshot.py` | `4cf1fbd094554418361b441381dc375e3a9830f5383ea45a7a781c315a32fc3c` |
| `tests/offline/runner/test_stages.py` | `a656e72784906b939c4f87861f1bdd594b37f7c7ed9502c8fbfb19e49d1f8b84` |
| `ts-prototype/cmd/s3-capture/main.go` | `b571efdbe7470b290b85c0b4ae32deda6b94d129f0fc88add32daa76dac0dfef` |
| `ts-prototype/cmd/s3-facade/main.go` | `cac6f93a1a5efb58b9858c90ca4581b5d0b85be7842f913bed8403bc607255e0` |
| `ts-prototype/cmd/s3-keygen/main.go` | `5b02c0b3dd321e132853863346ed011c9bffffa7d744aacc3e8f56d11d4d4943` |
| `ts-prototype/go.mod` | `ab9ff6caf92ce5a2ffc18cf502e10059a4c199e90c1d6a33f8614af7dc17d2be` |
| `ts-prototype/go.sum` | `c8fe14a25be4e0ef57a9f01abc6020528614cea3dd1b29fc5ea1ac6a308cb593` |
| `ts-prototype/internal/admit/admit.go` | `f2439b558d61b827bbeeae95eb31864904474a21be9d745f9890306da9b1cfea` |
| `ts-prototype/internal/admit/admit_test.go` | `f686a21864dfa8773af8fd1ff15447f3e7ac513b95eabe92b5510a7bae341d6f` |
| `ts-prototype/internal/capture/capture.go` | `e7c56dbc44dd1647f37a953743033e762a12bb7cf1ad84bdbf1055b007459914` |
| `ts-prototype/internal/cborx/cborx.go` | `12aafd884a43aeedf7d83438f634f707602edfc6f7b82ab1728a6984d618c7d9` |
| `ts-prototype/internal/cborx/cborx_test.go` | `e8938494d857cb5cb515a0fd08214c63cc4090c25fb870b71a327756ea431927` |
| `ts-prototype/internal/facade/facade.go` | `00a35c4e93f436a5b69b08aa86ae844ac198b547c57901f0c0d6cde02076f549` |
| `ts-prototype/internal/issuerauth/issuerauth.go` | `e7713e2d12bab9248500e00dd8a37c014097eb79c771dfd90bd6805b8aa7293a` |
| `ts-prototype/internal/issuerauth/issuerauth_test.go` | `1c27e3c9178c5704c0dac10b239ad2c0e91e105501193eb489e67b6bf954af21` |
| `ts-prototype/internal/leafenc/leafenc.go` | `a6580867a1f039a2c987e353de8a3cda9f41351efc579864ec55dec4568ca275` |
| `ts-prototype/internal/leafenc/leafenc_test.go` | `e4f719f27f70aeaa4f45adb3ab5816fe05f3eff7011a9a73ba9dd688914d3d96` |
| `ts-prototype/internal/publicread/publicread.go` | `fa7ef642930e915f85e1d352bc6a132aed66708c8b4e9d591cb0da357fd6e623` |
| `ts-prototype/internal/receipt/receipt.go` | `7c297929258a0c75c50097d0b3fa28d9243b631f3771a759261f3471319a1d9d` |
| `ts-prototype/internal/receipt/receipt_test.go` | `96fbfd4bb2843f94cb1703e142a8f79d7e3e616b3b9466e03a803a4e14f5e075` |
| `ts-prototype/producer/README.md` | `a2b3256bfba455346efe1d338d1a7b7b2ebecbae20cd996086a02d13134fa17d` |
| `ts-prototype/producer/gen_config.py` | `555b195528d2277ff93c1a15e379d77f9f9816aa41c0e9d166d51b2857ed7a20` |
| `ts-prototype/producer/issuer_tool.py` | `eff89d1c13c705a16e315af52e60e523ab3ac0dc6800709d5231c851079ded71` |
| `ts-prototype/producer/operator_note.py` | `6f87bf9b4e131c6151376d0039b5f5fcde576794a180e37a24145366e0842191` |
| `ts-prototype/scripts/assemble_capture_v2.py` | `7b62e198da840c511d050c2f652de69be71469d96e5dd3c57ed2b85cd516a68f` |
| `ts-prototype/scripts/derive_expected_tb.py` | `11586882eedc0ca991a02f0602396d710de74193e8b66613824396c816aebb14` |
| `ts-prototype/scripts/derive_expected_tb_from_prefix.py` | `a77b7597439137869bec528125528b80ec91b5c061a7da947d1c00e9c0e11c7d` |
| `ts-prototype/scripts/facade_tests.py` | `651e448848e8f9d3e39decccd076e8dfbf94797787d902fa7b392692736220e3` |
| `ts-prototype/scripts/make_detached_variant.py` | `39f6bbbb711a854a5e906dc467f0b188117f40286a1d138baa021f0bc91e8ec2` |
| `ts-prototype/scripts/producer_index_record.py` | `9c577e42fd53be80093d5b0037eeb04be94eb8fcb37b823f4f167ac34bc6a13f` |
| `ts-prototype/scripts/run_exploratory.sh` | `0e44f7eab82d93b2f578fe950359ca6fb66b53819cee97942692f6ccf2e844a6` |
| `ts-prototype/scripts/run_lifecycle.sh` | `3f48e866a45d83b27c62956c29532f0a4af9e6ecd0af395c266a6c4954b05bfe` |
| `ts-prototype/scripts/s3check.py` | `5703c2a8b0195e21cd742986ce478ce5c6ea7efb962a1ef11515121be654847d` |
| `ts-prototype/scripts/s3check_mutations.py` | `c7d6671b35223c361d5c575e6962292d6a613536cda2a155b3a4a87abbc1fc1b` |
| `ts-prototype/scripts/stall_proxy.py` | `cf4f46cbc0843cb1a21bdc1f0dcfcf5311c4eee39ad73c80b2baa55f79f1d6ca` |
| `ts-prototype/scripts/timeout_tests.py` | `c74648a2473a783aff406f0946e23fab225d0c68765d5c87f8fbe1d5fc070616` |
| `verifier/artifacts/BUILD_RECORD.md` | `a03760fbbddddc2f4b45fe7f0608b0543e8e2249a9ffb2f8518eee9b4ec3bb1e` |
| `verifier/artifacts/SHA256SUMS` | `5eac291cc7f800c7df4c2d367c90dab6288228887941052f17f30e46820ee5f8` |
| `verifier/artifacts/s3-g5` | `a2b4b1efeda26302ec5f0710905c46f7c180ad862035959d47ba1e33305ee0bd` |
| `verifier/artifacts/s3-spike-entry` | `53ba44408b1de7322010681f45bb4aa576931f0974c448d9e6b7a662683ca863` |
| `verifier/g5/Cargo.lock` | `1551158b9ed9969674b7d8c022c98ae339d5852d287dba81240baf651fbafe99` |
| `verifier/g5/Cargo.toml` | `fd7e2a49fc96a26a745c096e8e221cc8c0d811c1b3797c4d1db48230de6b9eff` |
| `verifier/g5/README.md` | `b343ad23ab4a1cf9423e237a3c25fab245462874460256e438785344e25ca86f` |
| `verifier/g5/rust-toolchain.toml` | `8e0c5bd6d955bff9fcb7d2028bc78d6cd5c66c74ea8586a9a56afe4c03939af4` |
| `verifier/g5/src/lib.rs` | `ab5634a8e30a3d10de49a30639559e389fedaf5e32d22f34ef8eb3d9d318692f` |
| `verifier/g5/src/main.rs` | `c63b9bf9209aa2ce66511fe263fda65537cee7b27728afde759bb277666ec96d` |
| `verifier/runner/CONTRACT.md` | `1ef9566a1073208f35b6ade9854b72d8c3fc4dcf1260d166fa9d7b545c7943b2` |
| `verifier/runner/PINNED_INPUTS.json` | `3a1550f8230a70431ca8c7d4905db9d486b2ca7fc6cde1bbc66265ced7ec9912` |
| `verifier/runner/README.md` | `8601b4dbe89f13dbce319efe9ae07b7b074dd5d8c481b4feff48b606b5d8829c` |
| `verifier/runner/VALIDATION.md` | `d31d892ddf23b0dd2a7a662bcb2cc9f053633e065c0b02b09a67e40113e2da2f` |
| `verifier/runner/pin_tcb.py` | `70882046c9865399c2ce3051979d6e7a06710f09d6dee1f80e653a0be4671474` |
| `verifier/runner/s3c_chain.py` | `de3450bbb1b6268773bbee9eb7bc2d5e86d2ad433d59985b8ccf05b56bd50494` |
| `verifier/runner/s3c_verify.py` | `7e6c457a6cc54e7a5c05610f80361201aa958022e44d8aa303a982ffbe95f628` |

## 10. After the freeze (not done here)

Ivan freezes with his own key. Then, and only then, the real S3-B capture runs with the candidate key set through `deployment/candidate/RUN.md`, the anchor is committed by the operator before verification, the runner is run under the reviewed offline invocation, and, after successful acceptance, the operator manually retires the one-use keys (`spec/operator-record-receipt-key-retirement.md`). Nothing in this paragraph has happened.
