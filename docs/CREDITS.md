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
- **Nunzio Raciti (Copper-And-Code)** — the STM32H743 boards come from his earlier
  work, reused and adapted to MicroPython 1.29 out-of-tree boards:
  `boards/stm32/STM32H7_CORE/` from `Copper-And-Code/micropython` commit `7d0f87a84`
  (branch `add-STM32H7_CORE-board`); `boards/stm32/{DEV190806042,FK743M5-XIH6}/`
  `mpconfigboard.h` from `Copper-And-Code/lv_micropython` commits `c3545d440`,
  `a763dc856`, `d84e00f8e`. Schematics and photos: `Copper-And-Code/stm32h7-boards-docs`
  (schematic owners listed there). See `docs/stm32-inventory.md`.
- **HomeDing, Matthias Hertel** (BSD 3-Clause) — the ST7701 init sequence of the
  ESP32-4848S040 panel (`modules/esp_rgb/st7701_init.h`, re-encoded as data, with a
  software reset added and the display not inverted); licence in
  `modules/esp_rgb/LICENSE-HomeDing.txt`. Board pinout from the HomeDing board page.
