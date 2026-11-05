<!--
Draft issue for PyDevices/omnipython-lvgl (ports/micropython/src/lv_mem_core_micropython.c,
LV_ASSERT_HANDLER in lv_conf.h). Not filed. Review, then file it yourself or tell Claude to.
-->

# Out of memory during `lv.timer_handler()` leaves LVGL stuck; the next invalidation hangs the MCU

## Summary

When an LVGL allocation fails while rendering (typically a layer for a widget with
opacity or a transform), LVGL never recovers:

- on **rp2** (`MICROPY_MALLOC_USES_ALLOCATED_SIZE` = 0) `lv_malloc_core()` calls
  `m_malloc()`, which raises `MemoryError` by `nlr` jump straight through LVGL's C code.
  `lv_timer_handler()`'s `already_running` and the display's `rendering_in_progress` stay
  `true`. From then on every `lv.timer_handler()` returns immediately (UI frozen, no error),
  and the first call that invalidates an area (`obj.delete()`, `set_x()`, an animation...)
  hits `LV_ASSERT_MSG(!disp->rendering_in_progress, ...)` in `lv_inv_area()` →
  `LV_ASSERT_HANDLER` = `while(1);` → the board hangs (USB dead, power cycle needed).
- on **unix** (`MICROPY_MALLOC_USES_ALLOCATED_SIZE` = 1) `lv_malloc_core()` calls
  `gc_alloc()`, which returns NULL; the same script then never returns from the first
  `lv.timer_handler()` (killed after 15 s; the binary is stripped, so we do not have the
  backtrace — likely `LV_ASSERT_MALLOC` → `while(1);`).

So on both ports one oversized widget style turns into a hang, with nothing the
application can catch.

## Versions

- rp2 (RP2350B, Waveshare RP2350-Touch-LCD-4, no PSRAM), MicroPython v1.29.0:
  `PyDevices/omnipython-lvgl` `92f8c0a` plus the pools change of #6, which does not touch this code,
  3 runs out of 3; also on `lvgl-micropython` `3e287e7`, the code this moved from.
- unix: only on `lvgl-micropython` `3e287e7`, not re-run on omnipython-lvgl.

## Reproduce

Any display; the heap is filled first so that the layer (200x200 ARGB8888 = 160 000 B)
does not fit:

```python
import gc, time, lvgl as lv
# ... display set up, no periodic timer_handler running ...
scr = lv.obj(); lv.screen_load(scr); lv.timer_handler()
gc.collect()
ballast = bytearray(gc.mem_free() - 70_000)   # leave ~70 KB

o = lv.obj(scr)
o.set_size(200, 200)
o.set_style_opa(200, 0)
o.set_style_transform_rotation(10, 0)

for i in range(3):
    try:
        lv.timer_handler(); print(i, "ok")
    except MemoryError as e:
        print(i, "MemoryError", e)

o.delete()          # rp2: hangs here (lv_obj_delete invalidates the area)
lv.label(scr).set_text("after")
print("not reached")
```

rp2 (a watchdog reset the board each run):

```text
0 MemoryError memory allocation failed, allocating 176403 bytes
1 ok        <- returns at once: `already_running` is still true (from the source)
2 ok
(hang: nothing printed after o.delete() / the next label)
```

unix (`-X heapsize=1M`), on the old code, 2 runs out of 2: no output after the first
`lv.timer_handler()`.

## Possible directions (for discussion)

1. In the binding's `lv.timer_handler()` / `lv.refr_now()` wrappers, `nlr_push()` around
   the call; on an exception, reset `already_running` and the display's
   `rendering_in_progress` (and drop the half-built layers / draw tasks) before re-raising.
   This keeps `MemoryError` catchable, but needs care to leave LVGL's draw state
   consistent.
2. Make `lv_malloc_core()` never raise (`m_malloc_maybe()` / `gc_alloc()` on every port)
   so LVGL sees NULL as it expects, **and** an `LV_ASSERT_HANDLER` that does not spin
   forever (e.g. record the failure and raise once back in Python). On its own, returning
   NULL is not enough: that is what unix does today, and it hangs too.
3. At least document it: on small-heap boards, opacity/transform on large widgets can
   hang the MCU.

`LV_ASSERT_HANDLER` is still `while(1);` in `lv_conf.h` for MicroPython.

Happy to test on RP2350 hardware.
