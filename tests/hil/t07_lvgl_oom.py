# Phase 7: what happens when LVGL runs out of memory while rendering.
# A rotated, semi-transparent object is drawn through a full ARGB8888 layer,
# allocated at once; it is made larger than the free heap. Then LVGL renders
# a plain label. Watchdog 8 s: if LVGL hangs, the board resets by itself.
# Run with: mpremote run tests/hil/t07_lvgl_oom.py
import gc
import machine
import time
import lvgl as lv
import display_driver

display_driver.stop()
wdt = machine.WDT(timeout=8000)

scr = lv.obj()
lv.screen_load(scr)
lv.timer_handler()
gc.collect()
ballast = bytearray(gc.mem_free() - 70_000)  # leave ~70 KB, like a large generated UI
gc.collect()
free = gc.mem_free()
side = 200  # 200x200 ARGB8888 layer = 160 000 B, more than the free heap
print("mem_free", free, "layer needs about", side * side * 4)

o = lv.obj(scr)
o.set_size(side, side)
o.set_style_opa(200, 0)
o.set_style_transform_rotation(10, 0)

for i in range(3):
    print("render %d:" % i, end=" ")
    wdt.feed()
    try:
        lv.timer_handler()
        print("ok")
    except MemoryError as e:
        print("MemoryError", e)
    time.sleep_ms(50)

print("delete the object, add a label")
o.delete()
lv.label(scr).set_text("after OOM")
for i in range(5):
    print("render after %d:" % i, end=" ")
    wdt.feed()
    try:
        lv.timer_handler()
        print("ok")
    except MemoryError as e:
        print("MemoryError", e)
    time.sleep_ms(50)
print("OOM_TEST_DONE (the watchdog resets the board in 8 s)")
