#!/usr/bin/env bash
# Builds the portable offline package from local checkouts (packaging work only; reads the repositories, changes none of them).
# usage: make_offline_package.sh STAGING_PARENT_DIR   (creates STAGING_PARENT_DIR/p10-s3-offline and the tarball next to it)
set -euo pipefail
PARENT="$1"; NAME=p10-s3-offline; SUFFIX="${PKG_SUFFIX:-}"; P="$PARENT/$NAME"; HERE="$(cd "$(dirname "$0")" && pwd)"
S3=/home/user/p10-scitt-transparency-s3; HEADC=e56d3ea8bbe14c9c88a0dde339c29b55b1032a66
[ ! -e "$P" ] || { echo "refusing: $P exists"; exit 2; }
mkdir -p "$P/deps"
clone() { git clone -q --no-local --no-checkout "$1" "$2" && git -C "$2" checkout -q --detach "$3" && git -C "$2" remote remove origin; }
clone "$S3" "$P/repo" "$HEADC"
git -C "$S3" cat-file -e v0.1.0-s3a-frozen && git -C "$S3" cat-file -e v0.1.0-s3-accepted
for t in v0.1.0-s3a-frozen v0.1.0-s3-accepted; do [ "$(git -C "$P/repo" rev-parse "$t")" = "$(git -C "$S3" rev-parse "$t")" ]; done
clone /home/user/volmax-studio/s1 "$P/deps/s1" e4db3747eaeeb1a07227bb9029f9a9c3b566cdb1
clone /home/user/volmax-studio/s2a "$P/deps/s2a" 741d56d36d7b2bfe2e9e0080a1cba4393e4a47da
clone /home/user/volmax-studio/s2b-8eaa91c "$P/deps/s2b" 8eaa91cad1ffa963158b365c6d0d7316f4965e89
cp "$HERE/verify_offline.sh" "$HERE/README_PACKAGE.md" "$P/"; chmod +x "$P/verify_offline.sh"
# exclusions: nothing secret may be in the package
if find "$P" -path '*/.git' -prune -o \( -name '*.pem' -o -name '*.age' -o -name 'note.skey' -o -name '*.agekey' -o -name 'transfer*' \) -print | grep -q .; then echo "ABORT: key-like file present"; find "$P" -path '*/.git' -prune -o \( -name '*.pem' -o -name '*.age' -o -name 'note.skey' -o -name '*.agekey' \) -print; exit 3; fi
if grep -rIl --exclude-dir=.git -E "BEGIN [A-Z ]*PRIVATE KEY|AGE-SECRET-KEY" "$P" | grep -v 'verify_custody\|test_verify_custody\|make_definition\|assemble_capture\|receipt_test' | grep -q .; then echo "ABORT: private key text present"; exit 3; fi
{ for d in repo deps/s1 deps/s2a deps/s2b; do echo "$d HEAD $(git -C "$P/$d" rev-parse HEAD)"; git -C "$P/$d" for-each-ref --format="$d tag %(refname:short) object %(objectname) target %(*objectname)" refs/tags; done; } > "$P/git-state.txt"
cat > "$P/PACKAGING_RECORD.md" <<R
# Packaging record
Built by packaging/offline-package/make_offline_package.sh on $(date -u +%FT%TZ) from the repository at $HEADC and the pinned S1/S2a/S2b checkouts (clones; origin removed). No file of repo/ or deps/ was modified after checkout. Revision: ${PKG_SUFFIX:-original}. Validation of the extracted package is recorded in the repository under packaging/offline-package/ (VALIDATION.md, VALIDATION-rev2.md).
R
(cd "$P" && find . -path ./.git -prune -o -path '*/.git' -prune -o -type f ! -name PACKAGE_SHA256SUMS ! -path './out/*' -print | LC_ALL=C sort | sed 's#^\./##' | xargs -d '\n' sha256sum > PACKAGE_SHA256SUMS)
(cd "$PARENT" && tar --sort=name --owner=0 --group=0 --numeric-owner -cf - "$NAME" | gzip -n > "$NAME-e56d3ea$SUFFIX.tar.gz" && sha256sum "$NAME-e56d3ea$SUFFIX.tar.gz" > "$NAME-e56d3ea$SUFFIX.tar.gz.sha256")
echo "built $PARENT/$NAME-e56d3ea$SUFFIX.tar.gz"; cat "$PARENT/$NAME-e56d3ea$SUFFIX.tar.gz.sha256"; du -sh "$PARENT/$NAME-e56d3ea$SUFFIX.tar.gz"
