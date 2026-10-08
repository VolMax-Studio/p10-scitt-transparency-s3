# P10 Transparency Log Deployment and Offline Capture Verification — candidate deployment definition (decision-ready; selected for review, not adopted)

Status: **Adopted decisions: none.** The operator (Ivan) directed that the choices below be prepared as the candidate deployment definition. They remain proposals until he explicitly authorizes the deployment-definition freeze; this document does not ratify, freeze, sign, tag, merge or release anything, and normative S3-B has not started. "Evidence" means executed, retained outputs of this repository (exploratory runs, not acceptance evidence) unless stated otherwise. Machine-readable form: `deployment/candidate/definition-manifest.json`; exact commands: `deployment/candidate/RUN.md`.

This revision supersedes the r14 text of this file (commit `9213446`) where they differ. Corrections made since then: the bootstrap is described as preconfigured declarations (not as an unchecked first registration, and not as RFC 9943 mechanism (b)); the facade now authenticates issuers, so the earlier statement that it does not is withdrawn for builds from `10638c2` on; Rust 1.82.0 is listed as a current runner prerequisite; the Go build claim is narrowed to the recorded experiment; the anchor is labelled as an operator-generated record; Receipt-key retirement no longer claims to prove anything; no third-party validator is required.

## 1. Decision table

| # | Choice | Candidate (selected for review) | Status |
|---|---|---|---|
| D1 | Log engine | Tessera `v1.0.4` (`6bca8e8d5e23c9941f2b8a08f512b373f7131730`), POSIX storage, antispam off, no witnesses | candidate; not adopted |
| D2 | Facade | `ts-prototype/` at source pin `10638c239b27d7c87b238a6f387c95882162c4dc`, with issuer authentication (§2) | candidate; not adopted |
| D3 | Bootstrap mechanism | Preconfigured deployment declarations: the issuer table is operator configuration supplied out of band; two declaration statements are published as leaves 0 and 1 | candidate; not adopted |
| D4 | Bootstrap content | The two payloads in `deployment/candidate/config/bootstrap/` (§3) | candidate; not adopted |
| D5 | Non-target subjects | `urn:volmax:s3:policy-declaration`, `urn:volmax:s3:verification-material-declaration`, `urn:volmax:s3:operator-note` | candidate; exercised once with throwaway keys |
| D6 | Layout | 8 leaves: 0 policy declaration, 1 verification-material declaration, 2 profile, 3 operator note, 4 instance, 5 admission, 6 closure, 7 adjudication | candidate; exercised once |
| D7 | Instance material | `volmax-owner`, fresh keys, unchanged toy `iB` and A12–A14 digests | candidate; not adopted |
| D8 | Keys | Fresh set per §5; issuer keys archived offline under the operator's custody; Receipt and checkpoint keys: **one use — manual retirement by the operator after successful capture and acceptance** (selected plan; nothing executed) | candidate; custody handoff prepared, awaiting the operator's confirmation |
| D9 | Receipts | Detached payload, ES256, low-S, one key for the whole capture | candidate; not adopted |
| D10 | Runtime prerequisites | Declared host prerequisites, verified by the runner's preflight (§7) | candidate; not adopted |
| D11 | Executables | Entry and G5 supplied as the exact validated bytes with a build record; Go binaries by recipe | candidate; not adopted |
| D12 | Anchor | Operator-generated record committed before verification (§9) | candidate; not adopted |
| D13 | Acceptance contract | §10 | candidate; not adopted |

## 2. D1/D2 — Engine and facade, including issuer authentication

