# LVGL display driver for the STM32H743 boards (LTDC panel + GT911 touch).
#
# `import display_driver` is all an application needs, as on the RP2350 board:
# it starts the panel (st_ltdc), LVGL on its framebuffers and a periodic
# lv.timer_handler(), so the application has no main loop.
#
# Panel: PANEL in /flash/display_config.py (default IPS1024x600, see panels.py).
# LVGL renders in DIRECT mode into the two framebuffers (outside the GC heap);
# the flush (in C) shows the new one at vertical blanking: no tearing.
# The GT911 is registered as LVGL pointer device (touch, indev); its pins come
# from stm32_board.py.
#
# Importing again is safe. After a soft reset the panel keeps scanning out the
# last image (st_ltdc.init() with the same timings does not restart it) and the
# board's soft-reset hook has already deinitialised LVGL.
#
# display_driver.stop() stops the periodic timer_handler, for applications
# that want their own loop; display_driver.start() restarts it.

import lvgl as lv
import micropython
import panels
import st_ltdc
import stm32_board
from machine import Timer

PERIOD_MS = 5
BUFFERS = 2

PANEL = stm32_board.panel()
_timing = panels.get(PANEL)
st_ltdc.init(**_timing, buffers=BUFFERS)
WIDTH, HEIGHT = _timing["width"], _timing["height"]

if not lv.is_initialized():
    lv.init()
st_ltdc.lv_tick_install()
disp = lv.display_get_default()
if disp is None:
    st_ltdc.lv_display_create()
    disp = lv.display_get_default()

# Touch: GT911 reports panel pixels (its configuration holds the panel size).
try:
    touch = stm32_board.touch()
    indev = touch.lv_register()
except OSError as e:
    touch = indev = None
    print("display_driver: no touch:", e)

_timer = None
_busy = False


# Ctrl-C while a program runs: lv.timer_handler() takes most of the CPU, so the
# KeyboardInterrupt usually lands in these callbacks, where it would be lost
# and the program would never stop. Stop the timer instead: the next Ctrl-C
# reaches the program. display_driver.start() resumes.
def _interrupted():
    stop()
    print("display_driver: stopped by Ctrl-C (display_driver.start() resumes)")


def _task(_):
    global _busy
    if _busy:
        return
    _busy = True
    try:
        lv.timer_handler()
    except KeyboardInterrupt:
        _interrupted()
    finally:
        _busy = False


def _tick(_):
    try:
        micropython.schedule(_task, None)
    except RuntimeError:
        pass  # schedule queue full: the next tick will catch up
    except KeyboardInterrupt:
        _interrupted()


def start():
    global _timer
    if _timer is None:
        _timer = Timer(-1, period=PERIOD_MS, mode=Timer.PERIODIC, callback=_tick)


def stop():
    global _timer
    if _timer is not None:
        _timer.deinit()
        _timer = None


start()
