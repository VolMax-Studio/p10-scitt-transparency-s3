# Runner hardening after the feasibility baseline — report

**NON-NORMATIVE.** Spike code and spike evidence; nothing here is adopted, ratified or accepted. Baseline preserved unchanged: commit `23ba96f` and `spike/evidence/2026-10-07-container/`. New evidence is in `spike/evidence/hardening-container/`. Candidate acceptance-code evidence (G5) is separate: `tests/offline/g5/evidence/`.

Environment of all executed items: the same Claude Code container as the baseline (Ubuntu 24.04, gcc 13.3.0, Python 3.13.16 for the chain glue and the venv Python 3.13 with `cbor2` for the G5 test harness), pinned Lean obtained and hash-verified in the baseline pass. Not the maintainer's host.

## 1. Requested changes and what was executed

| Item | Change | Executed evidence |
|---|---|---|
| Default offline mode must stop without isolation | `run_host.sh` tries `unshare -n`, then `unshare -rn`; stops if neither works; then tests the isolation from inside (only the loopback interface exists; no external TCP connection succeeds) and stops if the test fails | `stop-shim1/`: a fake `unshare` that exits 1 → `STOP: network isolation could not be established`; `stop-shim2/`: a fake `unshare` that does not isolate → `STOP: network isolation test failed`. In both, no chain run directory exists (`files-present-at-stop.txt`) |
| Connected run only by explicit `--no-offline`, labelled | banner `*** CONNECTED RUN ***` and `OFFLINE_STATUS.txt` (`network-isolated: NO (--no-offline)`); the default writes `network-isolated: yes (unshare -n)` | `connected-run/`, `default-run_host/OFFLINE_STATUS.txt` |
| Pins of components actually used | the Lean directory that passes the `lean` check is selected; `lean`, `lake`, `libleanshared.so` and the version string are then REQUIRED against the S1 manifest (`leanchecker` stays informational: unused on this chain); the host script exports the selected directory to the launchers | `preflight-negative/`: a directory with a wrong `lake` fails `selected-lake-vs-S1-manifest`; one with a wrong `libleanshared.so` fails `selected-libleanshared-vs-S1-manifest` (both exit 1) |
| Stale Lean digest in the runtime table | corrected to the S2a manifest's `lean_toolchain_artifact_digest` `9842f89b…2847` (equal to the S1 pin); `f8380b19…` is the S2a verifier manifest file's own digest | `spec/acceptance-runner-map.md` §5 |
| e2e / cov / codec output handling | strict readers: a runner error object, a missing `evidence_repr`, a result other than explicit `some`/`none`, a malformed `cov` result, or a codec job that is not `decode` ∧ `reencode_identical` is an infrastructure failure recorded in `infra_failures`; it can never become `false` or an A15 REJECT | `glue-unit-tests.txt` (7 tests, including seven malformed e2e shapes that must return an error, never a value) |
| Exact post-S2a comparison | controls compare result, code and rule exactly, plus the T5 detail text, and require the real helper's binary hash where the helper is required; expected codes are a spike annotation derived by inspection of `post_s2a.py` (the ratified vectors record only verdict and rule) | all nine cases `PASS` in `default-run_host/` and `connected-run/`; `glue-unit-tests.txt` includes a record `HALT/T5` with code `ClosureAtUnavailable` that must NOT satisfy the `closureAt returned none` expectation |
| Helper unavailability cannot satisfy the closureAt-none control | test hook `--inject-closureat-unavailable` skips the helper run | `fault-injection/`: `C-ACC`, `C-POST-REJ`, `C-POST-HALT` and `FX-volmax-owner` all `FAIL`; the other five cases (which never reach the helper) still pass; exit 1 |

## 2. Observations

1. **The frozen code already refuses to record such a verdict as evidence.** With the helper unavailable, `post_s2a.evidence_record` raises `UntrustedVerdictError` (T5 was consulted without a trusted provider), so the record is `NOT_EVIDENCE`, not `HALT/T5`. The baseline glue would therefore also have failed that control, but only through that behavior of the frozen code. The hardened comparison now states the requirement itself (exact code, detail and helper hash), and treats `ClosureAtUnavailable`, `ClosureAtInconsistent` and `NOT_EVIDENCE` as infrastructure failures.
2. **The first version of the isolation test was wrong.** It created an IPv6 socket outside its `try` block, and inside the new network namespace IPv6 sockets are unsupported, so a correctly isolated run was reported as "not isolated". Found by running the default mode; fixed (socket creation moved into the `try`); the final scripts were rerun.
3. The isolation test does not depend on the host's egress policy: it first requires that only the loopback interface exists inside the namespace.

## 3. Limits

- The tests of the stop paths use shims for `unshare`; they show the script's decisions, not how a host without namespace privileges behaves. A non-root user may need `unshare -rn` (user namespaces), which the script tries second.
- The expected post-S2a codes are an annotation, not frozen vector content.
- `--inject-closureat-unavailable` is a test hook; no normal run uses it.
- All hashes of Lean-built helper binaries are specific to the container's native compiler and libraries (see the `link-log` lines in the stderr logs).

## 4. Remaining blockers for an adopted runner

Review of the glue as S3-owned TCB code against the completed preregistration; toolchain carriage; Python and OS pins; the `libuv` development prerequisite; a run on the maintainer's host; the mixed-log test (`spec/mixed-log-test-plan.md`); a live TS.
