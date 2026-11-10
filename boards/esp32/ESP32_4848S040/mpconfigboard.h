#define MICROPY_HW_BOARD_NAME               "ESP32-4848S040"
#define MICROPY_HW_MCU_NAME                 "ESP32-S3"

// The REPL is on UART0, through the board's USB-UART (CH340).
#define MICROPY_HW_ENABLE_UART_REPL         (1)
// No native USB: its pads are GPIO 19 (touch SDA) and 20 (panel green bit 1), and the
// USB PHY holds them, so the I2C bus cannot pull SDA low.
#define MICROPY_HW_ENABLE_USBDEV            (0)
#define MICROPY_HW_ESP_USB_SERIAL_JTAG      (0)

// Panel (from https://homeding.github.io/boards/esp32s3/panel-4848S040.htm).
#define MICROPY_HW_RGB_HSYNC                (16)
#define MICROPY_HW_RGB_VSYNC                (17)
#define MICROPY_HW_RGB_DE                   (18)
#define MICROPY_HW_RGB_PCLK                 (21)
// Bit 0 to bit 15 of an RGB565 pixel: blue, green, red. Checked by eye: the published
// pin lists call 4, 5, 6, 7, 15 red and 11, 12, 13, 14, 0 blue, which swaps them here.
#define MICROPY_HW_RGB_DATA                 4, 5, 6, 7, 15, 8, 20, 3, 46, 9, 10, 11, 12, 13, 14, 0
#define MICROPY_HW_RGB_BL                   (38)
// ST7701 command bus (bit-banged, 9 bits).
#define MICROPY_HW_RGB_SPI_CS               (39)
#define MICROPY_HW_RGB_SPI_SCK              (48)
#define MICROPY_HW_RGB_SPI_MOSI             (47)

// LVGL's memory pools (modules/esp32_usermods.cmake). lvmp_pool.h takes them on ESP32 only
// with MICROPY_MALLOC_USES_ALLOCATED_SIZE, which the esp32 port leaves at 0; LVMP_POOL_TLSF
// turns them on anyway, and with ESP_PLATFORM they use ESP-IDF's multi_heap. Here, not in
// the cmake file, so that the scan for root pointers sees it too. LVMP_POOLS=none sets 0.
#ifndef LVMP_POOL_TLSF
#define LVMP_POOL_TLSF (1)
#endif
