# Phase 5 performance on the STM32H743 boards (heap and framebuffers both in SDRAM).
#   scripts/uart_run.py tests/hil/stm32/t05_perf.py --timeout 300
#
# A. CPU cost of the SDRAM shared with the LTDC: the same Python benchmarks
#    (loop, allocations, 1 MB copies, gc.collect) with
#      off   the LTDC stopped (st_ltdc.deinit()),
#      qos   the LTDC running with the driver's AXI QoS (LTDC/DMA2D before the CPU,
#            SDRAM port limited to one outstanding transaction), as in the old port,
#      noqos the LTDC running with the AXI QoS registers at their reset values.
#    Underruns are counted for each (the ER interrupt is enabled since be477e3).
# B. LVGL render modes on the same scene (DIRECT 2 buffers, DIRECT 1 buffer,
#    PARTIAL 60 and 200 lines): full-screen refresh and a small label change.
# The driver's QoS is put back at the end.
import gc
import time

import lvgl as lv
import machine
import panels
import st_ltdc
import stm32_board

PANEL = stm32_board.panel()
timing = panels.get(PANEL)

# AXI interconnect (GPV) registers set by st_ltdc (offsets from the CMSIS GPV_TypeDef).
QOS_REGS = {
    "TARG5_FN_MOD_ISS_BM": (0x51006008, 0x01),  # SDRAM (FMC) target: 1 outstanding
    "INI6_READ_QOS": (0x51047100, 0x0F),  # LTDC
    "INI6_WRITE_QOS": (0x51047104, 0x0F),
    "INI5_READ_QOS": (0x51046100, 0x0E),  # DMA2D
    "INI5_WRITE_QOS": (0x51046104, 0x0E),
    "INI2_READ_QOS": (0x51043100, 0x00),  # Cortex-M7
    "INI2_WRITE_QOS": (0x51043104, 0x00),
}


def qos(on):
    for addr, val in QOS_REGS.values():
        machine.mem32[addr] = val if on else 0


def qos_state():
    return " ".join("%s=%x" % (k, machine.mem32[a] & 0xFF) for k, (a, _) in QOS_REGS.items())


# ---- A. benchmarks --------------------------------------------------------


def b_loop():
    x = 0
    t0 = time.ticks_us()
    for i in range(200_000):
        x = (x + i * 3) & 0xFFFF
    return time.ticks_diff(time.ticks_us(), t0) // 1000


def b_alloc():
    t0 = time.ticks_us()
    keep = []
    for i in range(20_000):
        keep.append([i, i + 1, str(i)])
        if len(keep) > 2000:
            keep = []
    return time.ticks_diff(time.ticks_us(), t0) // 1000


SRC = bytearray(1024 * 1024)
DST = bytearray(1024 * 1024)


def b_copy():
    t0 = time.ticks_us()
    for i in range(10):
        DST[:] = SRC
    dt = time.ticks_diff(time.ticks_us(), t0)
    return 10 * 1024 * 1024 // dt  # MB/s (bytes per us)


JUNK = None


def b_gc():
    global JUNK
    JUNK = [[i, str(i)] for i in range(30_000)]
    t0 = time.ticks_us()
    gc.collect()
    dt = time.ticks_diff(time.ticks_us(), t0)
    JUNK = None
    return dt // 1000


def bench(name):
    gc.collect()
    u0 = st_ltdc.info()["underruns"]
    r = (b_loop(), b_alloc(), b_copy(), b_gc())
    u1 = st_ltdc.info()["underruns"]
    print("%-6s loop %4d ms  alloc %4d ms  copy %4d MB/s  gc %3d ms  underruns %d"
          % ((name,) + r + (u1 - u0,)))
    return r


print("panel", PANEL, "board", stm32_board.NAME, "freq", machine.freq())
st_ltdc.init(**timing, buffers=2, backlight=100)
print("driver QoS:", qos_state())
res = {}
st_ltdc.deinit()
res["off"] = bench("off")
st_ltdc.init(**timing, buffers=2, backlight=100)
qos(True)
res["qos"] = bench("qos")
qos(False)
res["noqos"] = bench("noqos")
qos(True)
for k in ("qos", "noqos"):
    o, r = res["off"], res[k]
    print("%-6s vs off: loop %+d%%  alloc %+d%%  copy %+d%%  gc %+d%%"
          % (k, (r[0] - o[0]) * 100 // o[0], (r[1] - o[1]) * 100 // o[1],
             (r[2] - o[2]) * 100 // o[2], (r[3] - o[3]) * 100 // max(o[3], 1)))

# ---- B. LVGL render modes -------------------------------------------------

lv.init()
st_ltdc.lv_tick_install()


def build(scr):
    scr.set_style_bg_color(lv.color_hex(0x203040), 0)
    W, H = timing["width"], timing["height"]
    cols, rows = 8, 6
    for r in range(rows):
        for c in range(cols):
            b = lv.button(scr)
            b.set_size(W // cols - 16, H // rows - 30)
            b.set_pos(c * (W // cols) + 8, r * (H // rows) + 8)
            lb = lv.label(b)
            lb.set_text("B%d" % (r * cols + c))
            lb.center()
    arc = lv.arc(scr)
    arc.set_size(100, 100)
    arc.center()
    arc.set_value(40)
    info = lv.label(scr)
    info.set_text("t=0")
    info.align(lv.ALIGN.BOTTOM_MID, 0, -4)
    return info


MODES = (("DIRECT 2 buf", 2, 0), ("DIRECT 1 buf", 1, 0), ("PARTIAL 60", 2, 60), ("PARTIAL 200", 2, 200))
disp = None
for name, bufs, lines in MODES:
    if disp is not None:
        disp.delete()
    st_ltdc.init(**timing, buffers=bufs, backlight=100)
    st_ltdc.lv_display_create(lines)
    disp = lv.display_get_default()
    label = build(lv.screen_active())
    lv.refr_now(disp)
    gc.collect()
    u0 = st_ltdc.info()["underruns"]
    full = []
    for i in range(5):
        lv.screen_active().invalidate()
        t0 = time.ticks_us()
        lv.refr_now(disp)
        full.append(time.ticks_diff(time.ticks_us(), t0))
    small = []
    for i in range(20):
        label.set_text("t=%d" % i)
        t0 = time.ticks_us()
        lv.refr_now(disp)
        small.append(time.ticks_diff(time.ticks_us(), t0))
    print("%-13s full refr min %6d avg %6d us   label min %5d avg %5d us   underruns %d"
          % (name, min(full), sum(full) // len(full), min(small), sum(small) // len(small),
             st_ltdc.info()["underruns"] - u0))

print("end QoS:", qos_state())
print("mem_free", gc.mem_free())
