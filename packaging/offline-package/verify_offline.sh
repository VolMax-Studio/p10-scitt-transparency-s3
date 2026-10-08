#!/usr/bin/env bash
# One offline verification command for the portable S3 package.
#   LEAN_BIN=/path/to/pinned/lean/bin ./verify_offline.sh [FRESH_OUTPUT_DIR]
# Checks prerequisites and package integrity FIRST (any mismatch stops here, nothing is run), then runs the unchanged standalone offline runner over the accepted capture,
# and only AFTER the run compares its verdict.json byte-for-byte with the accepted verdicts. Exit 0 only if everything holds. It modifies nothing under repo/ or deps/.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"; REPO="$HERE/repo"; DEPS="$HERE/deps"
EXPECT_HEAD=e56d3ea8bbe14c9c88a0dde339c29b55b1032a66
EXPECT_TAG_S3A=8f0c97f3745131f79936dec71ebe09316332f5ab; EXPECT_TAG_ACC=4148a7403e8d5ed0a30ca878d617323bb3a75b3a
EXPECT_VERDICT_SHA=6368022f06cc6ef6e4c9698cd45e71c44db505b4bf8b5812aaf0cbe26f41db22
EXPECT_ANCHOR=2662c2daf912d2ce4796a26b13464d7bc2df6ba8825fa399fed3a87185d700a7
S1=e4db3747eaeeb1a07227bb9029f9a9c3b566cdb1; S2A=741d56d36d7b2bfe2e9e0080a1cba4393e4a47da; S2B=8eaa91cad1ffa963158b365c6d0d7316f4965e89
OUT="${1:-$HERE/out/run-$(date -u +%Y%m%dT%H%M%SZ)}"
bad=0; fail() { echo "FAIL $*"; bad=1; }; ok() { echo "PASS $*"; }

echo "== 1. host prerequisites (NOT carried by this package)"
for t in python3 git unshare rustc sha256sum cmp tar; do command -v "$t" >/dev/null 2>&1 && ok "tool $t" || fail "tool $t is missing"; done
[ -n "${LEAN_BIN:-}" ] && [ -x "$LEAN_BIN/lean" ] && [ -x "$LEAN_BIN/lake" ] && ok "Lean bin directory $LEAN_BIN" || fail "LEAN_BIN must name the bin directory of the pinned Lean 4.33.0 (lean, lake)"
rv="$(cd "$REPO/spike/s3-entry" 2>/dev/null && rustc -V 2>/dev/null)"; case "$rv" in "rustc 1.82.0 "*) ok "$rv (inside spike/s3-entry)";; *) fail "rustc inside spike/s3-entry must be 1.82.0, got: ${rv:-none}";; esac
unshare -n true 2>/dev/null && ok "unshare -n" || { unshare -rn true 2>/dev/null && ok "unshare -rn" || fail "unprivileged network namespaces unavailable"; }

echo "== 2. package and Git state"
(cd "$HERE" && sha256sum -c PACKAGE_SHA256SUMS --quiet 2>&1 | head -5) | grep -q . && fail "PACKAGE_SHA256SUMS: a file differs or is missing" || ok "PACKAGE_SHA256SUMS: every listed file matches"
[ "$(git -C "$REPO" rev-parse HEAD)" = "$EXPECT_HEAD" ] && ok "repo HEAD $EXPECT_HEAD" || fail "repo HEAD differs"
[ "$(git -C "$REPO" rev-parse v0.1.0-s3a-frozen)" = "$EXPECT_TAG_S3A" ] && ok "tag object v0.1.0-s3a-frozen $EXPECT_TAG_S3A -> $(git -C "$REPO" rev-parse 'v0.1.0-s3a-frozen^{commit}')" || fail "tag v0.1.0-s3a-frozen differs"
[ "$(git -C "$REPO" rev-parse v0.1.0-s3-accepted)" = "$EXPECT_TAG_ACC" ] && ok "tag object v0.1.0-s3-accepted $EXPECT_TAG_ACC -> $(git -C "$REPO" rev-parse 'v0.1.0-s3-accepted^{commit}')" || fail "tag v0.1.0-s3-accepted differs"
for t in v0.1.0-s3a-frozen v0.1.0-s3-accepted; do git -C "$REPO" cat-file -p "$t" | grep -q "BEGIN SSH SIGNATURE" && ok "$t carries a signature block (validity: see README_PACKAGE.md, needs the signer's public key)" || fail "$t has no signature block"; done
if [ -n "${ALLOWED_SIGNERS:-}" ]; then for t in v0.1.0-s3a-frozen v0.1.0-s3-accepted; do git -C "$REPO" -c gpg.ssh.allowedSignersFile="$ALLOWED_SIGNERS" verify-tag "$t" >/dev/null 2>&1 && ok "signature of $t verifies against ALLOWED_SIGNERS" || fail "signature of $t does not verify against ALLOWED_SIGNERS"; done; fi
for p in "s1 $S1" "s2a $S2A" "s2b $S2B"; do set -- $p; h="$(git -C "$DEPS/$1" rev-parse HEAD)"; d="$(git -C "$DEPS/$1" status --porcelain | wc -l)"; [ "$h" = "$2" ] && [ "$d" = 0 ] && ok "$1 at $2, clean" || fail "$1 is not the clean pinned commit ($h, $d changes)"; done
(cd "$REPO" && sha256sum -c deployment/candidate/freeze-set.sha256 --quiet 2>&1 | head -3) | grep -q . && fail "frozen set: a file differs" || ok "frozen set: 99 of 99 files match"
[ "$(cat "$REPO/ts-prototype/evidence/s3b-capture/ANCHOR.sha256")" = "$EXPECT_ANCHOR" ] && ok "anchor $EXPECT_ANCHOR" || fail "anchor differs"
[ "$(sha256sum "$REPO/ts-prototype/evidence/s3b-capture/runner/verdict.json" | cut -c1-64)" = "$EXPECT_VERDICT_SHA" ] && ok "accepted verdict.json present ($EXPECT_VERDICT_SHA)" || fail "accepted verdict.json differs"
[ "$bad" = 0 ] || { echo "STOP: a prerequisite or integrity check failed; the runner was not started."; exit 2; }
[ ! -e "$OUT" ] || [ -z "$(ls -A "$OUT" 2>/dev/null)" ] || { echo "STOP: output directory $OUT is not empty"; exit 2; }

