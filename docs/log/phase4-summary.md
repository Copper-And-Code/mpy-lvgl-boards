# Phase 4 — LVGL on the panel (display_driver.py)

- `display_driver.py` (frozen): rgbpanel.init(), lv.init(), C tick (`rgbpanel.lv_tick_install()`),
  240x240 RGB565 display in DIRECT mode on the rgbpanel framebuffer (memoryview of static
  SRAM, accepted by `set_buffers`), flush_cb = flush_ready only, `lv.timer_handler()` every
  5 ms via machine.Timer → micropython.schedule with re-entrancy guard; stop()/start().
- **Soft reset bug found** (lvgl-micropython binding): LVGL's global state lives in GC memory
  behind root pointers (`mp_lv_roots`, `mp_lv_roots_initialized`) that `mp_init()` does not
  clear. After Ctrl-D without `lv.deinit()`, `lv.init()` sees "initialized" and works on freed
  memory: the board hung (USB enumerated, REPL dead, not recoverable over USB; needed a power
  cycle). Probe log: `phase4-lvgl-softreset-probe.txt`.
  Fix in this repo: `MICROPY_BOARD_END_SOFT_RESET()` → `rgbpanel_board_end_soft_reset()` →
  `mp_lv_deinit_gc()`. Verified: 3 consecutive soft resets with LVGL live, mem_free identical
  (331 968 B) each time (`phase4-lvgl-softreset.txt`). Candidate upstream issue (🧑).
- Pixel check vs the unix port (same binding, same lv_conf): static scene `tests/hil/scene_static.py`,
  CRC32 per 32x32 tile: **64/64 tiles identical** (`phase4-crc-target.txt`, `phase4-crc-unix.txt`).
- `lv.refr_now()` full screen invalidated, 240x240, 150 MHz: 9426, 9330, 9125, 9119, 9123 us.