- **Candidate.** Tessera v1.0.4 behind the S3-owned facade. Facade configuration: entry limit 65535, batch 1:10ms, checkpoint interval 200ms, publish timeout 30s, fetch timeout 10s, detached-payload limit 1 MiB; registration and public read on separate listeners; registration serialized; a Receipt only after a published, signature- and origin-verified checkpoint covers the entry.
- **Issuer authentication (new, `10638c2`).** Interface and rules were written first (`spec/registration-interface.md`, commit `77c31b2`). Every submitted statement is verified before any append, `intent` journal record, duplicate answer or Receipt: ES256 over the COSE `Sig_structure` built from the submitted protected-header bytes and the exact signed payload, against the key preconfigured for the statement's `iss` in the issuer table (`--issuers`, mandatory); protected labels limited to 1, 3, 4, 15; `kid`, if present, must equal the configured key's thumbprint; unknown issuers, other algorithms, unsupported labels and bad signatures are refused. A statement with a null payload needs its signed payload as a separate request part (used for verification only, never logged); the registered bytes and `LeafEncodeV0` input are unchanged.
- **Trust source.** The issuer table is operator configuration supplied out of band, including the operator key that signs the declaration statements. Statements in the log, the declarations included, are never read by the facade.
- **Evidence.** Unit tests, facade tests T1–T8, chaos (30 statements, 47 external SIGKILLs, each statement exactly once and in order), public-read timeouts — all PASS from the pinned source (`ts-prototype/evidence/auth-regression/`); one eight-leaf qualification run through the public capture path, prototype checks F0–F8, G5, the unchanged chain and the candidate runner (`ts-prototype/evidence/qualification-auth-ml2/`).
- **Limits.** This is authentication, not authorization: any configured issuer may register any statement. No payload parsing, no P10 semantic checks, no witnesses, no rotation, no X.509, no operator independence (one operator holds the log, facade, table and every key). Chaos and regression runs are SIGKILL-class only (no power loss or fsync faults). **No claim of RFC 9943 or SCRAPI compliance is made.** The title and target sentence now speak of a "P10 transparency log" and state that the deployment is not claimed to be an RFC 9943 Transparency Service or SCRAPI-compliant; the non-claims stand.

## 3. D3/D4 — Bootstrap: preconfigured declarations published as leaves 0 and 1

- **Mechanism.** RFC 9943 permits a preconfigured Registration Policy and trust anchors. Here the preconfiguration is the facade's issuer table. Publishing two declaration statements as the first leaves keeps `[0,n)` a complete SCITT statement sequence that carries the declarations; preconfiguration itself does not make the prefix incomplete. The two statements are registered through the facade like any other statement, i.e. **authenticated** against the operator key in the issuer table; this is not "a first policy statement registered without registration checks".
- **Policy declaration** (`policy-declaration.json`, SHA-256 `c9ac82ddc94da80f87c68547e5ca84b0f0c98da80264614b8df9fb169818763e`) states: structural admission rules; ES256 issuer authentication against the preconfigured table and its label limits; handling of detached payloads; size limits (leaf input 65535 bytes, statement 65474 bytes, detached payload 1 MiB); duplicate handling (byte-identical statements are registered once, a resubmission is authenticated again and returns the original index and stored Receipt); one writer, sequential registration; Receipt issuance conditions. Its `not_done` list: no authorization of issuers for subjects or statement types, no payload parsing or P10 semantic check, no Registration Policy beyond the stated rules, no witnesses/rotation/X.509, no operator independence, no RFC 9943 / SCRAPI claim.
- **Verification-material declaration** (`verification-material-declaration.json`, SHA-256 `c09e60ab6d7f36107245e3f8d5fa272eb8859b3f64c4f9cd39f26eaec8f27e68`) lists, separately: the **Receipt key** (role, `ts_iss`, thumbprint, COSE_Key hex) and the **checkpoint key** (origin, note verifier key) — these are not issuer keys — and the **declared issuer keys** (`volmax-owner`, `admitter-one`, `admitter-two`, `volmax-s3-operator`, each with role, thumbprint and COSE_Key hex). `intruder-x` is not registered anywhere in the facade.
- **What the logged declarations do not do.** They are published bytes. They establish neither key authority nor policy enforcement; nothing reads them. The sources of authority are the preconfigured issuer table (for registration) and the profile artifact's `key_resolution` (for the frozen chain), both committed outside the log.
- **Evidence.** Both payloads were generated by the pinned `gen_config.py`, signed by the operator key and registered by the facade in the qualification run (with throwaway keys); the chain read them only as classifiable non-target rows.
- **Limits.** The candidate payloads have not been registered with the candidate key set. Alternatives not chosen: a single declaration; a log without declaration leaves (then the declarations would live only outside the log).

## 4. D5/D6/D7 — Subjects, layout, instance material

- **Subjects.** The three `urn:volmax:s3:*` strings above and `iss` `volmax-s3-operator` for the operator's statements. They are valid UTF-8, not byte-equal to the instance subject, and satisfy the frozen readability conditions. **Evidence:** exercised in the qualification run (no unreadable row; subject observations at indices 2, 4, 5, 6, 7 only, so 0, 1 and 3 are non-subject). **Limit:** the candidate-key run has not happened.
- **Layout.** ML-2: the operator note after the profile shifts later indices by one (ordinal ≠ returned index). Evidence: run3 and the qualification run (pre-verification record: nine checks true). Limit: one divergence, no concurrent writers.
- **Instance material.** Owner `volmax-owner`; `pB`, `inst`, subject and `LogIdentityV0` derived by `gen_config.py` from the fresh configuration; the toy `iB` (`62353069823aace3a91b37ffabcdf7b2d608134457276b2a5e597ebb49e0e824`) and the A12–A14 digests are unchanged. The strict S2a decoder and the unchanged chain accepted generated configurations with `volmax-owner` in the qualification run.

