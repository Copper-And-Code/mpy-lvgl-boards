# Phase 6 performance at several sys clocks (core voltage untouched).
# For each (sys_hz, pclk_hz): machine.freq(), rgbpanel.init() (restarts the
# scan-out with the new integer divider), then fps, underruns, full-screen
# lv.refr_now() time and underruns during 200 KB of flash writes.
# Needs scene_static.py on the board. Ends back at 150 MHz / 15 MHz.
# Run with: mpremote resume run tests/hil/t06_perf.py
import gc
import os
import time
import machine
import lvgl as lv
import display_driver
import rgbpanel
import scene_static

CONFIGS = (
    (150_000_000, 15_000_000),
    (200_000_000, 20_000_000),
    (240_000_000, 20_000_000),
    (150_000_000, 15_000_000),
)

display_driver.stop()
scr = lv.obj()
scene_static.build(scr)
lv.screen_load(scr)
lv.refr_now(display_driver.disp)


def measure(sys_hz, pclk_hz):
    machine.freq(sys_hz)
    rgbpanel.init(pclk_hz=pclk_hz)
    info = rgbpanel.info()
    u0 = rgbpanel.underruns()
    f0 = rgbpanel.frame_count()
    t0 = time.ticks_ms()
    time.sleep_ms(3000)
    fps = (rgbpanel.frame_count() - f0) * 1000 / time.ticks_diff(time.ticks_ms(), t0)
    refr = []
    for i in range(5):
        scr.invalidate()
        t1 = time.ticks_us()
        lv.refr_now(display_driver.disp)
        refr.append(time.ticks_diff(time.ticks_us(), t1))
    u1 = rgbpanel.underruns()
    buf = bytearray(4096)
    with open("/t06.bin", "wb") as f:
        for i in range(50):
            f.write(buf)
    os.remove("/t06.bin")
    u2 = rgbpanel.underruns()
    gc.collect()
    print("sys %3d MHz pclk %4.1f MHz: fps %.2f (nominal %.2f), refr_now us min %d avg %d, underruns run %d flash %d"
          % (machine.freq() // 1_000_000, info["pclk"] / 1e6, fps, info["fps_nominal"],
             min(refr), sum(refr) // len(refr), u1 - u0, u2 - u1))


for sys_hz, pclk_hz in CONFIGS:
    measure(sys_hz, pclk_hz)

# A sys clock whose divider for the requested PCLK is not an integer is refused.
machine.freq(200_000_000)
try:
    rgbpanel.init(pclk_hz=15_000_000)
    print("200 MHz / 15 MHz: accepted (unexpected)")
except ValueError as e:
    print("200 MHz / 15 MHz refused:", e)
machine.freq(150_000_000)
rgbpanel.init(pclk_hz=15_000_000)
print("back to", machine.freq(), rgbpanel.info()["pclk"], "running", rgbpanel.info()["running"])
display_driver.start()
