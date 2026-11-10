# Build target and pinned inputs

Recorded 2026-10-29 (Phase 0), for the RP2350 board. Since 2026-11-10 every board uses
PyDevices/omnipython-lvgl, at `OPL_SHA` in `scripts/build_esp32.sh` and `scripts/build.sh`
(`c34fbeeb0440e71acb62c92ddee1c3c65d089622`), with its `lvgl` submodule (LVGL 9.5,
`85aa60d`, the same LVGL as before); the lvgl-micropython and lvgl-bindings rows below are
the RP2350 inputs up to v0.1.5.

| Input | Commit | Tag / note |
|---|---|---|
| micropython/micropython | `0fd6c573ea815774668bbb16b8e197c8822368b2` | `v1.29.0` |
| micropython `lib/pico-sdk` | `98a542c1a62fb549ffb5d66a3e5892b06276b670` | `2.3.0` |
| PyDevices/lvgl-micropython | `3e287e725886673d0a3b019a68d83ccf66ae4196` | HEAD on 2026-10-29 |
| PyDevices/lvgl-bindings | `7740c2fae0daa10992f5f8fe54acf670a70e2d3b` | `v9.5.23`, = `LVGL_BINDINGS_COMMIT` |
| lvgl (submodule of lvgl-bindings) | `85aa60d18b3d5e5588d7b247abf90198f07c8a63` | LVGL 9.5 |
| Copper-And-Code/RP2350Touch4-Exp (reference only) | `a78b701595a8c57695069e0a637ad549d2b5e082` | |

| Tool | Version |
|---|---|
| arm-none-eabi-gcc | xPack 15.2.1-1.1 (`work/tools/`, 15.2.1 20251203) |
| picotool | 2.0.0 (`~/.pico-sdk/picotool/2.0.0`) |
| mpremote | 1.27.0 |
| Python | 3.11.7 |

## Workspace layout

```text
work/
  micropython/        v1.29.0, rp2 + unix submodules
  omnipython-lvgl/    PyDevices, at OPL_SHA, with lvgl submodule
  mpy-lvgl-boards/    this repo
  tools/              xPack toolchain
../RP2350Touch4-Exp/  reference C demo (read only)
```

## Build commands

`scripts/build_rp2.sh` does all of this with the pins above (sources in `.work/` unless
`WORK_DIR` is set). By hand, in the workspace:

```bash
export PATH=$PWD/tools/xpack-arm-none-eabi-gcc-15.2.1-1.1/bin:$PATH
B=$PWD/mpy-lvgl-boards/boards/rp2/WAVESHARE_RP2350_TOUCH_LCD_4

# with LVGL (default manifest; omnipython-lvgl beside mpy-lvgl-boards, or
# LVMP_DIR=<omnipython-lvgl>/ports/micropython)
make -C micropython/ports/rp2 BOARD_DIR=$B BUILD=build-TLCD4 -j

# bring-up build without LVGL
make -C micropython/ports/rp2 BOARD_DIR=$B BUILD=build-TLCD4-nolvgl FROZEN_MANIFEST=$B/manifest_nolvgl.py -j
```

MicroPython 1.29 takes the LVGL C module from the manifest
(`include("$(LVMP_DIR)/manifest.py")`, which calls `c_module(".")`), not from
`USER_C_MODULES`. `LVMP_DIR` reaches the manifest as the CMake variable
`MICROPY_MANIFEST_LVMP_DIR`, set in `mpconfigboard.cmake`.
