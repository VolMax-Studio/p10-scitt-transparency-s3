# p10-scitt-transparency-s3

P10 S3 — SCITT Transparency Service Deployment and Offline Capture Verification.

**Status: candidate preparation only.** Nothing here is ratified, frozen, signed, or verified. See `S3_PREREG_v0.1.md` (draft).

## Layers

- **S3-A — deployment definition.** What a P10-compatible Transparency Service instance is: frozen `LeafEncodeV0`, VDS 1 (`RFC9162_SHA256`), fixed Receipt key, frozen bootstrap and registration policy, exact full-prefix export.
- **S3-B — live capture.** A one-time live event: register exact Signed Statements sequentially, retain the original Receipts, export `[0,n)`, freeze the capture. Not required to reproduce identical bytes when repeated.
- **S3-C — offline acceptance.** The unchanged frozen chain (`S2b -> S2a -> post-S2a checks`) run over the frozen capture with public material only, offline. This is the byte-reproducible part.

## RFC 9943 compliance vs. P10 S3 compatibility

These are different properties.

- **RFC 9943 compliance** concerns the SCITT Transparency Service behavior. RFC 9943 permits a VDS that stores only hashes/metadata.
- **P10 S3 compatibility** is stricter and profile-specific: the leaf function is the P10 `LeafEncodeV0` wrapper, and the TS must export the exact full `[0,n)` Statement bytes.

A service can be fully RFC 9943-compliant and still not be P10 S3-compatible. S3 makes no claim about arbitrary RFC 9943 services, and no claim of independence between issuer and operator.

## Layout

```
S3_PREREG_v0.1.md   draft preregistration
spec/               deployment profile, registration policy, capture format (planned)
ts/                 TS deployment (planned)
capture/            frozen live capture (planned)
vectors/            committed vectors (planned)
verifier/           runner for the frozen chain (planned)
tests/{live,offline,mutations}/
MANIFEST.sha256
```
