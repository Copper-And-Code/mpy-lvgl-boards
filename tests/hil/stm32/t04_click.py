# Phase 4 (fingers): tap an LVGL button through display_driver's GT911 indev.
#   scripts/uart_run.py tests/hil/stm32/t04_click.py --timeout 120
# Prints "clicked N" on every tap; ends after 5 taps or 90 s. Measured: the GT911
# poll time and read_cb calls / max time, frames and underruns while tapping.
import time

import lvgl as lv
import st_ltdc

import display_driver

t = display_driver.touch
n = 100
t0 = time.ticks_us()
for i in range(n):
    t.read()
print("gt911 read() no touch, avg us:", time.ticks_diff(time.ticks_us(), t0) // n)

# Wrap the read callback to count calls and time them.
stats = {"calls": 0, "down": 0, "max_us": 0}
_read = t.lv_read_cb


def timed_read(indev, data):
    t0 = time.ticks_us()
    _read(indev, data)
    dt = time.ticks_diff(time.ticks_us(), t0)
    stats["calls"] += 1
    stats["down"] += data.state == lv.INDEV_STATE.PRESSED
    if dt > stats["max_us"]:
        stats["max_us"] = dt


display_driver.indev.set_read_cb(timed_read)

scr = lv.obj()
btn = lv.button(scr)
btn.set_size(300, 150)
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
i0 = st_ltdc.info()
print("tap the button 5 times")
end = time.ticks_add(time.ticks_ms(), 90_000)
while count[0] < 5 and time.ticks_diff(end, time.ticks_ms()) > 0:
    time.sleep_ms(50)
i1 = st_ltdc.info()
print("done, clicks:", count[0], "read_cb", stats,
      "frames", i1["frames"] - i0["frames"], "underruns", i1["underruns"] - i0["underruns"])
lbl.set_text("done: %d clicks" % count[0])
