# v0.1.2 evidence (Claude Code cloud container, not the HP laptop)

* `unittest-A-…`: 123 tests, OK (3 skipped: the no-/proc emulation class's /proc-specific cases), Python 3.13, normal /proc.
* `unittest-B-no-proc-…`: the same suite in a mount namespace with `/proc` unmounted: OK, 6 skipped (the 3 above plus the 3 tests that exercise /proc start times and command lines). Without the v0.1.2 changes this configuration produced exactly five process-test failures.
* `unittest-C-pid1-runner-…`: Python 3.12, the test runner is PID 1 of a fresh PID namespace (orphans are reparented to a process that never reaps): OK. This configuration exposed zombie group members keeping group cleanup waiting 8 s; fixed by waiting for live members only.
* All runs: `env -i PATH=/usr/bin:/bin` (no Rust), `-W error::ResourceWarning`.
* Mutation checks (not recorded as files): removing the post-finalization re-check made 3 of the new race tests fail; making interruption registration lock-free made 4 fail.
* `integration-cloud-cached-smoke.txt` / `integration-cloud-report.tar.gz`: cached real-package run (package and Lean helpers from the earlier import): `COMPLETED`, wrapper exit 0, `BINDING_MATCH`, reproduction `MATCH` (14/14, badge), 52.5 s; second start refused (`JOB_ACTIVE`); mid-run and final exports 0 checksum mismatches; exported `runner/verdict.json` SHA-256 `6368022f…db22`.
* Earlier evidence (`../`, `../v0.1.1/`) preserved.
