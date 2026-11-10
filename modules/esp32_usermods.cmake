# User C modules of the ESP32 boards. A file rather than a list: the ";" of a list
# does not survive make's shell. scripts/build_esp32.sh sets OMNIPYTHON_LVGL_DIR.
include($ENV{OMNIPYTHON_LVGL_DIR}/ports/micropython/micropython.cmake)
include(${CMAKE_CURRENT_LIST_DIR}/esp_rgb/micropython.cmake)

# LVGL's memory pools (omnipython-lvgl#10, #15): on with the board's LVMP_POOL_TLSF
# (mpconfigboard.h, where the scan for root pointers sees it too). LVMP_POOLS=none
# (scripts/build_esp32.sh) turns them off in the compiled code, for comparisons; the root
# pointer stays registered, unused.
if("$ENV{LVMP_POOLS}" STREQUAL "none")
    target_compile_definitions(lv_micropython INTERFACE LVMP_POOL_TLSF=0)
endif()
