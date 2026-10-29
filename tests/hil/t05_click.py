# Phase 5 (fingers): tap the LVGL button through display_driver's GT911 indev.
# Prints "clicked" on every tap and the time of one read_cb, then keeps running.
# Run with: mpremote resume run tests/hil/t05_click.py
import time
import lvgl as lv
import display_driver

# read_cb timing (I2C status poll, no touch)
t = display_driver.touch
n = 50
t0 = time.ticks_us()
for i in range(n):
    t.read()
print("gt911 read() avg us:", time.ticks_diff(time.ticks_us(), t0) // n)

scr = lv.obj()
btn = lv.button(scr)
btn.set_size(140, 60)
btn.center()
lbl = lv.label(btn)
lbl.set_text("Tap me")
lbl.center()
count = [0]


def on_click(e):
    count[0] += 1
    lbl.set_text("clicked %d" % count[0])
    print("clicked", count[0])


btn.add_event_cb(on_click, lv.EVENT.CLICKED, None)
lv.screen_load(scr)
print("tap the button")
end = time.ticks_add(time.ticks_ms(), 60_000)
while count[0] < 3 and time.ticks_diff(end, time.ticks_ms()) > 0:
    time.sleep_ms(50)
print("done, clicks:", count[0])
