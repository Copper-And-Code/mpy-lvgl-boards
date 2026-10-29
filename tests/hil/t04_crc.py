# Phase 4: render scene_static on the board and print per-tile CRC32 of the
# framebuffer; tests/host/t04_crc_unix.py does the same on the unix port.
# Run with: mpremote cp tests/hil/scene_static.py :scene_static.py + run tests/hil/t04_crc.py
import time
import lvgl as lv
import display_driver
import rgbpanel
import scene_static

display_driver.stop()
scr = lv.obj()
scene_static.build(scr)
lv.screen_load(scr)
lv.refr_now(display_driver.disp)

# Full-screen invalidated refresh time
times = []
for i in range(5):
    scr.invalidate()
    t0 = time.ticks_us()
    lv.refr_now(display_driver.disp)
    times.append(time.ticks_diff(time.ticks_us(), t0))
print("refr_now full screen us:", times)

fb = rgbpanel.framebuffer(rgbpanel.shown())  # the buffer LVGL rendered last
crcs = scene_static.tile_crcs(bytes(fb), display_driver.WIDTH, display_driver.HEIGHT)
print("CRCS", " ".join("%08x" % c for c in crcs))
display_driver.start()
