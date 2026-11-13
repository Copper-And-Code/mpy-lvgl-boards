# Host test of the Ctrl-C hand-on in a real driver (python/display_driver.py, RP2350;
# python/stm32/display_driver.py has the same code), on the unix port with LVGL. The
# hardware is stubbed: rgbpanel, machine.Timer (fired by hand), gt911 and
# micropython.schedule (recorded, not run).
#   cd tests/host && micropython test_driver_ctrlc.py
import sys

import lvgl as lv


class Timer:
    PERIODIC = 1
    ONE_SHOT = 0
    live = []

    def __init__(self, *args, period=0, mode=1, callback=None):
        self.period, self.mode, self.callback = period, mode, callback
        Timer.live.append(self)

    def deinit(self):
        if self in Timer.live:
            Timer.live.remove(self)

    def fire(self):
        if self.mode == Timer.ONE_SHOT:
            self.deinit()
        self.callback(self)


class Machine:
    pass


machine = Machine()
machine.Timer = Timer
sys.modules["machine"] = machine


class RgbPanel:
    WIDTH = HEIGHT = 240

    def init(self, buffers=2):
        pass

    def lv_tick_install(self):
        pass

    def lv_display_create(self):
        d = lv.display_create(240, 240)
        d.set_color_format(lv.COLOR_FORMAT.RGB565)
        self.buf = bytearray(240 * 240 * 2)
        d.set_buffers(self.buf, None, len(self.buf), lv.DISPLAY_RENDER_MODE.DIRECT)
        d.set_flush_cb(lambda dd, a, p: dd.flush_ready())

    def backlight(self, percent=None):
        return 100


sys.modules["rgbpanel"] = RgbPanel()


class Touch:
    interrupted = False

    def lv_register(self):
        return None


class GT911mod:
    def GT911(self, scale=1):
        return Touch()


sys.modules["gt911"] = GT911mod()

sys.path.insert(0, "../../python")
import display_driver as dd  # noqa: E402


class Sched:
    def __init__(self):
        self.calls = []

    def schedule(self, f, arg):
        self.calls.append(f)

    def kbd_intr(self, c):
        pass


sched = Sched()
dd.micropython = sched  # the driver's view of micropython: recorded schedule()

failed = []


def check(name, ok):
    print(("ok  " if ok else "FAIL"), name)
    if not ok:
        failed.append(name)


def periodic():
    return [t for t in Timer.live if t.mode == Timer.PERIODIC]


def one_shot():
    return [t for t in Timer.live if t.mode == Timer.ONE_SHOT]


check("CONTRACT 1, running after import", dd.CONTRACT == 1 and dd.running())
check("one periodic timer", len(periodic()) == 1 and periodic()[0].period == dd.PERIOD_MS)

# _tick schedules _task
sched.calls.clear()
periodic()[0].fire()
check("_tick schedules _task", sched.calls == [dd._task])

# a KeyboardInterrupt inside lv.timer_handler(): handed on, pause, resume
t = lv.timer_create(lambda t: (_ for _ in ()).throw(KeyboardInterrupt), 0, None)
sched.calls.clear()
dd._task(None)
t.delete()
check("Ctrl-C in the service: kbd_intr scheduled", sched.calls == [sched.kbd_intr])
check("paused: no periodic timer, one one-shot of HOLD_MS",
      not periodic() and len(one_shot()) == 1 and one_shot()[0].period == dd.HOLD_MS)
check("running() during the pause", dd.running())
check("not busy after it", dd._busy is False)
one_shot()[0].fire()
check("resumed: periodic timer back", len(periodic()) == 1 and not one_shot())

# the touch callback kept a Ctrl-C
sched.calls.clear()
dd.touch = Touch()
dd.touch.interrupted = True
dd._task(None)
check("Ctrl-C kept by the touch: handed on", sched.calls == [sched.kbd_intr] and not dd.touch.interrupted)
one_shot()[0].fire()

# stop() during the pause: stays stopped
dd.touch.interrupted = True
dd._task(None)
dd.stop()
check("stop() during the pause: nothing left", not Timer.live and not dd.running())
dd.start()

# start() during the pause: resumes at once, the one-shot is gone
dd.touch.interrupted = True
dd._task(None)
dd.start()
check("start() during the pause: periodic, no one-shot", len(periodic()) == 1 and not one_shot())

# a Ctrl-C while resuming: pause again
dd.touch.interrupted = True
dd._task(None)
resumer = one_shot()[0]
real_start = dd.start


def failing_start():
    raise KeyboardInterrupt


dd.start = failing_start
sched.calls.clear()
resumer.fire()
dd.start = real_start
check("Ctrl-C while resuming: handed on and paused again",
      sched.calls == [sched.kbd_intr] and len(one_shot()) == 1 and not periodic())
one_shot()[0].fire()
check("then resumed", len(periodic()) == 1)

# _tick: a Ctrl-C raised during its schedule() call (once, as a real one is)
keep = sched.schedule


def raising(f, a):
    sched.schedule = keep
    raise KeyboardInterrupt


sched.schedule = raising
sched.calls.clear()
try:
    periodic()[0].fire()
    check("Ctrl-C in _tick: caught", True)
except KeyboardInterrupt:
    check("Ctrl-C in _tick: caught", False)
sched.schedule = keep
check("Ctrl-C in _tick: handed on and paused",
      sched.calls == [sched.kbd_intr] and len(one_shot()) == 1 and not periodic())
one_shot()[0].fire()

dd.stop()
dd.stop()
check("stop() twice", not dd.running() and not Timer.live)

print("RESULT:", "FAILED " + ", ".join(failed) if failed else "OK")
