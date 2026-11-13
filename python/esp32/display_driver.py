# LVGL display driver for the ESP32-4848S040 (RGB panel + GT911 touch).
#
# `import display_driver` is all an application needs, as on the RP2350 board:
# it starts the panel (esp_rgb), LVGL on its framebuffers and a periodic
# lv.timer_handler(), so the application has no main loop.
#
# LVGL renders in DIRECT mode into the two framebuffers (in PSRAM, outside the GC
# heap); the flush (in C) shows the new one at the next frame: no tearing.
# The GT911 is registered as LVGL pointer device (touch, indev). Its RST and INT are
# not wired on this board.
#
# Importing again is safe. After a soft reset the panel keeps scanning out the
# last image (esp_rgb.init() with the same timings does not restart it) and the
# board's soft-reset hook has already deinitialised LVGL.
#
# display_driver.stop() stops the periodic timer_handler, for applications
# that want their own loop; display_driver.start() restarts it.
#
# The names an application may use, and what they promise, are the contract in
# docs/display-driver.md (CONTRACT). Everything else here is internal.

import esp_rgb
import gt911
import lvgl as lv
import micropython
import panels
from machine import PWM, Pin, SoftI2C, Timer

CONTRACT = 1  # version of the contract in docs/display-driver.md
PERIOD_MS = 5
# After a Ctrl-C handed on to the program, the next service run waits this long, so
# that the scheduler run that raises it has no service run queued behind it.
HOLD_MS = 30
# LVGL's display refresh period. The binding's lv_conf.h has 33 ms (30 Hz at
# most); the panels run at about 58 Hz, and the flush no longer blocks for the
# vertical blanking, so animations can follow the panel.
REFR_PERIOD_MS = 16
BUFFERS = 2

TIMER_ID = 0
BACKLIGHT = 70  # percent, at start
BACKLIGHT_PIN = 38
BACKLIGHT_HZ = 2000
PANEL = "ST7701_4848S040"
_timing = panels.get(PANEL)
esp_rgb.init(**_timing, buffers=BUFFERS, backlight=0)
WIDTH, HEIGHT = _timing["width"], _timing["height"]

if not lv.is_initialized():
    lv.init()
esp_rgb.lv_tick_install()
disp = lv.display_get_default()
if disp is None:
    esp_rgb.lv_display_create()
    disp = lv.display_get_default()
    disp.get_refr_timer().set_period(REFR_PERIOD_MS)

# GT911 reports panel pixels (its configuration holds the panel size).
try:
    touch = gt911.GT911(i2c=SoftI2C(scl=Pin(45), sda=Pin(19), freq=400_000), rst=None)
    indev = touch.lv_register()
except OSError as e:
    touch = indev = None
    print("display_driver: no touch:", e)

_timer = None
_backlight = PWM(Pin(BACKLIGHT_PIN), freq=BACKLIGHT_HZ, duty_u16=0)
_percent = 0


# Ctrl-C: the program gets it, and the screen goes on (docs/display-driver.md).
# lv.timer_handler() takes most of the CPU, so a Ctrl-C usually becomes pending while it
# runs, in C. The VM raises it at the next jump; without one inside the try that is
# after it, where the scheduler prints and drops it. The `if` below is that jump. The
# KeyboardInterrupt caught here is then scheduled again for the program, and the next
# service run waits HOLD_MS: run sooner, it would be in the same scheduler run and get
# it again. A Ctrl-C that lands in the touch read callback is kept by gt911 and handed
# on here in the same way. One that lands in a Python callback of the application is
# printed by LVGL and lost (measured: docs/log/ctrlc-probe-*).
def _task(_):
    delay = PERIOD_MS
    try:
        lv.timer_handler()
        if touch is not None and touch.interrupted:
            touch.interrupted = False
            raise KeyboardInterrupt
    except KeyboardInterrupt:
        micropython.schedule(micropython.kbd_intr, None)
        delay = HOLD_MS
    finally:
        if _timer is not None:
            _arm(delay)


# One shot, armed again when the work is done, not a periodic timer: with a periodic one, each
# tick takes a place in MicroPython's schedule queue (8 places). During a time.sleep_ms()
# the queue drains at 200 callbacks/s, it fills up, and whatever else is scheduled is lost,
# such as the I2S callback of audio.py.
# Deprecated as a public name (examples/shell/ansiterm.py before CONTRACT 1 called it):
# it goes away with the next contract version, as _task and _timer.
def _arm(period=PERIOD_MS):
    _timer.init(period=period, mode=Timer.ONE_SHOT, callback=_task)


def backlight(percent=None):
    """Set the backlight (0-100, PWM) or, with no argument, read it."""
    global _percent
    if percent is None:
        return _percent
    _percent = max(0, min(100, percent))
    _backlight.duty_u16(65535 * _percent // 100)


def start():
    """Serve LVGL in the background every PERIOD_MS. Does nothing if it already does."""
    global _timer
    if _timer is None:
        _timer = Timer(TIMER_ID)
        _arm()


def stop():
    """Stop serving LVGL; the screen keeps the last image. Does nothing if stopped."""
    global _timer
    if _timer is not None:
        _timer.deinit()
        _timer = None


def running():
    """True while LVGL is served in the background."""
    return _timer is not None


backlight(BACKLIGHT)
start()
