# Changelog

## 0.1.2 – terminal-state race and /proc-independent process identity (fixes found in `244ed8dca40e476467712d0d5869d9f8d6bdda05`)

Application layer only; wrapper, runner, frozen files, packages, tags and keys unchanged.

1. **Interruption racing with result publication.** Interruption registration (`interrupt.json`: shutdown, restart recovery) and final-result publication (`result.json`) are serialized by one per-job lock (`seal.lock`). Rule: *whoever takes the lock first wins.* Worker first: the job finished before the interruption; result, report and status say so and the late registration returns `too_late`. Interruption first: the worker converts its result to an application failure (no badge, nothing promoted), writes `app-report.json` for exactly that result under the same lock, then publishes. A marker or stop request that appears while the report is being written (a writer bypassing the lock) triggers a re-decision before publication. If the lock holder is unresponsive (stopped), the registration times out, writes the marker anyway and the holder honours it when it resumes. The marker is written atomically. Raw runner records are never touched.
2. **Process identity without /proc.** The worker holds `worker.lock` for its life and the supervised command group inherits `child.lock`; a held lock is proof of a live worker/group of that job and cannot be faked by PID reuse. When `/proc` is readable the recorded start time and command line must match in addition. A worker records its pid before taking the lock and refuses to run a job that was already interrupted or sealed. Group cleanup now waits for *live* members only (zombies, e.g. under a PID 1 that never reaps, no longer cost 8 s or fail checks). Previously five process tests failed on hosts without a readable `/proc`.
3. **Tests.** 123 tests (104 before): deterministic interruption-during-finalization, concurrent interruption/publication invariants, a real-worker shutdown during finalization, lock-based identity, no-/proc host emulation. Three tests that exercise `/proc` start times and command lines are skipped on hosts without `/proc`.


## 0.1.1 – fixes for review findings in 0.1.0 (`af38bea35486dc140de4d8da57ee0e6e48f9e6ff`)

Application layer only. The wrapper, runner, frozen files, packages, tags and keys are unchanged; the accepted S3 evidence is not affected.

1. **Swallowed write errors.** Log open/write/flush errors, failing event/status callbacks and report-finalization errors are now explicit application failures (`LOG_WRITE_FAILED`, `SUPERVISION_CALLBACK_FAILED`, `REPORT_FINALIZATION_FAILED:*`, `WORKER_EXCEPTION:*`). The reproduction badge is never retained, no P10 outcome is promoted, original runner records are left untouched. Subprocess cleanup (TERM, KILL after 5 s) now also runs when supervision itself raises, and the leader is reaped while waiting so cancellation no longer always costs five seconds.
2. **Process control.** One application instance per workspace (`instance.lock`); one active job per workspace across instances (`active-job.lock` handed to the worker). `result.json` is published exactly once and is the authoritative terminal record; status is derived from it. Recovery and shutdown stop live orphan workers (TERM, then KILL) and seal their jobs as `APP_FAILURE` (`INTERRUPTED_BY_RESTART` / `INTERRUPTED_BY_SHUTDOWN`); a late worker cannot overwrite the sealed result and the application report is regenerated from it. Signals are sent only after an identity check (start time; command line for workers).
3. **Export snapshot.** Every artifact is copied once as a stable prefix, hashed during that copy, and archived from the copy. `export-info.json` records sizes/hashes and whether the job had a final result.
4. **Tests.** 95 tests (was 71). Readiness tests no longer depend on a Rust toolchain or any host tool (`S3Module.which` is injectable).

Version 0.1.0 evidence under `evidence/` is preserved; v0.1.1 evidence is under `evidence/v0.1.1/`; v0.1.2 under `evidence/v0.1.2/`.
