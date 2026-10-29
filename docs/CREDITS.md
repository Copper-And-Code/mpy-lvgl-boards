# Credits and provenance

- **Waveshare** — RP2350-Touch-LCD-4 hardware and schematic (pin assignment in
  `boards/rp2/WAVESHARE_RP2350_TOUCH_LCD_4/`), and the original C demo.
- **Dr Jon Durrant (DrJonEA)** — `RP2350Touch4-Exp` (MIT), used as reference for the
  board header layout. The `lib/RP2350Touch4/bsp/*` files in that repo come from the
  Waveshare demo and carry no licence header: nothing is copied from them. The ST7701S
  init sequence (panel data) will be reported with attribution in Phase 3.
- **PyDevices** — `lvgl-micropython` and `lvgl-bindings` (LVGL binding).
- **MicroPython** — `ports/rp2/boards/WAVESHARE_RP2350B_CORE` as starting point of the
  board definition (MIT).
