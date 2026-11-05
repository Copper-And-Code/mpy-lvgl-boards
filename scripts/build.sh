#!/usr/bin/env bash
# Build MicroPython + LVGL firmware for a board of this repo.
#
#   scripts/build.sh <port> <BOARD> [VARIANT]
#
#   port     rp2 or stm32; the board lives in boards/<port>/<BOARD>
#            (esp32: handed over to scripts/build_esp32.sh)
#   VARIANT  optional board variant (mpconfigvariant_<VARIANT>.{mk,cmake})
#
# Idempotent: clones the pinned sources into $WORK_DIR on the first run, checks
# them on later runs, applies the patches in patches/<project>/, then builds.
# Nothing outside $WORK_DIR and dist/ is written.
#
# Environment:
#   WORK_DIR          where the sources live (default: .work in this repo). A directory
#                     that already holds micropython/ and lvgl-micropython/ at the pins
#                     is reused as is; a checkout at another commit, or with changes
#                     that are not the patches of this repo, stops the build.
#   GIT_REFERENCE_DIR optional directory with existing clones (micropython/,
#                     lvgl-micropython/, lvgl-bindings/) to copy git objects from
#                     instead of downloading them; origin still points upstream.
#   TOOLCHAIN_DIR     an arm-none-eabi toolchain (its bin/ is put first in PATH).
#                     Default: arm-none-eabi-gcc from PATH if it is the pinned version,
#                     else the pinned xPack release, downloaded into $WORK_DIR/tools.
#   JOBS              parallel jobs (default: nproc).
#   FROZEN_MANIFEST   passed to make if set (e.g. a board's manifest_nolvgl.py); a
#                     manifest other than the board's manifest.py adds its name to the
#                     build directory and the output (manifest_nolvgl.py: -nolvgl).
#
# Output: dist/<BOARD>[-<VARIANT>]-<this repo commit>.<ext> and .sha256 files
# (rp2: .uf2; stm32: .dfu and .hex).
set -euo pipefail

# --- pins (bump together, then re-run the hardware tests: docs/) ---
MPY_URL=https://github.com/micropython/micropython.git
MPY_REF=v1.29.0
MPY_SHA=0fd6c573ea815774668bbb16b8e197c8822368b2
LVMP_URL=https://github.com/PyDevices/lvgl-micropython.git
LVMP_SHA=3e287e725886673d0a3b019a68d83ccf66ae4196   # pins lvgl-bindings in LVGL_BINDINGS_COMMIT
XPACK_VER=15.2.1-1.1
XPACK_SHA256=da6a49ad4003944b823c6c93702a8787c922ab34bd7e918ec0eaf6933a9b1ff6   # linux-x64

log() { printf '\n== %s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

[[ ${1:-} != esp32 ]] || { shift; exec "$(dirname "$0")/build_esp32.sh" "$@"; }
[[ $# -ge 2 && $# -le 3 ]] || die "usage: $0 <rp2|stm32> <BOARD> [VARIANT]"
PORT=$1
BOARD=$2
VARIANT=${3:-}

REPO=$(cd "$(dirname "$0")/.." && pwd)
BOARD_DIR=$REPO/boards/$PORT/$BOARD
WORK_DIR=$(mkdir -p "${WORK_DIR:-$REPO/.work}" && cd "${WORK_DIR:-$REPO/.work}" && pwd)
REF_DIR=${GIT_REFERENCE_DIR:-}
JOBS=${JOBS:-$(nproc)}

case $PORT in
    rp2) BOARD_FILE=mpconfigboard.cmake VARIANT_FILE=mpconfigvariant_$VARIANT.cmake ;;
    stm32) BOARD_FILE=mpconfigboard.mk VARIANT_FILE=mpconfigvariant_$VARIANT.mk ;;
    *) die "unknown port $PORT (rp2 or stm32)" ;;
esac
[[ -f $BOARD_DIR/$BOARD_FILE ]] || die "no board $BOARD in $REPO/boards/$PORT"
[[ -z $VARIANT || -f $BOARD_DIR/$VARIANT_FILE ]] || die "no variant $VARIANT of $BOARD ($VARIANT_FILE)"

