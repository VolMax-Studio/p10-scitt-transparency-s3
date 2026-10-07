#!/usr/bin/env bash
# NON-NORMATIVE FEASIBILITY SPIKE. Single host command for the traced S3-C chain over the ratified controls and the volmax-owner fixture.
#
#   spike/host/run_host.sh --s1 <S1 checkout> --s2a <S2a checkout> --s2b <S2b checkout> --out <empty output dir> [--lean-bin-dir <dir with pinned lean>] [--no-offline]
#
# Required checkouts (clean, detached at the pinned commits; preflight verifies): S1 e4db3747..., S2a 741d56d3..., S2b 8eaa91ca...
# Preparation (may use a network): obtaining checkouts and the pinned Lean, `cargo fetch --locked`.
# Chain execution: DEFAULT is network-isolated (`unshare -n`, else `unshare -rn`) and the isolation is tested; if isolation cannot be established the
# run STOPS. Only an explicit --no-offline permits a connected run, which is labelled CONNECTED RUN in the log and in OFFLINE_STATUS.txt.
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

# the Lean directory that passed the pin checks is the one the S2b launchers must use
SEL="$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['selected_lean_bin_dir'] or '')" "$OUT/preflight.json")"
[ -n "$SEL" ] || die "preflight selected no Lean directory"
export P10_LEAN_BIN_DIR="$SEL"; echo "Lean directory used by the launchers: $SEL"

step "2 build the S3 spike entry against the pinned S2b crate (cargo --locked)"
ln -sfn "$S2B" "$SPIKE/.deps/s2b" 2>/dev/null || { mkdir -p "$SPIKE/.deps" && ln -sfn "$S2B" "$SPIKE/.deps/s2b"; }
( cd "$SPIKE/s3-entry" && rustc -V && cargo fetch --locked && cargo build --locked --offline ) || die "entry build failed"
ENTRY="$SPIKE/s3-entry/target/debug/s3-spike-entry"; sha256sum "$ENTRY" | tee "$OUT/entry.sha256"

step "2b candidate G5 (verifier/g5): build, unit tests, and the correspondence check of the committed test capture against its external anchor"
VER="$REPO/verifier"; mkdir -p "$VER/.deps" && ln -sfn "$S2B" "$VER/.deps/s2b"
( cd "$VER/g5" && cargo build --locked --offline && cargo test --locked --offline --lib ) || die "G5 build or unit tests failed"
CAPDIR="$REPO/tests/offline/g5/fixtures/volmax-owner-capture"
ANCHOR="$(grep -E '  tests/offline/g5/fixtures/volmax-owner-capture/capture.json$' "$REPO/MANIFEST.sha256" | cut -d' ' -f1)"
[ -n "$ANCHOR" ] || die "no MANIFEST.sha256 anchor for the committed test capture's capture.json (regenerate MANIFEST.sha256)"
"$VER/g5/target/debug/s3-g5" --capture "$CAPDIR" --index-sha256 "$ANCHOR" | tee "$OUT/g5-committed-capture.json"
grep -q '"g5":"PASS"' "$OUT/g5-committed-capture.json" || die "G5 did not pass on the committed test capture"

step "3 cases (controls reuse ratified S2b fixtures unchanged; plus spike/fixtures/*)"
python3 -B "$HERE/make_cases.py" --s2b "$S2B" --fixtures "$SPIKE/fixtures" --out "$OUT/cases.json" || die "make_cases failed"

RUNNER=(env)
if [ "$OFFLINE" = 1 ]; then
  ISO=""
  for cand in "unshare -n" "unshare -rn"; do
    if $cand true 2>/dev/null; then ISO="$cand"; break; fi
  done
  [ -n "$ISO" ] || die "network isolation could not be established (neither 'unshare -n' nor 'unshare -rn' works). Re-run with an environment that allows it, or pass --no-offline to accept a CONNECTED run (it will be labelled as such)."
  # test the isolation from inside the namespace: no interface other than loopback may exist (independent of any egress policy), and no
  # external TCP connection may succeed
  if $ISO python3 -c "
import socket,sys
names=[n for _,n in socket.if_nameindex()]
if any(n!='lo' for n in names):
    sys.exit(1)
for fam,addr in ((socket.AF_INET,('1.1.1.1',53)),(socket.AF_INET6,('2606:4700:4700::1111',53))):
    try:
        s=socket.socket(fam,socket.SOCK_STREAM); s.settimeout(3)
        s.connect(addr)
    except OSError:
        continue            # unsupported family or unreachable: isolated for this family
    sys.exit(1)             # a connection succeeded: not isolated
sys.exit(0)"; then
    echo "network isolation established and tested: $ISO (loopback only; no external TCP connection possible)"
  else
    die "network isolation test failed: a non-loopback interface or an external address was reachable inside '$ISO'. Pass --no-offline to accept a CONNECTED run."
  fi
  RUNNER=($ISO); echo "network-isolated: yes ($ISO)" > "$OUT/OFFLINE_STATUS.txt"
else
  echo "*** CONNECTED RUN (--no-offline): chain execution is NOT network-isolated ***"
  echo "network-isolated: NO (--no-offline)" > "$OUT/OFFLINE_STATUS.txt"
fi

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
