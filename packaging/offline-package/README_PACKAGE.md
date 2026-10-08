# Portable offline verification package — accepted S3 capture (P10 Transparency Log Deployment and Offline Capture Verification)

**What this is.** A directory (shipped as one tarball) holding the accepted S3-B capture, its anchor, both standalone-runner records, the signed tags, the exact runner sources and supplied entry/G5 binaries, and the pinned S1/S2a/S2b repositories with Git metadata, laid out the way the runner needs, plus one command that replays the offline verification and compares the new verdict with the accepted one.

**What it is not.** It does **not** carry the host toolchains and does **not** claim to work on arbitrary machines. It was validated on one host only (Linux x86_64 container, kernel 6.18, CPython 3.13, rustc 1.82.0, Lean 4.33.0). It contains no private key, no encrypted custody package and no age identity. It does not accept the capture (acceptance is the operator's signed tag), it does not retire any key, and it does not change any frozen file.

## Contents

| Path | What |
|---|---|
| `repo/` | Git clone of the S3 repository, detached at `e56d3ea8bbe14c9c88a0dde339c29b55b1032a66` (carries the accepted capture, anchor, `runner/` and `runner-2/` records, the runner, `verifier/artifacts/` binaries, all 99 frozen files, and the tags below) |
| `deps/s1`, `deps/s2a`, `deps/s2b` | clean clones detached at the pinned commits `e4db3747…`, `741d56d3…`, `8eaa91ca…` (tags `v0.1.0-s1-ratified`, `v0.1.0-s2a-ratified`, `v0.1.0-s2b-complete` peel to them). Build outputs (`.lake`, `target/`) are not carried |
| tags in `repo/` | `v0.1.0-s3a-frozen` (object `8f0c97f3745131f79936dec71ebe09316332f5ab` → `7c3b2d4b919c356a566f8f5d3628d4f546e41afa`) and `v0.1.0-s3-accepted` (object `4148a7403e8d5ed0a30ca878d617323bb3a75b3a` → `5acc277a13dc122e39fcb5f9f3e646b06cc95009`), both SSH-signed by the operator |
| `verify_offline.sh` | the one verification command |
| `PACKAGE_SHA256SUMS` | SHA-256 of every file of the package except `.git/` directories, itself and `out/` |
| `git-state.txt` | commits, tag objects and tag targets of the four repositories at packaging time |
| `PACKAGING_RECORD.md` | how the package was made and validated |

## Host prerequisites (declared, verified by the script, not carried)

Linux x86_64 with unprivileged network namespaces (`unshare -n` or `-rn`); CPython 3 (tested: 3.13); `git`, `sha256sum`, `cmp`; **Rust 1.82.0** selected by `repo/spike/s3-entry/rust-toolchain.toml` (the runner's preflight requires `rustc -V` there to report 1.82.0, although only the supplied binaries are executed); the pinned conda-forge **Lean 4.33.0** (`lean`, `lake`, with the hashes recorded in `repo/verifier/runner/PINNED_INPUTS.json`) and the native `libuv` development library needed by the Lean link step. Building the Lean sides of S2a/S1 happens on the first run on a host (`.lake` is not carried), takes time, and writes only ignored build directories inside `deps/`.

## Install

```
tar -xzf p10-s3-offline-e56d3ea.tar.gz        # into a fresh directory; verify the tarball first: sha256sum -c p10-s3-offline-e56d3ea.tar.gz.sha256
cd p10-s3-offline
```

## The offline verification command

```
LEAN_BIN=/path/to/pinned/lean/bin ./verify_offline.sh
```

It (1) checks the prerequisites above, (2) checks package integrity, the Git state, the tag objects, the pinned dependency commits, the 99 frozen files, the anchor and the accepted verdict, (3) stops without running anything if any of that fails, (4) runs the unchanged standalone runner (no `--no-offline`, no `--pinned`; it creates and measures the network namespace) into a fresh `out/run-<time>/` directory, and (5) only after the run compares the new `verdict.json` byte for byte with the accepted `runner/verdict.json` (SHA-256 `6368022f06cc6ef6e4c9698cd45e71c44db505b4bf8b5812aaf0cbe26f41db22`) and `runner-2/verdict.json`, and checks the acceptance conditions (`BINDING_MATCH`, both executable pins matched, measured `network_isolated=true`, runner and binary hashes). It prints `ALL PASS` and exits 0 only if everything holds; a failure is reported and its output is preserved.

Optional: `ALLOWED_SIGNERS=/path/to/allowed_signers LEAN_BIN=… ./verify_offline.sh` also verifies the two tag signatures against the operator's public key (`git verify-tag` with `gpg.ssh.allowedSignersFile`). Without that file the script only confirms that each tag carries a signature block; **signature validity is not established by this package alone.**

## Reading the result

`BINDING_MATCH` with a byte-identical `verdict.json` means: on this host, with these inputs and pins, the unchanged frozen P10 chain reproduces the accepted offline verdict. It is a reproduction, not a new acceptance, and not a claim about other hosts, other toolchains, the candidate keys' custody, or anything the S3 non-claims exclude (policy enforcement, operator independence, RFC 9943 / SCRAPI compliance).