## 5. D8 — Keys and custody

- **Candidate key set** (generated fresh, never used in any run, outside the repository): instance owner, admitter-one, admitter-two, intruder-x (appears in `pB.key_resolution` only), operator, Receipt key (ES256, separate directory the issuer tooling cannot read), checkpoint (note) key (Ed25519). Only COSE public keys, thumbprints and the note verifier key are committed.
- **Custody.** Issuer keys (owner, admitters, intruder-x, operator): archived **offline outside the repository under the operator's custody**; this document performs and plans no destruction of them. The Receipt key and the checkpoint key: used for one capture, then retired by the operator (below).
- **Custody handoff (prepared; awaiting the operator).** The operator supplied the public age recipient `age10j748jfyazq8qk2yfnapmd4z80kcf5e09u47eg5n30vjgc7ju30qyn7hcj` (generated locally by him; no identity was seen by Claude). Two separate packages were produced by streaming `tar | age` with no plaintext archive: `issuer-archive.tar.age` (issuer keys) and `one-use-receipt-checkpoint.tar.age` (Receipt key, checkpoint signing key, public verifier key). Hashes and file inventory, without secret content: `deployment/candidate/custody/transit-record.json`. The local check `deployment/candidate/custody/verify_custody.py` decrypts into a private temporary directory and prints only package hashes, public fingerprints and PASS/FAIL. **Nothing is deleted** until the operator confirms successful local decryption and matching public fingerprints.
- **Copies that exist now** (inventory for the retirement record): (1) plaintext originals in the session container, `/home/user/s3-custody/`; (2) the encrypted transit packages in the session container, `/home/user/s3-custody-transit/`; (3) the encrypted packages as delivered to the operator, and every copy he makes of them; (4) the operator's decrypted copies, if any. The regression and qualification runs used other, throwaway keys (not part of this set).
- **Selected plan: one-use retirement.** No further registrations are planned under this log identity. After successful capture and acceptance, **the operator manually** stops the service and removes every known copy of the Receipt and checkpoint private keys, including the encrypted transit packages, their decrypted copies and the container plaintext, and fills `spec/operator-record-receipt-key-retirement.md` (template; nothing has been done). Issuer-archive packages are not retired by this step.
- **Limits, stated plainly.** The record is self-attested; it does not prove that no copy survives (backups, snapshots, copy-on-write storage, unknown copies, the encrypted packages and whoever holds the age identity); it does not undo anything signed earlier (a Receipt signed before retirement and never published would still verify); it is not a cryptographic proof of non-equivocation; it adds no operator independence. It reduces the opportunity for later signing under the assumption of complete removal.

## 6. D9 — Receipts

