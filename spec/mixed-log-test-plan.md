# Mixed-log test plan (candidate; not executed)

Status: **DRAFT CANDIDATE plan.** Nothing in this document has been executed. It identifies the test that remains after G5 and the work it requires; it is not a fixture and not a result. Not ratified, not frozen, not adopted.

## 1. Why a separate test

The committed `volmax-owner` fixture and every ratified fixture are P10-only logs: all five leaves are P10 lifecycle statements at indices 0–4. A real S3 Statement Sequence is mixed (prereg I1): Registration Policy and trust-anchor Statements are registered on the same VDS before the P10 lifecycle, so the lifecycle starts at index `k > 0`. Merely prepending `k` leaves to the existing request would invalidate the Receipt, the Merkle root, the proof path, the transcript and every index-bearing statement, and would test nothing. The test must therefore be a **new log built from scratch with the lifecycle at shifted indices**, not a mutation of the existing fixture.

## 2. Shape

`[0,k)` leading non-target leaves (Registration Policy and trust-anchor Statements; the bootstrap choice is still OPEN, so the plan fixes only the property "leading, non-target, classifiable"), then the five-statement lifecycle at indices `k..k+4`: profile commitment, instance commitment, admission, closure, adjudication (target = `k+4`). Suggested `k = 2` (one policy, one trust-anchor statement); a second variant with `k = 3` and a non-target leaf *between* lifecycle statements checks that only the lifecycle order matters.

## 3. Constraints each leading leaf must satisfy (from the frozen sources)

- tagged `#6.18(COSE_Sign1)`; protected header exactly one CBOR map, no duplicate labels, containing label 15 (CWT claims) with `iss` and `sub` as valid UTF-8 text strings (otherwise the row is `unavailable` and S2a HALTs, `c2_rowUnavailable`);
- `sub` not byte-equal to `instance_subject` (then the row is `available(sub)` with no detailed entry and no signature, algorithm or payload processing);
- unprotected header exactly `{}` (a non-empty map in any readable leaf, target or not, is `Invalid(binding, LeafInputDomainViolation)`, composed REJECT);
- registered through `LeafEncodeV0` like every other leaf.
The non-target `iss` is not alphabet-restricted by the frozen chain, so the existing builder's URI-form issuer string for non-target statements is acceptable and also exercises that point.

## 4. Bindings that change when the lifecycle shifts by `k`

| Item | Why it changes |
|---|---|
| `ReplayRequestV0` leaves, tree size `n = k+5`, Receipt `tree_size`, `leaf_index` (`k+4`), inclusion path, signed root | new log |
| Closure `ordered_admission_refs` (decimal-string indices) | admission is at `k+2` |
| Closure `checkpoint_preclosure_transcript_digest` | `PreclosureDigestV0` is computed over a view that contains the indices of the valid owner lifecycle entries and relevant admissions |
| Adjudication refs (`profile`, `commit`, `closure`) and wire members `profile_commitment_ref`, `instance_commitment_ref`, `evidence_closure_ref`, `evidence_admission_refs`, `preclosure_transcript_digest` | index-bearing |
| `tB` rows (`k` additional `available(other)` rows), detailed-entry indices, root | derived by S2b |
| Post-S2a `leaf_index`, T6 (`target idx > closureRef`) | shifted consistently |
| Signatures of closure and adjudication statements (payload changed); the profile/instance/admission statements keep their payload but are new log entries | re-signed with the test keys |

Unchanged: instance subject, `pB`, `inst`, `iB`, claim/evidence/witness digests, A12–A14 values, TS key and `LogIdentityV0`, key tables.

## 5. Feasibility by inspection (not executed)

The ratified S2b test builder `tests/s2a/scenarios.py::build_log` already fills every index that has no subject entry with a signed non-subject statement (`rows[idx]` = a different subject), and `post_scenarios.preclosure_digest` and `scenarios.adj_wire` take their indices from the entries dictionary. A mixed log is therefore expressible by placing the `entries` at indices `k..k+4` and declaring `rows[0..k)` as other subjects, without editing any frozen file. The spike's `gen_volmax_owner.py` would need its entries and size parameterized; that was not done.

## 6. Test set

| ID | Log | Expected |
|---|---|---|
| ML-1 | mixed log, `k = 2`, all leading leaves compliant | G5 pass; S2b `Verified`; `tB` rows 0–1 `available(other)`, detailed entries at `2..6`; S2a `accept`; S1 e2e `some`; post-S2a `BINDING_MATCH` with A1–A15 `match` |
| ML-2 | `k = 3` with one compliant non-target leaf between lifecycle statements | same verdicts; confirms only relative lifecycle order matters |
| ML-3 | leading leaf with a protected header lacking `sub` | `unavailable` row; S2a HALT `c2_rowUnavailable` (cf. ratified `E5-sub-notstr`) |
| ML-4 | leading leaf with a non-empty unprotected header, authenticated | `Invalid(binding, LeafInputDomainViolation)`, REJECT (cf. ratified `E10-unprotected`) |
| ML-5 | leading leaf with the same `sub` as the instance subject but unparsable P10 content | the S2a C2 liveness limitation (`c2_subjectPayloadUnavailable` HALT), documented as an accepted incompleteness, not a failure |
| ML-6 | capture packaging of ML-1 | G5 pass with `origin="ts"` for policy leaves that the TS (not the issuer) originated, and the corresponding rule that no submission file is required for them |

ML-3 to ML-5 reuse ratified vectors for rule coverage and only check that the rules still apply at shifted positions; they are optional if the prereg keeps its principle of not regenerating semantic mutation families. ML-1 and ML-6 are the required ones.

## 7. Dependencies and open decisions

Bootstrap mechanism and the content of the leading statements (OPEN); who originates them (`origin` in the capture index); whether policy statements are signed with the TS operator key or a separate policy issuer (the frozen chain does not verify their signatures either way, prereg non-claim 1); the lifecycle statement count for the real capture.
