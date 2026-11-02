# Phase 3: soft reset with the panel on (and LVGL on it, if built in).
# Run it three times in a row; mpremote soft-resets the board before each run:
#   mpremote run tests/hil/stm32/t03_softreset.py \
#            run tests/hil/stm32/t03_softreset.py \
#            run tests/hil/stm32/t03_softreset.py
# Expected from the second run on: "scan-out survived the soft reset: True",
# frames still counting, and on the panel the previous run's label stays
# visible until the new one replaces it (no garbage, no flicker).
# Panel from /display_config.py (PANEL, default "IPS1024x600").
import time

import panels
import st_ltdc

try:
    from display_config import PANEL
except ImportError:
    PANEL = "IPS1024x600"

before = st_ltdc.info()
print("scan-out survived the soft reset:", before["running"], "frames", before["frames"],
      "underruns", before.get("underruns"))
st_ltdc.init(**panels.get(PANEL), buffers=2, backlight=100)
after = st_ltdc.info()
print("init kept the scan-out (same timings):", before["running"] and after["frames"] >= before["frames"])

try:
    import lvgl as lv
except ImportError:
    lv = None

if lv is not None:
    lv.init()
    st_ltdc.lv_tick_install()
    st_ltdc.lv_display_create()
    scr = lv.screen_active()
    label = lv.label(scr)
    label.set_text("soft reset test %d" % (time.ticks_ms() % 1000))
    label.center()
    t0 = time.ticks_ms()
    lv.refr_now(None)
    print("LVGL refr_now %d ms, shown buffer %d" % (time.ticks_diff(time.ticks_ms(), t0), st_ltdc.shown()))
else:
    fb = st_ltdc.framebuffer(st_ltdc.shown())
    c = time.ticks_ms() & 0xFFFF
    for i in range(0, len(fb), 7):
        fb[i] = c
    print("no LVGL: wrote a dotted pattern")
print("OK (left running on purpose)", st_ltdc.info())
