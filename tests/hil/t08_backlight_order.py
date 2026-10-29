# Backlight polarity, second check (eyes): raw GPIO levels and PWM duties on
# GPIO40, 5 s each, with the step letter on screen. Ends at GPIO low.
# Run with: mpremote run tests/hil/t08_backlight_order.py
import time
import lvgl as lv
import display_driver
from machine import Pin, PWM

scr = lv.obj()
scr.set_style_bg_color(lv.color_hex(0xFFFFFF), 0)
lbl = lv.label(scr)
lbl.set_style_text_color(lv.color_hex(0x000000), 0)
lbl.set_style_text_font(lv.font_montserrat_24, 0)
lbl.center()
lv.screen_load(scr)

steps = (
    ("A", "GPIO40 low", None, 0),
    ("B", "GPIO40 high", None, 1),
    ("C", "PWM duty 10 %", 6554, None),
    ("D", "PWM duty 90 %", 58982, None),
)
for name, what, duty, level in steps:
    lbl.set_text(name)
    time.sleep_ms(200)
    if duty is None:
        Pin(40, Pin.OUT, value=level)
    else:
        PWM(Pin(40), freq=20_000, duty_u16=duty)
    print(name, what)
    time.sleep(5)
Pin(40, Pin.OUT, value=0)
lbl.set_text("end")
print("end: GPIO40 low")
