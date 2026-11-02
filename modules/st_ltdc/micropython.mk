# st_ltdc: LTDC + DMA2D display driver for the STM32H743 boards of this repo.
ST_LTDC_MOD_DIR := $(USERMOD_DIR)

SRC_USERMOD_C += $(ST_LTDC_MOD_DIR)/st_ltdc.c
CFLAGS_USERMOD += -I$(ST_LTDC_MOD_DIR)
