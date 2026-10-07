# spike/ — NON-NORMATIVE FEASIBILITY SPIKE

Experimental code and evidence showing that the traced offline chain can be executed end to end. **Not** the S3 acceptance runner. Successful execution does not adopt any of this code; adoption requires explicit review against the completed S3 preregistration. No ratification, freeze, signature or acceptance is implied.

| Path | What |
|---|---|
| `s3-entry/` | thin Rust entry over the unchanged pinned S2b crate (`decode_request`, `replay_p0_p9`, `parse_cose_sign1`, `read_protected`); no new parser |
| `glue/s3_spike_chain.py` | sequencing glue: S2b result composition, S2a runner jobs, post-S2a inputs from actual outputs, comparison (expected artifacts only read after actual outputs) |
| `host/run_host.sh` | single host command; `preflight.py` checks each pin; `make_cases.py`, `compare_runs.py` |
| `fixtures/volmax-owner/` | public material of a `volmax-owner` instance on the frozen toy semantics (test keys; private keys not in the repository); `gen_volmax_owner.py` is the generator |
| `PINS.json`, `API_INVENTORY.md`, `A12_A14_APPLICABILITY.md`, `FEASIBILITY_REPORT.md` | pins, API accessibility, A12–A14 analysis, results |
| `evidence/2026-10-07-container/` | commands' outputs from the Claude Code container run (not the maintainer's host) |

Not committed: `.deps/` (symlink to the S2b checkout), `s3-entry/target/`, private keys.

The generator needs `cryptography` and `jcs` (the S2b oracle lock pins CPython 3.12.3, cryptography 50.0.2, jcs 0.2.1, cbor2 6.1.5; the container run used Python 3.13.16 with those library versions in a scratch venv). The chain itself needs only the standard library.
