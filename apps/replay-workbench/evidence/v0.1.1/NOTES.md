# v0.1.1 evidence

Environment: Claude Code cloud container (not the HP laptop).

* `unittest-python3.13.txt`, `unittest-python3.12.txt`: full suite, 95 tests, OK on each, run with `env -i PATH=/usr/bin:/bin` (no Rust toolchain on PATH) and `-W error::ResourceWarning`.
* `integration-cloud-real-run.txt` / `integration-cloud-report.tar.gz`: real approved rev2 package through the app after the fixes. Application execution `COMPLETED`, wrapper exit 0, P10 `BINDING_MATCH`, reproduction `MATCH` (14/14 conditions, badge), exported `runner/verdict.json` SHA-256 `6368022f…db22`. The package had been extracted by an earlier attempt of the same driver (that attempt was rejected because the driver passed a non-normalized Lean path, which the app correctly refuses), hence `reused: True`.
* During the run: a second start was refused (`JOB_ACTIVE`); a report exported mid-run (job still running, marked `job_had_final_result=false`) and the final export both had zero checksum mismatches; a second `run.py` on the same workspace exited 2 with an explanation.
* Version 0.1.0 evidence (`../`) is preserved unchanged.
