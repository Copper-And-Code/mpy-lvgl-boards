# Backlight: a slider sets the screen brightness.
#
#   mpremote run examples/backlight.py
#
# rgbpanel is the board's display module; rgbpanel.backlight(percent) sets
# the backlight (PWM on GPIO40), rgbpanel.backlight() reads it.
import lvgl as lv
import display_driver
import rgbpanel

scr = lv.obj()

label = lv.label(scr)
label.align(lv.ALIGN.CENTER, 0, -40)

slider = lv.slider(scr)
slider.set_width(180)
slider.center()
slider.set_range(5, 100)  # not 0: a black screen is hard to bring back by touch
slider.set_value(rgbpanel.backlight(), False)


def show():
    label.set_text("Backlight %d %%" % rgbpanel.backlight())


def on_change(e):
    rgbpanel.backlight(slider.get_value())
    show()


slider.add_event_cb(on_change, lv.EVENT.VALUE_CHANGED, None)
show()

lv.screen_load(scr)
