# ESP32-4848S040: ESP32-S3, 16 MB flash, 8 MB octal PSRAM, 4" 480x480 RGB panel.
include(boards/mpconfigboard_esp32s3_common.cmake)

# The partition table lives here, outside the port: sdkconfig needs its full path,
# which only CMake knows.
file(WRITE ${CMAKE_BINARY_DIR}/sdkconfig.partitions
    "CONFIG_PARTITION_TABLE_CUSTOM_FILENAME=\"${MICROPY_BOARD_DIR}/partitions-16MiB.csv\"\n")

list(APPEND SDKCONFIG_DEFAULTS
    boards/sdkconfig.240mhz
    boards/sdkconfig.flash_qio_80m
    boards/sdkconfig.spiram_oct
    ${MICROPY_BOARD_DIR}/sdkconfig.board
    ${CMAKE_BINARY_DIR}/sdkconfig.partitions
)

list(APPEND IDF_COMPONENTS esp_lcd)

set(MICROPY_FROZEN_MANIFEST ${MICROPY_BOARD_DIR}/manifest.py)
