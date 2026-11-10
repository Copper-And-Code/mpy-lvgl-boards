# LVGL's allocations from TLSF pools kept in GC blocks instead of one gc_alloc()
# each (patches/lvgl-micropython/0001-lvmp-pools-on-lvgl-tlsf.patch): with the
# 28 MB GC heap in SDRAM, gc_alloc() walks the allocation table from the first
# free block, and one large live object behind it made every LVGL refresh up to
# 10x slower (docs/stm32h743.md, phase 5). Included by the boards' mpconfigboard.mk.
# LVMP_POOLS=none (scripts/build.sh) builds without them, one gc_alloc() each, for comparisons.
ifneq ($(LVMP_POOLS),none)
CFLAGS += -DLVMP_POOL_TLSF=1
endif