echo "== 3. offline runner (no --no-offline, no --pinned; network namespace is created and measured by the runner)"
cd "$REPO" && python3 -B verifier/runner/s3c_verify.py --capture ts-prototype/evidence/s3b-capture/capture --anchor-file ts-prototype/evidence/s3b-capture/ANCHOR.sha256 \
  --out "$OUT" --s1 "$DEPS/s1" --s2a "$DEPS/s2a" --s2b "$DEPS/s2b" --entry verifier/artifacts/s3-spike-entry --g5 verifier/artifacts/s3-g5 --lean-bin-dir "$LEAN_BIN"
rc=$?; echo "runner exit code: $rc"

echo "== 4. comparison (made only after the run)"
[ "$rc" = 0 ] && ok "runner exit 0" || fail "runner exit $rc"
for acc in runner runner-2; do cmp -s "$OUT/verdict.json" "$REPO/ts-prototype/evidence/s3b-capture/$acc/verdict.json" && ok "verdict.json is byte-identical to the accepted $acc/verdict.json" || fail "verdict.json differs from the accepted $acc/verdict.json"; done
echo "verdict.json sha256: $(sha256sum "$OUT/verdict.json" 2>/dev/null | cut -c1-64) (accepted: $EXPECT_VERDICT_SHA)"
python3 - "$OUT" <<'P' || bad=1
import json, sys
o = sys.argv[1]
try:
    v = json.load(open(o + "/verdict.json")); i = json.load(open(o + "/run-info.json"))
except Exception as e:
    print("FAIL cannot read the run records:", type(e).__name__); sys.exit(1)
chk = [("outcome BINDING_MATCH", v["outcome"] == "BINDING_MATCH"), ("executables_pinned entry and g5", v.get("executables_pinned") == {"entry": True, "g5": True}),
       ("network_isolated true (measured)", i.get("network_isolated") is True), ("no problems", not i.get("problems")), ("no tcb_source_mismatch", not i.get("tcb_source_mismatch")),
       ("runner s3c_verify.py hash", i["runner_source_sha256"].get("s3c_verify.py") == "7e6c457a6cc54e7a5c05610f80361201aa958022e44d8aa303a982ffbe95f628"),
       ("runner s3c_chain.py hash", i["runner_source_sha256"].get("s3c_chain.py") == "de3450bbb1b6268773bbee9eb7bc2d5e86d2ad433d59985b8ccf05b56bd50494"),
       ("entry binary hash", i.get("entry_binary_sha256") == "53ba44408b1de7322010681f45bb4aa576931f0974c448d9e6b7a662683ca863"),
       ("g5 binary hash", i.get("g5_binary_sha256") == "a2b4b1efeda26302ec5f0710905c46f7c180ad862035959d47ba1e33305ee0bd")]
ok = True
for n, g in chk:
    print(("PASS " if g else "FAIL ") + n); ok &= g
sys.exit(0 if ok else 1)
P
[ "$bad" = 0 ] && { echo "ALL PASS: the offline replay reproduced the accepted verdict on this host. Output: $OUT"; exit 0; }
echo "FAILURES (output preserved in $OUT)"; exit 1
