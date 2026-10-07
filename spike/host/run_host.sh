#!/usr/bin/env bash
# NON-NORMATIVE FEASIBILITY SPIKE. Single host command for the traced S3-C chain over the ratified controls and the volmax-owner fixture.
#
#   spike/host/run_host.sh --s1 <S1 checkout> --s2a <S2a checkout> --s2b <S2b checkout> --out <empty output dir> [--lean-bin-dir <dir with pinned lean>] [--no-offline]
#
# Required checkouts (clean, detached at the pinned commits; preflight verifies): S1 e4db3747..., S2a 741d56d3..., S2b 8eaa91ca...
# Preparation (may use a network): obtaining checkouts and the pinned Lean, `cargo fetch --locked`.
# Chain execution: run under `unshare -n` (no network) when available; pass --no-offline to skip (then the log says so).
# Stops on the first failed required prerequisite or failed stage. Never substitutes expected outputs: expected artifacts are only compared.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; SPIKE="$(dirname "$HERE")"; REPO="$(dirname "$SPIKE")"
S1=""; S2A=""; S2B=""; OUT=""; LEANBIN=""; OFFLINE=1
while [ $# -gt 0 ]; do case "$1" in
  --s1) S1="$2"; shift 2;; --s2a) S2A="$2"; shift 2;; --s2b) S2B="$2"; shift 2;; --out) OUT="$2"; shift 2;;
  --lean-bin-dir) LEANBIN="$2"; shift 2;; --no-offline) OFFLINE=0; shift;; *) echo "unknown argument $1" >&2; exit 2;; esac; done
for v in S1 S2A S2B OUT; do [ -n "${!v}" ] || { echo "missing --$(echo $v | tr 'A-Z' 'a-z')" >&2; exit 2; }; done
S1="$(cd "$S1" && pwd)"; S2A="$(cd "$S2A" && pwd)"; S2B="$(cd "$S2B" && pwd)"
mkdir -p "$OUT"; OUT="$(cd "$OUT" && pwd)"
[ -z "$(ls -A "$OUT")" ] || { echo "output dir $OUT is not empty" >&2; exit 2; }
[ -n "$LEANBIN" ] && export P10_LEAN_BIN_DIR="$LEANBIN"
LOG="$OUT/host.log"; exec > >(tee -a "$LOG") 2>&1
step() { echo; echo "=== $*"; }
die() { echo "STOP: $*" >&2; exit 1; }

step "host"; { date -u +%FT%TZ; uname -a; python3 --version; cargo --version 2>&1 | head -1; git --version; } | tee "$OUT/host.txt"

step "1 preflight (each toolchain/source against its own frozen pin)"
python3 -B "$HERE/preflight.py" --s1 "$S1" --s2a "$S2A" --s2b "$S2B" ${LEANBIN:+--lean-bin-dir "$LEANBIN"} --out "$OUT/preflight.json" || die "preflight failed: see the MISSING/WRONG lines above"

step "2 build the S3 spike entry against the pinned S2b crate (cargo --locked)"
ln -sfn "$S2B" "$SPIKE/.deps/s2b" 2>/dev/null || { mkdir -p "$SPIKE/.deps" && ln -sfn "$S2B" "$SPIKE/.deps/s2b"; }
( cd "$SPIKE/s3-entry" && rustc -V && cargo fetch --locked && cargo build --locked --offline ) || die "entry build failed"
ENTRY="$SPIKE/s3-entry/target/debug/s3-spike-entry"; sha256sum "$ENTRY" | tee "$OUT/entry.sha256"

step "3 cases (controls reuse ratified S2b fixtures unchanged; plus spike/fixtures/*)"
python3 -B "$HERE/make_cases.py" --s2b "$S2B" --fixtures "$SPIKE/fixtures" --out "$OUT/cases.json" || die "make_cases failed"

RUNNER=(env)
if [ "$OFFLINE" = 1 ]; then
  if unshare -n true 2>/dev/null; then RUNNER=(unshare -n); echo "chain execution: network namespace without network (unshare -n)"; else echo "WARNING: unshare -n unavailable; chain execution is NOT network-isolated"; fi
else echo "chain execution: network isolation skipped (--no-offline)"; fi

for n in 1 2; do
  step "4.$n chain run $n (S2b -> S2a -> post-S2a with real closureAt helper)"
  "${RUNNER[@]}" python3 -B "$HERE/../glue/s3_spike_chain.py" --cases "$OUT/cases.json" --out "$OUT/run$n" --s2b "$S2B" --s2a "$S2A" --entry "$ENTRY"
  rc=$?; echo "run $n exit=$rc"; [ $rc -eq 0 ] || die "chain run $n did not fully pass (see $OUT/run$n/report.json; NOT RUN stages mean a missing prerequisite)"
done

step "5 repeatability of run 1 vs run 2 (verdicts, tB bytes, helper binaries; logs/timestamps/paths excluded)"
python3 -B "$HERE/compare_runs.py" "$OUT/run1" "$OUT/run2" "$OUT/repro.json" || die "runs differ"

step "6 hashes of every output file"
( cd "$OUT" && find . -type f ! -name host.log ! -name OUTPUT_HASHES.txt -print0 | sort -z | xargs -0 sha256sum > OUTPUT_HASHES.txt ); wc -l "$OUT/OUTPUT_HASHES.txt"
echo; echo "HOST RUN COMPLETE. Feasibility evidence only; not ratification, freeze or acceptance."
