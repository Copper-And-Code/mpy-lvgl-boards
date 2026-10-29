# Examples for the Waveshare RP2350-Touch-LCD-4

Run one with `mpremote run examples/<name>.py`; to start it at power-on copy it to
the board as `main.py` (`mpremote cp examples/<name>.py :main.py`).

| Example | Shows |
|---|---|
| [hello.py](hello.py) | the minimum: `import display_driver`, a label, a spinner |
| [button.py](button.py) | touch: a button counting taps |
| [animation.py](animation.py) | LVGL animations (no tearing: double buffered) |
| [backlight.py](backlight.py) | a slider setting the backlight with `rgbpanel.backlight()` |
| [c64_keyboard.py](c64_keyboard.py) | typing on a C64-style keyboard (TCA8418 on connector H4, see `python/c64keyboard.py`); without it, says so |
| [breakout.py](breakout.py) | a game: drag the paddle, break the bricks (ball physics in an LVGL timer, buzzer) |
| [pong.py](pong.py) | a game: you against the microcontroller, drag your paddle up and down |
| [simon.py](simon.py) | a game: repeat the growing sequence of colours (LVGL timer, buzzer on GPIO1) |
| [snake.py](snake.py) | a game: snake controlled by tapping on the side to turn to (LVGL objects reused as segments) |
| [tictactoe.py](tictactoe.py) | a game: you (X) against the microcontroller (O, minimax: it never loses) |

The display is 240x240 for LVGL (the 480x480 panel shows each pixel as 2x2, see the
[board README](../boards/rp2/WAVESHARE_RP2350_TOUCH_LCD_4/README.md)); the examples use
`display_driver.WIDTH` / `HEIGHT` or LVGL alignment, so they also fit 480x480.

Every example ends after building its screen: `display_driver` keeps LVGL running from
a timer. `mpremote` resets the board before each `run`, so running another example
replaces the previous one. Ctrl-C works as usual in programs with their own loop.
