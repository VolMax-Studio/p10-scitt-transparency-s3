# Candidate capture-and-verification command (for review; nothing is authorized to run)

Status: **PROPOSAL. Normative S3-B has not been started and must not start before the operator explicitly authorizes the deployment-definition freeze.** This file fixes the commands so that the freeze can be reviewed against them. The sequence below is exactly what was exercised once, with throwaway keys and a throwaway configuration, in `ts-prototype/evidence/qualification-auth-ml2/` (exploratory); it has not been run with the candidate key set.

## Preconditions

0. **Freeze set.** From the repository root, `sha256sum -c deployment/candidate/freeze-set.sha256` reports every file OK (the exact files listed in `deployment/candidate/FREEZE_CANDIDATE.md`; this is the set the operator would freeze, and it is checked here, not assumed).
1. **Source pin.** The checkout's `HEAD` satisfies the check recorded in `definition-manifest.json`:
   `git diff --quiet 10638c239b27d7c87b238a6f387c95882162c4dc HEAD -- ts-prototype/cmd ts-prototype/internal ts-prototype/producer ts-prototype/scripts ts-prototype/go.mod ts-prototype/go.sum`
   and `git status --porcelain -- ts-prototype ':!ts-prototype/evidence'` is empty (the capture phase refuses otherwise).
2. **Go binaries** (recipe; the hashes in the manifest are those of the two builds in the recorded experiment, not a reproducibility guarantee):
   `cd ts-prototype && CGO_ENABLED=0 go build -trimpath -buildvcs=false -o $BIN ./cmd/...` with go1.24.7. Compare with `go_binaries_sha256_from_that_recipe`; a difference is a finding to report, not something to work around.
3. **Entry and G5**: `verifier/artifacts/s3-spike-entry` and `s3-g5`, SHA-256 in `verifier/artifacts/SHA256SUMS` and `verifier/runner/PINNED_INPUTS.json`. Build record: `verifier/artifacts/BUILD_RECORD.md`.
4. **Checkouts and toolchains** (runner prerequisites at this candidate): S1/S2a/S2b clean at the pinned commits; pinned Lean (hashes in `PINNED_INPUTS.json`; native `libuv` development library present); Rust 1.82.0 (a current runner prerequisite: the preflight requires `rustc -V`, run inside `spike/s3-entry`, to report 1.82.0, even though only the supplied binaries are executed; the preflight also expects the repository layout, so the runner is not yet usable from the package alone); CPython 3.13 (tested: 3.13.16); Linux x86_64 with unprivileged network namespaces.
5. **Keys.** The private keys of the candidate set exist in the custody directories named in the environment file. They were generated outside the repository and are not part of it. The `install` phase refuses to continue unless the thumbprints computed from the key files equal those in the definition. If the custody set is lost or replaced, the definition's key-dependent values (thumbprints, profile digest, instance commitment, subject, `LogIdentityV0`, bootstrap payload hashes) are void and must be regenerated and re-reviewed.

## Commands

```
cd REPO                                                     # the checkout; all commands run from its root
cp deployment/candidate/env.example.sh ENV                  # then edit ONLY the <...> paths in ENV
set -a; . ./ENV; set +a                                     # source ENV in THIS shell: the commands below use $OUT, $S1, $S2A, $S2B, $ENTRY, $G5, $LEAN_BIN
bash ts-prototype/scripts/run_lifecycle.sh install ./ENV    # public configuration from the definition; checks manifest hashes and key custody; no key generation
bash ts-prototype/scripts/run_lifecycle.sh capture ./ENV    # facade + runtime issuer tooling + capture client, public export, capture assembly, ANCHOR.sha256 (stops here)
git add "$OUT" && git commit -m "S3-B capture and anchor"    # the OPERATOR records the anchor BEFORE verification (operator-generated record, not an independent channel)
bash ts-prototype/scripts/run_lifecycle.sh verify ./ENV     # prototype checks F0-F8, G5 with the recorded anchor, the unchanged chain (network-isolated)
python3 -B verifier/runner/s3c_verify.py --capture "$OUT/capture" --anchor-file "$OUT/ANCHOR.sha256" --out RUNNER_OUT \
    --s1 "$S1" --s2a "$S2A" --s2b "$S2B" --entry "$ENTRY" --g5 "$G5" --lean-bin-dir "$LEAN_BIN"      # candidate acceptance runner; RUNNER_OUT must be outside "$OUT/capture"
```

`run_lifecycle.sh` sources ENV itself, but the later commands run in the parent shell, so ENV must have been sourced there first (`set -a` exports the variables). `ENV` is a plain shell file: no `<...>` placeholder may remain.

**Reviewed offline invocation (`verifier/runner/CONTRACT.md` §4a).** The runner command above is the normative one only as written: no `--no-offline`, no `--pinned` (the reviewed `verifier/runner/PINNED_INPUTS.json` is used), `--out` outside the capture. After it, check in `RUNNER_OUT`: exit code 0; `verdict.json` `outcome` is `BINDING_MATCH`; `verdict.json` `executables_pinned` is `{"entry": true, "g5": true}`; `run-info.json` `network_isolated` is `true`; `run-info.json` `runner_source_sha256` equals the reviewed hashes (`s3c_verify.py` `7e6c457a…f628`, `s3c_chain.py` `de3450bb…0494`). If any of these fails the run is diagnostic and is not offline acceptance. The `verify` phase of `run_lifecycle.sh` is the prototype-check and glue-chain pass and does not replace this runner run.

Two invocations bracket the anchor commit on purpose: the anchor must exist before anything verifies the capture. Expected for the runner: exit 0, `BINDING_MATCH`. Any other result is reported as it is.

## After a successful acceptance

No registration is planned under this log identity. The selected plan (D8) is one-use retirement of the Receipt and checkpoint keys, executed manually by the operator, with its own record: `spec/operator-record-receipt-key-retirement.md`. Nothing here deletes a key, and nothing is deleted before the operator has confirmed local decryption of the custody packages and matching public fingerprints (`deployment/candidate/custody/verify_custody.py`).
