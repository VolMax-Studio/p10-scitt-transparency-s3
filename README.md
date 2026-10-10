# p10-scitt-transparency-s3

**P10 Transparency Log Deployment and Offline Capture Verification (S3).**

This repository implements and records one complete, bounded flow. A transparency-log deployment (a Go facade over [Tessera](https://github.com/transparency-dev/tessera) with issuer-authenticated registration) registers a fixed set of Signed Statements, and a **public-interface capture** keeps the original Receipts and the exact exported log prefix. The capture is then replayed **offline** through the **unchanged frozen P10 chain** (S2b decode and replay, the pinned S2a runner, the existing post-S2a orchestration) with public material only. The accepted result is a byte-reproducible `verdict.json` with outcome `BINDING_MATCH`.

Scope: a declared **toy profile**, a single operator, a pinned toolchain. See [What this does not claim](#what-this-does-not-claim).

## Status

| | State |
|---|---|
| **S3-A** — deployment definition | **Frozen** by the operator's signed tag `v0.1.0-s3a-frozen` (the 99-file set `deployment/candidate/freeze-set.sha256`). |
| **S3-B** capture and **S3-C** `BINDING_MATCH` | **Accepted** by the operator's signed tag `v0.1.0-s3-accepted` (capture-index SHA-256 `2662c2da…00a7`, runner-verdict SHA-256 `6368022f…db22`). |
| Reproduction on the operator's HP | The accepted verdict was **reproduced offline on the operator's HP**, first with the offline package's verification command and later through the Replay Workbench (byte-identical `verdict.json` both times). This is a reproduction, not a new acceptance, and not an independent audit. |
| Replay Workbench **v0.3.1** | Local application that runs the unchanged wrapper and runner. Reviewed, tested and exercised on the HP. The final UI checks (launcher, saved paths, module screen, earlier-job banner after refresh) are **operator-reported**. |
| Key retirement | **Not done and not claimed.** It is a separate manual decision of the operator. |

## Signed decisions

The decisions are the operator's. They are recorded as **signed Git tags**, which are Git objects of their own and therefore do not appear as separate commits in the file listing. Implementation commits in this repository were produced with Claude Code (see [Roles](#project-roles)); they record implementation work, not decisions.

| Decision | Signed tag | Tag object | Target commit | Signed (UTC) |
|---|---|---|---|---|
| Freeze of the S3-A definition | [`v0.1.0-s3a-frozen`](https://github.com/VolMax-Studio/p10-scitt-transparency-s3/releases/tag/v0.1.0-s3a-frozen) | `8f0c97f3745131f79936dec71ebe09316332f5ab` | [`7c3b2d4b919c356a566f8f5d3628d4f546e41afa`](https://github.com/VolMax-Studio/p10-scitt-transparency-s3/commit/7c3b2d4b919c356a566f8f5d3628d4f546e41afa) | 2026-10-08 19:08 |
| Acceptance of the S3-B capture and recorded S3-C result | [`v0.1.0-s3-accepted`](https://github.com/VolMax-Studio/p10-scitt-transparency-s3/releases/tag/v0.1.0-s3-accepted) | `4148a7403e8d5ed0a30ca878d617323bb3a75b3a` | [`5acc277a13dc122e39fcb5f9f3e646b06cc95009`](https://github.com/VolMax-Studio/p10-scitt-transparency-s3/commit/5acc277a13dc122e39fcb5f9f3e646b06cc95009) | 2026-10-08 19:22 |

Tagger: `VolMax-Studio <volmax.core@gmail.com>`; the tag messages are signed "Ivan Nestorov". The acceptance tag also names the capture-and-anchor commit [`149953c29780e566b0b23f7a1b975dc93349daf2`](https://github.com/VolMax-Studio/p10-scitt-transparency-s3/commit/149953c29780e566b0b23f7a1b975dc93349daf2). The freeze tag states that **no key deletion is authorized by the freeze**; the acceptance tag states that **no key deletion is performed or attested by its signature** and that execution occurred in the recorded container environment, so it **does not claim an independent host rerun**.

**Verify the signatures yourself.** The tags are SSH-signed. A signature is only as meaningful as the public key you check it against, so obtain the operator's **public** signing key from the operator through a channel you trust (a key taken only from this repository would prove nothing more than self-consistency). Put it in an allowed-signers file (`<principal> namespaces="git" <public key>`), then:

```bash
git clone https://github.com/VolMax-Studio/p10-scitt-transparency-s3.git && cd p10-scitt-transparency-s3
git fetch --tags
for t in v0.1.0-s3a-frozen v0.1.0-s3-accepted; do
  git -c gpg.ssh.allowedSignersFile=/path/to/allowed_signers verify-tag "$t"
  git rev-parse "$t" "$t^{commit}"          # tag object and target commit, compare with the table above
done
```

Without that file Git can only show that a signature block is present. The GitHub release pages linked above are a convenience; the local check is the authoritative one. The offline package and the Workbench perform the same optional check when given `ALLOWED_SIGNERS`.

## Evidence

Acceptance, later reproductions and UI checks are different things; they are kept apart on purpose.

**Acceptance (the operator's signed decision rests on these records)**

| Record | What it is |
|---|---|
| [`ts-prototype/evidence/s3b-capture/RESULT.md`](ts-prototype/evidence/s3b-capture/RESULT.md) | The S3-B capture and S3-C verification result record: freeze check, anchor, G5, unchanged chain, standalone runner (`BINDING_MATCH` at `post-s2a`, A1–A15 hold), acceptance conditions and hashes. It reports results; the acceptance is the signed tag. |
| [`ts-prototype/evidence/s3b-capture/REPRODUCIBILITY.md`](ts-prototype/evidence/s3b-capture/REPRODUCIBILITY.md) | A second offline replay of the same capture in the same environment: byte-identical `verdict.json`. |

**Later reproductions (additional evidence; they accept nothing new)**

| Record | What it is |
|---|---|
| [`packaging/offline-package/VALIDATION-hp-replay.md`](packaging/offline-package/VALIDATION-hp-replay.md) | Reproduction on a second host, the operator's HP, with the runner records and the terminal transcript stored unmodified. Not an independent operator audit. |
| [`packaging/offline-package/VALIDATION.md`](packaging/offline-package/VALIDATION.md), [`VALIDATION-rev2.md`](packaging/offline-package/VALIDATION-rev2.md) | Validation of the portable offline package and of its revised wrapper. |
| [`apps/replay-workbench/evidence/hp-20261009/`](apps/replay-workbench/evidence/hp-20261009/NOTES.md) | Two report archives exported from the Workbench on the HP (v0.1.3): one run blocked at readiness by the host's namespace policy (the wrapper was not started), one run `COMPLETED` with `BINDING_MATCH` and reproduction `MATCH` for the accepted verdict. |

**Application checks (the Workbench UI, not the S3 result)**

| Record | What it is |
|---|---|
| [`apps/replay-workbench/`](apps/replay-workbench/README.md) | Application source, tests, [`CHANGELOG.md`](apps/replay-workbench/CHANGELOG.md) and per-version `evidence/` (cloud-container test runs, browser checks, integration runs). Cloud checks are not HP runs. |
| [`evidence/v0.2.0/HP_OPERATOR_REPORT.md`](apps/replay-workbench/evidence/v0.2.0/HP_OPERATOR_REPORT.md), [`evidence/v0.3.1/HP_OPERATOR_REPORT.md`](apps/replay-workbench/evidence/v0.3.1/HP_OPERATOR_REPORT.md) | **Operator-reported** confirmation on the HP of the launcher, the saved host paths, the module screen and the earlier-job banner after a refresh. No transcript or screenshot of those UI checks is stored. |

## Quick start

**Offline package (accepted capture, no network, no private keys).** [`packaging/offline-package/README_PACKAGE.md`](packaging/offline-package/README_PACKAGE.md) describes the portable package and its single command, `LEAN_BIN=/path/to/lean/bin ./verify_offline.sh`, which checks prerequisites and integrity first, runs the unchanged runner, and only afterwards compares its `verdict.json` byte for byte with the accepted verdicts. `packaging/offline-package/make_offline_package.sh` builds the package from local checkouts of the pinned repositories (its paths are those of the original build machine). The approved revision for the Workbench is `p10-s3-offline-e56d3ea-rev2.tar.gz`, **SHA-256 `e19f8d84cac0ecb2de61dbd0e7085014d525829ba51007b7fdaa24895df37d9b`**. **This repository does not host or distribute that archive**, and no public download is asserted here; the operator holds the approved copy. Anyone else can rebuild a package from the sources and compare, but a rebuilt archive is a different file unless its hash matches.

**Replay Workbench (local web interface around the same package).**

```bash
python3 apps/replay-workbench/run.py            # opens http://127.0.0.1:<free port>/#token=… in your browser
python3 apps/replay-workbench/run.py --install-launcher   # optional user-level desktop entry; --remove-launcher removes it
```

Details, screens, limitations and the HP instructions: [`apps/replay-workbench/README.md`](apps/replay-workbench/README.md). It runs the package's unchanged `verify_offline.sh` and runner and shows three separate results (application execution, P10 outcome, reproduction of the accepted result); it verifies nothing itself.

**Runtime prerequisites (declared, not carried by the package).** Linux x86_64; unprivileged network namespaces (`unshare -n`, or `-rn`, which some Ubuntu configurations restrict by policy; the Workbench reports this as a host-setup problem and does not change host policy); Python 3.12 or newer for the Workbench (the runner uses only the standard library; its preflight notes CPython 3.12.3 for the S2b oracle); `git`, `sha256sum`, `cmp`, `tar`, `bash`; **Rust 1.82.0** (selected by `spike/s3-entry/rust-toolchain.toml`); a C toolchain with libuv (`cc … -luv`); the pinned **Lean 4.33.0** toolchain (`lean`, `lake`, `libleanshared`) checked by the runner's preflight against the S1/S2a manifests. The first replay on a host builds Lean helpers and is slower and more memory-hungry.

## Layers

- **S3-A — deployment definition.** What a P10-compatible transparency-log instance is: frozen `LeafEncodeV0`, VDS 1 (`RFC9162_SHA256`), fixed Receipt key, frozen bootstrap and registration policy, empty unprotected header on every leaf, exact full-prefix export. Frozen by `v0.1.0-s3a-frozen`.
- **S3-B — live capture.** A one-time live event: register exact Signed Statements sequentially, retain the original Receipts, export `[0,n)`, assemble `request.cbor`, freeze the capture. Not required to reproduce identical bytes when repeated. Accepted by `v0.1.0-s3-accepted`.
- **S3-C — offline acceptance.** The unchanged frozen chain (S2b `decode_request` → `replay_p0_p9` → `tB` → pinned S2a runner → existing post-S2a orchestration) run over the frozen capture with public material only, offline, in the declared pinned environment. This is the byte-reproducible part. Its traced path and S3-owned glue are described in [`spec/acceptance-runner-map.md`](spec/acceptance-runner-map.md). S1, S2a and S2b are stages of this chain, not separate products of this repository.

## What this does not claim

- **RFC 9943 / SCRAPI:** compliance with RFC 9943 concerns the SCITT Transparency Service behavior (it permits a VDS that stores only hashes or metadata). **P10 S3 compatibility** is stricter and profile-specific: the leaf function is the P10 `LeafEncodeV0` wrapper and the TS must export the exact full `[0,n)` Statement bytes. A service can be fully RFC 9943-compliant and still not be P10 S3-compatible. S3 makes **no claim of full RFC 9943 or SCRAPI compliance**, none about arbitrary RFC 9943 services, and no claim that the live TS enforced the declared Registration Policy (the frozen chain authenticates policy-statement bytes as prefix members but does not verify their signatures or payload semantics).
- **Operators:** the same operator ran the log, the facade, the issuer table and every key, before and after (the **same-operator limitation**). No independence between issuer and operator, and no independent-operator validation, is claimed. Reproductions on a second host were run by the same operator.
- **Scope:** the declared **toy profile**, the frozen limitations and the declared runtime only. `BINDING_MATCH` concerns the authenticated capture and the frozen chain; it is not evidence of scientific truth or policy enforcement.
- **Proofs:** the entry, runner, glue and G5 were accepted as the declared TCB on the basis of recorded source review and validation; no formal proof of the glue is claimed.
- **Keys:** no key was retired by any record here. The private keys and the encrypted custody packages are outside the repository; retirement (see the operator-record template in `spec/`) remains a separate manual decision.

## Repository map

```
S3_PREREG_v0.1.md                    preregistration (revision r19), part of the frozen set
MANIFEST.sha256                      provenance listing of repository files (no normative authority)
spec/                                acceptance-runner-map, deployment-profile, registration-interface, capture-format, open-items resolutions,
                                     mixed-log test plan, operator-record template for key retirement (a template; nothing has been retired)
deployment/candidate/                the frozen S3-A definition: freeze-set.sha256, FREEZE_CANDIDATE.md, RUN.md, public configuration,
                                     bootstrap declarations, pins, custody records (no private keys)
ts-prototype/                        the Go facade over Tessera v1.0.4 (issuer authentication), HTTP-only capture client, tests, results
ts-prototype/evidence/s3b-capture/   the accepted capture, ANCHOR.sha256, RESULT.md, REPRODUCIBILITY.md and the runner records (runner/, runner-2/)
verifier/runner/                     the standalone S3-C runner (contract, pinned inputs, code)
verifier/g5/                         the G5 capture-correspondence checker
verifier/artifacts/                  exact entry and G5 binaries with their build record
spike/                               feasibility spike, reused by the runner as pinned glue; the host preflight lives here
ts-selection/                        transparency-service selection pass (recommendation, probe, procedure dry run)
tests/offline/                       offline test tooling and executed evidence (G5, mixed-log ML-1, runner validation)
packaging/offline-package/           the portable offline package: wrapper, builder, validation records, HP replay record and evidence
apps/replay-workbench/               the Replay Workbench: source, tests, ARCHITECTURE.md, README, CHANGELOG, evidence/, APP_MANIFEST.sha256
capture/  ts/  vectors/  tests/live/ empty placeholders (.gitkeep); the capture lives under ts-prototype/evidence/s3b-capture/
```

Several documents inside the frozen set were written before the freeze and still say "candidate", "proposal" or "nothing adopted". They are preserved unchanged on purpose: **the signed tags, not those words, record the adoption and the acceptance.**

## The frozen set and this README

`deployment/candidate/freeze-set.sha256` lists the 99 files of the S3-A definition, and **this `README.md` is one of them**. The README you are reading was rewritten after the acceptance to describe the finished project, so it **differs from the historical README** that the signed tags contain; the historical version is preserved at the tags (`git show v0.1.0-s3a-frozen:README.md`). Nothing else changed: `freeze-set.sha256`, the tags, the preregistration, the accepted evidence and all other frozen files are untouched, and the `README.md` line of `MANIFEST.sha256` is the only manifest line updated.

Consequently, `sha256sum -c deployment/candidate/freeze-set.sha256` run at the current branch reports `README.md: FAILED` and the other **98** frozen files OK; the full **99 of 99** check holds in a checkout of the frozen tag. Both results were verified when this README was updated (in a separate checkout of `v0.1.0-s3a-frozen`, and on the updated branch). The offline package and the Workbench run that check against their own copy of the repository at the pinned commit `e56d3ea8bbe14c9c88a0dde339c29b55b1032a66`, where all 99 files match, so this documentation update does not affect them.

## Project roles

- **Ivan Nestorov** — project author, operator and **final ratifier**. The freeze and the acceptance are his decisions, recorded as the signed tags above.
- **Claude Code** — implementation assistance (code, tests, packaging, the Replay Workbench, documentation drafts). Commit metadata in this repository shows the implementation commits as authored by "Claude"; they are implementation records, are not re-attributed, and carry no decision authority.
- **ChatGPT / Sol** — architecture and review assistance.

Nothing here is an independent validation, and no co-author trailer or authorship has been added or altered for presentation.

## Feasibility spike

`spike/` is a non-normative feasibility spike (experimental entry and glue, host script, a test-key fixture, executed evidence). Parts of it are reused by the runner as pinned glue and are covered by the frozen set; the spike as such is not the S3 acceptance runner. See `spike/README.md` and `spike/FEASIBILITY_REPORT.md`.
