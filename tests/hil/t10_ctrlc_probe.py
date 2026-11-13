# Where does a Ctrl-C land while display_driver serves LVGL? Read only: firmware and
# drivers as they are; nothing is written to the board.
#
# Regression test of the contract (docs/display-driver.md, CONTRACT 1): every Ctrl-C
# reaches the program and the screen goes on. On firmware with the contract:
#   tests/hil/ctrlc_probe_host.py --port P --mode sleep|stdin|cb --expect contract
# The candidates below (CANDIDATE) replay, in RAM on older firmware, the measurements
# that chose the driver code (docs/log/ctrlc-probe-*, 2026-11-13).
#
# Driven by tests/hil/ctrlc_probe_host.py, which prepends MODE = "sleep" or "stdin", sends
# Ctrl-C at random moments and classifies the text that comes back:
#   "MAIN <n>"                 the main program caught KeyboardInterrupt
#   "display_driver: stopped"  the driver's _interrupted() (printed by the driver itself)
#   "Traceback ... KeyboardInterrupt" without MAIN: the scheduler printed and dropped it
#   nothing                    lost
# "S <frames> <running>" reports the service: frames rendered so far, and whether the
# driver's timer is set. If it is not, the program restarts it after reporting.
#
# Load: an LVGL timer invalidates the whole screen on every lv.timer_handler() run, so
# LVGL redraws a full-screen gradient all the time and the timer handler takes most of
# the CPU. The two callbacks (timer and REFR_READY) have no jump in their body: the VM
# raises a pending exception only at a jump, so they do not give the Ctrl-C a place to
# land that the driver alone would not have.
import sys
import time

import micropython

try:
    MODE
except NameError:
    MODE = "sleep"
try:
    SECONDS
except NameError:
    SECONDS = 60  # sleep and cb modes: how long the program runs (Ctrl-C cannot end it)
try:
    CANDIDATE
except NameError:
    CANDIDATE = ""  # "base", "A" or "AB": replace display_driver._task in RAM (see below)
try:
    HOLD_MS
except NameError:
    HOLD_MS = 30  # candidates A and AB: the pause after handing a Ctrl-C on
try:
    LOOP
except NameError:
    LOOP = 300  # cb mode: iterations of the Python loop inside the LVGL timer callback

# micropython.schedule(micropython.kbd_intr, None) schedules a KeyboardInterrupt, but only
# with MICROPY_SCHEDULER_STATIC_NODES; without it, ValueError.
try:
    micropython.schedule(micropython.kbd_intr, None)
    try:
        i = 0
        while i < 1000:
            time.sleep_ms(1)
            i += 1
        print("SPECIAL no KeyboardInterrupt within 1 s")
    except KeyboardInterrupt:
        print("SPECIAL ok: KeyboardInterrupt raised in the main program")
except ValueError:
    print("SPECIAL ValueError: no MICROPY_SCHEDULER_STATIC_NODES")

# After the check: with LVGL served, the KeyboardInterrupt could land in the driver instead.
import lvgl as lv
import display_driver as dd

scr = lv.screen_active()
scr.set_style_bg_color(lv.color_hex(0x203060), 0)
scr.set_style_bg_grad_color(lv.color_hex(0xC08020), 0)
scr.set_style_bg_grad_dir(lv.GRAD_DIR.VER, 0)
scr.set_style_bg_opa(255, 0)
lbl = lv.label(scr)
lbl.set_text("Ctrl-C probe")
lbl.center()

frames = [0]


def _refr(e):
    frames[0] += 1


def _load(t):
    scr.invalidate()


lv.display_get_default().add_event_cb(_refr, lv.EVENT.REFR_READY, None)
_t = lv.timer_create(_load, 0, None)


# The candidates. All replace display_driver._task in RAM; the driver file is untouched.
#   base  a jump inside the try, so that a pending Ctrl-C is raised there, and the
#         KeyboardInterrupt handed on to the main program (micropython.schedule(kbd_intr))
#         instead of stopping the driver
#   A     base, and after handing it on the next service run waits HOLD_MS instead of
#         PERIOD_MS: the scheduler run that raises it has no _task queued behind it
#   AB    A, and the touch read callback catches a Ctrl-C that lands in it and tells the
#         task, which hands it on as in A
#   A2    periodic timers (STM32, RP2350): A, and the busy guard inside the try, and _tick
#         (the timer callback that schedules _task) replaced as well, with a jump in its try
#   AB2   A2 and B. On the ESP32 A2 and AB2 are A and AB.
_kbd = [0]
_touched = 0  # status reports (every 100 ms) with a finger on the screen
_hold = CANDIDATE in ("A", "AB", "A2", "AB2")

