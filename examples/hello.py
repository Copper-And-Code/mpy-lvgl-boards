# Hello: a label and a spinner.
#
#   mpremote run examples/hello.py
#
# `import display_driver` starts the panel, LVGL, the touch and a timer that
# calls lv.timer_handler(): the script can end and the screen keeps running.
import lvgl as lv
import display_driver

scr = lv.obj()
scr.set_style_bg_color(lv.color_hex(0x102030), 0)

title = lv.label(scr)
title.set_text("Hello RP2350!")
title.set_style_text_color(lv.color_hex(0xFFFFFF), 0)
title.align(lv.ALIGN.TOP_MID, 0, 30)

spinner = lv.spinner(scr)
spinner.set_size(80, 80)
spinner.center()

size = lv.label(scr)
size.set_text("%d x %d" % (display_driver.WIDTH, display_driver.HEIGHT))
size.set_style_text_color(lv.color_hex(0x80A0C0), 0)
size.align(lv.ALIGN.BOTTOM_MID, 0, -20)

lv.screen_load(scr)
