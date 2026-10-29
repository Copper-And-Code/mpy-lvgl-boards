# C64-style keyboard: type on a blue screen, Commodore colours.
#
#   mpremote run examples/c64_keyboard.py
#
# Needs a TCA8418 keypad controller on connector H4 (pin 7 I2C_VCC 3.3 V,
# 8 GND, 9 SDA, 10 SCL) wired to a C64-style 8x8 matrix: see
# python/c64keyboard.py. The bottom line shows the last key and the
# modifiers held. Without the TCA8418 the screen says so.
import lvgl as lv
import display_driver
import c64keyboard

BORDER, SCREEN, TEXT = 0x352879, 0x6C5EB5, 0xA59EFF  # C64 palette, approx.

scr = lv.obj()
scr.set_style_bg_color(lv.color_hex(SCREEN), 0)
scr.set_style_border_color(lv.color_hex(BORDER), 0)
scr.set_style_border_width(10, 0)
scr.remove_flag(lv.obj.FLAG.SCROLLABLE)

status = lv.label(scr)
status.set_style_text_color(lv.color_hex(TEXT), 0)
status.align(lv.ALIGN.BOTTOM_LEFT, 0, 0)

try:
    kb = c64keyboard.C64Keyboard()
except OSError as e:
    kb = None
    status.set_text("No TCA8418 on H4:\n%s" % e)
    status.align(lv.ALIGN.CENTER, 0, 0)

if kb is not None:
    indev = kb.lv_register()

    ta = lv.textarea(scr)  # joins the keyboard's group by itself
    ta.set_size(lv.pct(100), lv.pct(85))
    ta.align(lv.ALIGN.TOP_LEFT, 0, 0)
    ta.set_style_bg_opa(lv.OPA.TRANSP, 0)
    ta.set_style_border_width(0, 0)
    ta.set_style_text_color(lv.color_hex(TEXT), 0)
    ta.set_style_bg_color(lv.color_hex(TEXT), lv.PART.CURSOR)  # block cursor
    ta.set_style_bg_opa(lv.OPA.COVER, lv.PART.CURSOR)
    ta.set_text("**** RP2350 MICROPYTHON ****\n\nREADY.\n")
    lv.group_focus_obj(ta)

    # Bottom line: the last key and the modifiers held
    def read_and_show(indev, data):
        kb.lv_read_cb(indev, data)
        if kb.last is not None:
            pressed, name, char = kb.last
            status.set_text("%s %s" % (name, " ".join(sorted(kb.held))))
            kb.last = None

    indev.set_read_cb(read_and_show)
    status.set_text("Type on the keyboard")

lv.screen_load(scr)
