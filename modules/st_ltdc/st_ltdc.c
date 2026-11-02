// st_ltdc: LTDC + DMA2D display driver for the STM32H743 boards of this repo.
//
// For now: the board's end-of-soft-reset hook. The display driver itself
// follows (phase 3 of the STM32 port, docs/stm32h743.md).

#include "py/runtime.h"
#include "boardctrl.h"

#if __has_include("lvgl/lvgl.h")
#define ST_LTDC_LVGL (1)
// From the lvgl-micropython binding: forgets LVGL's GC-allocated global state.
void mp_lv_deinit_gc(void);
#else
#define ST_LTDC_LVGL (0)
#endif

// MICROPY_BOARD_END_SOFT_RESET of the boards (see their mpconfigboard.h).
// The binding keeps LVGL's state in GC memory behind root pointers that a soft
// reset does not clear: without this, lv.init() after Ctrl-D reuses freed
// memory and hangs.
void st_ltdc_board_end_soft_reset(boardctrl_state_t *state) {
    #if ST_LTDC_LVGL
    mp_lv_deinit_gc();
    #endif
    boardctrl_end_soft_reset(state);
}
