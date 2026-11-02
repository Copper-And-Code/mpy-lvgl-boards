# Backlight: a slider sets the screen brightness.
#
#   mpremote run examples/backlight.py
#
# display_driver.backlight(percent) sets the backlight, display_driver.backlight()
# reads it. RP2350 board: PWM on GPIO40. STM32 boards: on/off for now.
import lvgl as lv
import display_driver
import ui

scr = lv.obj()
scr.set_style_text_font(ui.font(16), 0)

label = lv.label(scr)
label.align(lv.ALIGN.CENTER, 0, -ui.px(40))

slider = lv.slider(scr)
slider.set_size(ui.px(180), ui.px(10))
slider.set_style_pad_all(ui.px(4), lv.PART.KNOB)
slider.center()
slider.set_range(5, 100)  # not 0: a black screen is hard to bring back by touch
slider.set_value(max(5, display_driver.backlight()), False)


def show():
    label.set_text("Backlight %d %%" % display_driver.backlight())


def on_change(e):
    display_driver.backlight(slider.get_value())
    show()


slider.add_event_cb(on_change, lv.EVENT.VALUE_CHANGED, None)
show()

lv.screen_load(scr)
