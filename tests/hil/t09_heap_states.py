# Full redraws of scene_static in four heap states (docs/rp2350-touch-lcd4.md): with
# LVGL's memory pools they cost the same, without them up to 17 ms more.
# lv.refr_now() after a 60 ms pause, median of N. BUFFERS = 1: one framebuffer and no
# display_driver, so the figure is the rendering alone; 2: display_driver as shipped,
# the figure includes the wait for the end of the frame.
# Run with: mpremote cp tests/hil/scene_static.py :scene_static.py + run tests/hil/t09_heap_states.py
import gc
import os
import time

import lvgl as lv

BUFFERS = 2
if BUFFERS == 1:
    import rgbpanel

    rgbpanel.init(buffers=1)
    lv.init()
    rgbpanel.lv_tick_install()
    rgbpanel.lv_display_create()
    stop = start = lambda: None
else:
    import display_driver

    stop, start = display_driver.stop, display_driver.start
import scene_static

N = 15


def median(xs):
    xs = sorted(xs)
    return xs[len(xs) // 2]


def measure(name):
    stop()
    scr = lv.screen_active()
    ts = []
    for _ in range(N):
        scr.invalidate()
        time.sleep_ms(60)
        t = time.ticks_us()
        lv.refr_now(None)
        ts.append(time.ticks_diff(time.ticks_us(), t) / 1000)
    start()
    print("%-12s free=%6d refr_med=%5.1f min=%5.1f max=%5.1f" % (name, gc.mem_free(), median(ts), min(ts), max(ts)))


print("FW", os.uname().version, "buffers", BUFFERS, "free", gc.mem_free())
scr = lv.obj()
scene_static.build(scr)
lv.screen_load(scr)
stop()
lv.refr_now(None)
start()
gc.collect()
measure("clean")

junk = [bytearray(16) for _ in range(1000)]  # ~30 KB with headers
del junk
measure("garbage")
gc.collect()

live = [bytearray(16) for _ in range(2000)]  # ~60 KB of small live objects
measure("live")

for i in range(0, len(live), 2):
    live[i] = None
gc.collect()
measure("holes")
del live
gc.collect()
measure("clean again")
