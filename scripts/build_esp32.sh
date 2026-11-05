#!/usr/bin/env bash
# Build MicroPython + LVGL firmware for an ESP32 board of this repo.
#
#   scripts/build_esp32.sh <BOARD>      # the board lives in boards/esp32/<BOARD>
#
# Separate from scripts/build.sh: these boards use omnipython-lvgl, the successor of
# the archived lvgl-micropython, and ESP-IDF instead of the arm toolchain.
#
# Environment:
#   WORK_DIR   where the sources live (default: .work/esp32 in this repo)
#   IDF_PATH   an ESP-IDF checkout at the pinned version, with its tools installed
#              (default: the one already exported, else /opt/devel/espressif/v$IDF_VER/esp-idf)
#   IDF_TOOLS_PATH  passed to ESP-IDF if set
#   JOBS       parallel jobs (default: nproc)
#
# Output: dist/<BOARD>-<this repo commit>.bin, to write at offset 0, and its .sha256.
set -euo pipefail

# --- pins (bump together, then re-run the hardware tests: docs/) ---
MPY_URL=https://github.com/micropython/micropython.git
MPY_REF=v1.29.0
MPY_SHA=0fd6c573ea815774668bbb16b8e197c8822368b2
OPL_URL=https://github.com/PyDevices/omnipython-lvgl.git
OPL_SHA=92f8c0a493fa71bccc151b78f9a451f64ed78a18
IDF_VER=5.5.2

log() { printf '\n== %s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

[[ $# -eq 1 ]] || die "usage: $0 <BOARD>"
BOARD=$1
REPO=$(cd "$(dirname "$0")/.." && pwd)
BOARD_DIR=$REPO/boards/esp32/$BOARD
[[ -f $BOARD_DIR/mpconfigboard.cmake ]] || die "no board $BOARD_DIR"
WORK_DIR=$(mkdir -p "${WORK_DIR:-$REPO/.work/esp32}" && cd "${WORK_DIR:-$REPO/.work/esp32}" && pwd)
JOBS=${JOBS:-$(nproc)}
# An index that does not answer makes every pip install of ESP-IDF crawl.
export PIP_CONFIG_FILE=${PIP_CONFIG_FILE:-/dev/null}

# Clone $1 at commit $3 (reached through ref $2) into $4, or check that it is there.
checkout() {
    local url=$1 ref=$2 sha=$3 dir=$4 head
    if [[ ! -d $dir/.git ]]; then
        git init -q "$dir"
        git -C "$dir" remote add origin "$url"
        git -C "$dir" fetch -q --depth 1 origin "$ref"
        git -C "$dir" checkout -q FETCH_HEAD
    fi
    head=$(git -C "$dir" rev-parse HEAD)
    [[ $head == "$sha" ]] || die "$dir is at ${head:0:12}, expected ${sha:0:12}"
    [[ -z $(git -C "$dir" status --porcelain --untracked-files=no) ]] || die "$dir has local changes"
}

log "sources in $WORK_DIR"
checkout "$MPY_URL" "refs/tags/$MPY_REF" "$MPY_SHA" "$WORK_DIR/micropython"
checkout "$OPL_URL" "$OPL_SHA" "$OPL_SHA" "$WORK_DIR/omnipython-lvgl"
git -C "$WORK_DIR/omnipython-lvgl" submodule update -q --init --depth 1 lvgl

log "ESP-IDF"
IDF_PATH=${IDF_PATH:-/opt/devel/espressif/v$IDF_VER/esp-idf}
[[ -f $IDF_PATH/export.sh ]] || die "no ESP-IDF in $IDF_PATH: install v$IDF_VER, set IDF_PATH"
# shellcheck disable=SC1091
. "$IDF_PATH/export.sh" >/dev/null
[[ $(idf.py --version) == *"v$IDF_VER"* ]] || die "need ESP-IDF v$IDF_VER, found $(idf.py --version)"
idf.py --version

MPY=$WORK_DIR/micropython
export OMNIPYTHON_LVGL_DIR=$WORK_DIR/omnipython-lvgl
MAKE_ARGS=(BOARD_DIR="$BOARD_DIR" USER_C_MODULES="$REPO/modules/esp32_usermods.cmake")
log "submodules"
make -C "$MPY/ports/esp32" "${MAKE_ARGS[@]}" submodules >/dev/null
log "mpy-cross"
make -C "$MPY/mpy-cross" -j"$JOBS" >/dev/null
log "firmware $BOARD"
make -C "$MPY/ports/esp32" "${MAKE_ARGS[@]}" -j"$JOBS"

REV=$(git -C "$REPO" describe --always --dirty 2>/dev/null || echo unknown)
out=$BOARD-$REV.bin
mkdir -p "$REPO/dist"
cp "$MPY/ports/esp32/build-$BOARD/firmware.bin" "$REPO/dist/$out"
(cd "$REPO/dist" && sha256sum "$out" > "$out.sha256")
log "done"
echo "$REPO/dist/$out"
echo "  micropython $MPY_REF, omnipython-lvgl ${OPL_SHA:0:7}, ESP-IDF v$IDF_VER"