if hasattr(dd, "_arm"):  # ESP32: one shot timer, armed again in finally
    from machine import Timer

    def _candidate(_):
        delay = dd.PERIOD_MS
        try:
            lv.timer_handler()
            if _kbd[0]:
                _kbd[0] = 0
                raise KeyboardInterrupt
        except KeyboardInterrupt:
            micropython.schedule(micropython.kbd_intr, None)
            if _hold:
                delay = HOLD_MS
        finally:
            if dd._timer is not None:
                dd._timer.init(period=delay, mode=Timer.ONE_SHOT, callback=dd._task)

else:  # STM32 and RP2350: periodic timer, _tick schedules _task
    from machine import Timer

    _resumer = None

    def _hand_on():
        global _resumer
        micropython.schedule(micropython.kbd_intr, None)
        if _hold and dd._timer is not None:
            dd.stop()
            _resumer = Timer(-1, period=HOLD_MS, mode=Timer.ONE_SHOT, callback=_resume)

    def _resume(_):
        try:
            dd.start()
            if _kbd[0]:
                pass
        except KeyboardInterrupt:
            _hand_on()

    if CANDIDATE.endswith("2"):

        def _candidate(_):
            try:
                if dd._busy:
                    return
                dd._busy = True
                try:
                    lv.timer_handler()
                    if _kbd[0]:
                        _kbd[0] = 0
                        raise KeyboardInterrupt
                finally:
                    dd._busy = False
            except KeyboardInterrupt:
                _hand_on()

        def _candidate_tick(_):
            try:
                micropython.schedule(dd._task, None)
                if _kbd[0]:
                    pass
            except RuntimeError:
                pass  # schedule queue full: the next tick will catch up
            except KeyboardInterrupt:
                _hand_on()

    else:

        def _candidate(_):
            if dd._busy:
                return
            dd._busy = True
            try:
                lv.timer_handler()
                if _kbd[0]:
                    _kbd[0] = 0
                    raise KeyboardInterrupt
            except KeyboardInterrupt:
                micropython.schedule(micropython.kbd_intr, None)
                if _hold and dd._timer is not None:
                    dd.stop()
                    Timer(-1, period=HOLD_MS, mode=Timer.ONE_SHOT, callback=lambda t: dd.start())
            finally:
                dd._busy = False


if CANDIDATE in ("AB", "AB2") and dd.indev is not None:
    _read = dd.touch.lv_read_cb

    def _read_cb(indev, data):
        try:
            _read(indev, data)
            if _kbd[0]:
                pass
        except KeyboardInterrupt:
            _kbd[0] = 1

    dd.indev.set_read_cb(_read_cb)


def fps(ms):
    f0 = frames[0]
    t0 = time.ticks_ms()
    time.sleep_ms(ms)
    return (frames[0] - f0) * 1000 / time.ticks_diff(time.ticks_ms(), t0)


time.sleep_ms(500)
before = fps(3000)
if CANDIDATE:
    dd._task = _candidate
    if CANDIDATE.endswith("2") and not hasattr(dd, "_arm"):
        dd.stop()  # the timer holds the callback it was created with
        dd._tick = _candidate_tick
        dd.start()
    time.sleep_ms(200)
after = fps(3000)
print("FPS driver %.1f %s %.1f" % (before, ("candidate-" + CANDIDATE) if CANDIDATE else "driver", after))


def _busy_cb(t):
    i = 0
    while i < LOOP:
        i += 1


if MODE == "cb":
    _cb = lv.timer_create(_busy_cb, 20, None)

n = 0


def status():
    global _touched
    running = dd._timer is not None  # served now (running() is True during the pause too)
    if dd.touch is not None and dd.touch.pressed:
        _touched += 1
    print("S %d %d %d" % (frames[0], 1 if running else 0, _touched))
    if not running and not _hold:  # A, AB...: the candidate resumes by itself; check that it does
        dd.start()


print("READY", MODE, sys.implementation._machine)
if MODE in ("sleep", "cb"):
    last = start = time.ticks_ms()
    while time.ticks_diff(time.ticks_ms(), start) < SECONDS * 1000:
        try:
            while time.ticks_diff(time.ticks_ms(), start) < SECONDS * 1000:
                time.sleep_ms(10)
                if time.ticks_diff(time.ticks_ms(), last) >= 100:
                    last = time.ticks_ms()
                    status()
        except KeyboardInterrupt:
            n += 1
            print("MAIN", n)
else:
    while True:
        try:
            c = sys.stdin.read(1)
            if c == "s":
                status()
            elif c == "q":
                break
        except KeyboardInterrupt:
            n += 1
            print("MAIN", n)
_t.delete()
if MODE == "cb":
    _cb.delete()
print("END", n)
