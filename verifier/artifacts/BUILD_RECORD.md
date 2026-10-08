# Executable artifacts of the candidate S3-C chain: exact bytes and build record

Status: **CANDIDATE; nothing adopted.** `s3-spike-entry` and `s3-g5` here are the exact bytes the candidate runner was validated with (`verifier/runner/PINNED_INPUTS.json` `executables`, SHA-256 in `SHA256SUMS`). They are supplied so that a reviewer can run the candidate runner with `--entry verifier/artifacts/s3-spike-entry --g5 verifier/artifacts/s3-g5` and have the runner's executable-identity check pass; recording their hashes alone would not let anyone do that.

| Artifact | SHA-256 | Source (tree at commit `10638c2`, unchanged for these crates since the commits shown) | Profile |
|---|---|---|---|
| `s3-spike-entry` | `53ba44408b1de7322010681f45bb4aa576931f0974c448d9e6b7a662683ca863` | `spike/s3-entry` (last changed in `23ba96f`): `src/main.rs` `a6bb33d4…`, `Cargo.lock` `d0283512…`, `Cargo.toml` `b729e1f4…` | debug (unoptimized + debuginfo) |
| `s3-g5` | `a2b4b1efeda26302ec5f0710905c46f7c180ad862035959d47ba1e33305ee0bd` | `verifier/g5` (last changed in `8d154b5`): `src/lib.rs` `ab5634a8…`, `src/main.rs` `c63b9bf9…`, `Cargo.lock` `1551158b…`, `Cargo.toml` `fd7e2a49…` | debug |

## How they were produced

- Commands (from `spike/host/run_host.sh` steps 2 and 2b and `verifier/g5/README.md`): `cd spike/s3-entry && cargo build --locked --offline` and `cd verifier/g5 && cargo build --locked --offline`, in the repository checkout at the paths `spike/s3-entry` and `verifier/g5`, with the pinned S2b checkout (`8eaa91cad1ffa963158b365c6d0d7316f4965e89`, clean) linked at the relative path `../.deps/s2b` that both `Cargo.toml` files use for the `p10_replay` path dependency.
- Toolchain: `rustc 1.82.0 (f6e511eec 2024-10-15)`, `cargo 1.82.0 (8f40fc59f 2024-08-21)` (selected by each crate's `rust-toolchain.toml`, channel 1.82.0), host `x86_64-unknown-linux-gnu`, LLVM 19.1.1.
- Host: Linux 6.18.44 x86_64 container. The crates' dependencies are the versions in the committed `Cargo.lock` (`--locked`); for the entry crate every package except the crate itself is identical to the S2b `Cargo.lock` (`spike/PINS.json`).
- The binaries were built in the repository tree on the validation host and then pinned by hash; the hashes were computed again when the files were copied here and equal the pinned values.

## What is and is not claimed

- Claimed: these bytes are the ones validated and pinned; the runner refuses a different executable.
- **Not claimed:** reproducible compilation. In the recorded experiment (`spec/deployment-profile-evidence/build-repro.txt`) a clean rebuild of the entry crate in the same directory was byte-identical, but builds placed in two different directories differed (debug and release, with and without `--remap-path-prefix`; cause not investigated). These two artifacts were not rebuilt for this record. A reviewer who rebuilds them elsewhere should expect different hashes and compare behaviour (the validation suite), not bytes.
- The binaries embed build-time absolute paths and debug information of the validation host.
