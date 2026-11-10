// machine.bootloader() on the STM32H743 boards: USB DFU in the ROM bootloader.
//
// The port jumps to the vector table at 0x1ff00000 on every H7, but on the STM32H743
// (rev V, DBGMCU IDCODE 0x20036450) that address reads as zeros: the jump loads SP = 0
// and PC = 0, faults, and the board resets into MicroPython. The ROM bootloader's vector
// table is at 0x1ff09800 (AN2606). The port's own reset path cannot reach it either: it
// keeps a key in the low 12 bits of the address, so it takes only 4 KB aligned ones.
//
// So: store a key in _bl_state (the 8 bytes above the stack, kept across a reset),
// reset, and jump from MICROPY_BOARD_STARTUP, before the clocks, the caches, the SDRAM
// and the LTDC are set up. Used through h743_bootloader.h and h743_bootloader.mk.
#include <stdint.h>

#include "py/mpconfig.h"
#include STM32_HAL_H

#include "powerctrl.h"

#define H743_BL_VECTORS (0x1ff09800)
#define H743_BL_KEY     (0x4446552d48373433ULL) // "DFU-H743"

extern uint64_t _bl_state[];

MP_NORETURN static __attribute__((naked)) void h743_branch(uint32_t vectors) {
    __asm volatile (
        "ldr r1, [r0, #0]\n"    // initial stack pointer
        "msr msp, r1\n"
        "ldr r1, [r0, #4]\n"    // reset handler
        "bx r1\n"
        );
}

MP_NORETURN void h743_enter_bootloader(void) {
    // 64-bit write: the AXI SRAM has ECC, a smaller write may not reach it before the reset.
    _bl_state[0] = H743_BL_KEY;
    SCB_CleanDCache();
    NVIC_SystemReset();
    for (;;) {
    }
}

void h743_board_startup(void) {
    uint64_t state = _bl_state[0];
    _bl_state[0] = 0;
    if (state == H743_BL_KEY && (RCC->RSR & RCC_RSR_SFTRSTF)) {
        RCC->RSR = RCC_RSR_RMVF;
        h743_branch(H743_BL_VECTORS);
    }
}
