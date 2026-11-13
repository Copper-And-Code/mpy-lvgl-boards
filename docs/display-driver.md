# The `display_driver` contract

Every board has a frozen `display_driver.py`:
- `python/display_driver.py` on the RP2350;
- `python/stm32/display_driver.py` on the STM32H743 boards;
- `python/esp32/display_driver.py` on the ESP32-S3.

The names below are what an application, a test or LVGL MPY Studio may rely on, on
every board. Everything else in the drivers is internal and may change between
releases.

**Version 1** (`CONTRACT = 1`), from firmware v0.1.7. Before it, firmware v0.1.6 and
older, there is no `CONTRACT`.

## Names

| Name | What it promises |
|---|---|
| `import display_driver` | Display, touch and LVGL are on. LVGL is served in the background, `lv.timer_handler()` every `PERIOD_MS`, so the application needs no main loop. Importing again is safe. |
| `CONTRACT` | `1`, the version of this contract. A program can test `hasattr(display_driver, "CONTRACT")` to tell older firmware apart. |
| `WIDTH`, `HEIGHT` | The logical resolution LVGL draws at. On the RP2350 without PSRAM it is 240x240, shown as 2x2 pixels. |
| `BUFFERS` | How many framebuffers the driver uses: 2, or 1 when there was no room for two. |
| `PERIOD_MS` | The period of the background service. |
| `indev` | The touch input device, or `None` if no touch controller answered. |
| `start()` | Resumes the background service. Calling it while LVGL is being served does nothing. |
| `stop()` | Suspends the background service, and the screen keeps the last image. Calling it twice does nothing. For programs that want their own loop. |
| `running()` | `True` while LVGL is served in the background, including the short pause after a Ctrl-C (see below). |
| `backlight(percent=None)` | Sets the backlight, from 0 to 100. With no argument it returns the current level. On the STM32 boards the backlight is a GPIO for now, so any value above 0 is full brightness. |

## Ctrl-C

**A Ctrl-C reaches the program, and the screen goes on.** That is true whether the program
is in a Python loop, for example `while True: time.sleep_ms(10)`, or waits in
`sys.stdin.read()`, as the shell in `examples/shell` does. The driver is not stopped and
does not need `start()` afterwards.

### Why the driver has to do something

`lv.timer_handler()` takes most of the CPU, so a Ctrl-C usually arrives while it runs. It
arrives in C, inside a callback that MicroPython's scheduler runs. MicroPython raises a
pending Ctrl-C only at a jump in the bytecode. On the ports with threads (ESP32, RP2350)
it is raised in whatever Python code runs next. Without help from the driver, that is
right after the driver's own `try`, where the scheduler prints the exception and drops it.

The v0.1.6 drivers did catch the exception, but in the wrong place, so their "stopped by
Ctrl-C" path never ran. What happened instead (60 attempts each case, firmware v0.1.6):

| Board | Program in a Python loop | Program in `stdin.read()` |
|---|---|---|
| STM32H743 | 100% reach the program | 100% reach the program |
| ESP32-S3 | 22% (the rest printed and dropped) | 25% |
| RP2350 | 48% | 100% |

On the STM32H743 MicroPython has no threads. A pending Ctrl-C is never raised inside a
scheduled callback there: it waits for the program. So the STM32 drivers already behaved
as the contract says, and the code below costs nothing on them.

### What the driver does

- **A jump inside the `try` of each service callback.** This covers `_task` everywhere, and
  `_tick`, the timer callback, on the periodic timers of STM32 and RP2350. A Ctrl-C raised
  there lands in the driver's `except`.
- **The `KeyboardInterrupt` goes back to the program.** The driver schedules it again
  with `micropython.schedule(micropython.kbd_intr, None)`, which is documented MicroPython
  and needs `MICROPY_SCHEDULER_STATIC_NODES`, on in all three ports.
- **Then a pause of `HOLD_MS` (30 ms).** Any service run scheduled right behind would get
  the exception again, so the driver waits before serving LVGL again:
  - on the ESP32, the next one shot run is armed after `HOLD_MS`;
  - on the periodic timers, the service stops and a one shot timer resumes it.
  The pause is the cost: the screen stops for about 30 ms on every Ctrl-C. The frame rate
  is otherwise unchanged (58.3, 42.3 and 28.3 fps, before and after).
