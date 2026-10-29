# Phase 3 panel test. Run with: mpremote run tests/hil/t03_panel.py
# 1. colour bars (eyes): left to right red, green, blue, white, black,
#    with a 1-pixel yellow frame on the outer edge of the framebuffer;
# 2. measured fps and underruns over 5 s;
# 3. 200 KB file written to flash during scan-out: underruns must not change;
# 5. rp2.StateMachine on PIO0 still works.
# 4. (soft reset) is run separately, see docs/log/phase3-*.
import gc
import os
import time
import rgbpanel

RED, GREEN, BLUE, WHITE, BLACK, YELLOW = 0xF800, 0x07E0, 0x001F, 0xFFFF, 0x0000, 0xFFE0

rgbpanel.init(pclk_hz=15_000_000, backlight=80)
W, H = rgbpanel.WIDTH, rgbpanel.HEIGHT
fb = rgbpanel.framebuffer()
print("info:", rgbpanel.info())

# 1. Colour bars
colours = (RED, GREEN, BLUE, WHITE, BLACK)
bar = W // len(colours)
row = bytearray(W * 2)
for x in range(W):
    c = colours[min(x // bar, len(colours) - 1)]
    row[2 * x] = c & 0xFF
    row[2 * x + 1] = c >> 8
t0 = time.ticks_us()
for y in range(H):
    for x in range(W):
        fb[y * W + x] = row[2 * x] | (row[2 * x + 1] << 8)
for x in range(W):
    fb[x] = YELLOW
    fb[(H - 1) * W + x] = YELLOW
for y in range(H):
    fb[y * W] = YELLOW
    fb[y * W + W - 1] = YELLOW
print("bars drawn in %d ms" % (time.ticks_diff(time.ticks_us(), t0) // 1000))

# 2. fps and underruns
u0 = rgbpanel.underruns()
f0 = rgbpanel.frame_count()
t0 = time.ticks_ms()
time.sleep(5)
f1 = rgbpanel.frame_count()
dt = time.ticks_diff(time.ticks_ms(), t0)
print("frames %d in %d ms -> %.2f fps (nominal %.2f)" % (f1 - f0, dt, (f1 - f0) * 1000 / dt, rgbpanel.info()["fps_nominal"]))
print("underruns during 5 s:", rgbpanel.underruns() - u0)

# 3. flash write during scan-out
u0 = rgbpanel.underruns()
f0 = rgbpanel.frame_count()
buf = bytearray(4096)
t0 = time.ticks_ms()
with open("/t03_flash.bin", "wb") as f:
    for i in range(50):
        f.write(buf)
os.sync() if hasattr(os, "sync") else None
dt = time.ticks_diff(time.ticks_ms(), t0)
f1 = rgbpanel.frame_count()
print("wrote 200 KB in %d ms, frames %d (expected ~%d), underruns %d"
      % (dt, f1 - f0, dt * 58 // 1000, rgbpanel.underruns() - u0))
os.remove("/t03_flash.bin")

# 5. PIO0 for the user (no pins: returns the bitwise inverse of what it gets)
import rp2


@rp2.asm_pio()
def inv_prog():
    pull()
    mov(isr, invert(osr))
    push()


sm = rp2.StateMachine(0, inv_prog)
sm.active(1)
sm.put(0x12345678)
r = sm.get()
sm.active(0)
print("rp2.StateMachine(0) on PIO0:", "ok" if r == (~0x12345678) & 0xFFFFFFFF else "FAIL %x" % r)
print("underruns total:", rgbpanel.underruns(), "frames:", rgbpanel.frame_count())
gc.collect()
print("mem_free:", gc.mem_free())
