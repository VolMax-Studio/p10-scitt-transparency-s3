# producer (candidate, non-normative): runtime issuer tooling and fresh configuration

- `gen_config.py` generates only PUBLIC CONFIGURATION for a fresh instance on the frozen toy semantics: fresh issuer, policy-test and Receipt keys (outside the repository; the Receipt key in a separate directory the issuer tooling cannot read),
  then derives pB.key_resolution and the profile digest, the SubjectDeriveV0 subject, LogIdentityV0 and the instance commitment from that configuration. The exact toy `iB`, the frozen A12-A14 digests, the verifier manifest digest,
  claim/evidence/witness data, rule IDs, the admitter names and `request_id` are unchanged. No statement, request or Receipt is produced.
- `issuer_tool.py` is called by `s3-capture submit --producer` before each registration. It creates and signs statement N from the *authenticated prefix* it fetches from the public read endpoint (checkpoint verified with the
  pinned key, every entry proved into its root), cross-checked against the retained submissions and the indices the facade returned. Admission refs and adjudication refs are those actual indices; the closure's preclosure digest is the
  ratified S2b reference definition (`post_scenarios.preclosure_digest`) over the view decoded from that prefix; statements are built and signed with the ratified S2b test builders (`scenarios.statement_for`).
- **Ordinal, index and prefix size are separate** (from run3 on). The client derives the next expected append position from the verified public checkpoint and calls `issuer_tool.py --ordinal K --next-index N`;
  N is also the size of the authenticated prefix the tool fetches. The facade's returned index is validated against N (a rogue concurrent writer is detected). `--operator-insert K:FILE` registers one operator statement
  (`operator_note.py`: a classifiable non-target TEST note) through the same facade right after producer ordinal K, sequentially, not counted as a producer role. The strict fixture-submit mode (`--statements`, file number == expected index)
  is unchanged. The run2 `--step N` interface is still accepted by the tool (ordinal == index) but the client no longer uses it.
- Scripts: `../scripts/run_lifecycle.sh` (prepare / capture / verify), `derive_expected_tb_from_prefix.py`, `assemble_capture_v2.py`, `producer_index_record.py` (pre-verification record of ordinal vs index, closure/adjudication references and retention for the `ml2` layout; `LAYOUT=ml2`).

`gen_config.py` also writes the facade's preconfigured issuer table (`public/issuers.json`) and the two bootstrap declaration payloads (`bootstrap/*.json`, hashed in `PUBLIC_META.json`); `issuer_tool.py` signs them with the operator key as leaves 0 and 1. The declarations are published bytes: they confer no key authority and are not read by the facade.
