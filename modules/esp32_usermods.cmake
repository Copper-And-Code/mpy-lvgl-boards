# User C modules of the ESP32 boards. A file rather than a list: the ";" of a list
# does not survive make's shell. scripts/build_esp32.sh sets OMNIPYTHON_LVGL_DIR.
include($ENV{OMNIPYTHON_LVGL_DIR}/ports/micropython/micropython.cmake)
include(${CMAKE_CURRENT_LIST_DIR}/esp_rgb/micropython.cmake)
