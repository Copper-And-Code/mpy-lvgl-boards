# Phase 3: QSPI flash and SD card writes while the panel scans out.
#   mpremote run tests/hil/stm32/flash_stress.py
# Panel from /display_config.py (PANEL, default "IPS1024x600"). Shows the colour
# ramps, then for DURATION_S seconds writes and deletes 200 KB files in turn on
# /flash and /sd (if mounted). Watch the panel: no flicker, no shifted lines.
# Measured: frames against the nominal rate, LTDC FIFO underruns, write speed.
import os
import time

import panels
import st_ltdc

DURATION_S = 30
FILE_BYTES = 200 * 1024

try:
    from display_config import PANEL
except ImportError:
    PANEL = "IPS1024x600"

timing = panels.get(PANEL)
st_ltdc.init(**timing, buffers=2, backlight=100)
W, H = timing["width"], timing["height"]
nominal = st_ltdc.info()["refresh_mhz"] / 1000

# Ramps (as pattern B of t03_panel.py), drawn into the shown buffer.
fb = st_ltdc.framebuffer(st_ltdc.shown())
from array import array

band = H // 4
for i in range(4):
    row = array("H", [0] * W)
    for x in range(W):
        v = x * 32 // W
        row[x] = (v << 11, (x * 64 // W) << 5, v, (v << 11) | (v * 2 + (v >> 4)) << 5 | v)[i]
    for y in range(i * band, (i + 1) * band if i < 3 else H):
        fb[y * W : (y + 1) * W] = row

targets = ["/flash"]
if "sd" in os.listdir("/"):
    targets.append("/sd")
print("panel", PANEL, "targets", targets, "nominal %.2f fps" % nominal)

chunk = bytearray(4096)
for i in range(len(chunk)):
    chunk[i] = i & 0xFF
u0, f0 = st_ltdc.underruns(), st_ltdc.frame_count()
t_start = time.ticks_ms()
written = {t: 0 for t in targets}
spent = {t: 0 for t in targets}
n = 0
while time.ticks_diff(time.ticks_ms(), t_start) < DURATION_S * 1000:
    t = targets[n % len(targets)]
    name = "%s/stress_%d.bin" % (t, n % 2)
    t0 = time.ticks_ms()
    with open(name, "wb") as f:
        for _ in range(FILE_BYTES // len(chunk)):
            f.write(chunk)
    os.remove(name)
    spent[t] += time.ticks_diff(time.ticks_ms(), t0)
    written[t] += FILE_BYTES
    n += 1
dt = time.ticks_diff(time.ticks_ms(), t_start)
frames = st_ltdc.frame_count() - f0
for t in targets:
    kbs = written[t] / 1024 / (spent[t] / 1000) if spent[t] else 0
    print("%s: %d files, %d KB in %d ms (%.0f KB/s, write + delete)" % (t, written[t] // FILE_BYTES, written[t] // 1024, spent[t], kbs))
print("frames %d in %d ms -> %.2f fps (nominal %.2f)" % (frames, dt, frames * 1000 / dt, nominal))
print("underruns %d, info %s" % (st_ltdc.underruns() - u0, st_ltdc.info()))
