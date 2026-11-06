# Examples

They run on every board of this repo (the RP2350-Touch-LCD-4 at 240x240, the STM32H743
boards at their panel's size, 1024x600 on the IPS panel) with the same code.

RP2350: run one with `mpremote run examples/<name>.py`; to start it at power-on copy it
to the board as `main.py` (`mpremote cp examples/<name>.py :main.py`).
STM32H7_CORE V1.3 on the bench (CH340 on UART1, DTR/RTS wired to BOOT0/NRST):
`python3 scripts/uart_run.py examples/<name>.py` (see `docs/stm32h743.md`).

| Example | Shows |
|---|---|
| [hello.py](hello.py) | the minimum: `import display_driver`, a label, a spinner |
| [button.py](button.py) | touch: a button counting taps |
| [animation.py](animation.py) | LVGL animations (no tearing: double buffered) |
| [backlight.py](backlight.py) | a slider setting the backlight with `display_driver.backlight()` (on/off on the STM32 boards for now) |
| [c64_keyboard.py](c64_keyboard.py) | typing on a C64-style keyboard (TCA8418 on connector H4 of the RP2350 board, see `python/c64keyboard.py`); without it, says so |
| [breakout.py](breakout.py) | a game: drag the paddle, break the bricks (ball physics in an LVGL timer, buzzer if the board has one) |
| [pong.py](pong.py) | a game: you against the microcontroller, drag your paddle up and down |
| [simon.py](simon.py) | a game: repeat the growing sequence of colours (LVGL timer, buzzer if the board has one) |
| [snake.py](snake.py) | a game: snake controlled by tapping on the side to turn to (LVGL objects reused as segments) |
| [tictactoe.py](tictactoe.py) | a game: you (X) against the microcontroller (O, minimax: it never loses) |
| [weather.py](weather.py) | ESP32-4848S040 only: weather, wind and 5 days of forecast from Open-Meteo, with drawn icons, setup on the touchscreen and settings on the SD card |

Any resolution: sizes are written for a 240 px display and scaled with `ui.px(n)`
(`python/ui.py`: `n` times the shorter side / 240, so unchanged on the RP2350 board),
fonts with `ui.font(size)` (the closest Montserrat compiled in: 14, 16, 24, 32, 40),
positions from `display_driver.WIDTH` / `HEIGHT` or LVGL alignment. Game speeds scale
with `ui.UNIT` too; the breakout wall and the snake field get more columns on a wide
display. Sound goes through `python/buzzer.py` (GPIO1 on the RP2350 board; silent where
there is no buzzer, as on the STM32 boards so far).

Every example ends after building its screen: `display_driver` keeps LVGL running from
a timer. `mpremote` (or, on the STM32 bench, opening the serial port) resets the board before
each run, so running another example replaces the previous one. Ctrl-C works as usual in programs with their own loop.
