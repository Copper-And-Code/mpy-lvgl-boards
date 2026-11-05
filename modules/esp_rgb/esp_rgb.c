// esp_rgb: RGB parallel panel on the ESP32-S3 LCD peripheral, through ESP-IDF's
// esp_lcd. Same interface as st_ltdc (STM32) and rgbpanel (RP2350):
//
//   import esp_rgb, panels
//   esp_rgb.init(**panels.get("ST7701_4848S040"))
//   fb = esp_rgb.framebuffer(1)      # memoryview 'H', width * height
//   esp_rgb.swap()                   # shown at the next frame
//
// Pins are data in the board's mpconfigboard.h (MICROPY_HW_RGB_*). The framebuffers
// are in PSRAM, allocated by esp_lcd outside the GC heap: they stay valid across a
// soft reset, so the image stays too. The panel is fed through two bounce buffers
// in internal RAM, copied by the CPU in an interrupt, because the LCD DMA reading
// PSRAM directly loses pixels whenever anything else uses that memory.
//
// esp_lcd does not report FIFO underruns: underruns() and info() have none to give.
//
// LVGL (when the firmware has the binding): lv_display_create() renders in DIRECT
// mode into the framebuffers, lv_tick_install() gives LVGL the millisecond tick.
// This port has no board hook at the end of a soft reset, where the other drivers
// forget LVGL's state (a later lv.init() crashes otherwise): the board's _boot.py calls
// lvgl_guard(), which leaves an object in the heap whose finaliser does it, run by
// gc_sweep_all().

#include <string.h>

#include "py/mphal.h"
#include "py/obj.h"
#include "py/objarray.h"
#include "py/runtime.h"

#include "driver/gpio.h"
#include "esp_err.h"
#include "esp_lcd_panel_ops.h"
#include "esp_lcd_panel_rgb.h"
#include "esp_rom_sys.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/idf_additions.h"

#include "st7701_init.h"

#if __has_include("lvgl/lvgl.h")
#define ESP_RGB_LVGL (1)
#include "lvgl/lvgl.h"
// From the LVGL binding: forgets LVGL's GC-allocated global state.
void mp_lv_deinit_gc(void);
#else
#define ESP_RGB_LVGL (0)
#endif

#define POL_HS (1)  // HSYNC active high
#define POL_VS (2)  // VSYNC active high
#define POL_DE (4)  // DE active high
#define POL_PC (8)  // data clocked on the falling edge

#define BOUNCE_LINES (20)

static struct {
    esp_lcd_panel_handle_t panel;
    int width, height, buffers, shown, backlight;
    uint32_t pclk_hz, htotal, vtotal;
    void *fb[2];
    volatile uint32_t frames;
} st;

static bool IRAM_ATTR on_frame(esp_lcd_panel_handle_t panel, const esp_lcd_rgb_panel_event_data_t *edata, void *arg) {
    st.frames++;
    return false;
}

// --- ST7701: 9-bit SPI, written bit by bit, only before the panel starts ---

static void st7701_bit(int level) {
    gpio_set_level(MICROPY_HW_RGB_SPI_SCK, 0);
    gpio_set_level(MICROPY_HW_RGB_SPI_MOSI, level);
    esp_rom_delay_us(1);
    gpio_set_level(MICROPY_HW_RGB_SPI_SCK, 1);
    esp_rom_delay_us(1);
}

static void st7701_byte(int is_data, uint8_t b) {
    st7701_bit(is_data);
    for (int i = 7; i >= 0; i--) {
        st7701_bit((b >> i) & 1);
    }
}

