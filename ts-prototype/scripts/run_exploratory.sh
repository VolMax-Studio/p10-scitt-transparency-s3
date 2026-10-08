#!/usr/bin/env bash
# EXPLORATORY seven-leaf lifecycle through the candidate facade (NON-NORMATIVE; not acceptance evidence).
#   run_exploratory.sh capture  <env>   start facade, submit via capture client, export via public HTTP, facade/public-read checks, assemble capture, write ANCHOR
#   run_exploratory.sh accept   <env>   G5 with the recorded anchor, then the unchanged chain on G5-returned paths (network-isolated)
# <env> is a shell file defining: BIN PY S2A S2B ENTRY G5 GLUE KEYS NOTE_KEYS FIXTURE STATEMENTS OUT [DETACHED] [LABEL] [PORT] [LEAN_BIN]
set -euo pipefail
phase="$1"; . "$2"; HERE="$(cd "$(dirname "$0")" && pwd)"; REPO="$(cd "$HERE/../.." && pwd)"
VKEY="$(cat "$NOTE_KEYS/note.vkey")"; ORIGIN="${VKEY%%+*}"; PORT="${PORT:-19500}"
TS_ISS="$("$PY" -c "import json,sys;print(json.load(open('$FIXTURE/PUBLIC_META.json'))['identity']['ts_iss'])")"
THUMB="$("$PY" -c "import json,sys;print(json.load(open('$FIXTURE/PUBLIC_META.json'))['identity']['ts_key_thumbprint'])")"
if [ "$phase" = capture ]; then
  [ ! -e "$OUT" ] || [ -z "$(ls -A "$OUT")" ] || { echo "OUT not empty" >&2; exit 2; }
  mkdir -p "$OUT/run" "$OUT/operator"
  WORK="$(mktemp -d)"   # Tessera storage lives here (operator side); the capture client never sees it
  "$BIN/s3-facade" --storage "$WORK/log" --state "$OUT/operator/state" --origin "$ORIGIN" --note-skey-file "$NOTE_KEYS/note.skey" --note-vkey "$VKEY" \
     --cose-key "$KEYS/ts.pem" --ts-iss "$TS_ISS" --expect-thumbprint "$THUMB" --register-addr 127.0.0.1:$PORT --public-addr 127.0.0.1:$((PORT+1)) 2> "$OUT/operator/facade.stderr" &
  FPID=$!; trap 'kill $FPID 2>/dev/null || true' EXIT
  for _ in $(seq 100); do curl -sf "http://127.0.0.1:$PORT/config" -o "$OUT/operator/facade-config.json" && break; sleep 0.1; done
  echo "== submit (issuer/operator side) and retain returned Receipts and public checkpoints"
  DET=(); [ -z "${DETACHED:-}" ] || DET=(--detached "$DETACHED")
  "$BIN/s3-capture" submit --facade "http://127.0.0.1:$PORT" --public "http://127.0.0.1:$((PORT+1))" --note-vkey "$VKEY" --origin "$ORIGIN" --statements "$STATEMENTS" --ts-origin "${TS_ORIGIN:-0,1}" "${DET[@]}" --out "$OUT/run"
  N="$(ls "$STATEMENTS"/*.cose | wc -l)"
  echo "== export from the PUBLIC read endpoint only"
  "$BIN/s3-capture" export --public "http://127.0.0.1:$((PORT+1))" --note-vkey "$VKEY" --origin "$ORIGIN" --expect-size "$N" --out "$OUT/run"
  kill $FPID; wait $FPID || true; trap - EXIT
  cp "$OUT/operator/state/journal.jsonl" "$OUT/operator/journal.jsonl.copy"
  echo "== facade/public-read checks (independent Python; NOT a frozen-chain verdict)"
  "$PY" -B "$HERE/s3check.py" --run "$OUT/run" --s2b "$S2B" --note-vkey "$VKEY" --origin "$ORIGIN" --ts-pub "$FIXTURE/public/ts.public.cose_key.cbor" --ts-iss "$TS_ISS" --out "$OUT/facade-checks.json" --expect "$N"
  mkdir -p "$OUT/extra"; cp "$OUT/facade-checks.json" "$OUT/operator/facade-config.json" "$OUT/extra/"; cp "$OUT/operator/journal.jsonl.copy" "$OUT/extra/facade-journal.jsonl"
  printf '%s\n' "$VKEY" > "$OUT/extra/note.vkey"
  { echo "label: ${LABEL:-exploratory}"; echo "log engine: github.com/transparency-dev/tessera v1.0.4 (6bca8e8d5e23c9941f2b8a08f512b373f7131730), storage/posix, antispam off"; echo "go: $(go version)"
    echo "EXPERIMENTAL bootstrap: leaves 0 and 1 are synthetic TEST statements (operator-submitted), not a policy and not enforced"; } > "$OUT/extra/provenance.txt"
  ( cd "$REPO" && sha256sum ts-prototype/cmd/*/main.go ts-prototype/internal/*/*.go ts-prototype/go.mod ts-prototype/go.sum ts-prototype/scripts/*.py ) > "$OUT/extra/prototype-source-sha256.txt"
  sha256sum "$BIN/s3-facade" "$BIN/s3-capture" > "$OUT/extra/prototype-binaries-sha256.txt"
  echo "== assemble capture and request.cbor from the retained bytes"
  "$PY" -B "$HERE/assemble_capture_v2.py" --s2b "$S2B" --fixture "$FIXTURE" --run "$OUT/run" --out "$OUT/capture" --extra "$OUT/extra" --ts-origin "${TS_ORIGIN:-0,1}" --roles "${ROLES:-}" | tee "$OUT/assemble.json"
  "$PY" -c "import json;print(json.load(open('$OUT/assemble.json'))['capture_json_sha256'])" > "$OUT/ANCHOR.sha256"
  echo "anchor recorded: $(cat "$OUT/ANCHOR.sha256")  ($OUT/ANCHOR.sha256)"
elif [ "$phase" = accept ]; then
  ANCHOR="$(cat "$OUT/ANCHOR.sha256")"
  echo "== G5 with the recorded anchor $ANCHOR"
  "$G5" --capture "$OUT/capture" --index-sha256 "$ANCHOR" | tee "$OUT/g5.json"; grep -q '"g5":"PASS"' "$OUT/g5.json"
  echo "== unchanged chain on G5-returned paths (network-isolated)"
  python3 -B "$REPO/spike/host/make_capture_cases.py" --id "${LABEL:-EXPLORATORY}" --g5-result "$OUT/g5.json" --expect "$FIXTURE/expect.json" --out "$OUT/cases.json"
  P10_LEAN_BIN_DIR="${LEAN_BIN:-}" unshare -n python3 -B "$GLUE" --cases "$OUT/cases.json" --out "$OUT/chain" --s2b "$S2B" --s2a "$S2A" --entry "$ENTRY"
else echo "bad phase" >&2; exit 2; fi
