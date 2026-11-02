#!/usr/bin/env bash
# Download CPython's Lib/ (stdlib sources and Lib/test) for the version pp targets.
set -euo pipefail
VERSION="${1:-3.15.2}"
DEST="vendor/cpython-${VERSION}"
if [ -d "$DEST/Lib/test" ]; then echo "$DEST already present"; exit 0; fi
mkdir -p "$DEST"
curl -sSL "https://github.com/python/cpython/archive/refs/tags/v${VERSION}.tar.gz" \
  | tar -xz -C "$DEST" --strip-components=1 "cpython-${VERSION}/Lib"
echo "fetched $DEST/Lib"
