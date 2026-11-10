# User C modules of the ESP32 boards. A file rather than a list: the ";" of a list
# does not survive make's shell. scripts/build_esp32.sh sets OMNIPYTHON_LVGL_DIR.
include($ENV{OMNIPYTHON_LVGL_DIR}/ports/micropython/micropython.cmake)
include(${CMAKE_CURRENT_LIST_DIR}/esp_rgb/micropython.cmake)

# LVGL's memory pools (omnipython-lvgl#10), chosen by LVMP_POOLS (scripts/build_esp32.sh).
# As the module ships they are compiled out on ESP32, twice over: lvmp_pool.h wants
# ESP_PLATFORM and MICROPY_MALLOC_USES_ALLOCATED_SIZE. The esp32 port leaves the second at
# 0, and builds the module's sources twice, in the main component with ESP-IDF's
# ESP_PLATFORM and for the micropython.elf target without it; the second copy is the one
# linked. The board's LVMP_POOL_TLSF (mpconfigboard.h) turns the pools on instead.
#   empty: ESP_PLATFORM for the module too, so the pools use ESP-IDF's multi_heap;
#   "tlsf": LVGL's TLSF, through esp32_lvmp_tlsf.c;
#   "none": no pools.
if("$ENV{LVMP_POOLS}" STREQUAL "tlsf")
    get_target_property(LVGL_SOURCES lvgl INTERFACE_SOURCES)
    list(FILTER LVGL_SOURCES EXCLUDE REGEX "/lv_mem_core_micropython\\.c$")
    list(APPEND LVGL_SOURCES ${CMAKE_CURRENT_LIST_DIR}/esp32_lvmp_tlsf.c)
    set_target_properties(lvgl PROPERTIES INTERFACE_SOURCES "${LVGL_SOURCES}")
    target_compile_definitions(lvgl INTERFACE LVMP_POOL_TLSF=1)
    target_include_directories(lvgl INTERFACE $ENV{OMNIPYTHON_LVGL_DIR})
elseif("$ENV{LVMP_POOLS}" STREQUAL "none")
    target_compile_definitions(lv_micropython INTERFACE LVMP_POOL_TLSF=0)
else()
    target_compile_definitions(lv_micropython INTERFACE ESP_PLATFORM=1)
endif()
