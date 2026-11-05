# Phase 3 panel test on the ESP32-4848S040 (eyes, then numbers):
#   scripts/uart_run.py tests/hil/esp32/t03_panel.py --dtr 0 --boot-wait 5 --timeout 80
# 1. top two thirds, colour bars left to right: red, green, blue, white, black, with
#    a yellow 1-pixel frame on the outer edge; bottom third, three ramps from black to
#    full red, green and blue, 32 even steps left to right (a wrong bit shows as bands
#    out of order);
# 2. fps over 5 s against the nominal rate;
# 3. a 200 KB file written to flash during scan-out, the bars must not disturb;
# 4. swap between two framebuffers.
import os
import time

import esp_rgb
import panels

esp_rgb.init(**panels.get("ST7701_4848S040"))
print("info:", esp_rgb.info())
W, H = 480, 480
COLS = (0xF800, 0x07E0, 0x001F, 0xFFFF, 0x0000)


def draw(fb):
    t = time.ticks_ms()
    line = bytearray(W * 2)
    for x in range(W):
        c = COLS[x * len(COLS) // W]
        line[2 * x] = c & 255
        line[2 * x + 1] = c >> 8
    line[0] = line[1] = line[-1] = line[-2] = 0
    line[0], line[1] = 0xE0, 0xFF
    line[-2], line[-1] = 0xE0, 0xFF
    edge = bytes((0xE0, 0xFF)) * W
    ramps = H * 2 // 3
    for y in range(H):
        if y == 0 or y == H - 1:
            src = edge
        elif y < ramps:
            src = line
        else:
            n = (y - ramps) * 3 // (H - ramps)
            for x in range(W):
                v = x * 32 // W
                fb[y * W + x] = (v << 11, (v * 2 + (v >> 4)) << 5, v)[n]
            continue
        for x in range(W):
            fb[y * W + x] = src[2 * x] | src[2 * x + 1] << 8
    return time.ticks_diff(time.ticks_ms(), t)


fb = esp_rgb.framebuffer(1 - esp_rgb.shown())
print("bars drawn in", draw(fb), "ms")
print("swap:", esp_rgb.swap())

f0, t0 = esp_rgb.frame_count(), time.ticks_ms()
time.sleep_ms(5000)
f1, t1 = esp_rgb.frame_count(), time.ticks_ms()
dt = time.ticks_diff(t1, t0)
print("frames %d in %d ms -> %.2f fps (nominal %.2f)" % (f1 - f0, dt, (f1 - f0) * 1000 / dt, esp_rgb.info()["fps_nominal"]))

f0, t0 = esp_rgb.frame_count(), time.ticks_ms()
with open("/_t.bin", "wb") as f:
    chunk = bytes(4096)
    for i in range(50):
        f.write(chunk)
dt = time.ticks_diff(time.ticks_ms(), t0)
os.remove("/_t.bin")
print("wrote 200 KB in %d ms, frames %d" % (dt, esp_rgb.frame_count() - f0))
print("RESULT: ok")
