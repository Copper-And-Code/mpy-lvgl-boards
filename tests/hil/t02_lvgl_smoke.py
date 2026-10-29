# Phase 2 smoke test: LVGL on the target, no display hardware involved.
# The scene is the PyDevices README example (240x120 RGB565, Python flush_cb).
# Run with: mpremote run tests/hil/t02_lvgl_smoke.py
# then again after a soft reset (mpremote soft-reset run ...).
# Expected: "clicked" and "drew 240 px wide", twice (before and after lv.deinit()).
import gc
import time
import lvgl as lv


def scene():
    lv.init()
    disp = lv.display_create(240, 120)
    disp.set_color_format(lv.COLOR_FORMAT.RGB565)
    buf = bytearray(240 * 120 * 2)
    disp.set_buffers(buf, None, len(buf), lv.DISPLAY_RENDER_MODE.FULL)
    flushed = []
    disp.set_flush_cb(lambda d, area, px: (flushed.append(area.get_width()), d.flush_ready()))

    button = lv.button(lv.screen_active())
    button.center()
    label = lv.label(button)
    label.set_text("Hello from LVGL")
    button.add_event_cb(lambda e: print("clicked"), lv.EVENT.CLICKED, None)
    button.send_event(lv.EVENT.CLICKED, None)

    lv.tick_inc(50)
    t0 = time.ticks_us()
    lv.refr_now(disp)
    dt = time.ticks_diff(time.ticks_us(), t0)
    print(label.get_text(), "- drew", flushed[-1], "px wide", "refr_now %d us" % dt)


gc.collect()
print("mem_free before:", gc.mem_free())
scene()
gc.collect()
print("mem_free after scene:", gc.mem_free())
lv.deinit()
gc.collect()
print("mem_free after deinit:", gc.mem_free())
scene()
lv.deinit()
print("OK")
