# G5 r5 regression results (executed in the container)

- `bug-reproduction.txt`: the r4 inventory defect reproduced with the r4 binary (a root file literally named `prefix\000001.cose` beside the legitimate `prefix/000001.cose` gave `PASS`), and the r5 result for the same capture (`E_PATH_UNSAFE`, exit 30).
- `g5-unit-tests.txt`: 7 unit tests, including the backslash-name regression, the non-UTF-8 name and the component policy.
- `g5report.json` / `g5tests.console`: 34 cases, all as expected (`all_ok: true`): 2 passes (BASE, N-D1) and 32 expected failures. New relative to r4: X-P3 (the backslash-name regression), X-P4 (non-UTF-8 name), X-P5 (control character in a name), each `E_PATH_UNSAFE`, exit 30, chain not invoked. The chain was invoked exactly twice (BASE, N-D1), under `unshare -n`.
- G5 binary: `g5-binary.sha256`.

Correction of the r4 summary (`../container-run/RESULTS.md`, kept as written): the r4 run had 31 cases, of which 2 passed and 29 were expected failures; the summary's "28 G5 failures" was a miscount. The r4 raw outputs are unchanged.
