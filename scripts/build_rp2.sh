#!/usr/bin/env bash
# Build MicroPython + LVGL firmware for an rp2 board of this repo.
#
#   scripts/build_rp2.sh [BOARD]        (default WAVESHARE_RP2350_TOUCH_LCD_4)
#
# Idempotent: clones the pinned sources into $WORK_DIR on the first run, checks
# them on later runs, then builds. Nothing outside $WORK_DIR and dist/ is written.
#
# Environment:
#   WORK_DIR       where the sources live (default: .work in this repo). A directory
#                  that already holds micropython/ and lvgl-micropython/ at the pins
#                  is reused as is; a checkout at another commit stops the build.
#   TOOLCHAIN_DIR  an arm-none-eabi toolchain (its bin/ is put first in PATH).
#                  Default: arm-none-eabi-gcc from PATH if it is the pinned version,
#                  else the pinned xPack release, downloaded into $WORK_DIR/tools.
#   JOBS           parallel jobs (default: nproc).
#
# Output: dist/<board>-<this repo commit>.uf2 and a .sha256 file.
set -euo pipefail

# --- pins (bump together, then re-run the hardware tests: docs/rp2350-touch-lcd4.md) ---
MPY_URL=https://github.com/micropython/micropython.git
MPY_REF=v1.29.0
MPY_SHA=0fd6c573ea815774668bbb16b8e197c8822368b2
LVMP_URL=https://github.com/PyDevices/lvgl-micropython.git
LVMP_SHA=3e287e725886673d0a3b019a68d83ccf66ae4196   # pins lvgl-bindings in LVGL_BINDINGS_COMMIT
XPACK_VER=15.2.1-1.1
XPACK_SHA256=da6a49ad4003944b823c6c93702a8787c922ab34bd7e918ec0eaf6933a9b1ff6   # linux-x64

REPO=$(cd "$(dirname "$0")/.." && pwd)
BOARD=${1:-WAVESHARE_RP2350_TOUCH_LCD_4}
BOARD_DIR=$REPO/boards/rp2/$BOARD
WORK_DIR=$(mkdir -p "${WORK_DIR:-$REPO/.work}" && cd "${WORK_DIR:-$REPO/.work}" && pwd)
JOBS=${JOBS:-$(nproc)}

log() { printf '\n== %s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

[[ -f $BOARD_DIR/mpconfigboard.cmake ]] || die "no board $BOARD in $REPO/boards/rp2"

# Clone $1 at commit $3 (fetching ref $2) into $4, shallow; or check an existing clone.
checkout() {
    local url=$1 ref=$2 sha=$3 dir=$4
    if [[ -d $dir/.git ]]; then
        local head
        head=$(git -C "$dir" rev-parse HEAD)
        [[ $head == "$sha" ]] || die "$dir is at ${head:0:12}, expected ${sha:0:12} ($ref)"
        echo "$(basename "$dir") ${sha:0:12} ok"
        return
    fi
    log "clone $(basename "$dir") $ref"
    git init -q "$dir"
    git -C "$dir" remote add origin "$url"
    git -C "$dir" fetch -q --depth 1 origin "$ref"
    git -C "$dir" checkout -q FETCH_HEAD
    [[ $(git -C "$dir" rev-parse HEAD) == "$sha" ]] || die "$url $ref is not ${sha:0:12}"
}

log "sources in $WORK_DIR"
checkout "$MPY_URL" "refs/tags/$MPY_REF" "$MPY_SHA" "$WORK_DIR/micropython"
checkout "$LVMP_URL" "$LVMP_SHA" "$LVMP_SHA" "$WORK_DIR/lvgl-micropython"

# lvgl-micropython uses an lvgl-bindings beside it if there is one, else fetches its pin.
# A sibling at another commit would silently change LVGL: refuse it.
BINDINGS_SHA=$(tr -d '[:space:]' < "$WORK_DIR/lvgl-micropython/LVGL_BINDINGS_COMMIT")
if [[ -d $WORK_DIR/lvgl-bindings/.git ]]; then
    head=$(git -C "$WORK_DIR/lvgl-bindings" rev-parse HEAD)
    [[ $head == "$BINDINGS_SHA" ]] || die "$WORK_DIR/lvgl-bindings is at ${head:0:12}, lvgl-micropython pins ${BINDINGS_SHA:0:12}"
    [[ -f $WORK_DIR/lvgl-bindings/lvgl/lvgl.h ]] || git -C "$WORK_DIR/lvgl-bindings" submodule update --init lvgl
    echo "lvgl-bindings ${BINDINGS_SHA:0:12} ok (beside lvgl-micropython)"
else
    "$WORK_DIR/lvgl-micropython/scripts/fetch_bindings.sh"
fi

# --- toolchain ---
if [[ -n ${TOOLCHAIN_DIR:-} ]]; then
    export PATH=$TOOLCHAIN_DIR/bin:$PATH
elif ! arm-none-eabi-gcc --version 2>/dev/null | head -1 | grep -q "xPack GNU Arm Embedded GCC.* ${XPACK_VER%-*} "; then
    TOOLCHAIN_DIR=$WORK_DIR/tools/xpack-arm-none-eabi-gcc-$XPACK_VER
    if [[ ! -x $TOOLCHAIN_DIR/bin/arm-none-eabi-gcc ]]; then
        [[ $(uname -sm) == "Linux x86_64" ]] || die "no pinned toolchain for $(uname -sm): set TOOLCHAIN_DIR"
        tarball=xpack-arm-none-eabi-gcc-$XPACK_VER-linux-x64.tar.gz
        log "download $tarball"
        mkdir -p "$WORK_DIR/tools"
        curl -fsSL -o "$WORK_DIR/tools/$tarball" \
            "https://github.com/xpack-dev-tools/arm-none-eabi-gcc-xpack/releases/download/v$XPACK_VER/$tarball"
        echo "$XPACK_SHA256  $WORK_DIR/tools/$tarball" | sha256sum -c --quiet
        tar -xzf "$WORK_DIR/tools/$tarball" -C "$WORK_DIR/tools"
        rm "$WORK_DIR/tools/$tarball"
    fi
    export PATH=$TOOLCHAIN_DIR/bin:$PATH
fi
echo "toolchain: $(arm-none-eabi-gcc --version | head -1)"

# --- build ---
MPY=$WORK_DIR/micropython
log "submodules"
make -C "$MPY/ports/rp2" BOARD_DIR="$BOARD_DIR" submodules >/dev/null
log "mpy-cross"
make -C "$MPY/mpy-cross" -j"$JOBS" >/dev/null
log "firmware $BOARD"
BUILD=build-$BOARD
LVMP_DIR="$WORK_DIR/lvgl-micropython" \
    make -C "$MPY/ports/rp2" BOARD_DIR="$BOARD_DIR" BUILD="$BUILD" -j"$JOBS"

# --- output ---
REV=$(git -C "$REPO" describe --always --dirty 2>/dev/null || echo unknown)
mkdir -p "$REPO/dist"
OUT=$REPO/dist/$BOARD-$REV.uf2
cp "$MPY/ports/rp2/$BUILD/firmware.uf2" "$OUT"
(cd "$REPO/dist" && sha256sum "$(basename "$OUT")" > "$(basename "$OUT").sha256")
log "done"
echo "$OUT"
echo "  micropython $MPY_REF, lvgl-micropython ${LVMP_SHA:0:7}, lvgl-bindings ${BINDINGS_SHA:0:7}"
arm-none-eabi-size "$MPY/ports/rp2/$BUILD/firmware.elf"
