#!/usr/bin/env bash
# Host test of apply_patches() in scripts/build.sh, on a throwaway git repo.
#
#   tests/host/test_build_patches.sh
#
# Accepted clone states are HEAD plus the first k patches; anything else stops.
set -uo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
{
    echo 'set -euo pipefail; REPO=/x; die() { printf "error: %s\n" "$*" >&2; exit 1; }'
    sed -n '/^apply_patches() {/,/^}/p' "$HERE/../../scripts/build.sh"
    echo 'apply_patches "$1" "$2"'
} > "$T/harness.sh"

g() { git -C "$T/r" -c user.email=t@t -c user.name=t "$@"; }
mkdir "$T/p"
git init -q "$T/r"
printf 'a\nb\nc\n' > "$T/r/f"
g add f && g commit -qm base
sed -i 's/a/A/' "$T/r/f"
g diff > "$T/p/0001-first.patch"
g commit -qam tmp
sed -i 's/c/C/' "$T/r/f"
echo new > "$T/r/g"
g add -N g
g diff > "$T/p/0002-second.patch"
g reset -q --hard HEAD~1
rm -f "$T/r/g"

fails=0
check() {   # check <name> <expected exit> [expected file f]
    local out rc
    out=$(bash "$T/harness.sh" "$T/r" "$T/p" 2>&1); rc=$?
    if [[ $rc == "$2" && ( -z ${3:-} || $(tr '\n' ' ' < "$T/r/f") == "$3" ) ]]; then
        echo "ok   $1"
    else
        echo "FAIL $1 (exit $rc)"; echo "$out" | sed 's/^/     /'; fails=$((fails + 1))
    fi
}
reset() { g checkout -q -- f; rm -f "$T/r/g" "$T/r/u"; }

check "clean clone: both patches applied" 0 "A b C "
[[ $(cat "$T/r/g") == new ]] || { echo "FAIL new file missing"; fails=$((fails + 1)); }
check "already applied: nothing to do" 0 "A b C "
reset; sed -i 's/a/A/' "$T/r/f"
check "first applied only: second applied" 0 "A b C "
echo junk >> "$T/r/f"
check "foreign change: stop" 1
reset; echo stray > "$T/r/u"
check "stray untracked file: stop" 1
reset; echo x > "$T/r/h"; g add h
check "staged change: stop" 1
g reset -q; rm "$T/r/h"
sed -i 's/^a$/q/' "$T/r/f"; g commit -qam upstream-moved
check "patch does not apply to new upstream: stop" 1
g reset -q --hard HEAD~1; rm -rf "$T/p"; mkdir "$T/p"
check "no patches, clean clone" 0
echo x >> "$T/r/f"
check "no patches, dirty clone: stop" 1

echo "$((9 - fails))/9 passed"
exit $((fails > 0))
