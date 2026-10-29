# Phase 4 hello (eyes): button + label + spinner animation, through display_driver.
# Run with: mpremote run tests/hil/t04_hello.py  (the scene stays up afterwards)
import lvgl as lv
import display_driver

scr = lv.obj()
btn = lv.button(scr)
btn.set_size(140, 50)
btn.align(lv.ALIGN.CENTER, 0, -50)
lbl = lv.label(btn)
lbl.set_text("Hello RP2350")
lbl.center()
btn.add_event_cb(lambda e: print("clicked"), lv.EVENT.CLICKED, None)

spinner = lv.spinner(scr)
spinner.set_size(70, 70)
spinner.align(lv.ALIGN.CENTER, 0, 40)

info = lv.label(scr)
info.set_text("%dx%d  x%d" % (display_driver.WIDTH, display_driver.HEIGHT, 480 // display_driver.WIDTH))
info.align(lv.ALIGN.BOTTOM_MID, 0, -8)

lv.screen_load(scr)
print("hello scene loaded")