# Clone $1 at commit $3 (fetching ref $2) into $4, shallow; or check an existing clone.
# With GIT_REFERENCE_DIR/<name> the objects come from there, origin stays $1.
checkout() {
    local url=$1 ref=$2 sha=$3 dir=$4 name src
    name=$(basename "$dir")
    if [[ -d $dir/.git ]]; then
        local head
        head=$(git -C "$dir" rev-parse HEAD)
        [[ $head == "$sha" ]] || die "$dir is at ${head:0:12}, expected ${sha:0:12} ($ref)"
        echo "$name ${sha:0:12} ok"
        return
    fi
    src=$url
    [[ -n $REF_DIR && -d $REF_DIR/$name/.git ]] && { src=$REF_DIR/$name; ref=$sha; }
    log "clone $name $ref${REF_DIR:+ (from ${src})}"
    git init -q "$dir"
    git -C "$dir" remote add origin "$url"
    git -C "$dir" fetch -q --depth 1 "$src" "$ref"
    git -C "$dir" checkout -q FETCH_HEAD
    [[ $(git -C "$dir" rev-parse HEAD) == "$sha" ]] || die "$url $ref is not ${sha:0:12}"
}

# Check out submodule $2 of the clone $1 from the clone $3 (shallow ones too), at the
# commit $1 records; origin is the URL in .gitmodules.
copy_submodule() {
    local top=$1 path=$2 src=$3 sha url
    sha=$(git -C "$top" ls-tree HEAD "$path" | awk '{print $3}')
    url=$(git -C "$top" config -f .gitmodules "submodule.$path.url")
    rm -rf "${top:?}/$path"
    mkdir -p "$top/$path"
    git -C "$top/$path" init -q
    git -C "$top/$path" remote add origin "$url"
    git -C "$top/$path" fetch -q --depth 1 "$src" "$sha"
    git -C "$top/$path" checkout -q FETCH_HEAD
    git -C "$top" submodule init -q -- "$path"
    git -C "$top" submodule absorbgitdirs -- "$path" >/dev/null
}

