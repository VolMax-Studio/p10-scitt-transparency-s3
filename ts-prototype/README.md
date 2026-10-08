# ts-prototype: candidate Go facade over Tessera v1.0.4 (non-normative)

Prototype implementation authorized as a **candidate** only. Nothing here is ratified, frozen or adopted; TS selection (prereg OPEN item 3) and the
bootstrap, glue, G5 and acceptance path remain OPEN. The facade is not a SCRAPI-compliant Transparency Service and makes no RFC 9943 compliance claim.

Pinned log engine: `github.com/transparency-dev/tessera` `v1.0.4` = `6bca8e8d5e23c9941f2b8a08f512b373f7131730`, POSIX storage, antispam **off**, no witnesses.

| Path | Role |
|---|---|
| `cmd/s3-facade` | registration endpoint (`POST /register`, `GET /config`) and, on a **separate listener**, the static public read endpoint (checkpoint, hash tiles, entry bundles only) |
| `cmd/s3-capture` | capture client: `submit` (issuer/operator side) and `export` (public HTTP only; takes no storage path and no submission files) |
| `cmd/s3-keygen` | generates the Tessera checkpoint (note) key pair; the secret key stays outside the repository |
| `internal/facade` | registration flow, persistent duplicate prevention, checkpoint verification, Receipt issuance, state |
| `internal/issuerauth` | preconfigured issuer table, ES256 verification of the COSE Sig_structure, detached-payload form check |
| `internal/admit`, `internal/leafenc`, `internal/receipt`, `internal/cborx` | structural admission, LeafEncodeV0, COSE Receipt (ES256, detached payload), minimal CBOR |
| `internal/capture`, `internal/publicread` | HTTP-only log reader with verification; read-only whitelist handler |
| `producer/` | fresh public configuration generator and runtime issuer tooling (`gen_config.py`, `issuer_tool.py`; see its README) |
| `scripts/` | independent Python checks and tests (`s3check.py`, `facade_tests.py`, `s3check_mutations.py`), capture assembly, exploratory run driver |
| `evidence/` | executed outputs (raw; do not edit) |

## Registration flow

structural admission (`E_*` codes) -> `len(LeafEncodeV0(statement)) <= 65535` (statement <= 65474) -> **issuer authentication** (ES256 against the preconfigured issuer table, `--issuers`; a statement with a null payload needs its signed payload as a separate request part; see `../spec/registration-interface.md`) -> duplicate check -> Tessera append ->
wait for a **published** checkpoint covering the entry -> verify its note signature (pinned key, expected origin) -> inclusion proof from the public
tiles for exactly that checkpoint's size -> reconstructed root must equal the checkpoint root, public entry bundle must hold the submitted bytes ->
issue the COSE Receipt over that root (one stable ES256 key, detached payload) -> persist Receipt and the original signed checkpoint -> respond.

Duplicate prevention does not use Tessera's best-effort antispam. At start the facade scans every integrated entry of the log and keys it by
`SHA-256(leaf_input)`; registrations are serialized. A resubmission returns the stored Receipt (or issues it, if the process died between integration and
Receipt storage) and appends nothing.

## What the facade does NOT do

It authenticates the issuer of every statement (ES256) against a key table supplied out of band, but it does not authorize issuers for particular subjects, parse payloads, or enforce a Registration Policy beyond structure and authentication. Policy statements in the
prefix are published bytes; enforcement is not established by anything here (prereg non-claim 1). No witnesses; no rotation; no X.509; no multi-writer.

See `RESULTS.md` for what was executed.
