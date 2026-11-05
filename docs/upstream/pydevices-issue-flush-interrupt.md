<!--
Draft issue for PyDevices/omnipython-lvgl (mp_lv_nesting_call, in
binding/emit_c_micropython_style.py). Not filed. Review, then file it yourself or tell Claude to.
-->

# KeyboardInterrupt inside a Python `flush_cb` leaves LVGL waiting for the flush forever

## Summary

Python callbacks are called through `mp_lv_nesting_call()`, which catches any exception,
prints it and returns 0, so that LVGL's C state is never unwound. For a display `flush_cb`
this has a side effect: if the exception happens before the callback calls
`disp.flush_ready()`, the display stays in the "flushing" state. LVGL's next refresh calls
`wait_for_flushing()`, which (with no `flush_wait_cb`) spins in C until `flushing` is
cleared: forever. Nothing Python runs any more, so Ctrl-C cannot help either.

The exception that triggers it in practice is `KeyboardInterrupt`: Ctrl-C at the wrong
moment, or `mpremote`, which sends Ctrl-C before every `run` / `exec` / `soft-reset`. A
`flush_cb` that waits for anything (DMA, VSYNC, a buffer swap) while letting MicroPython
process pending events makes the window large; a short flush_cb only makes it small.

## Versions

- STM32H743 (STM32H7_CORE V1.3), MicroPython v1.29.0, `PyDevices/omnipython-lvgl`
  `92f8c0a` plus the pools change of #6, which does not touch this code: 4 runs out of 4.
- RP2350, on `lvgl-micropython` `3e287e7`, the code this moved from: the same.

## Reproduce (any port with a REPL)

```python
import lvgl as lv, time
lv.init()
d = lv.display_create(240, 240)
b1 = bytearray(240 * 240 * 2); b2 = bytearray(240 * 240 * 2)
d.set_buffers(b1, b2, len(b1), lv.DISPLAY_RENDER_MODE.DIRECT)

def flush(disp, area, px):
    time.sleep_ms(20)          # e.g. waiting for VSYNC / a buffer swap
    disp.flush_ready()

d.set_flush_cb(flush)
l = lv.label(lv.screen_active())
i = 0
while True:
    l.set_text(str(i)); i += 1
    lv.tick_inc(20)
    lv.timer_handler()
```

Press Ctrl-C once. The loop spends most of its time in that sleep, so the interrupt lands in
`flush()` and is printed by the binding:

```text
Traceback (most recent call last):
  File "<stdin>", line 8, in flush
KeyboardInterrupt:
```

The next `lv.timer_handler()` never returns: more Ctrl-C do nothing, the REPL is dead, and
only a hardware reset recovers the board. A short `flush_cb` makes the window smaller.

## What we did

We moved the flush callback to C on all our boards, so no Python code runs between LVGL
handing over a frame and the flush being acknowledged.

## Possible fixes in the binding (for discussion)

1. When a `flush_cb` raises, call `lv_display_flush_ready(disp)` before returning to LVGL
   (the frame is lost, LVGL keeps going), e.g. special-case `lv_display_flush_cb_t` in the
   callback trampoline.
2. Or re-raise `KeyboardInterrupt` / `SystemExit` after LVGL's state is consistent, instead
   of swallowing them (today a Ctrl-C landing in any callback is lost, so a program whose
   time is mostly spent in LVGL callbacks is hard to interrupt).
3. At least document: a Python `flush_cb` must call `flush_ready()` in a `finally`, and
   should not wait with events enabled.
