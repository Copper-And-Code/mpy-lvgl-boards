// Board and hardware specific configuration
#define MICROPY_HW_BOARD_NAME "Waveshare RP2350-Touch-LCD-4"

// UART0 on the header pins (GPIO46 TX, GPIO45 RX).
#define MICROPY_HW_UART0_TX     (46)
#define MICROPY_HW_UART0_RX     (45)
#define MICROPY_HW_UART0_CTS    (-1)
#define MICROPY_HW_UART0_RTS    (-1)

// UART1 on GPIO8 TX, GPIO9 RX.
#define MICROPY_HW_UART1_TX     (8)
#define MICROPY_HW_UART1_RX     (9)
#define MICROPY_HW_UART1_CTS    (-1)
#define MICROPY_HW_UART1_RTS    (-1)

// I2C1 (GT911 touch, PCF85063 RTC, QMI8658 IMU) is the default bus, on
// GPIO6 SDA / GPIO7 SCL: see PICO_DEFAULT_I2C in waveshare_rp2350_touch_lcd_4.h.

// RGB panel framebuffer scale (modules/rgbpanel): 2 = 240x240 framebuffer shown
// as 2x2 pixels (no PSRAM fitted), 1 = full 480x480 (needs the heap in PSRAM).
#ifndef MICROPY_HW_RGBPANEL_SCALE
#define MICROPY_HW_RGBPANEL_SCALE (2)
#endif
