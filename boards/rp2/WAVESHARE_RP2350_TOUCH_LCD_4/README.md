# Waveshare RP2350-Touch-LCD-4

Upstream MicroPython v1.29 with LVGL 9.5 (`import lvgl as lv`, PyDevices binding) for the
[Waveshare RP2350-Touch-LCD-4](https://www.waveshare.com/wiki/RP2350-Touch-LCD-4):
RP2350B, 16 MB flash, 4" 480x480 ST7701S RGB panel, GT911 capacitive touch.

This is an out-of-tree board: no fork of MicroPython or of the LVGL binding. The RGB
panel is driven by `rgbpanel`, a user C module in this repo (PIO + DMA, no CPU and no
interrupts during scan-out).

## Status

Measured on one board, without PSRAM. Logs and method in
[`docs/rp2350-touch-lcd4.md`](../../../docs/rp2350-touch-lcd4.md) and `docs/log/`.

| | State |
|---|---|
| Display | Works. **240x240 framebuffer shown as 2x2 pixels** (see *PSRAM* below). 57.7 fps at the default 150 MHz, 0 underruns in 1 h and during flash writes |
| LVGL | Works. Double buffered (no tearing), pixel output identical to the unix port (64/64 tiles CRC). Full-screen redraw 9.2 ms at 150 MHz |
| Touch | Works (GT911, LVGL pointer device, no rotation needed) |
| Soft reset, Ctrl-C | Work with LVGL running (the scan-out keeps going; LVGL restarts clean) |
| Overclock | 200 and 240 MHz tested (PCLK 20 MHz, 76.7 fps), core voltage unchanged. Not the default |
| Backlight | PWM, 0–100 % |
| PSRAM (U9, not fitted on our board) | Firmware supports it (autodetect, CS GPIO47); **not tested** |
| 480x480 framebuffer | Not possible without PSRAM; not tested |
| SD card, CAN (XL2515), RTC, IMU, buzzer, battery | Not covered by this port beyond the pin names. RTC (0x51) and IMU (0x6B) answer on I2C1 |

### PSRAM and resolution

A 480x480 RGB565 framebuffer is 460 800 B; the RP2350 has 520 KiB of SRAM. The PSRAM
footprint (U9) is marked NC on the schematic and is empty on our board, so the default
build uses a 240x240 framebuffer (115 200 B) that the hardware doubles in both directions.
LVGL works at 240x240; text and graphics are visibly coarser than native resolution.

With an APS6404L fitted on U9 the firmware adds the PSRAM to the MicroPython heap.
Building with `MICROPY_HW_RGBPANEL_SCALE` set to 1 in `mpconfigboard.h` should then give
480x480 with one buffer (a second 480x480 buffer does not fit in SRAM). Untested.

## Build

Linux x86-64, with git, make, cmake, Python 3 and a host C compiler:

```bash
scripts/build_rp2.sh            # → dist/WAVESHARE_RP2350_TOUCH_LCD_4-<commit>.uf2
```

The script clones MicroPython `v1.29.0` and PyDevices `lvgl-micropython` at pinned commits
into `.work/` (the LVGL binding and LVGL follow lvgl-micropython's pin), downloads the
xPack arm-none-eabi-gcc 15.2.1-1.1 toolchain (checksum verified) and builds. Running it
again reuses everything. `WORK_DIR` and `TOOLCHAIN_DIR` override the locations.

By hand, with checkouts of the pinned versions:

```bash
LVMP_DIR=/path/to/lvgl-micropython \
make -C micropython/ports/rp2 BOARD_DIR=$PWD/boards/rp2/WAVESHARE_RP2350_TOUCH_LCD_4
```

## Flash

Hold BOOT, plug USB (or press RESET with BOOT held): the board appears as the `RP2350`
drive. Copy the `.uf2` onto it, or:

```bash
picotool load -x WAVESHARE_RP2350_TOUCH_LCD_4-<commit>.uf2
```

From a running MicroPython: `mpremote bootloader`, then the same.

The filesystem (12 MiB, LittleFS) starts after the first 4 MiB of flash and is kept
across firmware updates.

## Use

```python
import lvgl as lv
import display_driver       # panel, LVGL display, touch, timer: nothing else to call

scr = lv.screen_active()
btn = lv.button(scr)
btn.center()
lv.label(btn).set_text("Hello")
```

`display_driver` runs `lv.timer_handler()` from a 5 ms timer, so a script can end and the
UI keeps running (put it in `main.py` to start at boot). It sets up:

- `display_driver.disp`: the LVGL display, `WIDTH` x `HEIGHT` (240 x 240), RGB565;
- `display_driver.indev`: the GT911 pointer device (`None` if the touch does not answer);
- `display_driver.stop()` / `start()`: stop/restart the timer, for programs with their own
  loop calling `lv.timer_handler()`.

Ctrl-C while an LVGL program runs: the first interrupt may stop the LVGL timer instead of
the program (a message says so); the next one reaches the program. `mpremote` sends
several, so `mpremote run` / `exec` are interrupted normally.

After `machine.freq(f)` call `rgbpanel.init(pclk_hz=...)` with a PCLK that divides
`f / 2` exactly (e.g. 15 MHz at 150 MHz, 20 MHz at 200 or 240 MHz). Otherwise the panel
clock follows the system clock and may go out of the panel's range.

### Memory limits (no PSRAM)

About 210 KB of heap is free after `import display_driver`; LVGL objects, styles, fonts
and images loaded at run time, and the application all share it. Tested with
lvgl-mpy-builder output: a 3-page, 21-widget UI runs with 205 KB free; its 34-widget
"all widgets" test project builds but leaves only ~70 KB free.

**Avoid opacity (`style_opa` < 255), transforms (`style_transform_rotation`/`_scale`)
and blend modes on large widgets.** LVGL draws those through a separate ARGB8888 layer
allocated in one piece (4 bytes per pixel of the widget): a 200x150 rotated panel asked for
146 KB. If that allocation fails, LVGL is left half-way through the refresh: the
`MemoryError` is printed, the screen stops updating, and the next change to a widget hangs
the board (power cycle needed). This is LVGL/binding behaviour, not specific to this
board (`docs/upstream/pydevices-issue-oom-render.md`); with PSRAM there is more room
but the rule stays.

### `rgbpanel` (lower level)

| | |
|---|---|
| `init(pclk_hz=15_000_000, backlight=80, *, buffers=None)` | start the panel (idempotent; restarts the scan-out if the system clock changed). `buffers=2` allocates a second framebuffer on the heap, `1` frees it |
| `deinit()` | stop the scan-out |
| `framebuffer(i=0)` | memoryview (`'H'`, RGB565) of framebuffer `i` |
| `shown()`, `swap(timeout_ms=100)` | index of the buffer on screen; show the other one at the end of the frame |
| `backlight([percent])` | get/set the backlight |
| `wait_vsync(timeout_ms=100)` | wait for the end of the active area |
| `frame_count()`, `underruns()`, `info()` | counters and state |
| `WIDTH`, `HEIGHT`, `SCALE` | framebuffer size and pixel scale |

### Resources used

- PIO1 (2 state machines) and PIO2 (2 state machines, all 32 instructions); PIO0 is free
  for `rp2.StateMachine`.
- 3 DMA channels, claimed from the pico-sdk (not visible to `rp2.DMA`).
- PWM slice 8 (backlight, GPIO40).
- SRAM: 123 KB for the static framebuffer and DMA control blocks, 123 KB more on the heap
  with double buffering. Free heap after `import display_driver`: ~211 KB.
- I2C1 (GPIO6/7, 400 kHz) for the touch, shared with RTC and IMU: `machine.I2C(1)`.

## Pinout

| Function | GPIO |
|---|---|
| LCD data RGB565 (B1–B5, G0–G5, R1–R5) | 24–39 |
| LCD DE / VSYNC / HSYNC / PCLK | 20 / 21 / 22 / 23 |
| LCD init SPI (9-bit, bit-banged): CS / SCK / SDA / RST | 18 / 2 / 3 / 19 |
| Backlight | 40 |
| Touch GT911 (I2C1 0x5D): SDA / SCL / RST / INT | 6 / 7 / 16 / 17 |
| RTC PCF85063 (I2C1 0x51) INT | 0 |
| IMU QMI8658 (I2C1 0x6B) INT1 / INT2 | 41 / 42 |
| CAN XL2515 (SPI0): SCK / MOSI / MISO / CS / INT | 2 / 3 / 4 / 5 / 44 |
| SD card (SDIO): CLK / CMD / D0–D3 | 10 / 11 / 12–15 |
| Buzzer | 1 |
| Battery CHRG / DONE | 42 / 43 (as on the schematic table; GPIO42 is listed twice) |
| UART0 TX / RX (REPL is on USB) | 46 / 45 |
| UART1 TX / RX | 8 / 9 |
| PSRAM CS (U9) | 47 |

GPIO2/3 are shared by the LCD init SPI and the CAN controller: initialise CAN after the
display (`rgbpanel.init()` only uses them during the panel init) and keep LCD_CS (GPIO18)
high. Names from `pins.csv` are available as `machine.Pin("LCD_BL")` etc.

## Credits

- Waveshare: hardware, schematic, C demo (ST7701S init sequence and panel timing values).
- Dr Jon Durrant (DrJonEA), `RP2350Touch4-Exp`: reference for the board header.
- PyDevices: `lvgl-micropython` and `lvgl-bindings`.
- MicroPython: `WAVESHARE_RP2350B_CORE` board definition as starting point.

Examples: [`examples/`](../../../examples/).

Details and provenance in [`docs/CREDITS.md`](../../../docs/CREDITS.md).