static void st7701_send(void) {
    static const int pins[] = { MICROPY_HW_RGB_SPI_CS, MICROPY_HW_RGB_SPI_SCK, MICROPY_HW_RGB_SPI_MOSI };
    for (int i = 0; i < 3; i++) {
        gpio_reset_pin(pins[i]);
        gpio_set_direction(pins[i], GPIO_MODE_OUTPUT);
        gpio_set_level(pins[i], 1);
    }
    const uint8_t *p = st7701_init;
    for (;;) {
        uint8_t cmd = *p++, n = *p++;
        if (n == ST7701_DELAY) {
            mp_hal_delay_ms(*p++);
            continue;
        }
        if (cmd == 0) {
            break;
        }
        gpio_set_level(MICROPY_HW_RGB_SPI_CS, 0);
        st7701_byte(0, cmd);
        while (n--) {
            st7701_byte(1, *p++);
        }
        gpio_set_level(MICROPY_HW_RGB_SPI_CS, 1);
    }
}

// --- module ---

static void check(esp_err_t err) {
    if (err != ESP_OK) {
        mp_raise_msg_varg(&mp_type_OSError, MP_ERROR_TEXT("esp_lcd: %s"), esp_err_to_name(err));
    }
}

static void set_backlight(int percent) {
    st.backlight = percent;
    gpio_set_level(MICROPY_HW_RGB_BL, percent > 0);
}

static void panel_stop(void) {
    if (st.panel != NULL) {
        esp_lcd_panel_del(st.panel);
        st.panel = NULL;
    }
}

typedef struct {
    const esp_lcd_rgb_panel_config_t *cfg;
    TaskHandle_t caller;
    esp_lcd_panel_handle_t panel;
    esp_err_t err;
} panel_start_args_t;

static void panel_start_task(void *arg) {
    panel_start_args_t *a = arg;
    esp_lcd_rgb_panel_event_callbacks_t cbs = { .on_vsync = on_frame };
    a->err = esp_lcd_new_rgb_panel(a->cfg, &a->panel);
    if (a->err == ESP_OK) {
        a->err = esp_lcd_rgb_panel_register_event_callbacks(a->panel, &cbs, NULL);
    }
    if (a->err == ESP_OK) {
        a->err = esp_lcd_panel_reset(a->panel);
    }
    if (a->err == ESP_OK) {
        a->err = esp_lcd_panel_init(a->panel);
    }
    xTaskNotifyGive(a->caller);
    vTaskDelete(NULL);
}

