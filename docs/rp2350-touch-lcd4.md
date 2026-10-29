# Waveshare RP2350-Touch-LCD-4: performance and memory

Measured on the board (RP2350B, 16 MB flash, **no PSRAM**: U9 not fitted), MicroPython
v1.29.0 + PyDevices lvgl-micropython `3e287e7` / lvgl-bindings `7740c2f` (LVGL 9.5),
`MICROPY_HW_RGBPANEL_SCALE = 2` (240x240 framebuffer shown as 2x2 pixels).
Raw logs in `docs/log/`.

## Scan-out and rendering vs clock

Core voltage untouched (default 1.10 V). `machine.freq()` then `rgbpanel.init(pclk_hz=...)`.
`refr_now` = full-screen invalidated `lv.refr_now()` of `tests/hil/scene_static.py`,
single buffer (no wait for the buffer swap). Source: `log/phase6-perf.txt`.

| sys clock | PCLK | divider | fps measured (nominal) | `refr_now` avg | underruns (3 s / 200 KB flash write) |
|---|---|---|---|---|---|
| 150 MHz | 15 MHz | 5 | 57.67 (57.73) | 9.23 ms | 0 / 0 |
| 200 MHz | 20 MHz | 5 | 76.67 (76.97) | 7.86 ms | 0 / 0 |
| 240 MHz | 20 MHz | 6 | 76.67 (76.97) | 7.25 ms | 0 / 0 |

Rendering speeds up less than the clock (150 → 240 MHz = x1.6, `refr_now` x1.27): code runs
from QSPI flash (XIP), whose clock divider MicroPython raises with the system clock.

Long flash-write test at 150 MHz: 107 x 200 KB in 90 s, 5219 frames (57.73 fps), 0 underruns,
no visible glitch (`log/phase3-flash-stress.txt`).

## Tearing and double buffering

With one framebuffer LVGL (DIRECT mode) draws into the buffer being scanned out: a vertical
bar sweeping across the screen showed visibly broken/offset (Nunzio, by eye). Waiting for
VSYNC in the flush callback cannot help in that mode (the drawing is already done when
flush is called).

Fix: **double buffering at 240x240**, which fits in SRAM (a second 480x480 buffer would not).
`rgbpanel.init(buffers=2)` allocates a second framebuffer and its list of control blocks on
the GC heap (122 896 B). The DMA block that ends every frame reads the list for the next
frame from a variable: pointing it at the other list swaps buffers exactly at the end of a
frame, in hardware, with no ISR. `swap()` returns once the control DMA channel reads from the
new list (so the old buffer is no longer read). LVGL draws into the hidden buffer; the flush
callback (in C) swaps. Result: bar straight, movement smooth (by eye).

`display_driver` uses two buffers by default (falls back to one on `MemoryError`).
Full-screen `lv.refr_now()` then takes ~17 ms (9.2 ms rendering + wait for the end of the
frame): LVGL refreshes at most once per panel frame (57.7 Hz at PCLK 15 MHz).
Pixel check vs the unix port still 64/64 tiles identical (`log/phase6-crc-doublebuf.txt`).

## Robustness: Ctrl-C and soft reset

- **Flush callback in C** (`rgbpanel.lv_display_create()`): with a Python `flush_cb`, a
  KeyboardInterrupt (Ctrl-C, or the Ctrl-C `mpremote` sends before every command) landing
  inside it is printed and swallowed by the binding, `flush_ready()` is never called, and
  LVGL's next refresh waits for the flush forever: the board hung (USB up, REPL dead,
  power cycle needed). With the Python flush + double buffer the board hung in 2 of 3
  soft-reset sequences (the third passed by timing luck); with the C flush
  6/6 soft resets with LVGL live were clean (`log/phase6-softreset-debug.txt`).
- **Ctrl-C reaches the program**: `lv.timer_handler()` takes most of the CPU, so a
  KeyboardInterrupt usually lands in display_driver's callbacks; there it now stops the
  timer, and the next Ctrl-C reaches the program (`mpremote` sends several). 3/3 interrupts
  of a running LVGL program succeeded at the first mpremote attempt (`log/phase6-ctrlc.txt`).
  `display_driver.start()` resumes.
