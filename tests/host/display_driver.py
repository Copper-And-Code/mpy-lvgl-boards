# Unix stand-in for the board's display_driver: 240x240 RGB565, DIRECT, two buffers.
import lvgl as lv
WIDTH = HEIGHT = 240
lv.init()
disp = lv.display_create(WIDTH, HEIGHT)
disp.set_color_format(lv.COLOR_FORMAT.RGB565)
_b1 = bytearray(WIDTH * HEIGHT * 2)
_b2 = bytearray(WIDTH * HEIGHT * 2)
disp.set_buffers(_b1, _b2, len(_b1), lv.DISPLAY_RENDER_MODE.DIRECT)
disp.set_flush_cb(lambda d, a, p: d.flush_ready())
