# CMake file for Waveshare RP2350-Touch-LCD-4 (out-of-tree board)
# Build with: make -C ports/rp2 BOARD_DIR=<this directory>

# RP2350B, 48 GPIOs (the RGB panel uses GPIO18-40)
set(PICO_NUM_GPIOS 48)

# No official pico-sdk support: use the header in this directory.
list(APPEND PICO_BOARD_HEADER_DIRS ${MICROPY_BOARD_DIR})
set(PICO_BOARD "waveshare_rp2350_touch_lcd_4")

set(PICO_FLASH_SIZE_BYTES 16777216)

# Leave 4 MiB to the firmware: LVGL is large.
if(NOT DEFINED MICROPY_HW_FLASH_STORAGE_BYTES)
    set(MICROPY_HW_FLASH_STORAGE_BYTES 12582912)  # 12 * 1024 * 1024
endif()

# Optional PSRAM footprint U9 (marked NC on the schematic), CS = QSPI_SS2 = GPIO47.
# Size is auto-detected: with no chip fitted psram_get_size() is 0 and the
# firmware runs with the SRAM heap only.
set(MICROPY_HW_ENABLE_PSRAM 1)
set(MICROPY_HW_PSRAM_CS_PIN 47)

set(MICROPY_FROZEN_MANIFEST ${MICROPY_BOARD_DIR}/manifest.py)

# lvgl-micropython (PyDevices) checkout, used as $(LVMP_DIR) in manifest.py.
# Default: the workspace layout, with lvgl-micropython beside mpy-lvgl-boards.
# Its lvgl-bindings is found by lvgl-micropython itself (BINDINGS_DIR or beside it).
if(NOT DEFINED MICROPY_MANIFEST_LVMP_DIR)
    if(DEFINED ENV{LVMP_DIR})
        set(MICROPY_MANIFEST_LVMP_DIR $ENV{LVMP_DIR})
    else()
        get_filename_component(MICROPY_MANIFEST_LVMP_DIR ${MICROPY_BOARD_DIR}/../../../../lvgl-micropython ABSOLUTE)
    endif()
endif()
