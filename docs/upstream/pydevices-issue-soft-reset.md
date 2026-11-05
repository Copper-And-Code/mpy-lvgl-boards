<!--
Draft issue for PyDevices/omnipython-lvgl (binding/emit_c_micropython_style.py:
mp_lv_init_gc, mp_lv_deinit_gc). Not filed. Review, then file it yourself or tell Claude to.
-->

# `lv.init()` after a MicroPython soft reset crashes or hangs if `lv.deinit()` was not called

## Summary

LVGL's global state (`lv_global_t`, via `LV_ENABLE_GLOBAL_CUSTOM`) is allocated on the
MicroPython GC heap by `mp_lv_init_gc()` and reached through the root pointers
`mp_lv_roots` / `mp_lv_roots_initialized`. A soft reset (Ctrl-D, `machine.soft_reset()`,
or `mpremote` starting a command) re-initialises the GC heap but does **not** clear root
pointers: `mp_init()` does not zero `mp_state_vm_t`. If the program did not call
`lv.deinit()` before the reset, the next `lv.init()` finds
`mp_lv_roots_initialized == 1`, keeps the stale `mp_lv_roots` (pointing into the old,
now freed heap), sees `lv_is_initialized()` as true and skips `lv_init()`. LVGL then
works on memory that MicroPython hands out again to other objects.

On an ESP32-S3 the next run panics (Guru Meditation, `LoadProhibited`) and the board
restarts. On an RP2350, on the older lvgl-micropython, it hung at the first LVGL call after
the reset: USB enumerated, REPL dead, only a power cycle recovered it.

Most real programs never call `lv.deinit()` (an LVGL app typically runs until reset), and
tools such as `mpremote run` / `mpremote exec` soft-reset the board before every command,
so this is easy to hit during development.

## Versions

- `PyDevices/omnipython-lvgl` `92f8c0a` (LVGL 9.5.0), MicroPython v1.29.0, ESP-IDF v5.5.2,
  ESP32-S3 (ESP32-4848S040): reproduced as below.
- RP2350: the hang above, on `lvgl-micropython` `3e287e7`, the code this moved from.

## Reproduce

Any firmware with the binding and no call to `mp_lv_deinit_gc()` at soft reset, no display
hardware needed. Run this twice with a soft reset (Ctrl-D) in between:

```python
import lvgl as lv
lv.init()
d = lv.display_create(320, 240)
d.set_color_format(lv.COLOR_FORMAT.RGB565)
b = bytearray(320 * 240 * 2)
d.set_buffers(b, None, len(b), lv.DISPLAY_RENDER_MODE.FULL)
d.set_flush_cb(lambda d, area, px: d.flush_ready())
lv.label(lv.screen_active()).set_text("soft reset test")
lv.tick_inc(50)
lv.refr_now(d)
print("OK")
```

Expected: `OK` twice. Actual on the ESP32-S3: `OK`, then on the second run

```text
Guru Meditation Error: Core  1 panic'ed (LoadProhibited). Exception was unhandled.
```

With `lv.deinit()` at the end of the first run, both print as expected.

## Cause

`mp_lv_init_gc()` trusts `MP_STATE_VM(mp_lv_roots_initialized)`, which survives the soft
reset together with the dangling `MP_STATE_VM(mp_lv_roots)`:

```c
void mp_lv_init_gc(void)
{
    if (!MP_STATE_VM(mp_lv_roots_initialized)) {
        MP_STATE_VM(mp_lv_roots) = m_new0(lv_global_t, 1);
        MP_STATE_VM(mp_lv_roots_initialized) = 1;
    }
}
```

`lvgl_mod_init()` then calls `lv_is_initialized()`, which reads `lv_global` through the
stale root, and skips `lv_init()`.

## Workaround we use (port/board side)

Drop the root at soft reset:

```c
void mp_lv_deinit_gc(void);   // exported by the binding
```

- **rp2, stm32**: the port has a board hook, `MICROPY_BOARD_END_SOFT_RESET`, that calls it.
- **esp32**: there is no such hook. The board's frozen `_boot.py` creates an object whose
  finaliser calls it, run by `gc_sweep_all()` in the soft-reset path; no change to
  MicroPython. See
  [`modules/esp_rgb/esp_rgb.c`](https://github.com/Copper-And-Code/mpy-lvgl-boards/blob/main/modules/esp_rgb/esp_rgb.c).

Verified: 3 soft resets out of 3 with LVGL left initialised on the ESP32-S3, the same on
an STM32H743, with `gc.mem_free()` identical each time.

This only drops the root; it does not call `lv_deinit()`, which could run Python
callbacks while the VM is shutting down. Everything LVGL allocated is GC memory that the
reset discards anyway. C statics outside `lv_global_t` (if any remain in LVGL with
`LV_ENABLE_GLOBAL_CUSTOM`) are not reset by this.

## Possible fixes in the binding (for discussion)

1. **Document** that ports/boards must call `mp_lv_deinit_gc()` on soft reset, with the
   hook above where a port has one (`MICROPY_BOARD_END_SOFT_RESET`), and the finaliser
   where it has none (esp32).
2. **Detect a new VM session** in `mp_lv_init_gc()` without relying on root pointers,
   e.g. keep a C static copy of the roots pointer next to a copy of something the soft
   reset changes; or check that `mp_lv_roots` is still the start of a live GC block of
   the right size (`gc_nbytes()`), accepting that this is a heuristic.
3. **Ask MicroPython** for a generic soft-reset callback for user C modules (similar to
   `MP_REGISTER_ROOT_POINTER`), so the binding can register its own cleanup. This would
   be the clean solution, and would also cover other modules that keep state across a
   soft reset.

Happy to test a fix on ESP32-S3, RP2350 and STM32H743 hardware.
