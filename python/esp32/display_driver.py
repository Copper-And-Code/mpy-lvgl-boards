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

import esp_rgb
import gt911
import lvgl as lv
import panels
from machine import Pin, SoftI2C, Timer

PERIOD_MS = 5
# LVGL's display refresh period. The binding's lv_conf.h has 33 ms (30 Hz at
# most); the panels run at about 58 Hz, and the flush no longer blocks for the
# vertical blanking, so animations can follow the panel.
REFR_PERIOD_MS = 16
BUFFERS = 2

TIMER_ID = 0
PANEL = "ST7701_4848S040"
_timing = panels.get(PANEL)
esp_rgb.init(**_timing, buffers=BUFFERS)
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


# Ctrl-C while a program runs: lv.timer_handler() takes most of the CPU, so the
# KeyboardInterrupt usually lands in these callbacks, where it would be lost
# and the program would never stop. Stop the timer instead: the next Ctrl-C
# reaches the program. display_driver.start() resumes.
def _interrupted():
    stop()
    print("display_driver: stopped by Ctrl-C (display_driver.start() resumes)")


def _task(_):
    try:
        lv.timer_handler()
    except KeyboardInterrupt:
        _interrupted()
    finally:
        if _timer is not None:
            _arm()


# One shot, armed again when the work is done, not a periodic timer: with a periodic one, each
# tick takes a place in MicroPython's schedule queue (8 places). During a time.sleep_ms()
# the queue drains at 200 callbacks/s, it fills up, and whatever else is scheduled is lost,
# such as the I2S callback of audio.py.
def _arm():
    _timer.init(period=PERIOD_MS, mode=Timer.ONE_SHOT, callback=_task)


def backlight(percent=None):
    """Set the backlight (0-100) or, with no argument, read it. On/off for now
    (GPIO), so any percent above 0 is full brightness."""
    if percent is None:
        return esp_rgb.backlight()
    esp_rgb.backlight(percent)


def start():
    global _timer
    if _timer is None:
        _timer = Timer(TIMER_ID)
        _arm()


def stop():
    global _timer
    if _timer is not None:
        _timer.deinit()
        _timer = None


start()
