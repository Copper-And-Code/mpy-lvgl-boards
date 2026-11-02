# Phase 2: soft reset with LVGL still initialised (no lv.deinit()).
# Run it several times in a row; mpremote soft-resets the board before each run:
#   mpremote run tests/hil/stm32/t02_lvgl_softreset.py \
#            run tests/hil/stm32/t02_lvgl_softreset.py \
#            run tests/hil/stm32/t02_lvgl_softreset.py
# Expected: "run: ..." and "OK" every time. Without the board's end-of-soft-reset hook
# (st_ltdc_board_end_soft_reset -> mp_lv_deinit_gc) the second lv.init() hangs.
# No watchdog here: the STM32 IWDG cannot be stopped and survives a soft reset, so
# it would hard-reset the board later and hide the very hang this test looks for.
# A hang means the test failed: press reset.
import gc
import time
import lvgl as lv

gc.collect()
free0 = gc.mem_free()
t0 = time.ticks_ms()
lv.init()
disp = lv.display_create(320, 240)
disp.set_color_format(lv.COLOR_FORMAT.RGB565)
buf = bytearray(320 * 240 * 2)
disp.set_buffers(buf, None, len(buf), lv.DISPLAY_RENDER_MODE.FULL)
flushed = []
disp.set_flush_cb(lambda d, area, px: (flushed.append(area.get_width()), d.flush_ready()))
label = lv.label(lv.screen_active())
label.set_text("soft reset test")
label.center()
lv.tick_inc(50)
lv.refr_now(disp)
print(
    "run: init+refr %d ms, flushed %s, mem_free before %d after %d, lv.is_initialized %s"
    % (time.ticks_diff(time.ticks_ms(), t0), flushed, free0, gc.mem_free(), lv.is_initialized())
)
print("OK (LVGL left initialised on purpose)")
