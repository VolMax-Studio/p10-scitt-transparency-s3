# producer (candidate, non-normative): runtime issuer tooling and fresh configuration

- `gen_config.py` generates only PUBLIC CONFIGURATION for a fresh instance on the frozen toy semantics: fresh issuer, policy-test and Receipt keys (outside the repository; the Receipt key in a separate directory the issuer tooling cannot read),
  then derives pB.key_resolution and the profile digest, the SubjectDeriveV0 subject, LogIdentityV0 and the instance commitment from that configuration. The exact toy `iB`, the frozen A12-A14 digests, the verifier manifest digest,
  claim/evidence/witness data, rule IDs, the admitter names and `request_id` are unchanged. No statement, request or Receipt is produced.
- `issuer_tool.py` is called by `s3-capture submit --producer` before each registration. It creates and signs statement N from the *authenticated prefix* it fetches from the public read endpoint (checkpoint verified with the
  pinned key, every entry proved into its root), cross-checked against the retained submissions and the indices the facade returned. Admission refs and adjudication refs are those actual indices; the closure's preclosure digest is the
  ratified S2b reference definition (`post_scenarios.preclosure_digest`) over the view decoded from that prefix; statements are built and signed with the ratified S2b test builders (`scenarios.statement_for`).
- Scripts: `../scripts/run_lifecycle.sh` (prepare / capture / verify), `derive_expected_tb_from_prefix.py`, `assemble_capture_v2.py`.

The two bootstrap statements are explicitly experimental synthetic test statements; no policy exists and none is enforced.
