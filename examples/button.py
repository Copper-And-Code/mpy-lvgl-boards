# Button: count the taps on the touch screen.
#
#   mpremote run examples/button.py
#
# The GT911 touch is already registered with LVGL by display_driver, so
# widgets react to the finger with no extra code.
import lvgl as lv
import display_driver

scr = lv.obj()

btn = lv.button(scr)
btn.set_size(140, 60)
btn.center()

label = lv.label(btn)
label.set_text("Tap me")
label.center()

taps = 0


def on_click(e):
    global taps
    taps += 1
    label.set_text("Taps: %d" % taps)


btn.add_event_cb(on_click, lv.EVENT.CLICKED, None)

lv.screen_load(scr)
