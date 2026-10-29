# Credits and provenance

- **Waveshare** — RP2350-Touch-LCD-4 hardware and schematic (pin assignment in
  `boards/rp2/WAVESHARE_RP2350_TOUCH_LCD_4/`), and the original C demo.
- **Dr Jon Durrant (DrJonEA)** — `RP2350Touch4-Exp` (MIT), used as reference for the
  board header layout. The `lib/RP2350Touch4/bsp/*` files in that repo come from the
  Waveshare demo and carry no licence header. Taken from them, as data only:
  the ST7701S init sequence (`modules/rgbpanel/st7701_init.h`, re-encoded) and the
  panel timing values (porches/sync widths in `modules/rgbpanel/rgbpanel.pio`).
  The PIO programs and the DMA code are rewritten (DE driven with the pixels,
  IRQ-free chained DMA, pixel doubling).
- **PyDevices** — `lvgl-micropython` and `lvgl-bindings` (LVGL binding).
- **MicroPython** — `ports/rp2/boards/WAVESHARE_RP2350B_CORE` as starting point of the
  board definition (MIT).
