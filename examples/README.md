# Examples for the Waveshare RP2350-Touch-LCD-4

Run one with `mpremote run examples/<name>.py`; to start it at power-on copy it to
the board as `main.py` (`mpremote cp examples/<name>.py :main.py`).

| Example | Shows |
|---|---|
| [hello.py](hello.py) | the minimum: `import display_driver`, a label, a spinner |
| [button.py](button.py) | touch: a button counting taps |
| [animation.py](animation.py) | LVGL animations (no tearing: double buffered) |
| [backlight.py](backlight.py) | a slider setting the backlight with `rgbpanel.backlight()` |

The display is 240x240 for LVGL (the 480x480 panel shows each pixel as 2x2, see the
[board README](../boards/rp2/WAVESHARE_RP2350_TOUCH_LCD_4/README.md)); the examples use
`display_driver.WIDTH` / `HEIGHT` or LVGL alignment, so they also fit 480x480.

Every example ends after building its screen: `display_driver` keeps LVGL running from
a timer. `mpremote` resets the board before each `run`, so running another example
replaces the previous one. Ctrl-C works as usual in programs with their own loop.
