# p10-scitt-transparency-s3

P10 S3 — SCITT Transparency Service Deployment and Offline Capture Verification.

**Status: candidate preparation only.** Nothing here is ratified, frozen, signed, or verified. See `S3_PREREG_v0.1.md` (draft, revision r7). Manifest coverage (`MANIFEST.sha256`) is provenance only and confers no normative authority.

## Layers

- **S3-A — deployment definition.** What a P10-compatible Transparency Service instance is: frozen `LeafEncodeV0`, VDS 1 (`RFC9162_SHA256`), fixed Receipt key, frozen bootstrap and registration policy, empty unprotected header on every leaf, exact full-prefix export.
- **S3-B — live capture.** A one-time live event: register exact Signed Statements sequentially, retain the original Receipts, export `[0,n)`, assemble `request.cbor`, freeze the capture. Not required to reproduce identical bytes when repeated.
- **S3-C — offline acceptance.** The unchanged frozen chain (S2b `decode_request` → `replay_p0_p9` → `tB` → pinned S2a runner → existing post-S2a orchestration) run over the frozen capture with public material only, offline, in the declared pinned environment. This is the byte-reproducible part. Its traced path and S3-owned glue are described in `spec/acceptance-runner-map.md`.

## RFC 9943 compliance vs. P10 S3 compatibility

These are different properties.

- **RFC 9943 compliance** concerns the SCITT Transparency Service behavior. RFC 9943 permits a VDS that stores only hashes/metadata.
- **P10 S3 compatibility** is stricter and profile-specific: the leaf function is the P10 `LeafEncodeV0` wrapper, and the TS must export the exact full `[0,n)` Statement bytes.

A service can be fully RFC 9943-compliant and still not be P10 S3-compatible. S3 makes no claim about arbitrary RFC 9943 services, no claim of independence between issuer and operator, and no claim that the live TS enforced the declared Registration Policy (the frozen chain authenticates policy-statement bytes as prefix members but does not verify their signatures or payload semantics).

## Feasibility spike

`spike/` is a non-normative feasibility spike (experimental entry and glue, host script, a test-key fixture, executed evidence). It is not the S3 acceptance runner and is not adopted by the preregistration. See `spike/README.md` and `spike/FEASIBILITY_REPORT.md`.

## Layout

```
S3_PREREG_v0.1.md   draft preregistration (r7)
spec/               acceptance-runner-map.md, capture-format.md, mixed-log-test-plan.md, CLOSURE_REPORT_OPEN_1_4_6.md; planned: deployment profile, registration policy
ts/                 TS deployment (planned)
capture/            frozen live capture (planned)
vectors/            committed vectors (planned)
verifier/g5/        candidate G5 capture-correspondence checker (candidate code, not adopted); pinned inputs and the rest of the runner: planned
spike/              non-normative feasibility spike
ts-selection/       non-normative TS selection pass: recommendation, probe, procedure dry run, evidence
ts-prototype/       non-normative candidate Go facade over Tessera v1.0.4, HTTP-only capture client, tests, results, evidence
tests/{live,offline,mutations}/   tests/offline/g5/ holds G5 test tooling, a test capture and executed evidence; tests/offline/ml/ the mixed-log test ML-1
MANIFEST.sha256
```
