# Phase 3 panel test for the STM32H743 boards (st_ltdc, no LVGL needed).
#   mpremote run tests/hil/stm32/t03_panel.py
# Panel: PANEL in /display_config.py on the board (default "IPS1024x600"), e.g.
#   mpremote exec "open('/flash/display_config.py','w').write('PANEL = \"RGB043M2\"\n')"
#
# Each pattern stays on screen for HOLD_S seconds; the console says which one.
# What to look at:
#   A. colour bars, left to right red, green, blue, white, black, with a 1-pixel
#      yellow frame on the outer edge (all four sides must be visible);
#   B. four ramps, top to bottom red, green, blue, grey, dark (left) to bright
#      (right), 32 steps (green 64): even steps, none twice as wide as its
#      neighbours (a missing or swapped RGB565 bit doubles or reorders steps). In
#      RGB565 the LTDC repeats the top bits on the low pins (R0-R2, G0-G1, B0-B2),
#      so a missing low pin is hard to see here;
#   C. 1-pixel checkerboard: even grey, no stripes or crawling;
#   D. double buffering: bars and inverted bars swapped 20 times;
# then measured: frame rate against the nominal one, underruns, and a 200 KB
# file written while the panel scans out. The bars stay on screen at the end.
import gc
import os
import time
from array import array

import panels
import st_ltdc

HOLD_S = 4

try:
    from display_config import PANEL
except ImportError:
    PANEL = "IPS1024x600"

RED, GREEN, BLUE, WHITE, BLACK, YELLOW = 0xF800, 0x07E0, 0x001F, 0xFFFF, 0x0000, 0xFFE0

timing = panels.get(PANEL)
st_ltdc.init(**timing, buffers=2, backlight=100)
W, H = timing["width"], timing["height"]
info = st_ltdc.info()
print("panel:", PANEL, info)


def fill_rows(fb, y0, y1, row):
    for y in range(y0, y1):
        fb[y * W : (y + 1) * W] = row


def frame(fb, c):
    fb[0:W] = array("H", [c] * W)
    fb[(H - 1) * W : H * W] = array("H", [c] * W)
    for y in range(H):
        fb[y * W] = c
        fb[y * W + W - 1] = c


def bars(fb, invert=False):
    colours = (RED, GREEN, BLUE, WHITE, BLACK)
    row = array("H", [0] * W)
    bar = W // len(colours)
    for x in range(W):
        c = colours[min(x // bar, len(colours) - 1)]
        row[x] = c ^ 0xFFFF if invert else c
    fill_rows(fb, 0, H, row)
    frame(fb, YELLOW)


def ramps(fb):
    band = H // 4
    for i in range(4):
        row = array("H", [0] * W)
        for x in range(W):
            v = x * 32 // W  # 0..31
            g6 = x * 64 // W  # 0..63
            if i == 0:
                c = v << 11
            elif i == 1:
                c = g6 << 5
            elif i == 2:
                c = v
            else:
                c = (v << 11) | (v * 2 + (v >> 4)) << 5 | v
            row[x] = c
        fill_rows(fb, i * band, (i + 1) * band if i < 3 else H, row)


def checker(fb):
    a = array("H", [WHITE, BLACK] * (W // 2))
    b = array("H", [BLACK, WHITE] * (W // 2))
    for y in range(H):
        fb[y * W : y * W + len(a)] = a if y & 1 == 0 else b


def show(name, draw):
    # Draw into the hidden buffer, then show it from the next vertical blanking.
    hidden = 1 - st_ltdc.shown()
    fb = st_ltdc.framebuffer(hidden)
    t0 = time.ticks_ms()
    draw(fb)
    dt = time.ticks_diff(time.ticks_ms(), t0)
    ok = st_ltdc.swap()
    print("%s: drawn in %d ms, swap %s" % (name, dt, ok))
    time.sleep(HOLD_S)


show("A colour bars + yellow frame", bars)
show("B ramps red/green/blue/grey", ramps)
show("C 1-pixel checkerboard", checker)

# D. swap cost
bars(st_ltdc.framebuffer(1 - st_ltdc.shown()), invert=True)
st_ltdc.swap()
bars(st_ltdc.framebuffer(1 - st_ltdc.shown()))
t0 = time.ticks_us()
for i in range(20):
    st_ltdc.swap()
    time.sleep_ms(100)
print("D 20 swaps: %d ms (incl. 20 x 100 ms sleep)" % (time.ticks_diff(time.ticks_us(), t0) // 1000))
if st_ltdc.shown() != 0:
    st_ltdc.swap()  # end on the normal bars

# Frame rate and underruns
u0, f0 = st_ltdc.underruns(), st_ltdc.frame_count()
t0 = time.ticks_ms()
time.sleep(3)
f1, dt = st_ltdc.frame_count(), time.ticks_diff(time.ticks_ms(), t0)
fps = (f1 - f0) * 1000 / dt
nominal = info["refresh_mhz"] / 1000
print("frames %d in %d ms -> %.2f fps (nominal %.2f), underruns %d"
      % (f1 - f0, dt, fps, nominal, st_ltdc.underruns() - u0))

# 200 KB written to the QSPI filesystem during scan-out
u0, f0 = st_ltdc.underruns(), st_ltdc.frame_count()
buf = bytearray(4096)
t0 = time.ticks_ms()
with open("/flash/t03_flash.bin", "wb") as f:
    for i in range(50):
        f.write(buf)
dt = time.ticks_diff(time.ticks_ms(), t0)
os.remove("/flash/t03_flash.bin")
print("wrote 200 KB in %d ms, frames %d (expected ~%d), underruns %d"
      % (dt, st_ltdc.frame_count() - f0, int(dt * nominal / 1000), st_ltdc.underruns() - u0))

gc.collect()
print("mem_free:", gc.mem_free())
print("info:", st_ltdc.info())
print("RESULT: patterns shown; check A-D by eye; underruns", st_ltdc.underruns())
