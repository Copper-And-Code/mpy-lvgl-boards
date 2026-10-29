# Phase 6 soak test: continuous animations + Python allocations + periodic
# gc.collect(), at the default 150 MHz. Logs one line per minute.
# The scene has a vertical bar sweeping left to right (tearing check, eyes).
# Run with: mpremote resume run tests/hil/t06_soak.py   (DURATION_S below)
import gc
import time
import lvgl as lv
import display_driver
import rgbpanel

DURATION_S = 3600
W, H = display_driver.WIDTH, display_driver.HEIGHT

scr = lv.obj()
scr.set_style_bg_color(lv.color_hex(0x101820), 0)

bar = lv.obj(scr)
bar.set_size(12, H)
bar.set_style_bg_color(lv.color_hex(0xFFFFFF), 0)
bar.set_style_border_width(0, 0)
bar.set_style_radius(0, 0)



a = lv.anim_t()
a.init()
a.set_var(bar)
a.set_values(0, W - 12)
a.set_duration(2000)
a.set_repeat_count(lv.ANIM_REPEAT_INFINITE)
a.set_custom_exec_cb(lambda anim, v: bar.set_x(v))
a.start()

spinner = lv.spinner(scr)
spinner.set_size(60, 60)
spinner.align(lv.ALIGN.TOP_RIGHT, -8, 8)

label = lv.label(scr)
label.align(lv.ALIGN.BOTTOM_MID, 0, -8)
label.set_style_text_color(lv.color_hex(0xFFFF00), 0)

lv.screen_load(scr)

start = time.ticks_ms()
f0 = rgbpanel.frame_count()
u0 = rgbpanel.underruns()
errors = 0
allocs = 0
min_free = gc.mem_free()
last_log = -1
junk = []

while True:
    elapsed = time.ticks_diff(time.ticks_ms(), start) // 1000
    if elapsed >= DURATION_S:
        break
    try:
        # Python allocation churn
        junk.append(["x" * (i % 64) for i in range(40)])
        allocs += 40
        if len(junk) > 20:
            junk = junk[10:]
        label.set_text("t=%ds free=%d" % (elapsed, gc.mem_free()))
        if elapsed % 10 == 0:
            gc.collect()
            min_free = min(min_free, gc.mem_free())
    except Exception as e:
        errors += 1
        print("ERROR", elapsed, repr(e))
    if elapsed // 60 != last_log:
        last_log = elapsed // 60
        frames = rgbpanel.frame_count() - f0
        print("t=%5ds frames=%7d fps=%.2f underruns=%d mem_free=%d min_free=%d allocs=%d errors=%d"
              % (elapsed, frames, frames / max(elapsed, 1), rgbpanel.underruns() - u0,
                 gc.mem_free(), min_free, allocs, errors))
    time.sleep_ms(200)

frames = rgbpanel.frame_count() - f0
print("SOAK DONE t=%ds frames=%d fps=%.2f underruns=%d min_free=%d allocs=%d errors=%d"
      % (DURATION_S, frames, frames / DURATION_S, rgbpanel.underruns() - u0, min_free, allocs, errors))
