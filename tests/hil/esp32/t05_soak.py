# Phase 5 soak on the ESP32-4848S040: display_driver (DIRECT, 2 buffers), continuous
# animations, Python allocation churn, gc.collect() every 10 s, and 2 MB of
# application data kept in the heap.
#   scripts/uart_run.py tests/hil/esp32/t05_soak.py --dtr 0 --boot-wait 5 --timeout 1100
# One line per minute: LVGL refreshes per second, panel fps, memory (esp_lcd does not
# report underruns: look at the panel).
# Watch the panel: the white bar sweeps left to right; it must stay straight
# (no tearing) and move smoothly.
import gc
import time

import esp_rgb
import lvgl as lv

import display_driver

DURATION_S = 900
W, H = display_driver.WIDTH, display_driver.HEIGHT
APP_DATA = [bytearray(256 * 1024) for i in range(8)]  # 2 MB, alive all along

scr = lv.obj()
scr.set_style_bg_color(lv.color_hex(0x101820), 0)

bar = lv.obj(scr)
bar.set_size(16, H)
bar.set_style_bg_color(lv.color_hex(0xFFFFFF), 0)
bar.set_style_border_width(0, 0)
bar.set_style_radius(0, 0)

a = lv.anim_t()
a.init()
a.set_var(bar)
a.set_values(0, W - 16)
a.set_duration(3000)
a.set_repeat_count(lv.ANIM_REPEAT_INFINITE)
a.set_custom_exec_cb(lambda anim, v: bar.set_x(v))
a.start()

spinner = lv.spinner(scr)
spinner.set_size(100, 100)
spinner.align(lv.ALIGN.TOP_RIGHT, -20, 20)

label = lv.label(scr)
label.align(lv.ALIGN.BOTTOM_MID, 0, -20)
label.set_style_text_color(lv.color_hex(0xFFFF00), 0)

refr = [0]


def on_refr(e):
    refr[0] += 1


display_driver.disp.add_event_cb(on_refr, lv.EVENT.REFR_READY, None)

lv.screen_load(scr)


def touch_errors():
    t = display_driver.touch
    return t.errors if t is not None else -1


start = time.ticks_ms()
i0 = esp_rgb.frame_count()
r0 = refr[0]
errors = 0
allocs = 0
min_free = gc.mem_free()
last_log = -1
junk = []
last_min = (time.ticks_ms(), refr[0], i0)

while True:
    elapsed = time.ticks_diff(time.ticks_ms(), start) // 1000
    if elapsed >= DURATION_S:
        break
    try:
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
        now, i = time.ticks_ms(), esp_rgb.frame_count()
        dt = max(time.ticks_diff(now, last_min[0]), 1)
        print("t=%5ds lvgl_rps=%.1f panel_fps=%.2f mem_free=%d min_free=%d allocs=%d errors=%d touch_errors=%d"
              % (elapsed, (refr[0] - last_min[1]) * 1000 / dt, (i - last_min[2]) * 1000 / dt,
                 gc.mem_free(), min_free, allocs, errors, touch_errors()))
        last_min = (now, refr[0], i)
    time.sleep_ms(200)

i = esp_rgb.frame_count()
print("SOAK DONE t=%ds lvgl_rps=%.1f panel_fps=%.2f min_free=%d allocs=%d errors=%d touch_errors=%d"
      % (DURATION_S, (refr[0] - r0) / DURATION_S, (i - i0) / DURATION_S, min_free, allocs, errors, touch_errors()))
print("RESULT:", "ok" if errors == 0 else "FAILED")
