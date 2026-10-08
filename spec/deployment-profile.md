# Candidate deployment profile (decision-ready; proposals only)

Status: **PROPOSALS FOR THE FINAL REVIEW. Adopted decisions: none.** Nothing here is ratified, frozen, signed, tagged or released, and no item of this document closes an OPEN item of `S3_PREREG_v0.1.md` by itself. Each row separates the **proposal** from the **evidence** behind it and the **limits** of that evidence. "Evidence" means executed, retained outputs of this repository (exploratory runs, not acceptance evidence) unless it says "document". Every choice marked *needs the reviewer* has a real alternative that I could not rank on evidence alone.

Baseline: repository at the commit that adds this file; frozen S1 `e4db3747…`, S2a `741d56d3…`, S2b `8eaa91ca…` (proposed pins, unchanged); candidate runner `verifier/runner/` (r14).

## 0. Decision table

| # | Choice | Proposal | Status |
|---|---|---|---|
| D1 | Log engine | Tessera `v1.0.4` (`6bca8e8d5e23c9941f2b8a08f512b373f7131730`), POSIX storage, antispam off, no witnesses | proposed |
| D2 | Facade and its configuration | S3-owned facade `ts-prototype/` at one pinned commit; configuration in §2 | proposed |
| D3 | Bootstrap mechanism | RFC 9943 option (b): two statements registered first without registration checks, operator-submitted | proposed; *needs the reviewer* |
| D4 | Bootstrap content | Short real texts that state exactly what is and is not enforced (§3) | proposed; *needs the reviewer* |
| D5 | Non-target subjects | `urn:volmax:s3:registration-policy`, `urn:volmax:s3:trust-anchors`, `urn:volmax:s3:operator-note` | proposed; one re-run implied |
| D6 | Lifecycle layout | Run3 layout (8 leaves: policy, trust anchors, profile, operator note, instance, admission, closure, adjudication) | proposed; *needs the reviewer* |
| D7 | Instance profile material | `volmax-owner`, new `pB`/`inst` derived by `gen_config.py`, unchanged toy `iB` and A12–A14 | proposed |
| D8 | Keys and custody | Fresh keys per §5; public material and thumbprints only in the repository | proposed; custody after the capture *needs the reviewer* |
| D9 | Receipts | Detached payload (frozen S2b form), ES256, low-S, one key for the whole capture | proposed |
| D10 | Runtime prerequisites | Declared host prerequisites verified by hash, not carried in the package (§7) | proposed |
| D11 | Executables | Pin the identity of the built artifacts; build recipe documented; Go is reproducible, Rust is not directory-independent (§8) | proposed |
| D12 | Anchor channel | Anchor committed before verification, plus an independent recording of the same value (§9) | *needs the reviewer* |
| D13 | Acceptance contract | §10 | proposed |

## 1. D1 — Log engine

- **Proposal.** Tessera `v1.0.4` at the commit above; Go module graph fixed by the facade's `go.mod`/`go.sum`; POSIX storage; antispam off; no witnesses; single writer, single process.
- **Evidence.** `ts-selection/RECOMMENDATION.md` (document + executed probe: roots and inclusion paths equal the S2b helpers; 5- and 7-entry export byte-equal to `LeafEncodeV0`); facade tests T1–T7, 115 random kills and 5 targeted ones with no violation (`ts-prototype/RESULTS.md` §A).
- **Limits.** No power-loss/fsync/disk-full faults; no operator independence; no witnesses; O(n) start-up scan; not an RFC 9943 / SCRAPI compliance claim. The emulator candidate was read, not executed, and is unsupported on four needed capabilities (document).
- **Alternative.** A different engine would restart the selection pass; not recommended.

## 2. D2 — Facade configuration (values used in the exploratory runs)

Entry limit 65535 (statement ≤ 65474); batch 1 entry / 10 ms; checkpoint interval 200 ms; publish timeout 30 s; fetch timeout 10 s; registration endpoint and public read endpoint on separate listeners; the public listener serves checkpoint, hash tiles and entry bundles only. Registration is serialized; a Receipt is issued only after a published, signature- and origin-verified checkpoint covers the entry and the reconstructed root matches.

