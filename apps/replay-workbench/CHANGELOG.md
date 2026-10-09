# Changelog

## 0.2.0 – persistent host settings and desktop launcher

Application layer only; wrapper, runner, profile, packages, binaries, frozen files, tags and keys unchanged. Automatic port selection is unchanged.

1. **Host settings** (`workbench/settings.py`, `GET/POST /api/settings`, *Save host settings* button): Lean directory, optional public allowed-signers path and job deadline are stored on the server side in `<workspace>/settings.json` (owner-only, atomic, strict JSON, unknown keys rejected, same path/deadline validation as a job start, no workspace-only restriction). The UI restores them into the fields at load, on any port; restoring never sets a readiness state, starts a job or yields a badge. Missing file: defaults; invalid or unreadable file (including links and FIFOs): warning and defaults. The settings API keeps the Host, Origin and token checks. Browser `localStorage` is no longer used.
2. **Launcher** (`workbench/launcher.py`, `run.py --install-launcher` / `--remove-launcher`): user-level `.desktop` entry and SVG icon under `$XDG_DATA_HOME` (default `~/.local/share`), Exec quoting per the Desktop Entry specification (spaces, `%`, quotes, backslashes, `$`, backticks tested by round trip and by actually executing the parsed command), marker-based ownership (foreign files are never overwritten or removed, symlinks never followed), idempotent install, no external commands, nothing started. `--pause-on-error` keeps the launcher terminal open after a startup error; `SIGHUP` now stops the server and any active job cleanly.
3. **Tests**: settings store, API boundaries, persistence across ports, parser without a fixed default port, UI source checks, launcher quoting/idempotency/ownership/removal and a CLI test with spy `sudo`/`sysctl`/AppArmor tools that must never be called.


## 0.1.3 – the timeout fallback no longer bypasses the seal lock (found in `f9ade39c822331e9501fcef955af257ea0568777`)

Application layer only; wrapper, runner, frozen files, packages, tags and keys unchanged.

1. **No marker and no result without the lock.** `register_interrupt()` no longer has a `forced` path: when the lock cannot be obtained it writes nothing and returns `timeout`. `publish_result()` returns `None` (nothing published) when it does not hold the lock, `False` when a result already exists (the committed result stands), `True` when it published. `claim_result()` is documented as a primitive whose caller must hold the lock; both call sites do. The worker's re-read after finalization remains only as defence in depth; it is no longer what makes the ordering correct.
2. **Unresponsive owner.** `JobManager._interrupt()` returns `already`, `sealed` or `pending`. On a lock timeout it waits for a verified worker (lock proof plus identity checks) to finish for the grace period; if it is still unresponsive it is killed and reaped, and only then is the lock taken and the interruption registered and the job sealed under it. An owner that cannot be verified is left untouched and the job stays `pending` (`interruption_pending` in the status) with no marker and no result.
3. **Tests.** 131 tests (123 before): the interruption at the boundary between the final check and `claim_result()` (the worker keeps the decision, the late attempts return `timeout`/`None`, the later registration returns `too_late`), registration and publication without the lock, a blocked real worker holding the lock during finalization (the marker must never exist while the owner is alive), an unverified owner, a publication timeout. Mutation checks: restoring the lock-free marker fails 4 of them, publishing without the lock check fails 2.
4. Sealing within one instance is serialized (watcher thread, shutdown, status polling, recovery), so `shutdown()` cannot return while another thread is still sealing the job it just stopped (this showed up as an occasional missing result right after shutdown).
5. `tests/fakes.py make_module()` closes its fixture file.


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

Version 0.1.0 evidence under `evidence/` is preserved; v0.1.1 evidence is under `evidence/v0.1.1/`; v0.1.2 under `evidence/v0.1.2/`; v0.1.3 under `evidence/v0.1.3/`; HP trial (v0.1.3) under `evidence/hp-20261009/`; v0.2.0 under `evidence/v0.2.0/`.
