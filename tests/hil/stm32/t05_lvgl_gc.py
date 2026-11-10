# Phase 5: LVGL memory in TLSF pools (omnipython-lvgl lvmp_pool.h, LVMP_POOL_TLSF=1) stays
# visible to the GC. No panel needed.
#   scripts/uart_run.py tests/hil/stm32/t05_lvgl_gc.py --timeout 120
# 300 buttons, each with an event callback that only LVGL refers to (a closure
# over its own list); then garbage, gc.collect() several times, freed memory
# overwritten. Every callback must still run and see its own data. Twice, with
# lv.deinit()/lv.init() in between (the pools are dropped and made again).
# Expected: "RESULT: ok" and no crash.
import gc
import time

import lvgl as lv

N = 300


def flush(d, area, px):
    d.flush_ready()


def setup():
    lv.init()
    disp = lv.display_create(320, 240)
    disp.set_color_format(lv.COLOR_FORMAT.RGB565)
    buf = bytearray(320 * 40 * 2)
    disp.set_buffers(buf, None, len(buf), lv.DISPLAY_RENDER_MODE.PARTIAL)
    disp.set_flush_cb(flush)
    return disp, buf


def make_cb(i, hits):
    data = [i, "button %d" % i, bytearray(64)]  # only the closure holds it

    def cb(e):
        hits.append((i, data[0], data[1]))

    return cb


def round_(name):
    disp, buf = setup()
    scr = lv.screen_active()
    hits = []
    buttons = []
    for i in range(N):
        b = lv.button(scr)
        b.set_size(20, 10)
        b.add_event_cb(make_cb(i, hits), lv.EVENT.CLICKED, None)
        buttons.append(b)
    lv.refr_now(disp)
    # garbage, collections, and freed memory overwritten
    for k in range(5):
        junk = [bytearray(b"\x55" * 512) for j in range(400)]
        junk = None
        gc.collect()
        fill = [bytearray(b"\xaa" * 512) for j in range(400)]
        fill = None
    gc.collect()
    t0 = time.ticks_ms()
    for b in buttons:
        b.send_event(lv.EVENT.CLICKED, None)
    bad = [h for h in hits if h[0] != h[1] or h[2] != "button %d" % h[0]]
    ok = len(hits) == N and not bad
    print("%s: %d/%d callbacks, %d wrong, %d ms, mem_free %d"
          % (name, len(hits), N, len(bad), time.ticks_diff(time.ticks_ms(), t0), gc.mem_free()))
    lv.refr_now(disp)
    lv.deinit()
    gc.collect()
    return ok


r1 = round_("round 1")
r2 = round_("round 2 (after lv.deinit/lv.init)")
print("RESULT:", "ok" if r1 and r2 else "FAILED")