- **Evidence.** `evidence/lifecycle-run2/run-config.json`, `lifecycle-run3-ml2/run-config.json`; timeout defect found and fixed (`RESULTS.md` §D, before/after retained).
- **Limits.** The facade does not verify issuer signatures and enforces no policy (structure only). Retries inside a producer-driven run and concurrent writers were not exercised beyond T5/T7.
- **To fix at adoption:** the facade commit (the exploratory runs used `0905dfb`, `f50e7aa`; the next capture needs its own pin), the Go toolchain version (1.24.7 observed), and `go.sum`.

## 3. D3/D4 — Bootstrap

- **Proposal D3.** Mechanism (b): leaf 0 = Registration Policy statement, leaf 1 = trust-anchor statement, both submitted by the operator through the facade without registration checks, signed by an operator key that is in no `key_resolution` table. Leaf 0 is therefore the policy; the policy active for every later P10 statement is derivable from the prefix (it is the last policy statement before it, i.e. leaf 0 for all).
- **Proposal D4.** The policy payload is a short UTF-8 text that states the facts of this deployment: (1) structural admission only, (2) issuer signatures are **not** verified by the TS, (3) no policy is enforced by the TS, (4) single operator, one fixed Receipt key, (5) the instance limit. The trust-anchor payload lists the public thumbprints of the Receipt key and the Tessera note key (the keys a verifier needs to check Receipts and checkpoints) and the issuer keys' thumbprints as *declared, unenforced*. Both payloads and their SHA-256 are recorded in the deployment definition before S3-B.
- **Why this form.** A policy text that overclaimed (e.g. "only admitted issuers may register") would be false for this facade. Stating the non-enforcement keeps the prefix consistent with non-claim 1.
- **Evidence.** Bootstrap by (b) with synthetic TEST statements at leaves 0–1 was executed three times through the unchanged chain (run2, run3, detached-closure: `BINDING_MATCH`); nothing in the chain reads their payloads.
- **Limits.** The real payload texts have not been run; only their structure (valid tagged `COSE_Sign1`, empty unprotected header, UTF-8 `iss`/`sub`) matters to the chain, so a re-run with them is a formality but is still a run. The payloads are not machine-interpreted by anything.
- **Alternatives.** (a) preconfigured policy with no leaf (breaks I1: `[0,n)` would not be a complete mixed sequence); (c) out-of-band management (nothing for the verifier to check). A single policy statement without a trust-anchor leaf is possible; I1 and RFC 9943 treat both as statements, so I propose both.

## 4. D5/D6 — Non-target subjects and layout

- **Proposal D5.** `sub` values `urn:volmax:s3:registration-policy`, `urn:volmax:s3:trust-anchors`, `urn:volmax:s3:operator-note`; `iss` of the bootstrap and note statements `https://ts.example/volmax-s3-operator` (placeholder host, as in the runs). They are valid UTF-8, not byte-equal to the instance subject (`p10s2sub:<64 hex>`), and use no `p10s2sub:` prefix. Exploratory runs used `urn:volmax:s3-test:*`; the proposal drops `-test` for the committed capture because the statements are no longer test statements.
- **Evidence.** Frozen readability conditions are satisfied identically by any such value (I2, document); the chain recorded the bootstrap and note leaves as non-subject rows in run3 (rows 0 and 3 named in the S2b output).
- **Limit.** The exact new strings have not been executed; a re-run is required before adoption.
- **Proposal D6.** The 8-leaf run3 layout. It exercises the producer ordinal ≠ returned-index separation with one operator insert; run2 (7 leaves) is the simpler alternative. *Needs the reviewer:* whether the committed capture should include the operator insert (more realistic mixed log, one more leaf) or not (smaller).
- **Evidence.** run3: F0–F8 OK; chain `BINDING_MATCH`, A1–A15 `match`, exact `tB`; pre-verification record with nine true checks. **Limit.** One divergence only; no concurrent writers.

