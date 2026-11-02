#!/usr/bin/env bash
# Prepare a git worktree of pp: link the vendored CPython Lib and the main pixi env.
set -euo pipefail
MAIN="$(git worktree list --porcelain | awk '/^worktree /{print $2; exit}')"
HERE="$(git rev-parse --show-toplevel)"
[ "$MAIN" = "$HERE" ] && { echo "already in the main worktree"; exit 0; }
[ -e "$HERE/vendor" ] || ln -s "$MAIN/vendor" "$HERE/vendor"
[ -e "$HERE/.pixi" ] || ln -s "$MAIN/.pixi" "$HERE/.pixi"
echo "linked vendor/ and .pixi/ from $MAIN"
