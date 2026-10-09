# Changelog

## 0.1.1 – fixes for review findings in 0.1.0 (`af38bea35486dc140de4d8da57ee0e6e48f9e6ff`)

Application layer only. The wrapper, runner, frozen files, packages, tags and keys are unchanged; the accepted S3 evidence is not affected.

1. **Swallowed write errors.** Log open/write/flush errors, failing event/status callbacks and report-finalization errors are now explicit application failures (`LOG_WRITE_FAILED`, `SUPERVISION_CALLBACK_FAILED`, `REPORT_FINALIZATION_FAILED:*`, `WORKER_EXCEPTION:*`). The reproduction badge is never retained, no P10 outcome is promoted, original runner records are left untouched. Subprocess cleanup (TERM, KILL after 5 s) now also runs when supervision itself raises, and the leader is reaped while waiting so cancellation no longer always costs five seconds.
2. **Process control.** One application instance per workspace (`instance.lock`); one active job per workspace across instances (`active-job.lock` handed to the worker). `result.json` is published exactly once and is the authoritative terminal record; status is derived from it. Recovery and shutdown stop live orphan workers (TERM, then KILL) and seal their jobs as `APP_FAILURE` (`INTERRUPTED_BY_RESTART` / `INTERRUPTED_BY_SHUTDOWN`); a late worker cannot overwrite the sealed result and the application report is regenerated from it. Signals are sent only after an identity check (start time; command line for workers).
3. **Export snapshot.** Every artifact is copied once as a stable prefix, hashed during that copy, and archived from the copy. `export-info.json` records sizes/hashes and whether the job had a final result.
4. **Tests.** 95 tests (was 71). Readiness tests no longer depend on a Rust toolchain or any host tool (`S3Module.which` is injectable).

Version 0.1.0 evidence under `evidence/` is preserved; v0.1.1 evidence is under `evidence/v0.1.1/`.
