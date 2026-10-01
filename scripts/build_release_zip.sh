#!/usr/bin/env bash
# Build dist/parcel_tracker.zip, the release asset HACS downloads (hacs.json:
# "zip_release": true, "filename": "parcel_tracker.zip").
#
# HACS unpacks the archive straight into custom_components/parcel_tracker/, so
# the zip holds the CONTENTS of that folder: manifest.json sits at the zip root.
#
# The result is reproducible: same sources, same bytes (sorted entries, fixed
# timestamps and permissions, no extra fields).
#
# Usage: scripts/build_release_zip.sh [output-dir]      (default: dist/)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE="$ROOT/custom_components/parcel_tracker"
OUT_DIR="${1:-$ROOT/dist}"
NAME="parcel_tracker.zip"

[ -f "$SOURCE/manifest.json" ] || { echo "manifest.json not found in $SOURCE" >&2; exit 1; }
command -v zip >/dev/null || { echo "zip is not installed" >&2; exit 1; }

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
export TZ=UTC LC_ALL=C

mkdir -p "$OUT_DIR"
OUT_DIR="$(cd "$OUT_DIR" && pwd)"

(
    cd "$SOURCE"
    find . -type f \
        ! -path '*/__pycache__/*' ! -name '*.py[co]' ! -name '.DS_Store' \
        | sort | while IFS= read -r file; do
            mkdir -p "$STAGE/$(dirname "$file")"
            cp "$file" "$STAGE/$file"
        done
)

find "$STAGE" -type d -exec chmod 755 {} +
find "$STAGE" -type f -exec chmod 644 {} +
find "$STAGE" -exec touch -t 202001010000.00 {} +

rm -f "$OUT_DIR/$NAME"
(cd "$STAGE" && find . -type f | sed 's|^\./||' | sort | zip -X -q -9 "$OUT_DIR/$NAME" -@)

echo "$OUT_DIR/$NAME"
