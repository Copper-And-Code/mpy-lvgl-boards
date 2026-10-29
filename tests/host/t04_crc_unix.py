# Phase 4: same scene as tests/hil/t04_crc.py on the unix port, 240x240 RGB565 DIRECT.
# Run with: micropython-lvgl tests/host/t04_crc_unix.py (cwd = repo root)
import sys
sys.path.insert(0, "tests/hil")
import lvgl as lv
import scene_static

W = H = 240
lv.init()
disp = lv.display_create(W, H)
disp.set_color_format(lv.COLOR_FORMAT.RGB565)
buf = bytearray(W * H * 2)
disp.set_buffers(buf, None, len(buf), lv.DISPLAY_RENDER_MODE.DIRECT)
disp.set_flush_cb(lambda d, a, p: d.flush_ready())
scr = lv.obj()
scene_static.build(scr)
lv.screen_load(scr)
lv.refr_now(disp)
print("CRCS", " ".join("%08x" % c for c in scene_static.tile_crcs(buf, W, H)))
