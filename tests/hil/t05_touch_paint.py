# Phase 5 (fingers): visual touch test, no LVGL.
# Draws 5 white target squares (4 corners + centre) and a dot where the finger is:
# green while pressed. Prints every new report. Ends after 5 touches or 180 s.
# Run with: mpremote resume run tests/hil/t05_touch_paint.py
import time
import rgbpanel
import gt911

rgbpanel.init()
W, H, S = rgbpanel.WIDTH, rgbpanel.HEIGHT, rgbpanel.SCALE
fb = rgbpanel.framebuffer()


def rect(x0, y0, w, h, c):
    for y in range(max(0, y0), min(H, y0 + h)):
        b = y * W
        for x in range(max(0, x0), min(W, x0 + w)):
            fb[b + x] = c


rect(0, 0, W, H, 0x0000)
m = 12
for (x, y) in ((0, 0), (W - m, 0), (W - m, H - m), (0, H - m), (W // 2 - m // 2, H // 2 - m // 2)):
    rect(x, y, m, m, 0xFFFF)

t = gt911.GT911(scale=S)
# (gt911.GT911 writes command 0 to 0x8040 itself)
print("product id:", t.product_id(), "cmd 0x8040 = %02x" % t.i2c.readfrom_mem(t.addr, 0x8040, 1, addrsize=16)[0])
print("touch the 5 white squares")

last = None
downs = 0
end = time.ticks_add(time.ticks_ms(), 180_000)
while time.ticks_diff(end, time.ticks_ms()) > 0:
    p = t.read()
    if p != last:
        print("%s x=%d y=%d" % ("DOWN" if p[0] else "UP  ", p[1], p[2]))
        if p[0]:
            rect(p[1] - 2, p[2] - 2, 5, 5, 0x07E0)
            if last is None or not last[0]:
                downs += 1
        last = p
        if downs >= 5 and not p[0]:
            break
    time.sleep_ms(10)
print("done, touches:", downs)
