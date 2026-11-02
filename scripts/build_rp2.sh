#!/usr/bin/env bash
# Build MicroPython + LVGL firmware for an rp2 board of this repo.
#
#   scripts/build_rp2.sh [BOARD]        (default WAVESHARE_RP2350_TOUCH_LCD_4)
#
# Kept for compatibility: same as scripts/build.sh rp2 <BOARD>, which holds the
# pins and documents the environment variables.
exec "$(dirname "$0")/build.sh" rp2 "${1:-WAVESHARE_RP2350_TOUCH_LCD_4}"
