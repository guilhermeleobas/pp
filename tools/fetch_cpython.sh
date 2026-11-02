#!/usr/bin/env bash
# Download CPython's Lib/ (stdlib sources and Lib/test). Always the same pinned tag:
# change CPYTHON_TAG here and VERSION in tools/stdlib_status.py together, never per run.
set -euo pipefail
CPYTHON_TAG="v3.15.2"
DEST="vendor/cpython-${CPYTHON_TAG#v}"
if [ -d "$DEST/Lib/test" ]; then echo "$DEST already present"; exit 0; fi
mkdir -p "$DEST"
curl -sSL "https://github.com/python/cpython/archive/refs/tags/${CPYTHON_TAG}.tar.gz" \
  | tar -xz -C "$DEST" --strip-components=1 "cpython-${CPYTHON_TAG#v}/Lib"
echo "fetched $DEST/Lib from tag $CPYTHON_TAG"
