# esp_rgb: RGB parallel panel on the ESP32-S3 LCD peripheral (ESP-IDF esp_lcd).
# The board asks for the component (IDF_COMPONENTS). User C modules are also built
# for the micropython.elf target, which does not see the component's include
# directories, and linking to idf::esp_lcd here would add all of ESP-IDF to the
# usermods: they are named by hand.
add_library(usermod_esp_rgb INTERFACE)
target_sources(usermod_esp_rgb INTERFACE ${CMAKE_CURRENT_LIST_DIR}/esp_rgb.c)
target_include_directories(usermod_esp_rgb INTERFACE
    ${CMAKE_CURRENT_LIST_DIR}
    $ENV{IDF_PATH}/components/esp_lcd/include
    $ENV{IDF_PATH}/components/esp_lcd/interface
    $ENV{IDF_PATH}/components/esp_lcd/rgb/include
)
target_link_libraries(usermod INTERFACE usermod_esp_rgb)