- **Soft reset**: the board hook moves the image to the static framebuffer if the GC one was
  shown, drops the GC buffer, and clears LVGL's root (binding bug, see
  `upstream/pydevices-issue-soft-reset.md`). Scan-out keeps running throughout.

## Soak tests (150 MHz)

| Configuration | Duration | Frames | fps | Underruns | Errors | Python allocations | GC free, per-minute samples (t ≥ 60 s) |
|---|---|---|---|---|---|---|---|
| single buffer, Python flush | 3600 s | 207 823 | 57.73 | 0 | 0 | 668 760 | 252 848 .. 270 912 B |
| double buffer, C flush | 3600 s | 207 828 | 57.73 | 0 | 0 | 374 400 | 66 688 .. 147 952 B |

Scene: sweeping bar animation, spinner, label updated 5x/s, list/string churn,
`gc.collect()` every 10 s (`tests/hil/t06_soak.py`, `log/phase6-soak.txt`,
`log/phase6-soak-doublebuf.txt`).

- No leak: GC free has no trend over the hour in either run. The samples are taken
  between collections, so they include garbage; the single 66 688 B sample in the double
  buffer run is one such instant (the next minute is back at 139 840 B).
- The `min_free` column printed by the test is not meaningful: its starting value is
  `gc.mem_free()` before the first `gc.collect()` and no later sample went below it.
- The Python loop ran ~44 % fewer iterations with double buffering (allocation count):
  LVGL now waits for the end of the panel frame on every refresh, which leaves less CPU
  to the main loop at 150 MHz.

## Changing `machine.freq()`

The scan-out runs from `clk_sys`: after `machine.freq(f)` the PCLK scales with it until
`rgbpanel.init(pclk_hz=...)` is called. `init()` notices the new system clock and restarts
the scan-out with the new divider (panel not re-initialised, framebuffer kept, the shown
buffer kept). Only integer dividers are accepted: e.g. 200 MHz with 15 MHz PCLK is refused
with `ValueError` (no fractional-divider jitter). Decision: the driver does **not** follow
clock changes by itself (MicroPython has no hook for that); applications call
`rgbpanel.init()` after `machine.freq()`. The GT911 (I2C1, 400 kHz) answers normally at
240 MHz and back at 150 MHz without re-initialisation (`log/phase6-touch-freq.txt`).

## SRAM map (520 KiB, firmware with LVGL + rgbpanel + display_driver)

From `firmware.elf` (`arm-none-eabi-size -A`, `nm`):

| Region | Bytes | Notes |
|---|---|---|
| vector table + `.data` | 18 808 | includes code copied to RAM |
| `.bss` total | 135 900 | |
| — `rgbpanel_fb` (240x240 RGB565) | 115 200 | static, scanned out by DMA |
| — `rgbpanel_cb` (481 control blocks) | 7 696 | |
| — `mp_state_ctx` | 9 076 | |
| — rest | 3 928 | |
| C heap (`.heap`) | 2 048 | |
| **MicroPython GC heap** | **365 476** | `__GcHeapStart` 0x20025c5c .. `__GcHeapEnd` 0x2007f000 |
| core 1 stack | 4 096 | 0x2007f000 .. 0x20080000 |
| core 0 stack (SCRATCH_X/Y) | 8 192 | 0x20080000 .. 0x20082000 |

GC heap free (`gc.mem_free()`): 345 056 B with rgbpanel only; 331 968 B right after
`import display_driver`; ~274 000 B with a small LVGL scene and touch.

With a second framebuffer for double buffering (`init(buffers=2)`, GC heap): 115 200 + 7 696 B more:
`gc.mem_free()` ~211 000 B right after `import display_driver` with two buffers and touch.

**480x480 is not possible without PSRAM**: a 460 800 B framebuffer leaves ~27 KiB of SRAM
heap for everything else. With PSRAM fitted (APS6404L on U9, 8 MB, CS GPIO47) the GC heap
extends into PSRAM and `MICROPY_HW_RGBPANEL_SCALE = 1` becomes usable; a second 480x480
framebuffer still would not fit in SRAM (double buffering only at 240x240).

## PSRAM

None on this board (`gc.mem_free()` 474 496 B with the upstream WAVESHARE_RP2350B_CORE
firmware: SRAM only). Not measured.
