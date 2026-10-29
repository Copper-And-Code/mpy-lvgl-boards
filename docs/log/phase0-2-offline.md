# Phases 0-2, offline part (2026-10-29)

Board not connected over USB at this point: everything below was run on the host.

## Schematic re-check (RP2350-Touch-LCD-4.pdf, single A4 sheet)
- U9 footprint (PSRAM, SOIC-8) is marked **NC**, /CS on `QSPI_SS2`, R24 10k pull-up.
- Pin table: `QSPI_SS2` = GPIO47. LCD 18-40 as in the plan.
- Not in the plan: **GPIO44 = XL2515_INT** (CAN interrupt). Added to `pins.csv` as `CAN_INT`.
- GPIO42 appears in both IMU_INT2 and BAT CHRG columns (left as-is, out of scope).

## Phase 0.3 — upstream WAVESHARE_RP2350B_CORE build
- `make -C ports/rp2 BOARD=WAVESHARE_RP2350B_CORE`: rc=0, FLASH 334 932 B, RAM 32 428 B, uf2 670 208 B.
- Boot-time pin check: `PICO_DEFAULT_LED_PIN 39` is only a `pins.csv` alias (not driven at
  boot); UART REPL off (`MICROPY_HW_ENABLE_UART_REPL 0`); PSRAM init touches only GPIO47.
  **No display pin (24-40) is driven at boot** → safe to flash.

## Phase 1 — board build without LVGL
- rc=0 (log: `phase1-build.log`). FLASH 336 084 B of 4 MiB, FLASH_FS 12 MiB, RAM 32 460 B.
- Fix needed: `PICO_FLASH_SIZE_BYTES` must not be redefined in `mpconfigboard.h` (the SDK
  passes it on the command line from the `pico_cmake_set_default` comment → `-Werror`).

## Phase 2 — board build with LVGL (PyDevices)
- Integration form on MicroPython 1.29: **manifest** (`include(".../lvgl-micropython/manifest.py")`
  → `c_module(".")`), not `USER_C_MODULES`. Bindings found beside lvgl-micropython, at the pin.
- rc=0, **no patch to PyDevices, no libm issue** (no undefined float symbols). Log: `phase2-build.log`.
- `arm-none-eabi-size`: text 1 076 448, data 0, bss 13 212. uf2 2 132 992 B.
- `__GcHeapStart` 0x20007bf4, `__GcHeapEnd` 0x2007f000 → **SRAM heap 488 460 B (477 KiB)**.
- With the 480×480 RGB565 framebuffer (460 800 B) taken from SRAM: **27 660 B (27 KiB) left**,
  not ~70 KiB as estimated in the plan (.data/.bss ~32 KiB, stack in SCRATCH_Y, 4 KiB above heap end).

## Smoke test script validated on the unix port
Unix build with the same binding (`micropython-lvgl`), `tests/hil/t02_lvgl_smoke.py`:
```text
mem_free before: 2070656
clicked
Hello from LVGL - drew 240 px wide refr_now 135 us
mem_free after scene: 2000384
mem_free after deinit: 2070656
clicked
Hello from LVGL - drew 240 px wide refr_now 122 us
OK
```
