# Phase 5 — GT911 touch (Python, polled)

- `python/gt911.py` (frozen): reset with INT low → address 0x5D, product id "911", polled
  status register 0x814E, first point at 0x8150, status cleared after each report; last
  state kept between reports. Registered by `display_driver` as LVGL POINTER indev
  (`display_driver.touch`, `display_driver.indev`), coordinates divided by the scale (2).
- GT911 config read back (`phase5-gt911-regs.txt`): fw 0x1060, config v79, 480x480, 5 points.
- Command register 0x8040 read **0xFF** after reset. The first two raw captures recorded no
  touch at all; after writing 0 to 0x8040 touches were reported. Not proven to be the cause
  (the first captures may simply have missed the user's taps), but harmless: `GT911()` now
  always writes command 0.
- Orientation (`phase5-touch-paint.txt`, targets drawn on screen): top-left (0,0),
  top-right (237,0), bottom-left (0,239), bottom-right (236,237), centre (122,118) in the
  240x240 framebuffer → **no rotation, no mirroring**.
- LVGL click (`phase5-click-counters.txt`): button clicked 6 times, 4001 read_cb calls,
  16 with finger down, underruns 0.
- Timing: `read()` with no touch (one 1-byte register read at 400 kHz) 186-236 us average;
  read_cb max 5249 us over 4001 calls (includes a GC pass or a point read).
- Glitches seen while pressing (horizontal lines moving inside the button) came from a
  broken test callback raising AttributeError on every read (traceback printed to USB every
  33 ms). With the fixed callback: no glitch when pressing (Nunzio, by eye).