- **The touch read callback** (`gt911.GT911.lv_read_cb`) is a Python callback that LVGL
  calls from inside `lv.timer_handler()`. It keeps a Ctrl-C that lands in it in
  `touch.interrupted`. The driver hands it on after `lv.timer_handler()` in the same way.

### What is not covered

**A Ctrl-C that lands in a Python callback of the application.** This means an
`lv.timer`, or an event or animation callback, that LVGL calls from inside
`lv.timer_handler()`. LVGL prints such a Ctrl-C as a traceback and it does not reach the
program. It is rare: on the ESP32-S3 it was 2 of 60 attempts, with an `lv.timer` running
a Python loop every 20 ms. It was none of 60 on the RP2350, and it cannot happen on the
STM32H743, where a Ctrl-C always waits for the program. An application that needs every
Ctrl-C can catch `KeyboardInterrupt` in its own callbacks.

**Measured on the firmware with these drivers frozen in**, 2026-11-13, on all three
boards: 60 attempts in each of `sleep`, `stdin`, `cb` and `sleep` with a finger moving
on the screen.
- STM32H743 (V1.3): every Ctrl-C reached the program once, in all four. 58.3 fps.
- RP2350: the same. 28.3 fps.
- ESP32-S3: the same, except 2 of 60 in `cb`, which landed in the application's own
  `lv.timer` (see above). 42.3 fps.
- The shell in `examples/shell` stopped `sleep 2` and a long `cat` every time, on all
  three boards, and `vi` and `edit` take Ctrl-C as a key.
- The display terminal of the shell, `examples/shell/ansiterm.py`, needs the same care
  as the driver. MicroPython calls its `write()` through `os.dupterm`, and drops the
  terminal for good if a `KeyboardInterrupt` leaves it. On the STM32H743 the serial port
  is a blocking UART, so a Ctrl-C usually arrives while the same text is being sent, in
  C, and is raised at the first jump in `write()`. That jump was before the `try`: half
  the Ctrl-C during a long `cat` were lost there, and the display stopped showing the
  output. Now the whole of `write()` is inside the `try`
  (`docs/log/shell-ctrlc-V13-contract-output*.txt`, before and after).
- Logs: `docs/log/ctrlc-contract-*`, `docs/log/shell-ctrlc-*-contract.txt`,
  `docs/log/editor-ctrlc-4848S040-contract.txt`; the measurements before the change,
  with candidate callbacks in RAM on firmware v0.1.6, are in `docs/log/ctrlc-probe-*`.
- The test: `tests/hil/t10_ctrlc_probe.py`, run by `tests/hil/ctrlc_probe_host.py`.
  - Modes: `--mode sleep|stdin|cb`.
  - `--expect contract` fails unless every Ctrl-C reached the program once and the
    service never stopped.

## Deprecated names

`_task` and `_timer` on every board, and `_arm()` on the ESP32, were used by
`examples/shell/ansiterm.py` before contract 1:
- they stay for this version, so programs written for v0.1.6 keep working;
- they go away with contract 2;
- a program that replaces `display_driver._task` still works, but then it also takes over
  the Ctrl-C handling described above.

## Tests

- `tests/host/display_driver.py` is the unix stand-in with the same names, and
  `tests/host/test_display_contract.py` checks them. Both run on the unix port with LVGL:
  `cd tests/host && micropython test_display_contract.py`.
- The same test also runs on a board, against the real driver.
- `tests/host/test_driver_ctrlc.py` runs the real RP2350 driver on the unix port, with
  `rgbpanel`, `machine.Timer`, the touch and `micropython.schedule` stubbed. It checks the
  hand-on and the pause, the resume, `stop()` and `start()` during the pause, and a Ctrl-C
  while resuming or inside `_tick`. The STM32 driver has the same code. The ESP32 one is
  checked only on the board.
- `tests/hil/t10_ctrlc_probe.py` is the regression test for the Ctrl-C behaviour above.
