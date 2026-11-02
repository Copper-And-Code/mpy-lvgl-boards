# Phase 5 experiment: where LVGL's software rendering time goes on the STM32H743.
#   scripts/uart_run.py tests/hil/stm32/t05_render_mem.py --timeout 300
# A Python LVGL display (1024x600, PARTIAL, 100-line buffers) whose flush does
# nothing, so only rendering is timed, with the render buffers in:
#   heap   GC heap in SDRAM (cached, write-back)
#   axi    AXI SRAM above .bss: unused when the GC heap is in SDRAM (test only,
#          through uctypes; nothing else may live there)
#   zone   the st_ltdc framebuffer zone in SDRAM (MPU write-through)
# Two scenes: "plain" (background, a few widgets) and "buttons" (48 themed buttons).
# The panel keeps showing whatever it showed: nothing is flushed to it.
import gc
import time

import lvgl as lv
import machine
import st_ltdc
import uctypes

W, H, LINES = 1024, 600, 100
NBYTES = W * LINES * 2
AXI_FREE = 0x24010000  # _ebss is about 0x24003e5c, the stack starts at 0x2407bff8

import panels
import stm32_board

st_ltdc.init(**panels.get(stm32_board.panel()), buffers=2, backlight=100)  # scan-out on, as in use
lv.init()


def flush(d, area, px):
    d.flush_ready()


def scene_plain(scr):
    scr.set_style_bg_color(lv.color_hex(0x203040), 0)
    b = lv.button(scr)
    b.set_size(200, 60)
    b.center()
    lv.label(b).set_text("plain")
    t = lv.label(scr)
    t.set_text("LVGL %d.%d" % (lv.version_major(), lv.version_minor()))
    t.align(lv.ALIGN.BOTTOM_MID, 0, -10)


def scene_buttons(scr):
    scr.set_style_bg_color(lv.color_hex(0x203040), 0)
    for r in range(6):
        for c in range(8):
            b = lv.button(scr)
            b.set_size(W // 8 - 16, H // 6 - 30)
            b.set_pos(c * (W // 8) + 8, r * (H // 6) + 8)
            lb = lv.label(b)
            lb.set_text("B%d" % (r * 8 + c))
            lb.center()


def scene_noshadow(scr):
    scene_buttons(scr)
    for i in range(scr.get_child_count()):
        scr.get_child(i).set_style_shadow_width(0, 0)


zone = st_ltdc.info()
zone_addr = zone["zone_addr"] + 2 * ((W * H * 2 + 1023) // 1024 * 1024)
bufs = {
    "heap": (bytearray(NBYTES), bytearray(NBYTES)),
    "axi": (uctypes.bytearray_at(AXI_FREE, NBYTES), uctypes.bytearray_at(AXI_FREE + NBYTES, NBYTES)),
    "zone": (uctypes.bytearray_at(zone_addr, NBYTES), uctypes.bytearray_at(zone_addr + NBYTES, NBYTES)),
}
assert AXI_FREE + 2 * NBYTES < 0x2407B000, "AXI buffers overlap the stack"
assert zone_addr + 2 * NBYTES <= zone["zone_addr"] + zone["zone_bytes"]

print("render only, PARTIAL %d lines, full screen %dx%d, us (min/avg of 3)" % (LINES, W, H))
for sname, scene in (("plain", scene_plain), ("buttons", scene_buttons), ("noshadow", scene_noshadow)):
    for where, (b0, b1) in bufs.items():
        disp = lv.display_create(W, H)
        disp.set_color_format(lv.COLOR_FORMAT.RGB565)
        disp.set_buffers(b0, b1, NBYTES, lv.DISPLAY_RENDER_MODE.PARTIAL)
        disp.set_flush_cb(flush)
        scr = lv.obj()
        scene(scr)
        lv.screen_load(scr)
        lv.refr_now(disp)
        ts = []
        for i in range(3):
            scr.invalidate()
            t0 = time.ticks_us()
            lv.refr_now(disp)
            ts.append(time.ticks_diff(time.ticks_us(), t0))
        print("%-9s %-5s min %7d avg %7d  (%.1f Mpx/s)"
              % (sname, where, min(ts), sum(ts) // 3, W * H / min(ts)))
        disp.delete()
        gc.collect()
print("st_ltdc underruns", st_ltdc.info()["underruns"])
