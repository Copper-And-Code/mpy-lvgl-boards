# LVGL display driver for the STM32H743 boards (LTDC panel + GT911 touch).
#
# `import display_driver` is all an application needs, as on the RP2350 board:
# it starts the panel (st_ltdc), LVGL on its framebuffers and a periodic
# lv.timer_handler(), so the application has no main loop.
#
# Panel: PANEL in /flash/display_config.py (default IPS1024x600, see panels.py).
# LVGL renders in DIRECT mode into the two framebuffers (outside the GC heap);
# the flush (in C) shows the new one at vertical blanking: no tearing. LVGL
# refreshes every REFR_PERIOD_MS (16 ms) instead of the binding's 33 ms.
# The GT911 is registered as LVGL pointer device (touch, indev); its pins come
# from stm32_board.py.
#
# Importing again is safe. After a soft reset the panel keeps scanning out the
# last image (st_ltdc.init() with the same timings does not restart it) and the
# board's soft-reset hook has already deinitialised LVGL.
#
# display_driver.stop() stops the periodic timer_handler, for applications
# that want their own loop; display_driver.start() restarts it.
#
# The names an application may use, and what they promise, are the contract in
# docs/display-driver.md (CONTRACT). Everything else here is internal.

import lvgl as lv
import micropython
import panels
import st_ltdc
import stm32_board
from machine import Timer

CONTRACT = 1  # version of the contract in docs/display-driver.md
PERIOD_MS = 5
# After a Ctrl-C handed on to the program, the service pauses this long, so that the
# scheduler run that raises it has no service run queued behind it.
HOLD_MS = 30
# LVGL's display refresh period. The binding's lv_conf.h has 33 ms (30 Hz at
# most); the panels run at about 58 Hz, and the flush no longer blocks for the
# vertical blanking, so animations can follow the panel.
REFR_PERIOD_MS = 16
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
    disp.get_refr_timer().set_period(REFR_PERIOD_MS)

# Touch: GT911 reports panel pixels (its configuration holds the panel size).
try:
    touch = stm32_board.touch()
    indev = touch.lv_register()
except OSError as e:
    touch = indev = None
    print("display_driver: no touch:", e)

# _timer and _task are deprecated as public names (examples/shell/ansiterm.py before
# CONTRACT 1 used them): they go away with the next contract version.
_timer = None
_busy = False
_resumer = None  # one shot timer that ends the pause after a Ctrl-C


# Ctrl-C: the program gets it, and the screen goes on (docs/display-driver.md).
# lv.timer_handler() takes most of the CPU, so a Ctrl-C usually becomes pending while it
# runs, in C, or in _tick. The VM raises it at the next jump; without one inside the try
# that is after it, where the scheduler prints and drops it. The `if`s inside the try
# blocks below are those jumps (the busy guard is inside too: it is a jump as well).
# The KeyboardInterrupt caught here is scheduled again for the program, and the service
# pauses HOLD_MS: a service run queued behind it would get it again. A Ctrl-C that lands
# in the touch read callback is kept by gt911 and handed on here in the same way. One
# that lands in a Python callback of the application is printed by LVGL and lost
# (measured: docs/log/ctrlc-probe-*). Where MicroPython has no threads (STM32) a
# pending Ctrl-C is not raised in scheduled callbacks at all and reaches the program
# directly; this code costs nothing there.
def _hand_on(resuming=False):
    global _resumer
    micropython.schedule(micropython.kbd_intr, None)
    if _timer is not None or resuming:
        stop()
        _resumer = Timer(-1, period=HOLD_MS, mode=Timer.ONE_SHOT, callback=_resume)


def _resume(_):
    try:
        if _resumer is not None:  # else stop() or start() came first
            start()
    except KeyboardInterrupt:
        _hand_on(True)  # a Ctrl-C while resuming: pause again, then resume


def _task(_):
    global _busy
    try:
        if _busy:
            return
        _busy = True
        try:
            lv.timer_handler()
            if touch is not None and touch.interrupted:
                touch.interrupted = False
                raise KeyboardInterrupt
        finally:
            _busy = False
    except KeyboardInterrupt:
        _hand_on()


def _tick(_):
    try:
        micropython.schedule(_task, None)
        if _busy:
            pass
    except RuntimeError:
        pass  # schedule queue full: the next tick will catch up
    except KeyboardInterrupt:
        _hand_on()


def backlight(percent=None):
    """Set the backlight (0-100) or, with no argument, read it. On/off on the
    STM32 boards for now (GPIO), so any percent above 0 is full brightness."""
    if percent is None:
        return st_ltdc.backlight()
    st_ltdc.backlight(percent)


def start():
    """Serve LVGL in the background every PERIOD_MS. Does nothing if it already does."""
    global _timer, _resumer
    if _resumer is not None:  # start() during the pause after a Ctrl-C: end it now
        _resumer.deinit()
        _resumer = None
    if _timer is None:
        _timer = Timer(-1, period=PERIOD_MS, mode=Timer.PERIODIC, callback=_tick)


def stop():
    """Stop serving LVGL; the screen keeps the last image. Does nothing if stopped."""
    global _timer, _resumer
    if _resumer is not None:
        _resumer.deinit()
        _resumer = None
    if _timer is not None:
        _timer.deinit()
        _timer = None


def running():
    """True while LVGL is served in the background (also during the HOLD_MS pause)."""
    return _timer is not None or _resumer is not None


start()
