# rgbpanel: RGB parallel panel scan-out (PIO + DMA) for RP2350 boards.
add_library(usermod_rgbpanel INTERFACE)

target_sources(usermod_rgbpanel INTERFACE
    ${CMAKE_CURRENT_LIST_DIR}/rgbpanel.c
)

target_include_directories(usermod_rgbpanel INTERFACE
    ${CMAKE_CURRENT_LIST_DIR}
)

pico_generate_pio_header(usermod_rgbpanel ${CMAKE_CURRENT_LIST_DIR}/rgbpanel.pio)

target_link_libraries(usermod INTERFACE usermod_rgbpanel)
