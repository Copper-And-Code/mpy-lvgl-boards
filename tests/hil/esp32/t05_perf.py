# Phase 5 on the ESP32-4848S040: LVGL on the panel through display_driver.
#   scripts/uart_run.py tests/hil/esp32/t05_perf.py --dtr 0 --boot-wait 5 --timeout 60
#   A. full refresh of 48 themed buttons, and a small label change (lv.refr_now());
#   B. 10 s of animation: a full-height bar sweeping and a spinner, LVGL refreshes per
#      second against the panel's frame rate.
# Watch the panel in B: the bar must stay straight (no tearing) and move smoothly.
import gc
import time

import esp_rgb
import lvgl as lv

import display_driver

W, H = display_driver.WIDTH, display_driver.HEIGHT
disp = display_driver.disp
display_driver.stop()

scr = lv.obj()
scr.set_style_pad_all(0, 0)
for i in range(48):
    b = lv.button(scr)
    b.set_size(W // 6 - 6, H // 8 - 6)
    b.set_pos((i % 6) * W // 6 + 3, (i // 6) * H // 8 + 3)
    lv.label(b).set_text("%d" % i)
label = lv.label(scr)
label.set_text("0")
lv.screen_load(scr)
lv.refr_now(disp)


def times(fn, n=8):
    r = []
    for i in range(n):
        fn(i)
        t = time.ticks_us()
        lv.refr_now(disp)
        r.append(time.ticks_diff(time.ticks_us(), t))
    return min(r), sum(r) // n


f = times(lambda i: scr.invalidate())
print("full refresh us: min %d avg %d" % f)
f = times(lambda i: label.set_text("%d" % i))
print("label change us: min %d avg %d" % f)

display_driver.start()
scr2 = lv.obj()
scr2.set_style_bg_color(lv.color_hex(0x101820), 0)
bar = lv.obj(scr2)
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
s = lv.spinner(scr2)
s.set_size(100, 100)
s.align(lv.ALIGN.TOP_RIGHT, -20, 20)
refr = [0]


def on_refr(e):
    refr[0] += 1


disp.add_event_cb(on_refr, lv.EVENT.REFR_READY, None)
lv.screen_load(scr2)
time.sleep_ms(500)
r0, f0, t0 = refr[0], esp_rgb.frame_count(), time.ticks_ms()
time.sleep_ms(10000)
dt = time.ticks_diff(time.ticks_ms(), t0)
print("animation: LVGL %.1f refreshes/s, panel %.2f fps" % ((refr[0] - r0) * 1000 / dt, (esp_rgb.frame_count() - f0) * 1000 / dt))
gc.collect()
print("mem_free", gc.mem_free())
print("RESULT: ok")
