# P10 Replay Workbench (v0.1)

A local, single-user web application that **reproduces the accepted S3 capture offline from the exact rev2 offline package**.
It runs the package's unchanged `verify_offline.sh` and runner; it does not verify anything itself. It shows three independent
results, keeps the raw records, and exports a report. Design: [`ARCHITECTURE.md`](ARCHITECTURE.md) (the reviewed blueprint, copied unchanged).

Python 3.12+ standard library only; HTML/CSS/JavaScript served locally. No npm, CDN, database, network access or private key.
Linux x86_64 first.

## What you need on the HP (host prerequisites, not carried by the package)

* The approved package: `p10-s3-offline-e56d3ea-rev2.tar.gz`, SHA-256 `e19f8d84cac0ecb2de61dbd0e7085014d525829ba51007b7fdaa24895df37d9b`.
  Any other archive is rejected as `UNSUPPORTED_PACKAGE` before extraction (an application status, not a P10 outcome).
* Commands: `python3` (3.12+), `git`, `unshare`, `rustc` **1.82.0** (rustup toolchain installed beforehand; the app never installs anything), `sha256sum`, `cmp`, `tar`, `bash`, a C toolchain with libuv (`cc ... -luv`).
* The pinned Lean 4.33.0 `bin` directory (containing `lean` and `lake`) installed locally; you give its absolute path in the UI.
* Unprivileged network namespaces (`unshare -n`, or `unshare -rn`). If AppArmor/sysctl blocks them, the readiness check reports a host-setup problem; the app does not change host policy. Handle it as you did for the earlier HP replay and restore the setting afterwards.
* Optional: the **public** allowed-signers file (absolute path) to verify the two signed tags. Without it the UI shows *Signature not checked*.
* About 5 GiB free disk and, for the first replay (it builds Lean helpers), several GiB of available memory. The worker runs at lower priority on at most two CPUs; that is scheduling only, not a RAM limit. Use **Stop** if the machine becomes sluggish.

## Launch

From a checkout of this repository:

```bash
python3 apps/replay-workbench/run.py
```

It prints a URL such as `http://127.0.0.1:41873/#token=...` and opens it in your browser (use `--no-browser` to only print it). Open that exact URL,
including the `#token=` part, in a browser on the same machine. Options: `--workspace DIR` (default `~/.local/share/p10-replay-workbench/`, mode 0700),
`--port N`, `--deadline-minutes N` (default 60). Stop with Ctrl+C; an active job is stopped first.

## Use

1. **Import package** – choose the `.tar.gz`; the app hashes it while streaming (limit 64 MiB), checks the approved digest, then extracts it safely into its private workspace (the archive and extraction are kept; the next start reuses them, which also reuses ignored Lean build caches).
2. Type the **Lean bin directory** (and optionally the allowed-signers file). Browsers do not reveal absolute paths, so these are text fields.
3. **Check readiness** – mechanical diagnostics (commands, Rust, Lean, namespace method, `sha256sum -c` exit status of `PACKAGE_SHA256SUMS` and the frozen set, pinned HEADs/tags/hashes, the existing `preflight.py` run offline, disk/memory). It never starts the wrapper or builds Lean. It is advisory and goes stale when you change an input.
4. **Run replay** – starts one dedicated worker; the wrapper runs under a fresh network namespace. Phases come from the wrapper's own headers (navigation only). **Stop** sends TERM to the job's process group, then KILL after 5 s. Closing the tab does not cancel the job. Only one job can be active; a second start is refused.
5. Read the **three result panels**, open the details (hashes, check list, raw `verdict.json` / `run-info.json`), and **Export report archive** (`replay-report-<job>.tar.gz` with `app-report.json`, the original records, logs, the profile copy and `REPORT_SHA256SUMS`). Exports may contain local host names and paths.

## The three result axes (never merged)

| Axis | Values | Source |
|---|---|---|
| Application execution | `BLOCKED`, `RUNNING`, `COMPLETED`, `CANCELLED`, `APP_FAILURE` | the app's supervisor |
| P10 runner outcome | `BINDING_MATCH`, `REJECT`, `HALT`, `S3-FAIL(packaging)`, `S3-FAIL(infrastructure)`, or *not evaluated* | the original `verdict.json` |
| Accepted-result reproduction | `MATCH`, `DIFFERENT`, `NOT_EVALUATED` (badge **Accepted replay reproduced** only if every condition in blueprint section 6 holds) | post-run comparison |

The wrapper's exit status (0 success, 1 failed replay/comparison, 2 prerequisite refusal, 3 test mode) is shown separately and is **not** a P10 outcome. A wrapper exit 1 never becomes "REJECT" unless a valid `verdict.json` says so.
`BINDING_MATCH` concerns the authenticated capture and the frozen chain; it is not evidence of scientific truth, policy enforcement, full RFC 9943/SCRAPI compliance or independent operators.

## Tests

```bash
python3 -m unittest discover -s apps/replay-workbench -t apps/replay-workbench -p "test_*.py"
```

The tests use injected synthetic dependencies (synthetic archives and records, a scripted command context and a **stub module**). A stub run is labelled
*SYNTHETIC TEST RUN – not an offline P10 run* in status, report and UI, and can never earn the reproduction badge. Production accepts only the shipped
profile; there is no HTTP or environment switch for synthetic packages or custom scripts. See `evidence/` for recorded test output, the manual UI notes and the app-local manifest.

## Scope and remaining limitations

* One module (S3 rev2). New captures or modules need a separately reviewed profile; uploaded archives cannot supply executable code.
* The app does not reimplement any P10, COSE/CBOR, Lean or transcript logic; record validation is structural only (bounded UTF-8 JSON, duplicate keys and non-finite numbers rejected, expected field types).
* Loopback plus a per-session token is not a security boundary against a malicious process of the same user. Host/Origin/token checks, a restrictive CSP and text-only rendering protect against browser-based cross-origin access and hostile log text.
* Priority and CPU affinity do not limit RAM and do not guarantee desktop responsiveness. The first replay can be slow and memory-hungry.
* Signature validity is checked only when you supply a public allowed-signers file; otherwise it is reported as not checked.
* Reports are generated by this application and are not independent attestations. Timestamps are local.
* The real HP run through this interface has to be performed by the operator; cloud-container integration runs recorded in `evidence/` are not HP runs.
* No automatic acceptance, key retirement, signing, tagging or publication exists in the application.
