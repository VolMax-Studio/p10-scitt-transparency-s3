#!/usr/bin/env bash
# NON-NORMATIVE DRY RUN of the provisional capture procedure against the Tessera candidate (a log engine, NOT a SCITT transparency service).
#
#   run_dryrun.sh --s2a D --s2b D --fixture D --statements D --keys-dir D --probe BIN --py PYTHON --glue F --entry BIN --g5 BIN --out D
#                 [--ts-origin 0,1] [--roles ...] [--issuers a,b]
#
# 1. the probe (Go, Tessera v1.0.4 POSIX storage) registers each submitted statement sequentially, as LeafEncodeV0 leaf inputs, waits for the checkpoint
#    that commits to it, and retains: submissions/, the entry bundles' exported leaves (export/), per-registration receipt inputs;
# 2. issue_receipts.py (reference Receipt issuer sketch) issues one COSE Receipt per registration from those receipt inputs;
# 3. assemble_capture.py builds the capture directory AND request.cbor from the retained bytes;
# 4. G5 checks the capture against an anchor computed here (SELF-ANCHORED: a dry run, not acceptance);
# 5. the unchanged chain runs on G5's returned paths (spike glue).
set -euo pipefail
A=(); while [ $# -gt 0 ]; do case "$1" in --*) k="${1#--}"; declare "o_${k//-/_}=$2"; shift 2;; *) echo "bad arg $1" >&2; exit 2;; esac; done
OUT="$o_out"; mkdir -p "$OUT"; [ -z "$(ls -A "$OUT")" ] || { echo "out not empty" >&2; exit 2; }
RET="$OUT/retained"; mkdir -p "$RET"
echo "== 1 register through the log engine"; "$o_probe" --statements "$o_statements" --out "$OUT/engine" | tail -1 >/dev/null
cp -r "$OUT/engine/retained/." "$RET/"
mkdir -p "$RET/provenance"
cp "$OUT/engine/probe-result.json" "$RET/provenance/probe-result.json"
printf 'log engine: github.com/transparency-dev/tessera v1.0.4 (tag commit 6bca8e8d5e23c9941f2b8a08f512b373f7131730), storage/posix\n' > "$RET/provenance/log-engine.txt"
sha256sum "$(dirname "$0")"/issue_receipts.py "$(dirname "$0")"/assemble_capture.py > "$RET/provenance/dryrun-tool-sha256.txt"
echo "== 2 issue Receipts (reference sketch)"; "$o_py" -B "$(dirname "$0")/issue_receipts.py" --s2b "$o_s2b" --fixture "$o_fixture" --keys-dir "$o_keys_dir" --retained "$RET"
echo "== 3 assemble capture and request.cbor from retained bytes"
"$o_py" -B "$(dirname "$0")/assemble_capture.py" --s2b "$o_s2b" --fixture "$o_fixture" --retained "$RET" --out "$OUT/capture" ${o_ts_origin:+--ts-origin "$o_ts_origin"} ${o_roles:+--roles "$o_roles"} ${o_issuers:+--issuers "$o_issuers"} | tee "$OUT/assemble.json"
if cmp -s "$OUT/capture/request.cbor" "$o_fixture/request.cbor"; then echo "request.cbor built from retained bytes is BYTE-IDENTICAL to the fixture generator's request"; else echo "request.cbor differs from the fixture's request (informational)"; fi
echo "== 4 G5 (self-anchored dry run)"
ANCHOR="$(sha256sum "$OUT/capture/capture.json" | cut -d' ' -f1)"
"$o_g5" --capture "$OUT/capture" --index-sha256 "$ANCHOR" | tee "$OUT/g5.json"; grep -q '"g5":"PASS"' "$OUT/g5.json"
echo "== 5 chain on G5-returned paths"
python3 -B "$(dirname "$0")/../../spike/host/make_capture_cases.py" --id DRYRUN --g5-result "$OUT/g5.json" --expect "$o_fixture/expect.json" --out "$OUT/cases.json"
unshare -n python3 -B "$o_glue" --cases "$OUT/cases.json" --out "$OUT/chain" --s2b "$o_s2b" --s2a "$o_s2a" --entry "$o_entry"
