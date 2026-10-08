# deployment/ — candidate deployment definition (nothing adopted)

- `candidate/`: the public part of the candidate definition for the normative S3-B: resolved configuration (`config/`), the two bootstrap declaration payloads and the issuer table (`config/bootstrap/`, `config/public/issuers.json`), the staged operator note, `definition-manifest.json` (identity, layout, hashes, source and executable pins, SHA-256 of every file), `RUN.md` (the exact commands) and `env.example.sh`.
- `make_definition.py`: assembles `candidate/` from the output of `ts-prototype/scripts/run_lifecycle.sh prepare`; it copies no private key.
- The private keys of the candidate set are **not** in this repository. Their values, and everything derived from them (thumbprints, profile digest, instance commitment, subject, `LogIdentityV0`, payload hashes), belong to that exact key set.
- Review document: `spec/deployment-profile.md`. Normative S3-B must not start before the operator explicitly authorizes the freeze.
