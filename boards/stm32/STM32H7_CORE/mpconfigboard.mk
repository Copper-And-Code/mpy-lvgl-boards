# STM32H7_CORE, out-of-tree board: make -C ports/stm32 BOARD_DIR=<this directory>
# Hardware revision: BOARD_VARIANT=V10 or V13 (mpconfigvariant_*.mk), required.
USE_MBOOT ?= 0

# MCU settings
MCU_SERIES = h7
CMSIS_MCU = STM32H743xx
MICROPY_FLOAT_IMPL = double
# LVGL also needs a few float functions (sinf, ...): see this file.
include $(BOARD_DIR)/../lvgl_libm.mk
include $(BOARD_DIR)/../lvgl_pool.mk
AF_FILE = boards/stm32h743_af.csv

# GC_HEAP=axi: the GC heap in the AXI SRAM (about 450 KB) instead of the SDRAM, for
# measurements with a small heap; the framebuffers stay in the SDRAM.
ifeq ($(GC_HEAP),axi)
CFLAGS += -DMICROPY_HW_GC_HEAP_AXI=1
endif

ifeq ($(USE_MBOOT),1)
# When using Mboot everything goes after the bootloader
LD_FILES = $(BOARD_DIR)/stm32h743.ld boards/common_bl.ld
TEXT0_ADDR = 0x08020000
else
# When not using Mboot everything goes at the start of flash
LD_FILES = $(BOARD_DIR)/stm32h743.ld boards/common_basic.ld
TEXT0_ADDR = 0x08000000
endif

# MicroPython settings
MICROPY_VFS_LFS2 = 1

FROZEN_MANIFEST ?= $(BOARD_DIR)/manifest.py

# The C module and manifest of omnipython-lvgl (PyDevices), its ports/micropython,
# used as $(LVMP_DIR) in manifest.py. Default: $LVMP_DIR from the environment
# (scripts/build.sh sets it), else the workspace layout, with omnipython-lvgl beside
# mpy-lvgl-boards.
ifneq ($(LVMP_DIR),)
MICROPY_MANIFEST_LVMP_DIR ?= $(LVMP_DIR)
else
MICROPY_MANIFEST_LVMP_DIR ?= $(abspath $(BOARD_DIR)/../../../../omnipython-lvgl/ports/micropython)
endif