static mp_obj_t esp_rgb_init(size_t n_args, const mp_obj_t *pos_args, mp_map_t *kw_args) {
    enum { ARG_width, ARG_height, ARG_hsync, ARG_hbp, ARG_hfp, ARG_vsync, ARG_vbp, ARG_vfp,
           ARG_polarity, ARG_pclk_hz, ARG_buffers, ARG_backlight };
    static const mp_arg_t allowed[] = {
        { MP_QSTR_width, MP_ARG_REQUIRED | MP_ARG_INT, {.u_int = 0} },
        { MP_QSTR_height, MP_ARG_REQUIRED | MP_ARG_INT, {.u_int = 0} },
        { MP_QSTR_hsync, MP_ARG_REQUIRED | MP_ARG_INT, {.u_int = 0} },
        { MP_QSTR_hbp, MP_ARG_REQUIRED | MP_ARG_INT, {.u_int = 0} },
        { MP_QSTR_hfp, MP_ARG_REQUIRED | MP_ARG_INT, {.u_int = 0} },
        { MP_QSTR_vsync, MP_ARG_REQUIRED | MP_ARG_INT, {.u_int = 0} },
        { MP_QSTR_vbp, MP_ARG_REQUIRED | MP_ARG_INT, {.u_int = 0} },
        { MP_QSTR_vfp, MP_ARG_REQUIRED | MP_ARG_INT, {.u_int = 0} },
        { MP_QSTR_polarity, MP_ARG_KW_ONLY | MP_ARG_INT, {.u_int = POL_DE | POL_PC} },
        { MP_QSTR_pclk_hz, MP_ARG_KW_ONLY | MP_ARG_INT, {.u_int = 12000000} },
        { MP_QSTR_buffers, MP_ARG_KW_ONLY | MP_ARG_INT, {.u_int = 2} },
        { MP_QSTR_backlight, MP_ARG_KW_ONLY | MP_ARG_INT, {.u_int = 100} },
    };
    mp_arg_val_t a[MP_ARRAY_SIZE(allowed)];
    mp_arg_parse_all(n_args, pos_args, kw_args, MP_ARRAY_SIZE(allowed), allowed, a);

    int buffers = a[ARG_buffers].u_int, width = a[ARG_width].u_int, height = a[ARG_height].u_int;
    if (buffers < 1 || buffers > 2) {
        mp_raise_ValueError(MP_ERROR_TEXT("buffers must be 1 or 2"));
    }
    // Already running with these settings: the image stays, as after a soft reset.
    if (st.panel != NULL) {
        if (st.width == width && st.height == height && st.buffers == buffers
            && st.pclk_hz == (uint32_t)a[ARG_pclk_hz].u_int) {
            set_backlight(a[ARG_backlight].u_int);
            return mp_const_none;
        }
        panel_stop();
    }

    gpio_reset_pin(MICROPY_HW_RGB_BL);
    gpio_set_direction(MICROPY_HW_RGB_BL, GPIO_MODE_OUTPUT);
    gpio_set_level(MICROPY_HW_RGB_BL, 0);
    st7701_send();

    int pol = a[ARG_polarity].u_int;
    esp_lcd_rgb_panel_config_t cfg = {
        .clk_src = LCD_CLK_SRC_DEFAULT,
        .timings = {
            .pclk_hz = a[ARG_pclk_hz].u_int,
            .h_res = width,
            .v_res = height,
            .hsync_pulse_width = a[ARG_hsync].u_int,
            .hsync_back_porch = a[ARG_hbp].u_int,
            .hsync_front_porch = a[ARG_hfp].u_int,
            .vsync_pulse_width = a[ARG_vsync].u_int,
            .vsync_back_porch = a[ARG_vbp].u_int,
            .vsync_front_porch = a[ARG_vfp].u_int,
            .flags = {
                .hsync_idle_low = (pol & POL_HS) != 0,
                .vsync_idle_low = (pol & POL_VS) != 0,
                .de_idle_high = (pol & POL_DE) == 0,
                .pclk_active_neg = (pol & POL_PC) != 0,
            },
        },
        .data_width = 16,
        .bits_per_pixel = 16,
        .num_fbs = buffers,
        .bounce_buffer_size_px = BOUNCE_LINES * width,
        .dma_burst_size = 64,
        .hsync_gpio_num = MICROPY_HW_RGB_HSYNC,
        .vsync_gpio_num = MICROPY_HW_RGB_VSYNC,
        .de_gpio_num = MICROPY_HW_RGB_DE,
        .pclk_gpio_num = MICROPY_HW_RGB_PCLK,
        .disp_gpio_num = -1,
        .data_gpio_nums = { MICROPY_HW_RGB_DATA },
        .flags = { .fb_in_psram = 1 },
    };
    // The panel's interrupt stays on the core that creates it, and it copies 24 MB/s
    // into the bounce buffers: keep it away from the core that runs MicroPython.
    panel_start_args_t start = { .cfg = &cfg, .caller = xTaskGetCurrentTaskHandle() };
    if (xTaskCreatePinnedToCore(panel_start_task, "esp_rgb", 4096, &start, configMAX_PRIORITIES - 2, NULL,
        MP_TASK_COREID == 0 ? 1 : 0) != pdPASS) {
        check(ESP_ERR_NO_MEM);
    }
    ulTaskNotifyTake(pdTRUE, portMAX_DELAY);
    check(start.err);
    esp_lcd_panel_handle_t panel = start.panel;
    if (buffers == 2) {
        check(esp_lcd_rgb_panel_get_frame_buffer(panel, 2, &st.fb[0], &st.fb[1]));
    } else {
        check(esp_lcd_rgb_panel_get_frame_buffer(panel, 1, &st.fb[0]));
        st.fb[1] = NULL;
    }
    st.panel = panel;
    st.width = width;
    st.height = height;
    st.buffers = buffers;
    st.shown = 0;
    st.pclk_hz = a[ARG_pclk_hz].u_int;
    st.htotal = width + cfg.timings.hsync_pulse_width + cfg.timings.hsync_back_porch + cfg.timings.hsync_front_porch;
    st.vtotal = height + cfg.timings.vsync_pulse_width + cfg.timings.vsync_back_porch + cfg.timings.vsync_front_porch;
    set_backlight(a[ARG_backlight].u_int);
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_KW(esp_rgb_init_obj, 0, esp_rgb_init);

static void check_running(void) {
    if (st.panel == NULL) {
        mp_raise_msg(&mp_type_RuntimeError, MP_ERROR_TEXT("panel not started"));
    }
}

static mp_obj_t esp_rgb_deinit(void) {
    panel_stop();
    set_backlight(0);
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_0(esp_rgb_deinit_obj, esp_rgb_deinit);

static mp_obj_t esp_rgb_framebuffer(size_t n_args, const mp_obj_t *args) {
    check_running();
    mp_int_t i = n_args > 0 ? mp_obj_get_int(args[0]) : 0;
    if (i < 0 || i >= st.buffers) {
        mp_raise_ValueError(MP_ERROR_TEXT("no such framebuffer"));
    }
    return mp_obj_new_memoryview('H' | MP_OBJ_ARRAY_TYPECODE_FLAG_RW, st.width * st.height, st.fb[i]);
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(esp_rgb_framebuffer_obj, 0, 1, esp_rgb_framebuffer);

static mp_obj_t esp_rgb_shown(void) {
    return MP_OBJ_NEW_SMALL_INT(st.shown);
}
static MP_DEFINE_CONST_FUN_OBJ_0(esp_rgb_shown_obj, esp_rgb_shown);

// Wait for the next frame. False on a timeout.
static bool wait_frame(int timeout_ms) {
    uint32_t f = st.frames, t0 = mp_hal_ticks_ms();
    while (st.frames == f) {
        if ((int)(mp_hal_ticks_ms() - t0) >= timeout_ms) {
            return false;
        }
        mp_hal_delay_ms(1);
    }
    return true;
}

static mp_obj_t esp_rgb_wait_vsync(size_t n_args, const mp_obj_t *args) {
    check_running();
    return mp_obj_new_bool(wait_frame(n_args > 0 ? mp_obj_get_int(args[0]) : 100));
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(esp_rgb_wait_vsync_obj, 0, 1, esp_rgb_wait_vsync);

static void show_buffer(int i) {
    // The address of one of its own framebuffers: esp_lcd only switches to it.
    check(esp_lcd_panel_draw_bitmap(st.panel, 0, 0, st.width, st.height, st.fb[i]));
    st.shown = i;
}

static mp_obj_t esp_rgb_swap(size_t n_args, const mp_obj_t *args) {
    check_running();
    if (st.buffers != 2) {
        mp_raise_msg(&mp_type_RuntimeError, MP_ERROR_TEXT("one framebuffer only"));
    }
    show_buffer(1 - st.shown);
    return mp_obj_new_bool(wait_frame(n_args > 0 ? mp_obj_get_int(args[0]) : 100));
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(esp_rgb_swap_obj, 0, 1, esp_rgb_swap);

static mp_obj_t esp_rgb_backlight(size_t n_args, const mp_obj_t *args) {
    if (n_args > 0) {
        set_backlight(mp_obj_get_int(args[0]));
    }
    return MP_OBJ_NEW_SMALL_INT(st.backlight);
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(esp_rgb_backlight_obj, 0, 1, esp_rgb_backlight);

static mp_obj_t esp_rgb_frame_count(void) {
    return mp_obj_new_int_from_uint(st.frames);
}
static MP_DEFINE_CONST_FUN_OBJ_0(esp_rgb_frame_count_obj, esp_rgb_frame_count);

static void dict_store(mp_obj_t d, qstr k, mp_obj_t v) {
    mp_obj_dict_store(d, MP_OBJ_NEW_QSTR(k), v);
}

static mp_obj_t esp_rgb_info(void) {
    mp_obj_t d = mp_obj_new_dict(0);
    dict_store(d, MP_QSTR_running, mp_obj_new_bool(st.panel != NULL));
    dict_store(d, MP_QSTR_width, MP_OBJ_NEW_SMALL_INT(st.width));
    dict_store(d, MP_QSTR_height, MP_OBJ_NEW_SMALL_INT(st.height));
    dict_store(d, MP_QSTR_buffers, MP_OBJ_NEW_SMALL_INT(st.buffers));
    dict_store(d, MP_QSTR_shown, MP_OBJ_NEW_SMALL_INT(st.shown));
    dict_store(d, MP_QSTR_frames, mp_obj_new_int_from_uint(st.frames));
    dict_store(d, MP_QSTR_pclk, mp_obj_new_int_from_uint(st.pclk_hz));
    dict_store(d, MP_QSTR_backlight, MP_OBJ_NEW_SMALL_INT(st.backlight));
    dict_store(d, MP_QSTR_fb_addr, mp_obj_new_int_from_uint((uint32_t)st.fb[0]));
    if (st.htotal != 0) {
        dict_store(d, MP_QSTR_fps_nominal, mp_obj_new_float((mp_float_t)st.pclk_hz / (st.htotal * st.vtotal)));
    }
    return d;
}
static MP_DEFINE_CONST_FUN_OBJ_0(esp_rgb_info_obj, esp_rgb_info);

#if ESP_RGB_LVGL

static uint32_t lv_tick_ms(void) {
    return mp_hal_ticks_ms();
}

static mp_obj_t esp_rgb_lv_tick_install(void) {
    lv_tick_set_cb(lv_tick_ms);
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_0(esp_rgb_lv_tick_install_obj, esp_rgb_lv_tick_install);

static uint32_t flush_frame;

// The new buffer is asked for here, and taken by the panel at the next frame. LVGL
// waits for that only when it next needs the other buffer, in lv_flush_wait_cb.
static void lv_flush_cb(lv_display_t *disp, const lv_area_t *area, uint8_t *px_map) {
    if (st.buffers == 2 && lv_display_flush_is_last(disp)) {
        flush_frame = st.frames;
        show_buffer(px_map == st.fb[1]);
        return;
    }
    lv_display_flush_ready(disp);
}

static void lv_flush_wait_cb(lv_display_t *disp) {
    uint32_t t0 = mp_hal_ticks_ms();
    while (st.frames == flush_frame && mp_hal_ticks_ms() - t0 < 100) {
        esp_rom_delay_us(100);
    }
    lv_display_flush_ready(disp);
}

// Its only job is its finaliser: see the top of this file.
static mp_obj_t lvgl_guard_del(mp_obj_t self) {
    mp_lv_deinit_gc();
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_1(lvgl_guard_del_obj, lvgl_guard_del);

static const mp_rom_map_elem_t lvgl_guard_locals_table[] = {
    { MP_ROM_QSTR(MP_QSTR___del__), MP_ROM_PTR(&lvgl_guard_del_obj) },
};
static MP_DEFINE_CONST_DICT(lvgl_guard_locals, lvgl_guard_locals_table);

static MP_DEFINE_CONST_OBJ_TYPE(lvgl_guard_type, MP_QSTR_lvgl_guard, MP_TYPE_FLAG_NONE,
    locals_dict, &lvgl_guard_locals);

static mp_obj_t esp_rgb_lv_display_create(void) {
    check_running();
    lv_display_t *disp = lv_display_create(st.width, st.height);
    lv_display_set_color_format(disp, LV_COLOR_FORMAT_RGB565);
    size_t bytes = st.width * st.height * 2;
    if (st.buffers == 2) {
        lv_display_set_buffers(disp, st.fb[1 - st.shown], st.fb[st.shown], bytes, LV_DISPLAY_RENDER_MODE_DIRECT);
    } else {
        lv_display_set_buffers(disp, st.fb[0], NULL, bytes, LV_DISPLAY_RENDER_MODE_DIRECT);
    }
    lv_display_set_flush_cb(disp, lv_flush_cb);
    lv_display_set_flush_wait_cb(disp, lv_flush_wait_cb);
    lv_display_set_default(disp);
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_0(esp_rgb_lv_display_create_obj, esp_rgb_lv_display_create);

static mp_obj_t esp_rgb_lvgl_guard_create(void) {
    MP_STATE_VM(esp_rgb_lvgl_guard) = mp_obj_malloc_with_finaliser(mp_obj_base_t, &lvgl_guard_type);
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_0(esp_rgb_lvgl_guard_obj, esp_rgb_lvgl_guard_create);

MP_REGISTER_ROOT_POINTER(mp_obj_t esp_rgb_lvgl_guard);

#endif // ESP_RGB_LVGL

static const mp_rom_map_elem_t esp_rgb_globals_table[] = {
    { MP_ROM_QSTR(MP_QSTR___name__), MP_ROM_QSTR(MP_QSTR_esp_rgb) },
    { MP_ROM_QSTR(MP_QSTR_init), MP_ROM_PTR(&esp_rgb_init_obj) },
    { MP_ROM_QSTR(MP_QSTR_deinit), MP_ROM_PTR(&esp_rgb_deinit_obj) },
    { MP_ROM_QSTR(MP_QSTR_framebuffer), MP_ROM_PTR(&esp_rgb_framebuffer_obj) },
    { MP_ROM_QSTR(MP_QSTR_shown), MP_ROM_PTR(&esp_rgb_shown_obj) },
    { MP_ROM_QSTR(MP_QSTR_swap), MP_ROM_PTR(&esp_rgb_swap_obj) },
    { MP_ROM_QSTR(MP_QSTR_wait_vsync), MP_ROM_PTR(&esp_rgb_wait_vsync_obj) },
    { MP_ROM_QSTR(MP_QSTR_backlight), MP_ROM_PTR(&esp_rgb_backlight_obj) },
    { MP_ROM_QSTR(MP_QSTR_frame_count), MP_ROM_PTR(&esp_rgb_frame_count_obj) },
    { MP_ROM_QSTR(MP_QSTR_info), MP_ROM_PTR(&esp_rgb_info_obj) },
    #if ESP_RGB_LVGL
    { MP_ROM_QSTR(MP_QSTR_lv_tick_install), MP_ROM_PTR(&esp_rgb_lv_tick_install_obj) },
    { MP_ROM_QSTR(MP_QSTR_lv_display_create), MP_ROM_PTR(&esp_rgb_lv_display_create_obj) },
    { MP_ROM_QSTR(MP_QSTR_lvgl_guard), MP_ROM_PTR(&esp_rgb_lvgl_guard_obj) },
    #endif
    { MP_ROM_QSTR(MP_QSTR_POL_HS), MP_ROM_INT(POL_HS) },
    { MP_ROM_QSTR(MP_QSTR_POL_VS), MP_ROM_INT(POL_VS) },
    { MP_ROM_QSTR(MP_QSTR_POL_DE), MP_ROM_INT(POL_DE) },
    { MP_ROM_QSTR(MP_QSTR_POL_PC), MP_ROM_INT(POL_PC) },
};
static MP_DEFINE_CONST_DICT(esp_rgb_globals, esp_rgb_globals_table);

const mp_obj_module_t esp_rgb_module = {
    .base = { &mp_type_module },
    .globals = (mp_obj_dict_t *)&esp_rgb_globals,
};
MP_REGISTER_MODULE(MP_QSTR_esp_rgb, esp_rgb_module);
