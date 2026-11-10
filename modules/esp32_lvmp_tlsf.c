// LVGL's allocator on ESP32 with the pools on LVGL's TLSF, instead of ESP-IDF's multi_heap
// (LVMP_POOLS=tlsf in the environment of scripts/build_esp32.sh, see esp32_usermods.cmake).
//
// lv_mem_core_micropython.c names its TLSF calls after multi_heap's, and takes multi_heap
// on ESP32. So: ESP-IDF's type under another name, which leaves the name free, and a file
// that does not know it is on ESP32.
#define multi_heap_handle_t idf_multi_heap_handle_t
#include "esp_heap_caps.h"
#undef multi_heap_handle_t
#undef ESP_PLATFORM

#include "ports/micropython/src/lv_mem_core_micropython.c"
