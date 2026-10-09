# Manual UI notes and integration record (v0.1)

**Environment: the Claude Code cloud container (Python 3.13, Chromium via Playwright), NOT the HP laptop.** The real HP run through this interface is still to be done by the operator.

## Integration run on the cloud container (real approved package, real unchanged wrapper and runner)

* Server: `python3 apps/replay-workbench/run.py --workspace <scratch> --no-browser`, driven through the HTTP API with the session token (driver script not part of the app).
* Package `p10-s3-offline-e56d3ea-rev2.tar.gz` (SHA-256 `e19f8d84cac0ecb2de61dbd0e7085014d525829ba51007b7fdaa24895df37d9b`) imported: `SUPPORTED`, 8,049 members.
* Readiness: no blocking row; `sha256sum -c` exit 0 for `PACKAGE_SHA256SUMS` (5,997 paths) and the frozen set (99); tag signature rows `NOT_CHECKED` (no allowed-signers file); existing `preflight.py` offline: 31 checks, 0 required failed. `ssh-keygen` is absent here (warning only).
* Run `20261009T083053Z-a5ab7143` (about 195 s): application execution `COMPLETED`; wrapper exit 0; P10 outcome `BINDING_MATCH`; reproduction `MATCH`, every profile condition ok.
* Full output: `integration-cloud-real-run.txt`; exported report: `integration-cloud-report.tar.gz` (contains local container paths).
* This shows the interface works end to end on this container. It is not an HP run and not an independent validation of S3.

## UI checks (Chromium, 1100 px wide): `screenshots/01-after-real-run.png`

* The three result panels are separate; the wrapper exit status is shown below them with the note that it is not a P10 outcome.
* Readiness rows, preflight sub-rows, reproduction checks and raw artifact hashes render as plain text; no script errors (one 404 for the browser's automatic favicon request).
* Inputs present: package chooser, Lean directory, optional allowed-signers path, deadline; Run/Stop, phase, elapsed and log tails.
* Not exercised in a browser: Stop during a run, the download button, upload progress (the API paths are covered by automated tests; the report was fetched through the API).
