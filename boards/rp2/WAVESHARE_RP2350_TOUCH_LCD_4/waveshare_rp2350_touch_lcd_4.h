// pico-sdk board header for the Waveshare RP2350-Touch-LCD-4.
// Pin assignment from the Waveshare schematic (RP2350-Touch-LCD-4.pdf).

// -----------------------------------------------------
// NOTE: THIS HEADER IS ALSO INCLUDED BY ASSEMBLER SO
//       SHOULD ONLY CONSIST OF PREPROCESSOR DIRECTIVES
// -----------------------------------------------------

// pico_cmake_set PICO_PLATFORM=rp2350

#ifndef _BOARDS_WAVESHARE_RP2350_TOUCH_LCD_4_H
#define _BOARDS_WAVESHARE_RP2350_TOUCH_LCD_4_H

#define WAVESHARE_RP2350_TOUCH_LCD_4

// --- RP2350 VARIANT ---
// RP2350B (QFN-80, 48 GPIOs)
#define PICO_RP2350A 0

// No user LED on this board. GPIO47 is the PSRAM chip-select (QSPI_SS2):
// do not use it for any default peripheral.

// --- UART ---
#ifndef PICO_DEFAULT_UART
#define PICO_DEFAULT_UART 0
#endif
#ifndef PICO_DEFAULT_UART_TX_PIN
#define PICO_DEFAULT_UART_TX_PIN 46
#endif
#ifndef PICO_DEFAULT_UART_RX_PIN
#define PICO_DEFAULT_UART_RX_PIN 45
#endif

// --- I2C ---
// Shared by GT911 touch, PCF85063 RTC and QMI8658 IMU.
#ifndef PICO_DEFAULT_I2C
#define PICO_DEFAULT_I2C 1
#endif
#ifndef PICO_DEFAULT_I2C_SDA_PIN
#define PICO_DEFAULT_I2C_SDA_PIN 6
#endif
#ifndef PICO_DEFAULT_I2C_SCL_PIN
#define PICO_DEFAULT_I2C_SCL_PIN 7
#endif

// --- SPI ---
// SPI0 on GPIO2/3/4 with CS on GPIO5 goes to the XL2515 CAN controller.
// GPIO2/3 are also the bit-banged init lines of the ST7701 panel (LCD_CS = GPIO18):
// keep LCD_CS high while using the CAN controller.
#ifndef PICO_DEFAULT_SPI
#define PICO_DEFAULT_SPI 0
#endif
#ifndef PICO_DEFAULT_SPI_SCK_PIN
#define PICO_DEFAULT_SPI_SCK_PIN 2
#endif
#ifndef PICO_DEFAULT_SPI_TX_PIN
#define PICO_DEFAULT_SPI_TX_PIN 3
#endif
#ifndef PICO_DEFAULT_SPI_RX_PIN
#define PICO_DEFAULT_SPI_RX_PIN 4
#endif
#ifndef PICO_DEFAULT_SPI_CSN_PIN
#define PICO_DEFAULT_SPI_CSN_PIN 5
#endif

// --- FLASH ---
// W25Q128JVSIQ, 16 MiB (U11)
#define PICO_BOOT_STAGE2_CHOOSE_W25Q080 1

#ifndef PICO_FLASH_SPI_CLKDIV
#define PICO_FLASH_SPI_CLKDIV 2
#endif

// pico_cmake_set_default PICO_FLASH_SIZE_BYTES = (16 * 1024 * 1024)
#ifndef PICO_FLASH_SIZE_BYTES
#define PICO_FLASH_SIZE_BYTES (16 * 1024 * 1024)
#endif

// pico_cmake_set_default PICO_RP2350_A2_SUPPORTED = 1
#ifndef PICO_RP2350_A2_SUPPORTED
#define PICO_RP2350_A2_SUPPORTED 1
#endif

#endif
