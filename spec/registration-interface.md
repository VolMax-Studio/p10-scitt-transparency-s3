# Facade registration interface and issuer-key bindings (candidate, written before implementation)

Status: **CANDIDATE INTERFACE; nothing adopted.** This document fixes what the S3 facade (`ts-prototype/`) is meant to do when it authenticates the issuer of a Signed Statement, so that the implementation and its tests can be checked against a text written first. It does not claim RFC 9943 or SCRAPI compliance: it implements one mandatory registration check (issuer signature verification against preconfigured keys) for the one algorithm of this deployment (ES256). Registration Policy enforcement, authorization of issuers for particular subjects, payload parsing and witnessing remain absent (preregistration non-claims unchanged).

## 1. Scope of the change

Added: (a) issuer authentication of every submitted statement before anything is appended, journaled as a registration, answered as a duplicate success, or covered by a Receipt; (b) transport of a detached statement payload to the facade, needed to verify such a statement; (c) the preconfigured issuer-to-key table. Not changed: `LeafEncodeV0`, the registered bytes (the exact submitted COSE bytes, nothing re-encoded), Receipt form (detached payload, ES256, low-S), the checkpoint and publication invariants, duplicate prevention, the public read endpoint, the frozen P10 chain.

## 2. Issuer table (preconfigured trust)

`--issuers FILE` is mandatory; without a valid table the facade does not start (fail closed). File `issuers.json`:

```
{"format": "S3-ISSUER-TABLE-V0",
 "issuers": [ {"iss": "<text>", "key_thumbprint": "<64 hex>", "cose_key_file": "<path relative to the table>"} , ... ]}
```

- `cose_key_file` holds one public COSE_Key (CBOR map) with exactly `{1: 2 (EC2), -1: 1 (P-256), -2: x, -3: y}` (an `alg` entry, label 3, is accepted only if it is -7). `key_thumbprint` is SHA-256 of the canonical-order encoding `{1:2, -1:1, -2:x, -3:y}` (RFC 9679 style, the construction already used by the instance commitment) and MUST equal the thumbprint computed from the file; a mismatch refuses start.
- `iss` values are exact byte strings (no normalization). `iss` values are unique; thumbprints are unique; an `iss` equal to the facade's `--ts-iss`, or a key equal to the Receipt-signing key, refuses start (Receipt/checkpoint keys and issuer keys are different roles).
- The table is operator configuration supplied out of band. **It is the only source of issuer trust.** Statements already in the log, including the declaration statements at leaves 0 and 1, are never read by the facade and confer no authority. The operator that signs the bootstrap statements is an entry of the table like any other issuer.
- The SHA-256 of the table file, the entry count and the thumbprints are reported by `GET /config` and recorded in the run configuration.

## 3. Request forms

`POST /register` on the registration listener.

1. **Attached statement.** Any content type other than `multipart/form-data` (the clients send `application/cose`); the body is the statement bytes. Allowed only if the COSE payload is a byte string.
2. **Statement with a separately supplied payload.** `multipart/form-data` with exactly the parts `statement` (the COSE_Sign1 bytes) and, when the COSE payload slot is `null`, `payload` (the exact bytes that were signed). Unknown or repeated parts are refused. A `payload` part together with an attached payload is refused (ambiguous). A `null` payload slot without a `payload` part is refused. An empty `payload` part is a supplied empty payload.

The detached payload is used for verification only. It is not logged, not stored by the facade and not part of any Receipt (the Receipt's own payload is detached for a different reason and is unaffected). Limits: `LeafEncodeV0(statement)` ≤ `--max-leaf-input` (65535, statement ≤ 65474); detached payload ≤ `--max-detached-payload` (default 1 MiB).

## 4. Verification order and rules

Everything below happens under the registration mutex and **before** `s.nreq` is advanced, the duplicate index is consulted, an `intent` is journaled, Tessera is called, or a stored Receipt is returned. A refusal journals one `reject` record with its code (as the existing refusals do); that record is not a registration, appends nothing, and issues no Receipt.

1. Size of `LeafEncodeV0(statement)`.
2. Structural admission (unchanged: tagged COSE_Sign1 of four elements, protected header one map without duplicate labels with CWT claims containing text `iss` and `sub`, empty unprotected header, payload bstr or null, signature bstr).
3. Payload form consistency (§3).
4. Protected header profile. Labels allowed: 1 (alg), 3 (content type), 4 (kid), 15 (CWT claims). Any other label, including `crit` (2) and the X.509 labels (33, 34, 35), is refused. Label 1 is required and must be the integer -7 (ES256); other or non-integer values are refused as an unsupported algorithm. If label 4 is present it must be a byte string equal to the 32-byte thumbprint of the key configured for the statement's `iss`.
5. Issuer lookup: the protected CWT `iss` must be an `iss` of the table (exact match).
6. Signature: 64-byte P1363 `r || s`, both in [1, n-1]; ECDSA over SHA-256 of `Sig_structure = ["Signature1", protected_bstr_bytes_as_submitted, h'', payload]` where the protected bytes are those of the submitted statement (not re-encoded) and the payload is the attached payload or the supplied detached payload. A low-S requirement is not applied to statements (the frozen verifier has none); Receipts remain low-S.

## 5. Error codes

| Code | HTTP | Meaning |
|---|---|---|
| `E_TOO_LARGE` | 413 | size limits (unchanged) |
| `E_*` of structural admission | 400 | unchanged |
| `E_BAD_REQUEST` | 400 | malformed multipart, unknown/repeated part, unreadable body |
| `E_PAYLOAD_PART_UNEXPECTED` | 400 | `payload` part with an attached payload |
| `E_PAYLOAD_PART_MISSING` | 400 | `null` payload slot, no `payload` part |
| `E_ALG_UNSUPPORTED` | 400 | label 1 missing or not -7 |
| `E_PROTECTED_LABEL_UNSUPPORTED` | 400 | a protected label outside {1, 3, 4, 15} |
| `E_KID_MISMATCH` | 400 | label 4 malformed or different from the configured key's thumbprint |
| `E_ISSUER_UNKNOWN` | 403 | `iss` not in the table |
| `E_SIGNATURE_INVALID` | 403 | malformed signature or verification failure (covers tampered signature, header, payload, or a statement signed by another key) |

## 6. Required tests (written before the implementation)

Valid statements (attached, detached) are registered; each of the following is refused with the code above, appends nothing, journals no `intent`, returns no Receipt, stores nothing, and leaves the checkpoint size unchanged: flipped signature bit; tampered protected header (the signature no longer covers it); tampered payload; payload signed under another iss's key (identity-to-key mismatch); unknown iss; kid mismatch; algorithm other than -7 (including ES384 = -35 and a missing alg); unsupported label; detached statement without payload; detached statement with a wrong payload; attached statement with a payload part; a duplicate (re-submission) with a bad signature or missing payload is also refused (no duplicate-success without authentication). The existing facade regressions (size limit, structural refusals, duplicates, abrupt termination at five points, chaos, pins, producer protocol, public-read timeouts) are re-run with correctly signed statements through the real capture client.

## 7. Limits of this change

Authentication, not authorization: any configured issuer may register any statement, so the policy "who may register what" is still not enforced. The facade does not parse payloads or check P10 semantics. The key table is operator configuration on the same host as the facade; no operator independence is gained. Only ES256 is supported. Passing the tests here is not a claim of RFC 9943 / SCRAPI compliance.
