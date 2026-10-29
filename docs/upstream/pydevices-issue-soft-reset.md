<!--
Draft issue for PyDevices/lvgl-bindings (the root-pointer code is generated there:
binding/emit_c_micropython_style.py → mp_lv_init_gc / mp_lv_deinit_gc).
Not filed. Review, then file it yourself or tell Claude to.
-->

# `lv.init()` after a MicroPython soft reset hangs if `lv.deinit()` was not called

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

On an RP2350 board this hangs the firmware at the first LVGL call after the reset:
USB stays enumerated, the REPL is dead, and neither `picotool reboot -f` nor the
1200-baud touch recovers it; only a power cycle does.

Most real programs never call `lv.deinit()` (an LVGL app typically runs until reset), and
tools such as `mpremote run` / `mpremote exec` soft-reset the board before every command,
so this is easy to hit during development.

## Versions

- MicroPython v1.29.0, `ports/rp2`, RP2350B (Waveshare RP2350-Touch-LCD-4, out-of-tree board)
- PyDevices/lvgl-micropython `3e287e7`
- PyDevices/lvgl-bindings `7740c2f` (`LVGL_BINDINGS_COMMIT`), LVGL 9.5
- Toolchain: xPack arm-none-eabi-gcc 15.2.1-1.1
- Also checked: no change in this area on lvgl-bindings `origin/main` as of 2026-10-29.

## Reproduce

Any rp2 firmware with the binding, no display hardware needed:

```bash
mpremote exec "
import lvgl as lv
lv.init()
d = lv.display_create(64, 64)
b = bytearray(64 * 64 * 2)
d.set_buffers(b, None, len(b), lv.DISPLAY_RENDER_MODE.FULL)
d.set_flush_cb(lambda d, a, p: d.flush_ready())
lv.label(lv.screen_active()).set_text('before')
lv.refr_now(d)
print('ok1')
"
# no lv.deinit(): soft reset, then use LVGL again
mpremote soft-reset exec "
import lvgl as lv
lv.init()
d = lv.display_create(64, 64)
b = bytearray(64 * 64 * 2)
d.set_buffers(b, None, len(b), lv.DISPLAY_RENDER_MODE.FULL)
d.set_flush_cb(lambda d, a, p: d.flush_ready())
for i in range(50):
    lv.label(lv.screen_active()).set_text('after %d' % i)
lv.refr_now(d)
print('ok2')
"
```

Expected: `ok1`, then `ok2`.
Actual: `ok1`, then the second command never returns and the board must be power-cycled.

With `lv.deinit()` at the end of the first command, both print as expected.

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

The rp2 port has a board hook that runs before the heap is swept. In the board's
`mpconfigboard.h`:

```c
void board_end_soft_reset(void);
#define MICROPY_BOARD_END_SOFT_RESET() board_end_soft_reset()
```

and in a C file of the firmware:

```c
void mp_lv_deinit_gc(void);   // exported by the binding

void board_end_soft_reset(void) {
    mp_lv_deinit_gc();         // forget LVGL's GC-allocated state
}
```

Verified on the board: three consecutive soft resets with LVGL live (display, 50 labels,
`lv.refr_now()`), `lv.init()` starts clean every time and `gc.mem_free()` is identical
after each reset (no leak).

This only drops the root; it does not call `lv_deinit()`, which could run Python
callbacks while the VM is shutting down. Everything LVGL allocated is GC memory that the
reset discards anyway. C statics outside `lv_global_t` (if any remain in LVGL with
`LV_ENABLE_GLOBAL_CUSTOM`) are not reset by this.

## Possible fixes in the binding (for discussion)

1. **Document** that ports/boards must call `mp_lv_deinit_gc()` on soft reset, with the
   hook above for rp2 (`MICROPY_BOARD_END_SOFT_RESET`) and the equivalent places for
   other ports (esp32 `main.c` soft-reset path, unix has no soft reset).
2. **Detect a new VM session** in `mp_lv_init_gc()` without relying on root pointers,
   e.g. keep a C static copy of the roots pointer next to a copy of something the soft
   reset changes; or check that `mp_lv_roots` is still the start of a live GC block of
   the right size (`gc_nbytes()`), accepting that this is a heuristic.
3. **Ask MicroPython** for a generic soft-reset callback for user C modules (similar to
   `MP_REGISTER_ROOT_POINTER`), so the binding can register its own cleanup. This would
   be the clean solution, and would also cover other modules that keep state across a
   soft reset.

Happy to test a fix on RP2350 hardware.
