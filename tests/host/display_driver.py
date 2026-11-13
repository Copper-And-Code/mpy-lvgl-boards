# Unix stand-in for the board's display_driver (tests/host only): 240x240 RGB565,
# DIRECT, two buffers, the names of the contract in docs/display-driver.md.
#
# The unix port has no machine.Timer, so nothing serves LVGL in the background:
# start() and stop() only change running(), and a test serves LVGL itself with
# serve(), which is not part of the contract. A KeyboardInterrupt in serve() goes to
# the caller, as on the boards a Ctrl-C goes to the program.
import lvgl as lv

CONTRACT = 1
WIDTH = HEIGHT = 240
BUFFERS = 2
PERIOD_MS = 5
HOLD_MS = 30

lv.init()
disp = lv.display_create(WIDTH, HEIGHT)
disp.set_color_format(lv.COLOR_FORMAT.RGB565)
_b1 = bytearray(WIDTH * HEIGHT * 2)
_b2 = bytearray(WIDTH * HEIGHT * 2)
disp.set_buffers(_b1, _b2, len(_b1), lv.DISPLAY_RENDER_MODE.DIRECT)
disp.set_flush_cb(lambda d, a, p: d.flush_ready())

touch = indev = None
_running = False
_backlight = 100


def start():
    """Serve LVGL in the background every PERIOD_MS. Does nothing if it already does."""
    global _running
    _running = True


def stop():
    """Stop serving LVGL; the screen keeps the last image. Does nothing if stopped."""
    global _running
    _running = False


def running():
    """True while LVGL is served in the background."""
    return _running


def backlight(percent=None):
    """Set the backlight (0-100) or, with no argument, read it."""
    global _backlight
    if percent is None:
        return _backlight
    _backlight = max(0, min(100, percent))


def serve():
    """Tests only: one service run, if running(); what LVGL does in the background."""
    if _running:
        lv.timer_handler()


start()