# Bring the clone $1 to "HEAD + all patches in $2", or stop.
# Accepted states: HEAD plus the first k patches (k = 0..n, in file name order);
# the missing patches are applied. Anything else is an unexpected change.
apply_patches() {
    local dir=$1 pdir=$2 name tmp k i n
    name=$(basename "$dir")
    local patches=()
    [[ -d $pdir ]] && mapfile -t patches < <(find "$pdir" -maxdepth 1 -name '*.patch' | sort)
    n=${#patches[@]}
    # Nothing may be staged: patches are applied to the work tree only.
    git -C "$dir" diff --cached --quiet || die "$dir has staged changes: see git -C $dir status"
    tmp=$(mktemp)
    # shellcheck disable=SC2064
    trap "rm -f '$tmp'" RETURN
    for ((k = n; k >= 0; k--)); do
        # A copy of the real index keeps stat data and sparse-checkout bits.
        cp "$(git -C "$dir" rev-parse --absolute-git-dir)/index" "$tmp"
        for ((i = 0; i < k; i++)); do
            GIT_INDEX_FILE=$tmp git -C "$dir" apply --cached "${patches[i]}" 2>/dev/null || continue 2
        done
        GIT_INDEX_FILE=$tmp git -C "$dir" update-index -q --refresh >/dev/null || true
        # Work tree == HEAD + k patches: no diff against that index, no stray files.
        GIT_INDEX_FILE=$tmp git -C "$dir" diff --quiet &&
            [[ -z $(GIT_INDEX_FILE=$tmp git -C "$dir" ls-files --others --exclude-standard) ]] && break
    done
    ((k >= 0)) || die "$dir has changes that are not the patches in ${pdir#"$REPO"/}: see git -C $dir status"
    for ((i = k; i < n; i++)); do
        git -C "$dir" apply --check "${patches[i]}" ||
            die "${patches[i]#"$REPO"/} does not apply to $name $(git -C "$dir" rev-parse --short HEAD)"
        git -C "$dir" apply "${patches[i]}"
        echo "$name: applied $(basename "${patches[i]}")"
    done
    ((n == 0)) || echo "$name: $n patch(es) in place"
}

log "sources in $WORK_DIR"
checkout "$MPY_URL" "refs/tags/$MPY_REF" "$MPY_SHA" "$WORK_DIR/micropython"
checkout "$LVMP_URL" "$LVMP_SHA" "$LVMP_SHA" "$WORK_DIR/lvgl-micropython"

# lvgl-micropython uses an lvgl-bindings beside it if there is one, else fetches its pin
# into its .deps/. A sibling at another commit would silently change LVGL: refuse it.
BINDINGS_SHA=$(tr -d '[:space:]' < "$WORK_DIR/lvgl-micropython/LVGL_BINDINGS_COMMIT")
BINDINGS_DIR=$WORK_DIR/lvgl-bindings
if [[ ! -d $BINDINGS_DIR/.git && -n $REF_DIR && -d $REF_DIR/lvgl-bindings/.git ]]; then
    # A full sibling clone from the reference, LVGL submodule included.
    checkout https://github.com/PyDevices/lvgl-bindings.git "$BINDINGS_SHA" "$BINDINGS_SHA" "$BINDINGS_DIR"
    copy_submodule "$BINDINGS_DIR" lvgl "$REF_DIR/lvgl-bindings/lvgl"
fi
if [[ -d $BINDINGS_DIR/.git ]]; then
    head=$(git -C "$BINDINGS_DIR" rev-parse HEAD)
    [[ $head == "$BINDINGS_SHA" ]] || die "$BINDINGS_DIR is at ${head:0:12}, lvgl-micropython pins ${BINDINGS_SHA:0:12}"
    [[ -f $BINDINGS_DIR/lvgl/lvgl.h ]] || git -C "$BINDINGS_DIR" submodule update --init lvgl
    echo "lvgl-bindings ${BINDINGS_SHA:0:12} ok (beside lvgl-micropython)"
else
    "$WORK_DIR/lvgl-micropython/scripts/fetch_bindings.sh"
    BINDINGS_DIR=$WORK_DIR/lvgl-micropython/.deps/lvgl-bindings
fi

# micropython submodules already present in the reference clone: copy them from there
# (make submodules below then finds them at the right commit and fetches only the rest).
if [[ -n $REF_DIR && -d $REF_DIR/micropython/.git ]]; then
    while read -r sm; do
        [[ -e $WORK_DIR/micropython/$sm/.git ]] && continue
        copy_submodule "$WORK_DIR/micropython" "$sm" "$REF_DIR/micropython/$sm"
        echo "micropython/$sm copied from the reference"
    done < <(git -C "$REF_DIR/micropython" submodule status | awk '/^ /{print $2}')
fi

log "patches"
apply_patches "$WORK_DIR/micropython" "$REPO/patches/micropython"
apply_patches "$WORK_DIR/lvgl-micropython" "$REPO/patches/lvgl-micropython"
apply_patches "$BINDINGS_DIR" "$REPO/patches/lvgl-bindings"

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
# Taken out of the environment: make would pass it to the mpy-cross build too.
FROZEN=${FROZEN_MANIFEST:-}
unset FROZEN_MANIFEST
NAME=$BOARD${VARIANT:+-$VARIANT}
# Another manifest gets its own build directory and output name:
# manifest_nolvgl.py -> <BOARD>[-<VARIANT>]-nolvgl.
if [[ -n $FROZEN && $FROZEN != "$BOARD_DIR/manifest.py" ]]; then
    m=$(basename "$FROZEN" .py)
    NAME=$NAME-${m#manifest_}
fi
BUILD=build-$NAME
MAKE_ARGS=(BOARD_DIR="$BOARD_DIR" BUILD="$BUILD")
[[ -n $VARIANT ]] && MAKE_ARGS+=(BOARD_VARIANT="$VARIANT")
[[ -n $FROZEN ]] && MAKE_ARGS+=(FROZEN_MANIFEST="$FROZEN")
export LVMP_DIR=$WORK_DIR/lvgl-micropython

log "submodules"
make -C "$MPY/ports/$PORT" "${MAKE_ARGS[@]}" submodules >/dev/null
log "mpy-cross"
make -C "$MPY/mpy-cross" -j"$JOBS" >/dev/null
log "firmware $NAME"
make -C "$MPY/ports/$PORT" "${MAKE_ARGS[@]}" -j"$JOBS"

# --- output ---
case $PORT in
    rp2) EXTS=(uf2) ;;
    stm32) EXTS=(dfu hex) ;;
esac
REV=$(git -C "$REPO" describe --always --dirty 2>/dev/null || echo unknown)
mkdir -p "$REPO/dist"
log "done"
for ext in "${EXTS[@]}"; do
    out=$NAME-$REV.$ext
    cp "$MPY/ports/$PORT/$BUILD/firmware.$ext" "$REPO/dist/$out"
    (cd "$REPO/dist" && sha256sum "$out" > "$out.sha256")
    echo "$REPO/dist/$out"
done
echo "  micropython $MPY_REF, lvgl-micropython ${LVMP_SHA:0:7}, lvgl-bindings ${BINDINGS_SHA:0:7}"
arm-none-eabi-size "$MPY/ports/$PORT/$BUILD/firmware.elf"