Detached payload (the frozen S2b form, RFC 9942's recommended form), ES256, low-S, one key for the whole capture, original Receipts retained (I8). Evidence: Go-issued Receipt equals the ratified S2b-tooling Receipt except for the signature (unit test); F5 on 7- and 8-leaf runs. Limits: the attached form was not exercised against the live facade; randomized ECDSA means `request.cbor` differs between runs while verdicts do not.

## 7. D10 — Runtime prerequisites for the candidate runner (current state)

| Prerequisite | Candidate requirement | Evidence / limit |
|---|---|---|
| OS | Linux x86_64 with unprivileged network namespaces (`unshare -n`/`-rn`); isolation measured in the stage process | tested on Linux 6.18 only |
| Python | CPython 3.13, standard library only for the runner | tested on 3.13.16 only; recorded, not pinned |
| Rust | **1.82.0** — a current runner prerequisite: the preflight requires `rustc -V`, run in `spike/s3-entry`, to report 1.82.0 even though only the supplied binaries are executed | enforced by `spike/host/preflight.py` |
| Lean/Lake | pinned conda-forge `lean4 4.33.0`, hashes in `PINNED_INPUTS.json`; native `libuv` development library for the Lean link step | used in all validation runs; `libuv` not covered by the frozen scripts |
| Checkouts | S1 `e4db3747…`, S2a `741d56d3…`, S2b `8eaa91ca…` clean | checked by preflight |
| Layout | the runner expects the repository layout (`spike/`, `verifier/g5` sources) | not yet runnable from the package alone |
| Go, `cbor2`, `cryptography` | S3-B tooling and test harness only | — |
| Network | allowed in preparation only; disabled in S3-C | enforced and recorded by the runner |

## 8. D11 — Executables

- **Entry and G5:** supplied as the exact validated bytes in `verifier/artifacts/` (`s3-spike-entry` `53ba44408b1de7322010681f45bb4aa576931f0974c448d9e6b7a662683ca863`, `s3-g5` `a2b4b1efeda26302ec5f0710905c46f7c180ad862035959d47ba1e33305ee0bd`; debug profile) with `BUILD_RECORD.md` (commands, toolchain, source hashes, build layout). The runner refuses any other bytes. No reproducible-compilation claim: in the recorded experiment (`spec/deployment-profile-evidence/build-repro.txt`) a clean rebuild of the entry crate in the same directory was identical, and builds in two different directories differed (cause not investigated). These two artifacts were not rebuilt for the record.
- **Go binaries:** recipe `CGO_ENABLED=0 go build -trimpath -buildvcs=false ./cmd/...` (go1.24.7). In the recorded experiment, two builds of the earlier facade in different directories were byte-identical, and the builds from the pinned source made for the regression and qualification runs gave the same hashes (facade `7c71d8615bc3d46152943e47bf0c7555bc310e93ba9f67b69fd7bfb9e3a0ec40`, capture `1ecde5e4bc10ad8587782f9ab74b070aed0665c800c261972bab5e69cc1fab4d`, keygen `fd829bd6e250b1c9294dd952d59bc1e7db2adaed9e028e41b2ee116c684e7532`). That is the evidence: two builds on one host; no broader claim.

## 9. D12 — Anchor

The anchor (SHA-256 of `capture.json`) is committed by the operator before the prototype checks, G5, the chain or the runner run. It is an **operator-generated record** in the operator's repository and session: it fixes what was verified, not who generated it, and it is not an independent channel. No third-party validator is required by this candidate; an additional independent recording remains optional.

## 10. D13 — Proposed acceptance contract

1. **Acceptance event.** The pinned runner, in the declared environment, over the frozen capture and its recorded anchor, with `--out` separate from the capture, exits 0 with `verdict.json` `outcome = BINDING_MATCH`. Exit 11 (REJECT) and 12 (HALT) are frozen-chain outcomes and are not acceptance; 30 and 40 are failures of the run, not verdicts about the capture.
2. **Reproducibility.** Two runs give byte-identical `verdict.json`; `run-info.json` is incidental.
3. **Negative controls.** The ratified propagation controls and the packaging cases (`tests/offline/runner/`) reproduce their recorded expectations; expectations stay in the harness.
4. **Preconditions.** Pinned inputs and executables match `PINNED_INPUTS.json`; the S1/S2a/S2b trees are clean at their pins; isolation is measured.
5. **Non-claims** of the preregistration §2 apply unchanged, in particular: the TS-side policy is not claimed to be enforced beyond the stated issuer authentication, and no operator independence is claimed.

## 11. Resolved public configuration (candidate key set; values depend on the exact keys)

| Item | Value |
|---|---|
| Owner `iss` / operator `iss` | `volmax-owner` / `volmax-s3-operator` |
| Receipt issuer (`ts_iss`, placeholder host) / origin | `https://ts.example/volmax-s3` / `volmax-s3/ts` |
| Instance subject | `p10s2sub:0fe1be115beb770330930911e69e4f2026c80809c64ada16e87fe63e7f9150d2` |
| `LogIdentityV0` digest | `6a510bcf3a122ae9af2714939d60a6a4e997ff9751836024dd480ebd60cd37c9` |
| Profile digest (`pB`) | `ac4895511c903e6836c471d197507793566f7d822c49aa5a02a6e0581e7a26ec` |
| Receipt key thumbprint | `6bc5b0ae47f8726379ffbfb0e0858fe10ef74ba5b8801edeba0b3d3b89944056` |
| Checkpoint verifier key | `volmax-s3/ts+50425c42+ASw9Mfm5hEfaIJgQ06LI7FHWIyKZb0wvk/uli2w4MiRt` |
| Issuer key thumbprints | owner `63759d03f57a34801b4405f54c6dd9a2ab6bf47e120fa8660f548e202dbce512`; admitter-one `d670cdd06104880626929398bb2bfad40103801a7ba156393ef9d1cac6172f62`; admitter-two `43e39148af008041703b0ab2f5cd86071e94b3bc1364d319bfff9a4ea8bd9ac1`; operator `f7cae36222deeaccc01ed6cf2508d7d5f9e7d8e323c17ab2f3a70a264620a45e`; intruder-x (profile only) `17b4ef8d400dc85b201f3ecf489a451e1216b155d88f601048ed67c29ef1f25d` |
| Policy declaration / verification-material declaration / issuer table SHA-256 | `c9ac82ddc94da80f87c68547e5ca84b0f0c98da80264614b8df9fb169818763e` / `c09e60ab6d7f36107245e3f8d5fa272eb8859b3f64c4f9cd39f26eaec8f27e68` / `e1fffa936136135da54c518328b55cb4915cf858dadd73860ff3c3f77d03d1ba` |
| Unchanged frozen inputs | `iB` `62353069823aace3a91b37ffabcdf7b2d608134457276b2a5e597ebb49e0e824`; codec `c156965f810643b115b6bbe720c87e874522bfff298490713be5874677346dd9`; capability proof `9482c3f775e78a72dd9b8290c67a59bf00716ac0adb86d5b7b0d8eb4045a4928`; proof `30f498438473d39566d951b75dd5ce7326d9c368da3cda4868635a3e422a8696`; verifier manifest `f8380b19b43334925e7f7621e1f7d7912f36c789199d3f8d069b87f5ea176d46` |
| Files | `deployment/candidate/config/`, `operator-staging/note.cose`, hashes in `definition-manifest.json` (checked by the `install` phase) |

## 12. Pins

S1 `e4db3747eaeeb1a07227bb9029f9a9c3b566cdb1`; S2a `741d56d36d7b2bfe2e9e0080a1cba4393e4a47da`; S2b `8eaa91cad1ffa963158b365c6d0d7316f4965e89`; Lean `leanprover/lean4:v4.33.0` (hashes in the manifest); Rust 1.82.0; Go 1.24.7; Tessera `v1.0.4` `6bca8e8d5e23c9941f2b8a08f512b373f7131730`; facade and tooling source `10638c239b27d7c87b238a6f387c95882162c4dc` (34 files, file-list digest `c360a25068c652b345b6325695cb16414b47afbe59c7b9ed0f3791992952a7d8`; check recorded in the manifest); runner sources `s3c_verify.py` `2abec1f4c22c32174f96519ab8f1650a420d7f13847418e4bb1f443df1724d14`, `s3c_chain.py` `de3450bbb1b6268773bbee9eb7bc2d5e86d2ad433d59985b8ccf05b56bd50494`, `PINNED_INPUTS.json` `3a1550f8230a70431ca8c7d4905db9d486b2ca7fc6cde1bbc66265ced7ec9912`; executables as in §8.

## 13. Capture-and-verification command

`deployment/candidate/RUN.md` fixes it: `install` → `capture` (stops at `ANCHOR.sha256`) → operator commits the anchor → `verify` → `s3c_verify.py`. The same sequence ran once, exploratory, with throwaway keys: `ts-prototype/evidence/qualification-auth-ml2/` (F0–F8 OK, G5 PASS, unchanged chain PASS, runner `BINDING_MATCH`). It has **not** been run with the candidate key set, and normative S3-B must not start before the operator explicitly authorizes the freeze.

## 14. What remains before any freeze (not done here)

The operator's actions: confirm local decryption and matching fingerprints of the custody packages, supply the ChatGPT wording of the target sentence (the preregistration carries a drafted sentence flagged as such), and authorize the freeze; the one-use retirement is executed manually by the operator after acceptance. Then: re-review of the definition against `RUN.md`; the live lifecycle once with the candidate keys; checks, G5 and the runner; anchor commit. Open preregistration items addressed by this candidate but **not closed**: 1, 2, 3, 4, 6, 7, 9, 11.

## 15. Evidence index

`spec/registration-interface.md`; `ts-prototype/RESULTS.md` §G; `ts-prototype/evidence/auth-regression/`; `ts-prototype/evidence/qualification-auth-ml2/QUALIFICATION.md`; `deployment/`; `verifier/artifacts/`; `verifier/runner/{CONTRACT,VALIDATION}.md`; `spec/deployment-profile-evidence/build-repro.txt`; `spec/operator-record-receipt-key-retirement.md`.
