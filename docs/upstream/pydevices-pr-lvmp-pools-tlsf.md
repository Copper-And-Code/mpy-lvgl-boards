<!-- Draft for PyDevices/lvgl-micropython, not sent. The change is
     patches/lvgl-micropython/0001-lvmp-pools-on-lvgl-tlsf.patch of this repo. -->

# LVGL memory pools on ports without multi_heap (LVGL's own TLSF)

The ESP32 already gets LVGL's allocations from TLSF pools kept in GC blocks
(`lv_mem_core_micropython.c`, `LVMP_POOL`), because `gc_alloc()` walks the allocation
table from the first free block. Other ports with a large GC heap have the same problem.

## What we measured

STM32H743, MicroPython 1.29.0, 28 MB GC heap in a 16-bit SDRAM, LVGL 9.5, a 1024x600
display with 48 themed buttons, full refresh with `lv.refr_now()`:

| GC heap state | 8 KB `bytearray` | full refresh |
|---|---|---|
| fresh | 181 us | 54 ms |
| 2 MB of bytearrays alive behind a free block | 611 us | **575 ms** |
| 30 000 small objects alive | 82 us | 53 ms |
| the same objects freed | 609 us | **574 ms** |

A refresh makes about 1200 LVGL allocations; a multi-block `gc_alloc()` does not move
`gc_last_free_atb_index`, so each one walks past every live block after the first hole.

## The change

- `src/lvmp_pool.h`: the `LVMP_POOL` switch and pool sizes, shared by three files.
  `LVMP_POOL` is now also on when the build defines `LVMP_POOL_TLSF=1`.
- `src/lv_mem_core_micropython.c`: on ESP32 unchanged (multi_heap); otherwise the same
  calls mapped to `lv_tlsf_*` (`multi_heap_register` -> `lv_tlsf_create_with_pool`,
  `multi_heap_get_allocated_size` -> `lv_tlsf_block_size`, ...).
- `src/lvmp_tlsf.c` (new, in `SOURCES` of both `micropython.mk` and `.cmake`): LVGL
  compiles `lv_tlsf.c` only with `LV_STDLIB_BUILTIN`, so this file includes it in a
  translation unit of its own with that setting, and `LV_MEM_SIZE` = one pool. Nothing in
  LVGL or `lv_conf.h` changes.
- The root pointer `lvmp_pool_mem` moved to `src/lvgl_micropython_build.c`: make builds
  put the LVGL sources and `lv_mem_core_micropython.c` in `SRC_USERMOD_LIB_C`, which is
  not scanned for `MP_REGISTER_ROOT_POINTER` (the build failed with "mp_state_vm_t has no
  member named lvmp_pool_mem"). CMake builds scanned it there before; now they find it
  in `lvgl_micropython_build.c` instead, still once.

Off by default outside ESP32: a board turns it on with `CFLAGS += -DLVMP_POOL_TLSF=1`.

## Results with the change

Full refresh 50-51 ms in all four heap states above. On the display driver: DIRECT
2 buffers 273 -> 56-66 ms, PARTIAL 200 lines 243 -> 78 ms. 300 event callbacks that
only LVGL refers to survive garbage, collections, `lv.deinit()`/`lv.init()` and soft
resets; `gc.mem_free()` is back to its starting value after `lv.deinit()`.
Not tested on an ESP32 build (only the moved root pointer touches that path).
