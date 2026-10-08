# Mixed-log test plan (candidate; ML-1 and ML-6 executed, ML-2 to ML-5 not executed)

Status: **DRAFT CANDIDATE plan.** ML-1 and ML-6 were built and executed in the r5 pass (§8); ML-2 to ML-5 were not built or executed. This document is a plan plus the pointer to those results; it is not itself a result. Not ratified, not frozen, not adopted.

## 1. Why a separate test

The committed `volmax-owner` fixture is a five-leaf P10-only log (all leaves lifecycle statements at indices 0-4). The ratified mirrored fixtures are mostly of that kind but not all: of the 90 expected transcripts that decode in `vectors/s2a-post` and `vectors/s2a-t11` (analysed in the r5 pass), sizes are 4 (4 transcripts), 5 (51), 6 (32), 7 (2) and 300 (1); 51 are five-leaf logs without any non-target row; three contain non-target rows (`N10`, size 7; `N17`, size 6; `T3-idx255-FFdigest`, size 300), always after a subject entry at index 0. None has leading non-target leaves before the lifecycle, and none combines non-target leaves with the `volmax-owner` instance. (The S2b prereg tables also list transport-level mixed-prefix vectors such as `E11` and a 1025-leaf `R9-full`; those were not re-examined.) The gap this test fills is therefore specific: leading policy/trust-anchor-like non-target leaves, the lifecycle at shifted indices, the `volmax-owner` instance, and the anchored capture path, together.

Merely prepending `k` leaves to an existing request would invalidate the Receipt, the Merkle root, the proof path, the transcript and every index-bearing statement, and would test nothing. The test must therefore be a **new log built from scratch with the lifecycle at shifted indices**, not a mutation of an existing fixture.

## 2. Shape

`[0,k)` leading non-target leaves (Registration Policy and trust-anchor Statements; the bootstrap choice is still OPEN, so the plan fixes only the property "leading, non-target, classifiable"), then the five-statement lifecycle at indices `k..k+4`: profile commitment, instance commitment, admission, closure, adjudication (target = `k+4`). ML-1 uses `k = 2` (one policy-like and one trust-anchor-like test statement). The optional ML-2 checks that only the relative lifecycle order matters, with one non-target leaf *between* lifecycle statements; its index map is:

| ML-1 index | leaf | | ML-2 index | leaf |
|---:|---|---|---:|---|
| 0 | policy TEST statement (non-target) | | 0 | policy TEST statement |
| 1 | trust-anchor TEST statement (non-target) | | 1 | trust-anchor TEST statement |
| 2 | profile commitment | | 2 | profile commitment |
| 3 | instance commitment | | 3 | non-target TEST note statement |
| 4 | admission | | 4 | instance commitment |
| 5 | closure | | 5 | admission |
| 6 | adjudication (Receipt target) | | 6 | closure |
| | | | 7 | adjudication (Receipt target) |

ML-2 is not built. (An earlier revision of this plan, including the §6 table row, called it "`k = 3`", which did not say where the extra leaf sits; the table above is the precise map, corrected in the r6 pass.)

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

The ratified S2b test builder `tests/s2a/scenarios.py::build_log` already fills every index that has no subject entry with a signed non-subject statement (`rows[idx]` = a different subject), and `post_scenarios.preclosure_digest` and `scenarios.adj_wire` take their indices from the entries dictionary. A mixed log is therefore expressible by placing the `entries` at indices `k..k+4` and declaring `rows[0..k)` as other subjects, without editing any frozen file. `tests/offline/ml/gen_ml1.py` does this for ML-1 (§8); the spike's `gen_volmax_owner.py` was left unchanged.

## 6. Test set

| ID | Log | Expected |
|---|---|---|
| ML-1 (**executed**, §8) | mixed log, `k = 2`, all leading leaves compliant | G5 pass; S2b `Verified`; `tB` rows 0–1 `available(other)`, detailed entries at `2..6`; S2a `accept`; S1 e2e `some`; post-S2a `BINDING_MATCH` with A1–A15 `match` |
| ML-2 | 8 leaves; index map in §2 (leading test statements at 0-1, profile 2, one compliant non-target note at 3 *between* lifecycle statements, instance 4, admission 5, closure 6, adjudication 7 = target); leading count is 2 as in ML-1 | same verdicts; confirms only relative lifecycle order matters |
| ML-3 | leading leaf with a protected header lacking `sub` | `unavailable` row; S2a HALT `c2_rowUnavailable` (cf. ratified `E5-sub-notstr`) |
| ML-4 | leading leaf with a non-empty unprotected header, authenticated | `Invalid(binding, LeafInputDomainViolation)`, REJECT (cf. ratified `E10-unprotected`) |
| ML-5 | leading leaf with the same `sub` as the instance subject but unparsable P10 content | the S2a C2 liveness limitation (`c2_subjectPayloadUnavailable` HALT), documented as an accepted incompleteness, not a failure |
| ML-6 (**executed**, §8) | capture packaging of ML-1 | G5 pass with `origin="ts"` for policy leaves that the TS (not the issuer) originated, and the corresponding rule that no submission file is required for them |

ML-3 to ML-5 reuse ratified vectors for rule coverage and only check that the rules still apply at shifted positions; they are optional if the prereg keeps its principle of not regenerating semantic mutation families. ML-1 and ML-6 are the required ones.

## 7. Dependencies and open decisions

Bootstrap mechanism and the content of the leading statements (OPEN); who originates them (`origin` in the capture index); whether policy statements are signed with the TS operator key or a separate policy issuer (the frozen chain does not verify their signatures either way, prereg non-claim 1); the lifecycle statement count for the real capture.

## 8. Execution of ML-1 and ML-6 (r5 pass, container)

ML-1 was generated by `tests/offline/ml/gen_ml1.py` as a new authenticated synthetic log (the external test keys of the `volmax-owner` fixture reused: they were available and their thumbprints matched the fixture's `pB.key_resolution` and `LogIdentityV0`; one further key, `policy-test`, signs the two leading statements and appears in no key table). `pB`, `inst` and `iB` are byte-identical to the fixture's; the closure, adjudication, Merkle tree, Receipt (tree size 7, leaf index 6) and request were recomputed for the shifted indices. The capture was materialized with the leading two leaves recorded as `origin="ts"` and no submission files for them (ML-6). The anchored host path ran: G5 PASS with `anchor_checked=true` -> S2b Verified (7 rows; subject entries 2-6; none unreadable) -> S2a accept -> S1 e2e `some` -> post-S2a `BINDING_MATCH` (code `BindingMatch`, real closureAt helper hash recorded, A1-A15 all `match`), in two network-isolated runs with identical results; the actual `tB` equals the generator's independently built expected `tB`. Evidence: `tests/offline/ml/evidence/container-run/` and `spike/evidence/anchored-capture-container/`.

What this shows: the unchanged chain accepts a mixed prefix with leading classifiable non-target leaves. What it does not show: that any policy exists or was enforced (the two statements are synthetic test content, signed by a key outside every key table; the frozen chain verifies neither their signatures nor their payloads), that any bootstrap mechanism was chosen, or anything about a live TS. ML-2 to ML-5 were not built or executed.