## 5. D7/D8 — Instance material and keys

- **D7 proposal.** Instance issuer `volmax-owner` (I10), with `pB`, `inst`, subject and `LogIdentityV0` derived by `gen_config.py` from the fresh public configuration; `iB` and A12–A14 digests unchanged (toy semantics). **Evidence.** Two fresh configurations (`s3-owner-run2`, `s3-owner-run3`) were accepted by the strict S2a `pB` decoder and the unchanged chain, which settles the open question in prereg §5 for generated configurations; the `volmax-owner` name itself was accepted in the spike (feasibility). **Limit.** `volmax-owner` with the final configuration has not been run through this exact pipeline.
- **D8 proposal.** Fresh keys per role, none reused from any exploratory run: instance owner, admitter-one, admitter-two, intruder-x, operator/policy key, Receipt key (ES256, separate directory the issuer tool cannot read), Tessera note key (Ed25519, `s3-keygen`). Generated outside the repository with mode 0600; only COSE public keys, RFC 9679 thumbprints and the note verifier key are committed. A thumbprint sanity check against all committed fixtures is repeated.
- **Evidence.** run2/run3 practice and the issuer tool's refusal to run when the Receipt key is reachable; I11.
- **Limits.** One operator holds every key: there is no key independence, no HSM, no rotation (I7 fixes one Receipt key for the interval). *Needs the reviewer:* custody after the capture — destroy the private keys once the capture is frozen (nothing later needs them; supports "no rotation") or archive them offline (allows regenerating negative material).

## 6. D9 — Receipts

- **Proposal.** Detached payload, ES256 with low-S, one stable key (thumbprint in `LogIdentityV0`), original Receipts retained (I8). This fixes the Receipt-fault reason codes to the detached references (prereg OPEN item 9, §7.4).
- **Evidence.** Go-issued Receipt equals the ratified S2b-tooling Receipt in every byte except the signature (unit test); verified in F5 for 7 and 8 registrations; chain verdicts independent of signature randomness. Detached form is RFC 9942's recommended form (document).
- **Limits.** Attached form for the live TS was not exercised (fixtures C5/C6 cover both forms by reference). Randomized ECDSA: `request.cbor` differs between runs; verdicts do not.

## 7. D10 — Runtime prerequisites for S3-C

Proposal: **declared host prerequisites verified by hash**, not carried in the package (toolchains are large and already hash-pinned by the frozen manifests).

| Prerequisite | Proposed requirement | Evidence / limit |
|---|---|---|
| OS | Linux x86_64 with unprivileged network namespaces (`unshare -n` or `-rn`); isolation is measured in the stage process | tested: Linux 6.18 container only; other kernels/OS unverified |
| Python | CPython 3.13, standard library only | tested: 3.13.16 only; no other version tried |
| Lean/Lake | pinned conda-forge `lean4 4.33.0`, hashes as in S1/S2a manifests (`spike/PINS.json`) | used in all validation runs |
| Native lib | `libuv` development library for the Lean link step | found during the spike; not covered by the frozen scripts (OPEN item 7) |
| Rust | 1.82.0 (selected by `rust-toolchain.toml`); needed only to build the entry and G5, not to run S3-C if the pinned binaries are supplied | tested |
| S1/S2a/S2b checkouts | at the proposed pins (S2b `8eaa91c`; the public tag `v0.1.1-s2b-public` differs only in licence/docs files) | document + `git diff --name-status` |
| Network | allowed in preparation only; disabled in S3-C | enforced and recorded by the runner |
| Go, `cbor2`, `cryptography` | not required for S3-C (S3-B and the test harness only) | — |

*Needs the reviewer:* whether an unsupported Python/OS is refused by the runner (strict) or merely recorded (current behaviour: recorded, not pinned).

## 8. D11 — Executable production and pinning

