# Hello: a label and a spinner.
#
#   mpremote run examples/hello.py
#
# `import display_driver` starts the panel, LVGL, the touch and a timer that
# calls lv.timer_handler(): the script can end and the screen keeps running.
# ui.px() and ui.font() scale sizes written for a 240 px display to this one.
import os

import lvgl as lv
import display_driver
import ui

scr = lv.obj()
scr.set_style_bg_color(lv.color_hex(0x102030), 0)
scr.set_style_text_font(ui.font(14), 0)  # inherited by the labels

title = lv.label(scr)
title.set_text("Hello %s!" % os.uname().machine.split(" with ")[-1])
title.set_style_text_color(lv.color_hex(0xFFFFFF), 0)
title.set_style_text_font(ui.font(24), 0)
title.align(lv.ALIGN.TOP_MID, 0, ui.px(30))

spinner = lv.spinner(scr)
spinner.set_size(ui.px(80), ui.px(80))
spinner.set_style_arc_width(ui.px(12), 0)
spinner.set_style_arc_width(ui.px(12), lv.PART.INDICATOR)
spinner.center()

size = lv.label(scr)
size.set_text("%d x %d" % (display_driver.WIDTH, display_driver.HEIGHT))
size.set_style_text_color(lv.color_hex(0x80A0C0), 0)
size.align(lv.ALIGN.BOTTOM_MID, 0, -ui.px(20))

lv.screen_load(scr)
