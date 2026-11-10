// machine.bootloader() on the STM32H743 boards reaches USB DFU: see h743_bootloader.c.
// Included by the boards' mpconfigboard.h, with h743_bootloader.mk in mpconfigboard.mk.
#ifndef __ASSEMBLER__
void h743_enter_bootloader(void) __attribute__((noreturn));
void h743_board_startup(void);
#endif
#define MICROPY_BOARD_ENTER_BOOTLOADER(nargs, args) h743_enter_bootloader()
#define MICROPY_BOARD_STARTUP h743_board_startup