- **Observation (this pass, `spec/deployment-profile-evidence/build-repro.txt`).** Go facade and capture client, `CGO_ENABLED=0 -trimpath -buildvcs=false`: byte-identical when built in two different directories. Rust entry and G5, `--locked`: byte-identical on a clean rebuild in the same directory, but **different** when built in two directories, in debug and release, and still different with `--remap-path-prefix` (cause not investigated). The two crates also require the S2b checkout at the relative path `../.deps/s2b`.
- **Proposal.** (1) Go components: record a build recipe (toolchain version, `go.sum`, flags above) and the resulting hashes; a verifier may rebuild and compare. (2) Rust entry and G5: ship or record the exact built artifacts and pin them by SHA-256 in `PINNED_INPUTS.json` (`executables`, already enforced by the runner); document the build command and directory layout; make **no** reproducible-compilation claim. (3) Keep the profile that was validated (debug) rather than switching to release, which would need a revalidation; *needs the reviewer* if release is preferred.
- **Limits.** Identity pinning proves "these bytes ran", not "these bytes come from these sources"; a reader who rebuilds in another directory will get different bytes and must compare behaviour, not hashes. Single host, single pass; Rust 1.82.0 only.

## 9. D12 — Anchor channel

- **Observation.** The anchors in the exploratory runs were committed before verification in the same repository and session (a timestamped record, not an independent channel).
- **Proposal.** For the committed capture: commit the anchor before G5 and the chain, and also record the same SHA-256 through a channel outside this repository's authors (for example a signed tag or an entry made by a second person). This document does not sign or tag anything. *Needs the reviewer:* which channel and who. Without it the anchor remains self-attested.

## 10. D13 — Proposed acceptance contract

Candidate wording (proposal; the runner `verifier/runner/CONTRACT.md` already implements the mechanics):

1. **Acceptance event.** A run of the pinned runner commit, in the declared environment, over the frozen capture and its recorded anchor, with `--out` separate from the capture, produces exit 0 and `verdict.json` `outcome = BINDING_MATCH`. Exit 11 (REJECT) and 12 (HALT) are frozen-chain outcomes and are **not** acceptance; 30 (packaging) and 40 (infrastructure) are failures of the run, not verdicts about the capture.
2. **Reproducibility.** Two runs give byte-identical `verdict.json`; `run-info.json` is incidental and not compared.
3. **Negative controls.** The eight ratified propagation controls and the packaging cases (`tests/offline/runner/`) reproduce their recorded expectations, with expectations kept in the harness only.
4. **Preconditions.** Pinned inputs and executables match `PINNED_INPUTS.json`; the S1/S2a/S2b trees are clean at their pins; network isolation is measured, not claimed.
5. **Non-claims** of the preregistration §2 apply unchanged; in particular the TS-side policy is not claimed to be enforced and no operator independence is claimed.
- **Evidence.** Candidate runner validation (`verifier/runner/VALIDATION.md`: 3 captures twice, 8 controls, 34 packaging cases, r13 defect record, r14 path guard).
- **Limits.** Exploratory captures, not the frozen one; the transcript/instance-decode classification (infrastructure) is a candidate pending your decision, which this review endorsed provisionally.

## 11. What remains before any freeze (not done here)

Pin the facade commit; decide D3, D4, D6, D8-custody, D11-profile, D12; generate fresh keys; register the real bootstrap texts and run the live lifecycle once under the pinned configuration; re-run the checks, G5 and the runner; record the anchor; only then could a freeze be considered, by a separate decision. Open items 1, 2, 3, 4, 6, 7, 9, 11 of the preregistration are addressed by proposals above but are **not closed**.

## 12. Evidence index

`ts-prototype/RESULTS.md`; `ts-prototype/evidence/lifecycle-run2`, `lifecycle-run3-ml2`, `exploratory-ml1-detached-closure-corrected`; `ts-selection/RECOMMENDATION.md`; `spike/PINS.json`; `verifier/runner/{CONTRACT,VALIDATION}.md` and `evidence/`; `spec/deployment-profile-evidence/build-repro.txt`.
