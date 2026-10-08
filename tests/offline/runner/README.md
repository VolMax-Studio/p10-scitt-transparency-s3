# tests/offline/runner: validation harness for the candidate S3-C runner (test tooling, not acceptance code)

- `test_stages.py`: stage logic with a fake S2b tree (real `post_s2a.py`, stub launchers and entry): infrastructure failures vs frozen HALT/REJECT, strict parsing, unattested closureAt.
- `test_runner_static.py`: reuse identity with the spike, pinned hashes, no expectation/fixture/producer inputs, usage and pin failures, unavailable isolation, wrong anchor.
- `run_validation.py`: the heavy validation (needs the pinned Lean): existing captures twice each, the eight ratified propagation controls (`materialize_control.py` packages each ratified vector as a capture; non-packageable controls run through the chain stages), and the G5 packaging cases through the single command.
- Needs `cbor2` (test tooling only). The runner itself uses the Python standard library.
