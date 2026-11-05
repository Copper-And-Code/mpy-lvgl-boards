<!-- Draft for PyDevices/omnipython-lvgl, not sent. Title and body of the pull request
     from Copper-And-Code:lvmp-pools-tlsf (commit dcf165f). -->

# MicroPython: LVGL memory pools on ports without multi_heap

The ESP32 keeps LVGL's allocations in TLSF pools held in GC blocks
(`ports/micropython/src/lv_mem_core_micropython.c`, `LVMP_POOL`), because `gc_alloc()`
walks the allocation table from the first free block. Other ports with a large GC heap
have the same problem, and have no `multi_heap`. This lets a board turn the pools on with
LVGL's own TLSF. Off by default: a board opts in with `CFLAGS += -DLVMP_POOL_TLSF=1`.

## Why

STM32H743, MicroPython 1.29.0, 28 MB GC heap in a 16-bit SDRAM, LVGL 9.5, a 1024x600
display with 48 themed buttons, full refresh with `lv.refr_now()`, without the pools:

| GC heap state | 8 KB `bytearray` | full refresh |
|---|---|---|
| fresh | 181 us | 54 ms |
| 2 MB of bytearrays alive behind a free block | 611 us | **575 ms** |
| 30 000 small objects alive | 82 us | 53 ms |
| the same objects freed | 609 us | **574 ms** |

A refresh makes about 1200 LVGL allocations; a multi-block `gc_alloc()` does not move
`gc_last_free_atb_index`, so each one walks past every live block after the first hole.
So the frame time depends on what the application left in the heap.

## The change

- `src/lvmp_pool.h` (new): the `LVMP_POOL` switch and pool sizes, shared by three files.
  `LVMP_POOL` is now also on when the build defines `LVMP_POOL_TLSF=1`.
- `src/lv_mem_core_micropython.c`: unchanged on ESP32 (`multi_heap`); otherwise the same
  calls mapped to `lv_tlsf_*`.
- `src/lvmp_tlsf.c` (new, in `micropython.mk` and `micropython.cmake`): LVGL compiles
  `lv_tlsf.c` only with `LV_STDLIB_BUILTIN`, so this file includes it in a translation
  unit of its own with that setting, and `LV_MEM_SIZE` = one pool. Nothing in LVGL or
  `lv_conf.h` changes.
- The root pointer `lvmp_pool_mem` moves to `src/lvgl_micropython_build.c`: make builds
  put `lv_mem_core_micropython.c` in `SRC_USERMOD_LIB_C`, which is not scanned for
  `MP_REGISTER_ROOT_POINTER` (with the pools on, the build fails with "mp_state_vm_t has
  no member named lvmp_pool_mem").

## Tested

On this branch (`92f8c0a` + this commit), STM32H743 board, IPS 1024x600 panel, 2 MB of
application data kept in the heap:

| Display mode | full refresh, before | with the pools |
|---|---|---|
| DIRECT, 2 buffers | 273 ms | 53-64 ms |
| PARTIAL, 200 lines | 243 ms | 78 ms |

- 300 event callbacks that only LVGL refers to survive garbage and collections, also
  after `lv.deinit()`/`lv.init()`; 3 soft resets with LVGL left initialised, heap back to
  the same value each time; a touch game played by hand.
- Build, no warnings: STM32 (make, pools on), RP2350 (CMake, pools off, no pool symbols in
  the firmware).
- RP2350 board, pools off, on this branch against the same board on the old code:
  LVGL smoke test with soft resets, panel at 57.8 fps with no underruns, a touch game
  played by hand. Refresh times match within 7 us; the out-of-memory test behaves the
  same on both.
- `pytest ports/micropython/tests`: 5 passed.

ESP32-S3 (16 MB flash, 8 MB PSRAM, no display attached), MicroPython 1.29, ESP-IDF 5.5.2:
the LVGL smoke test with soft resets and the 300 callbacks test pass with the pools on
(`lv.init()` plus a display takes 262 208 B of GC heap, so a pool is held, and the
`multi_heap` code is in the ELF) and with a stock build (pools off).

To get the pools on I had to change three things in my test copy, none in this PR: see
"Pools off on a stock ESP32 build" below.

## Pools off on a stock ESP32 build

Not caused by this change, and left alone here: with stock MicroPython 1.29 and
`USER_C_MODULES` the pools do not reach the firmware, for two reasons:

- `MICROPY_MALLOC_USES_ALLOCATED_SIZE` is 0 on the esp32 port, and setting it to 1 does
  not build as is: `esp32_rmt.c` calls `m_free()` and `m_realloc()` without the size.
- The sources of the module are compiled twice, for `__idf_main` and for `micropython.elf`,
  and the second has no `-DESP_PLATFORM`. The objects linked are those, so `LVMP_POOL` is
  0 in them even with the flag on. The root pointer is still registered, unused.

Your builds may differ (I did not try `micropython-pydevices`). If it happens there too,
I can open a separate issue.

The "before" figures were measured on `PyDevices/lvgl-micropython` 3e287e7, the code this
moved from. Tests, logs and the board code:
[Copper-And-Code/mpy-lvgl-boards](https://github.com/Copper-And-Code/mpy-lvgl-boards),
`docs/stm32h743.md`, `tests/hil/stm32/t05_lvgl_gc.py`.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
