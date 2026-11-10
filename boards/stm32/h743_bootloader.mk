# machine.bootloader() on the STM32H743 boards: see h743_bootloader.c.
# Included by the boards' mpconfigboard.mk.
SRC_C += $(abspath $(BOARD_DIR)/../h743_bootloader.c)
