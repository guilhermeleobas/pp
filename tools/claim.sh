#!/usr/bin/env bash
# Claim a work item before starting it, so two agents never work on the same
# thing. Claims are files in a shared directory outside the repository (never
# committed: what agents are doing right now is not published).
#
#   tools/claim.sh claim <item> <branch> [note]   # fails if already claimed
#   tools/claim.sh release <item>
#   tools/claim.sh list
#
# <item> is a short slug: a module (`_pickle`, `math`) or a task (`sre-pos`,
# `perf-eval-loop`). The directory is $PP_CLAIMS_DIR (default ~/pp-claims).
set -euo pipefail

dir="${PP_CLAIMS_DIR:-$HOME/pp-claims}"
mkdir -p "$dir"

usage() { sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }

check_item() {
    [[ "$1" =~ ^[A-Za-z0-9_.-]+$ ]] || { echo "bad item name: $1" >&2; exit 2; }
}

cmd="${1:-}"; shift || true
case "$cmd" in
    claim)
        [ $# -ge 2 ] || usage
        item="$1" branch="$2" note="${3:-}"
        check_item "$item"
        # noclobber opens with O_EXCL: of two agents racing, exactly one wins.
        if ( set -o noclobber
             printf 'branch: %s\nstarted: %s\nnote: %s\n' \
                 "$branch" "$(date -u +%Y-%m-%dT%H:%MZ)" "$note" > "$dir/$item"
           ) 2>/dev/null; then
            echo "claimed $item"
        else
            echo "already claimed: $item" >&2
            cat "$dir/$item" >&2
            exit 1
        fi
        ;;
    release)
        [ $# -eq 1 ] || usage
        check_item "$1"
        rm -f "$dir/$1"
        echo "released $1"
        ;;
    list)
        now=$(date +%s)
        for f in "$dir"/*; do
            [ -e "$f" ] || { echo "(no claims)"; break; }
            age=$(( (now - $(stat -c %Y "$f" 2>/dev/null || stat -f %m "$f")) / 3600 ))
            printf '%-20s %3sh  %s\n' "$(basename "$f")" "$age" \
                "$(tr '\n' ' ' < "$f")"
        done
        ;;
    *) usage ;;
esac
