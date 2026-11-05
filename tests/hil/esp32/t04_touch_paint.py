# Phase 4 (fingers) on the ESP32-4848S040: GT911 orientation and coordinates, no LVGL.
#   scripts/uart_run.py tests/hil/esp32/t04_touch_paint.py --dtr 0 --boot-wait 5 --timeout 170
# Same test as tests/hil/stm32/t04_touch_paint.py: 5 white squares (4 corners + centre),
# a green dot where the finger is; each new press prints the point and the nearest
# square. Ends after 5 presses or 150 s. Expected: every press lands on its square.
import time
from array import array

import esp_rgb
import gt911
import panels
from machine import Pin, SoftI2C


timing = panels.get("ST7701_4848S040")
esp_rgb.init(**timing, buffers=1, backlight=100)
W, H = timing["width"], timing["height"]
fb = esp_rgb.framebuffer(0)


def rect(x0, y0, w, h, c):
    x0, x1 = max(0, x0), min(W, x0 + w)
    if x1 <= x0:
        return
    row = array("H", [c] * (x1 - x0))
    for y in range(max(0, y0), min(H, y0 + h)):
        fb[y * W + x0 : y * W + x1] = row


rect(0, 0, W, H, 0x0000)
M = 40
targets = {
    "top-left": (0, 0),
    "top-right": (W - M, 0),
    "bottom-right": (W - M, H - M),
    "bottom-left": (0, H - M),
    "centre": (W // 2 - M // 2, H // 2 - M // 2),
}
for x, y in targets.values():
    rect(x, y, M, M, 0xFFFF)

t = gt911.GT911(i2c=SoftI2C(scl=Pin(45), sda=Pin(19), freq=400_000), rst=None)
print("GT911 product id", t.product_id(), "cmd 0x%02x" % t.i2c.readfrom_mem(t.addr, 0x8040, 1, addrsize=16)[0])

n = 100
t0 = time.ticks_us()
for i in range(n):
    t.read()
print("read() no touch, avg us:", time.ticks_diff(time.ticks_us(), t0) // n)

print("touch the 5 white squares, one at a time")
presses = 0
was = False
end = time.ticks_add(time.ticks_ms(), 150_000)
while presses < 5 and time.ticks_diff(end, time.ticks_ms()) > 0:
    p, x, y = t.read()
    if p:
        rect(x - 3, y - 3, 7, 7, 0x07E0)
    if p and not was:
        presses += 1
        best = min(targets, key=lambda k: (targets[k][0] + M // 2 - x) ** 2 + (targets[k][1] + M // 2 - y) ** 2)
        tx, ty = targets[best][0] + M // 2, targets[best][1] + M // 2
        print("press %d: x %d y %d -> nearest %s (centre %d,%d, off %d,%d)" % (presses, x, y, best, tx, ty, x - tx, y - ty))
    was = p
    time.sleep_ms(10)
print("done, presses:", presses)
