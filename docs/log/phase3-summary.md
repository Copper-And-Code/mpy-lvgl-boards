# Phase 3 — rgbpanel scan-out (option b: 240x240 framebuffer, 2x2 pixels)

Decision (Nunzio, 2026-10-29): no PSRAM (U9 not fitted) → option (b) now, PSRAM later.
Scale is a build option: `MICROPY_HW_RGBPANEL_SCALE` in `mpconfigboard.h` (2 now, 1 with PSRAM).

Backlight polarity (Phase 1, by eye): PWM duty 0 % = **off** → normal polarity,
unlike the demo's `100 - percent`.

## Build
- rc=0, no warnings (`phase3-build.log`). FLASH 1 070 360 B, RAM (static) 156 764 B
  (framebuffer 115 200 B + 481 control blocks 7 696 B).
- PIO instruction memory: PIO1 30/32 (hsync 15, vsync 15), PIO2 32/32 (line 16, data_x2 16).

## On target (`phase3-t03_panel.txt`, `phase3-t03_softreset.txt`)
- `info()`: state machines (4, 5, 8, 9) = PIO1 SM0/1, PIO2 SM0/1; DMA channels 0, 1, 2.
- fps: 289 frames in 5000 ms → **57.80 fps** (nominal 57.73 at PCLK 15 MHz, sys 150 MHz).
- underruns: 0 over 5 s; **0 while writing 200 KB to flash** (30 frames counted in 525 ms:
  scan-out kept running with flash writes and interrupts disabled).
- `rp2.StateMachine(0)` on PIO0 works alongside.
- soft reset: scan-out keeps running (58 frames/s right after), framebuffer intact,
  same SMs/DMA channels, `init()` idempotent.
- `gc.mem_free()` with LVGL firmware + rgbpanel: 345 056 B.

## Pending (eyes)
- colour bar order and the 1-px yellow frame on all four edges (alignment of first/last
  pixel and first/last line);
- no visible glitch during flash writes;
- backlight after soft reset: PWM (1-99 %) is switched off by MicroPython's soft reset
  (`machine_pwm_deinit_all`); 0 % and 100 % use plain GPIO and are not affected.
