// st_ltdc: LTDC + DMA2D display driver for the STM32H743 boards of this repo,
// for parallel RGB panels whose timings are given at run time (python/panels.py).
//
// Memory: the framebuffers live in a zone at the top of the SDRAM that the board
// keeps out of the GC heap (MICROPY_HW_LTDC_FB_BYTES, see the boards'
// MICROPY_HEAP_END). They are never freed, so the LTDC keeps scanning valid
// memory across a soft reset, and the image stays on the panel.
// The zone is write-through for the D-cache (MPU region 15): CPU writes reach
// the SDRAM at once, so the LTDC and the DMA2D need no cache maintenance.
// Region 15 because the port's dma.c reprograms and then disables regions 6
// and 7 (MPU_REGION_DMA_UNCACHED_1/2) around SD card reads.
//
// The LTDC, DMA2D and PLL3 registers are programmed directly (no HAL LTDC/DMA2D).
// The only interrupt is the LTDC's: line interrupt (frame counter), FIFO
// underrun and transfer error (counted, see underruns()).
//
// LVGL (when the firmware has the lvgl-micropython binding): lv_display_create()
// makes a display in DIRECT mode on the framebuffers, flushed in C; with two
// buffers each completed refresh is shown from the next vertical blanking.
// PARTIAL mode renders into small buffers in the same zone and copies each area
// into the shown framebuffer with the DMA2D.

#include <string.h>

#include "py/runtime.h"
#include "py/mphal.h"
#include "py/objarray.h"
#include "boardctrl.h"
#include "irq.h"
#include "mpu.h"
#include "sdram.h"

#if __has_include("lvgl/lvgl.h")
#define ST_LTDC_LVGL (1)
#include "lvgl/lvgl.h"
// From the lvgl-micropython binding: forgets LVGL's GC-allocated global state.
void mp_lv_deinit_gc(void);
#else
#define ST_LTDC_LVGL (0)
#endif

#if defined(MICROPY_HW_LTDC_PINS)

#ifndef MICROPY_HW_LTDC_BL_ACTIVE
#define MICROPY_HW_LTDC_BL_ACTIVE (1)
#endif

// One LTDC pin: GPIO port letter, pin number, alternate function.
typedef struct _st_ltdc_pin_t {
    char port;
    uint8_t pin;
    uint8_t af;
} st_ltdc_pin_t;

#define ST_LTDC_PIN(port, pin, af) { (port), (pin), (af) }

static const st_ltdc_pin_t st_ltdc_pins[] = { MICROPY_HW_LTDC_PINS };

// Polarity bits of init(polarity=...), as in the old driver and python/panels.py.
#define POL_HS (1 << 0)   // HSYNC active high
#define POL_VS (1 << 1)   // VSYNC active high
#define POL_DE (1 << 2)   // DE active high
#define POL_PC (1 << 3)   // pixel clock inverted

#define BPP (2)           // RGB565
#define FB_ALIGN (1024)   // framebuffer alignment, for the LTDC bursts
#define MPU_REGION_LTDC (MPU_REGION_NUMBER15)

static struct {
    bool running;
    bool partial;         // LVGL display in PARTIAL mode
    uint8_t buffers;      // 1 or 2
    uint8_t shown;        // index of the framebuffer being scanned out
    uint8_t backlight;    // percent, 0 = off
    uint8_t polarity;
    uint16_t width, height;
    uint16_t hsync, hbp, hfp, vsync, vbp, vfp;
    uint32_t pclk_req;    // pixel clock asked for
    uint32_t pclk_hz;     // pixel clock achieved
    uint32_t pll3_n, pll3_r;
    uint8_t *zone;        // MICROPY_HW_LTDC_FB_BYTES at the top of the SDRAM
    uint16_t *fb[2];
    uint8_t *pbuf[2];     // PARTIAL render buffers
    uint32_t pbuf_bytes;
    volatile uint32_t frames;
    volatile uint32_t underruns;   // LTDC FIFO underruns (the SDRAM did not keep up)
    volatile uint32_t bus_errors;  // LTDC transfer errors
    uint32_t reload_timeouts;
} st;

/******************************************************************************/
// Memory zone

static uint32_t fb_bytes(void) {
    return (uint32_t)st.width * st.height * BPP;
}

static uint32_t align_up(uint32_t x, uint32_t a) {
    return (x + a - 1) & ~(a - 1);
}

static uint8_t *zone_start(void) {
    return (uint8_t *)sdram_end() - MICROPY_HW_LTDC_FB_BYTES;
}

// MPU size encoding of MICROPY_HW_LTDC_FB_BYTES (a power of two): log2(n) - 1.
static uint32_t zone_mpu_size(void) {
    return 31 - __builtin_clz(MICROPY_HW_LTDC_FB_BYTES) - 1;
}

static void zone_setup(void) {
    if (st.zone != NULL) {
        return;
    }
    uint8_t *z = zone_start();
    if (((uintptr_t)z & (MICROPY_HW_LTDC_FB_BYTES - 1)) != 0) {
        mp_raise_msg(&mp_type_OSError, MP_ERROR_TEXT("st_ltdc: framebuffer zone not aligned"));
    }
    // Write-through, no write-allocate (TEX 0, C 1, B 0), no execution.
    uint32_t attr = MPU_INSTRUCTION_ACCESS_DISABLE << MPU_RASR_XN_Pos
        | MPU_REGION_FULL_ACCESS << MPU_RASR_AP_Pos
        | MPU_TEX_LEVEL0 << MPU_RASR_TEX_Pos
        | MPU_ACCESS_NOT_SHAREABLE << MPU_RASR_S_Pos
        | MPU_ACCESS_CACHEABLE << MPU_RASR_C_Pos
        | MPU_ACCESS_NOT_BUFFERABLE << MPU_RASR_B_Pos
        | zone_mpu_size() << MPU_RASR_SIZE_Pos
        | MPU_REGION_ENABLE << MPU_RASR_ENABLE_Pos;
    // Lines of the zone may sit in the D-cache from before (write-back then).
    SCB_CleanInvalidateDCache_by_Addr((uint32_t *)z, MICROPY_HW_LTDC_FB_BYTES);
    uint32_t irq_state = mpu_config_start();
    mpu_config_region(MPU_REGION_LTDC, (uint32_t)z, attr);
    mpu_config_end(irq_state);
    st.zone = z;
}

// Place fb[0], fb[1] and the PARTIAL render buffers in the zone.
static void zone_layout(uint32_t pbuf_bytes) {
    uint32_t fb_step = align_up(fb_bytes(), FB_ALIGN);
    uint32_t used = fb_step * 2;
    uint32_t pb_step = align_up(pbuf_bytes, 32);
    if (used + 2 * pb_step > MICROPY_HW_LTDC_FB_BYTES) {
        mp_raise_ValueError(MP_ERROR_TEXT("st_ltdc: buffers do not fit the framebuffer zone"));
    }
    st.fb[0] = (uint16_t *)st.zone;
    st.fb[1] = (uint16_t *)(st.zone + fb_step);
    st.pbuf[0] = pbuf_bytes ? st.zone + used : NULL;
    st.pbuf[1] = pbuf_bytes ? st.zone + used + pb_step : NULL;
    st.pbuf_bytes = pbuf_bytes;
}

/******************************************************************************/
// Hardware

static GPIO_TypeDef *gpio_port(char port) {
    return (GPIO_TypeDef *)(GPIOA_BASE + (port - 'A') * (GPIOB_BASE - GPIOA_BASE));
}

static void pins_init(void) {
    for (size_t i = 0; i < MP_ARRAY_SIZE(st_ltdc_pins); ++i) {
        const st_ltdc_pin_t *p = &st_ltdc_pins[i];
        RCC->AHB4ENR |= 1u << (p->port - 'A');
        (void)RCC->AHB4ENR;
        GPIO_TypeDef *g = gpio_port(p->port);
        uint32_t n = p->pin;
        g->AFR[n >> 3] = (g->AFR[n >> 3] & ~(0xfu << ((n & 7) * 4))) | ((uint32_t)p->af << ((n & 7) * 4));
        g->OSPEEDR = (g->OSPEEDR & ~(3u << (n * 2))) | (3u << (n * 2));   // very high speed
        g->OTYPER &= ~(1u << n);                                           // push-pull
        g->PUPDR &= ~(3u << (n * 2));                                      // no pull
        g->MODER = (g->MODER & ~(3u << (n * 2))) | (2u << (n * 2));        // alternate function
    }
}

static void backlight_set(mp_int_t pct) {
    if (pct > 100) {
        pct = 100;
    }
    st.backlight = pct;
    // On/off for now; PWM once the polarity is confirmed on each board.
    mp_hal_pin_output(MICROPY_HW_LTDC_BL);
    mp_hal_pin_write(MICROPY_HW_LTDC_BL, (pct > 0) == MICROPY_HW_LTDC_BL_ACTIVE);
}

static void lcd_reset(void) {
    #if defined(MICROPY_HW_LTDC_RST)
    mp_hal_pin_output(MICROPY_HW_LTDC_RST);
    mp_hal_pin_low(MICROPY_HW_LTDC_RST);
    mp_hal_delay_ms(20);
    mp_hal_pin_high(MICROPY_HW_LTDC_RST);
    mp_hal_delay_ms(20);
    #endif
}

// PLL3 R output (the LTDC kernel clock) as close as possible to pclk_hz:
// reference HSE / 5 = 5 MHz, VCO 192..836 MHz (wide range), N 4..512, R 1..128.
static void pll3_set(uint32_t pclk_hz) {
    const uint32_t m = 5;
    const uint32_t ref = HSE_VALUE / m;
    uint32_t best_n = 0, best_r = 0, best_err = UINT32_MAX;
    for (uint32_t r = 1; r <= 128; ++r) {
        uint64_t n = ((uint64_t)pclk_hz * r + ref / 2) / ref;
        if (n < 4 || n > 512) {
            continue;
        }
        uint64_t vco = (uint64_t)ref * n;
        if (vco < 192000000u || vco > 836000000u) {
            continue;
        }
        uint32_t f = vco / r;
        uint32_t err = f > pclk_hz ? f - pclk_hz : pclk_hz - f;
        if (err < best_err) {
            best_err = err;
            best_n = n;
            best_r = r;
        }
    }
    if (best_n == 0) {
        mp_raise_ValueError(MP_ERROR_TEXT("st_ltdc: pixel clock out of range"));
    }
    RCC_PeriphCLKInitTypeDef clk = {0};
    clk.PeriphClockSelection = RCC_PERIPHCLK_LTDC;
    clk.PLL3.PLL3M = m;
    clk.PLL3.PLL3N = best_n;
    clk.PLL3.PLL3P = 2;
    clk.PLL3.PLL3Q = 2;
    clk.PLL3.PLL3R = best_r;
    clk.PLL3.PLL3RGE = RCC_PLL3VCIRANGE_2;
    clk.PLL3.PLL3VCOSEL = RCC_PLL3VCOWIDE;
    clk.PLL3.PLL3FRACN = 0;
    if (HAL_RCCEx_PeriphCLKConfig(&clk) != HAL_OK) {
        mp_raise_msg(&mp_type_OSError, MP_ERROR_TEXT("st_ltdc: PLL3 config failed"));
    }
    st.pll3_n = best_n;
    st.pll3_r = best_r;
    st.pclk_hz = ref * best_n / best_r;
}

// Bus priorities for a tear-free scan-out (from the old driver): at most one
// outstanding transaction on the FMC (SDRAM) target, LTDC and DMA2D ahead of the CPU.
static void axi_qos_for_display(void) {
    GPV->AXI_TARG5_FN_MOD_ISS_BM = 0x01;
    GPV->AXI_INI6_READ_QOS = 0x0f;  // LTDC
    GPV->AXI_INI6_WRITE_QOS = 0x0f;
    GPV->AXI_INI5_READ_QOS = 0x0e;  // DMA2D
    GPV->AXI_INI5_WRITE_QOS = 0x0e;
    GPV->AXI_INI2_READ_QOS = 0x00;  // Cortex-M7
    GPV->AXI_INI2_WRITE_QOS = 0x00;
}

static void scanout_stop(void) {
    if (!st.running) {
        return;
    }
    LTDC->IER = 0;
    NVIC_DisableIRQ(LTDC_IRQn);
    LTDC->GCR &= ~LTDC_GCR_LTDCEN;
    __HAL_RCC_LTDC_CLK_DISABLE();
    st.running = false;
}

static void scanout_start(void) {
    const uint32_t ahbp = st.hsync + st.hbp - 1;  // accumulated horizontal back porch
    const uint32_t avbp = st.vsync + st.vbp - 1;
    const uint32_t aaw = ahbp + st.width;         // accumulated active width
    const uint32_t aah = avbp + st.height;

    pll3_set(st.pclk_req);
    __HAL_RCC_LTDC_CLK_ENABLE();
    __HAL_RCC_LTDC_FORCE_RESET();
    __HAL_RCC_LTDC_RELEASE_RESET();
    pins_init();
    axi_qos_for_display();

    LTDC->SSCR = ((uint32_t)(st.hsync - 1) << 16) | (st.vsync - 1);
    LTDC->BPCR = (ahbp << 16) | avbp;
    LTDC->AWCR = (aaw << 16) | aah;
    LTDC->TWCR = ((aaw + st.hfp) << 16) | (aah + st.vfp);
    LTDC->GCR = (st.polarity & POL_HS ? LTDC_GCR_HSPOL : 0)
        | (st.polarity & POL_VS ? LTDC_GCR_VSPOL : 0)
        | (st.polarity & POL_DE ? LTDC_GCR_DEPOL : 0)
        | (st.polarity & POL_PC ? LTDC_GCR_PCPOL : 0);
    LTDC->BCCR = 0;  // black outside the layer

    LTDC_Layer1->WHPCR = ((ahbp + st.width) << 16) | (ahbp + 1);
    LTDC_Layer1->WVPCR = ((avbp + st.height) << 16) | (avbp + 1);
    LTDC_Layer1->PFCR = 2;     // RGB565
    LTDC_Layer1->CACR = 255;   // constant alpha
    LTDC_Layer1->DCCR = 0;
    LTDC_Layer1->BFCR = (4 << 8) | 5;  // blending with the constant alpha
    LTDC_Layer1->CFBAR = (uint32_t)st.fb[st.shown];
    LTDC_Layer1->CFBLR = ((uint32_t)(st.width * BPP) << 16) | (st.width * BPP + 7);
    LTDC_Layer1->CFBLNR = st.height;
    LTDC_Layer1->CR = LTDC_LxCR_LEN;
    LTDC->SRCR = LTDC_SRCR_IMR;

    // Frame counter: line interrupt at the first line after the active area.
    LTDC->LIPCR = aah + 1;
    LTDC->ICR = LTDC_ICR_CLIF | LTDC_ICR_CFUIF | LTDC_ICR_CTERRIF;
    LTDC->IER = LTDC_IER_LIE | LTDC_IER_FUIE | LTDC_IER_TERRIE;
    NVIC_SetPriority(LTDC_IRQn, IRQ_PRI_TIMX);
    NVIC_EnableIRQ(LTDC_IRQn);

    LTDC->GCR |= LTDC_GCR_LTDCEN;
    st.running = true;
}

void LTDC_IRQHandler(void) {
    uint32_t isr = LTDC->ISR;
    LTDC->ICR = isr;
    if (isr & LTDC_ISR_LIF) {
        st.frames += 1;
    }
    if (isr & LTDC_ISR_FUIF) {
        st.underruns += 1;
    }
    if (isr & LTDC_ISR_TERRIF) {
        st.bus_errors += 1;
    }
}

// Show framebuffer i from the next vertical blanking and wait until the LTDC
// has taken the new address: the other buffer is then free to draw into.
// No MicroPython events are handled while waiting (also called from the flush).
static bool show_buffer(uint32_t i, uint32_t timeout_us) {
    __DSB();  // pixel writes before the address change
    LTDC_Layer1->CFBAR = (uint32_t)st.fb[i];
    LTDC->SRCR = LTDC_SRCR_VBR;
    st.shown = i;
    uint32_t t0 = mp_hal_ticks_us();
    while (LTDC->SRCR & LTDC_SRCR_VBR) {
        if (mp_hal_ticks_us() - t0 >= timeout_us) {
            st.reload_timeouts += 1;
            return false;
        }
    }
    return true;
}

static void dma2d_wait_idle(void) {
    if (__HAL_RCC_DMA2D_IS_CLK_ENABLED()) {
        uint32_t t0 = mp_hal_ticks_us();
        while ((DMA2D->CR & DMA2D_CR_START) && mp_hal_ticks_us() - t0 < 100000) {
        }
    }
}

#if ST_LTDC_LVGL
// DMA2D memory-to-memory copy of a w x h RGB565 block into fb[shown] at (x, y).
static void dma2d_copy(const uint8_t *src, uint32_t x, uint32_t y, uint32_t w, uint32_t h) {
    __HAL_RCC_DMA2D_CLK_ENABLE();
    __DSB();
    DMA2D->CR = 0;  // memory-to-memory, no pixel format conversion
    DMA2D->FGMAR = (uint32_t)src;
    DMA2D->FGOR = 0;
    DMA2D->FGPFCCR = 2;  // RGB565
    DMA2D->OPFCCR = 2;
    DMA2D->OMAR = (uint32_t)(st.fb[st.shown] + y * st.width + x);
    DMA2D->OOR = st.width - w;
    DMA2D->NLR = (w << DMA2D_NLR_PL_Pos) | h;
    DMA2D->IFCR = DMA2D_IFCR_CTCIF | DMA2D_IFCR_CTEIF | DMA2D_IFCR_CCEIF;
    DMA2D->CR |= DMA2D_CR_START;
    uint32_t t0 = mp_hal_ticks_us();
    while (DMA2D->CR & DMA2D_CR_START) {
        if (mp_hal_ticks_us() - t0 >= 100000) {
            DMA2D->CR |= DMA2D_CR_ABORT;
            break;
        }
    }
}
#endif

static uint32_t total_width(void) {
    return st.hsync + st.hbp + st.width + st.hfp;
}

static uint32_t total_height(void) {
    return st.vsync + st.vbp + st.height + st.vfp;
}

/******************************************************************************/
// Python API

// init(width, height, hsync, hbp, hfp, vsync, vbp, vfp, *, polarity=0,
//      pclk_hz=50_000_000, buffers=2, backlight=100)
// Idempotent: the same timings keep the scan-out running (only buffers and
// backlight are applied); other timings restart it with cleared framebuffers.
static mp_obj_t st_ltdc_init(size_t n_args, const mp_obj_t *pos_args, mp_map_t *kw_args) {
    enum {
        ARG_width, ARG_height, ARG_hsync, ARG_hbp, ARG_hfp, ARG_vsync, ARG_vbp, ARG_vfp,
        ARG_polarity, ARG_pclk_hz, ARG_buffers, ARG_backlight,
    };
    static const mp_arg_t allowed_args[] = {
        { MP_QSTR_width, MP_ARG_REQUIRED | MP_ARG_INT, {.u_int = 0} },
        { MP_QSTR_height, MP_ARG_REQUIRED | MP_ARG_INT, {.u_int = 0} },
        { MP_QSTR_hsync, MP_ARG_REQUIRED | MP_ARG_INT, {.u_int = 0} },
        { MP_QSTR_hbp, MP_ARG_REQUIRED | MP_ARG_INT, {.u_int = 0} },
        { MP_QSTR_hfp, MP_ARG_REQUIRED | MP_ARG_INT, {.u_int = 0} },
        { MP_QSTR_vsync, MP_ARG_REQUIRED | MP_ARG_INT, {.u_int = 0} },
        { MP_QSTR_vbp, MP_ARG_REQUIRED | MP_ARG_INT, {.u_int = 0} },
        { MP_QSTR_vfp, MP_ARG_REQUIRED | MP_ARG_INT, {.u_int = 0} },
        { MP_QSTR_polarity, MP_ARG_KW_ONLY | MP_ARG_INT, {.u_int = 0} },
        { MP_QSTR_pclk_hz, MP_ARG_KW_ONLY | MP_ARG_INT, {.u_int = 50000000} },
        { MP_QSTR_buffers, MP_ARG_KW_ONLY | MP_ARG_INT, {.u_int = 2} },
        { MP_QSTR_backlight, MP_ARG_KW_ONLY | MP_ARG_INT, {.u_int = 100} },
    };
    mp_arg_val_t a[MP_ARRAY_SIZE(allowed_args)];
    mp_arg_parse_all(n_args, pos_args, kw_args, MP_ARRAY_SIZE(allowed_args), allowed_args, a);

    for (size_t i = ARG_width; i <= ARG_vfp; ++i) {
        // Sizes, sync widths and porches must all be at least 1 for the LTDC.
        if (a[i].u_int < 1 || a[i].u_int > 4095) {
            mp_raise_ValueError(MP_ERROR_TEXT("st_ltdc: timing value out of range"));
        }
    }
    if (a[ARG_hsync].u_int + a[ARG_hbp].u_int + a[ARG_width].u_int + a[ARG_hfp].u_int > 4096
        || a[ARG_vsync].u_int + a[ARG_vbp].u_int + a[ARG_height].u_int + a[ARG_vfp].u_int > 2048) {
        mp_raise_ValueError(MP_ERROR_TEXT("st_ltdc: total size too large"));
    }
    mp_int_t buffers = a[ARG_buffers].u_int;
    if (buffers != 1 && buffers != 2) {
        mp_raise_ValueError(MP_ERROR_TEXT("st_ltdc: buffers must be 1 or 2"));
    }
    if (a[ARG_pclk_hz].u_int < 1000000 || a[ARG_pclk_hz].u_int > 150000000) {
        mp_raise_ValueError(MP_ERROR_TEXT("st_ltdc: pclk_hz out of range"));
    }
    if ((uint64_t)a[ARG_width].u_int * a[ARG_height].u_int * BPP * 2 > MICROPY_HW_LTDC_FB_BYTES) {
        mp_raise_ValueError(MP_ERROR_TEXT("st_ltdc: buffers do not fit the framebuffer zone"));
    }

    bool same = st.running
        && st.width == a[ARG_width].u_int && st.height == a[ARG_height].u_int
        && st.hsync == a[ARG_hsync].u_int && st.hbp == a[ARG_hbp].u_int && st.hfp == a[ARG_hfp].u_int
        && st.vsync == a[ARG_vsync].u_int && st.vbp == a[ARG_vbp].u_int && st.vfp == a[ARG_vfp].u_int
        && st.polarity == a[ARG_polarity].u_int && st.pclk_req == (uint32_t)a[ARG_pclk_hz].u_int;
    if (!same) {
        dma2d_wait_idle();
        scanout_stop();
        zone_setup();
        st.width = a[ARG_width].u_int;
        st.height = a[ARG_height].u_int;
        st.hsync = a[ARG_hsync].u_int;
        st.hbp = a[ARG_hbp].u_int;
        st.hfp = a[ARG_hfp].u_int;
        st.vsync = a[ARG_vsync].u_int;
        st.vbp = a[ARG_vbp].u_int;
        st.vfp = a[ARG_vfp].u_int;
        st.polarity = a[ARG_polarity].u_int;
        st.pclk_req = a[ARG_pclk_hz].u_int;
        st.partial = false;
        zone_layout(0);
        memset(st.fb[0], 0, fb_bytes());
        memset(st.fb[1], 0, fb_bytes());
        st.shown = 0;
        st.frames = 0;
        st.underruns = 0;
        st.bus_errors = 0;
        lcd_reset();
        scanout_start();
    }
    if (buffers == 1 && st.shown == 1) {
        // Keep the image: move it to buffer 0, which single-buffer mode shows.
        memcpy(st.fb[0], st.fb[1], fb_bytes());
        show_buffer(0, 100000);
    }
    st.buffers = buffers;
    backlight_set(a[ARG_backlight].u_int);
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_KW(st_ltdc_init_obj, 0, st_ltdc_init);

static mp_obj_t st_ltdc_deinit(void) {
    dma2d_wait_idle();
    backlight_set(0);
    scanout_stop();
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_0(st_ltdc_deinit_obj, st_ltdc_deinit);

static void check_running(void) {
    if (!st.running) {
        mp_raise_msg(&mp_type_OSError, MP_ERROR_TEXT("st_ltdc: init() first"));
    }
}

// framebuffer(i=0): memoryview ('H', RGB565) of buffer i (1 only with buffers=2).
static mp_obj_t st_ltdc_framebuffer(size_t n_args, const mp_obj_t *args) {
    check_running();
    mp_int_t i = n_args > 0 ? mp_obj_get_int(args[0]) : 0;
    if (i < 0 || i >= st.buffers) {
        mp_raise_ValueError(MP_ERROR_TEXT("no such framebuffer"));
    }
    return mp_obj_new_memoryview('H' | MP_OBJ_ARRAY_TYPECODE_FLAG_RW, st.width * st.height, st.fb[i]);
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(st_ltdc_framebuffer_obj, 0, 1, st_ltdc_framebuffer);

// shown(): index of the buffer being scanned out.
static mp_obj_t st_ltdc_shown(void) {
    return MP_OBJ_NEW_SMALL_INT(st.shown);
}
static MP_DEFINE_CONST_FUN_OBJ_0(st_ltdc_shown_obj, st_ltdc_shown);

// swap(timeout_ms=100): show the other buffer from the next vertical blanking;
// returns once the LTDC has taken it (False on timeout).
static mp_obj_t st_ltdc_swap(size_t n_args, const mp_obj_t *args) {
    check_running();
    mp_int_t timeout_ms = n_args > 0 ? mp_obj_get_int(args[0]) : 100;
    if (st.buffers != 2) {
        mp_raise_msg(&mp_type_OSError, MP_ERROR_TEXT("st_ltdc: init(buffers=2) first"));
    }
    return mp_obj_new_bool(show_buffer(1 - st.shown, timeout_ms * 1000));
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(st_ltdc_swap_obj, 0, 1, st_ltdc_swap);

// backlight([pct]): set (0..100) or read the backlight.
static mp_obj_t st_ltdc_backlight(size_t n_args, const mp_obj_t *args) {
    if (n_args == 0) {
        return MP_OBJ_NEW_SMALL_INT(st.backlight);
    }
    mp_int_t pct = mp_obj_get_int(args[0]);
    backlight_set(pct < 0 ? 0 : pct);
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(st_ltdc_backlight_obj, 0, 1, st_ltdc_backlight);

// frame_count(): frames scanned out since init() changed the timings.
static mp_obj_t st_ltdc_frame_count(void) {
    return mp_obj_new_int_from_uint(st.frames);
}
static MP_DEFINE_CONST_FUN_OBJ_0(st_ltdc_frame_count_obj, st_ltdc_frame_count);

// underruns(): LTDC FIFO underruns since init() changed the timings: frames
// (or parts of them) the SDRAM did not deliver in time.
static mp_obj_t st_ltdc_underruns(void) {
    return mp_obj_new_int_from_uint(st.underruns);
}
static MP_DEFINE_CONST_FUN_OBJ_0(st_ltdc_underruns_obj, st_ltdc_underruns);

// wait_vsync(timeout_ms=100): wait for the end of the active area of the
// current frame. Returns False on timeout.
static mp_obj_t st_ltdc_wait_vsync(size_t n_args, const mp_obj_t *args) {
    mp_int_t timeout_ms = n_args > 0 ? mp_obj_get_int(args[0]) : 100;
    if (!st.running) {
        return mp_const_false;
    }
    uint32_t f0 = st.frames;
    uint32_t t0 = mp_hal_ticks_ms();
    while (st.frames == f0) {
        if ((mp_int_t)(mp_hal_ticks_ms() - t0) >= timeout_ms) {
            return mp_const_false;
        }
        mp_event_handle_nowait();
    }
    return mp_const_true;
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(st_ltdc_wait_vsync_obj, 0, 1, st_ltdc_wait_vsync);

/******************************************************************************/
// LVGL glue (only when the firmware has the lvgl-micropython binding)

#if ST_LTDC_LVGL
static uint32_t lv_tick_ms(void) {
    return mp_hal_ticks_ms();
}

// lv_tick_install(): make LVGL read the millisecond tick itself, so Python
// never calls lv.tick_inc(). Call after lv.init() (lv.init() resets it).
static mp_obj_t st_ltdc_lv_tick_install(void) {
    lv_tick_set_cb(lv_tick_ms);
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_0(st_ltdc_lv_tick_install_obj, st_ltdc_lv_tick_install);

// Flush in C: no Python code runs between LVGL handing over a frame and
// lv_display_flush_ready(), so a KeyboardInterrupt can never leave LVGL
// waiting forever for the flush.
static void lv_flush_cb(lv_display_t *disp, const lv_area_t *area, uint8_t *px_map) {
    if (st.running) {
        if (st.partial) {
            dma2d_copy(px_map, area->x1, area->y1, lv_area_get_width(area), lv_area_get_height(area));
        } else if (st.buffers == 2 && lv_display_flush_is_last(disp)) {
            show_buffer((uint16_t *)px_map == st.fb[1] ? 1 : 0, 100000);
        }
    }
    lv_display_flush_ready(disp);
}

// lv_display_create(partial_lines=0): create the LVGL display on the panel,
// flushed in C, and make it the default one.
// partial_lines=0: DIRECT mode on the framebuffers; with two buffers LVGL draws
// into the hidden one and each completed refresh is shown from the next
// vertical blanking.
// partial_lines>0: PARTIAL mode, two render buffers of that many lines, each
// area copied by the DMA2D into the shown framebuffer.
// Returns None: get the display with lv.display_get_default().
static mp_obj_t st_ltdc_lv_display_create(size_t n_args, const mp_obj_t *args) {
    check_running();
    mp_int_t lines = n_args > 0 ? mp_obj_get_int(args[0]) : 0;
    if (lines < 0 || lines > st.height) {
        mp_raise_ValueError(MP_ERROR_TEXT("st_ltdc: partial_lines out of range"));
    }
    dma2d_wait_idle();
    zone_layout(lines * st.width * BPP);
    st.partial = lines > 0;
    lv_display_t *disp = lv_display_create(st.width, st.height);
    lv_display_set_color_format(disp, LV_COLOR_FORMAT_RGB565);
    if (st.partial) {
        lv_display_set_buffers(disp, st.pbuf[0], st.pbuf[1], st.pbuf_bytes, LV_DISPLAY_RENDER_MODE_PARTIAL);
    } else if (st.buffers == 2) {
        // Both buffers start with the image on screen: DIRECT mode only redraws
        // what changed, into the hidden buffer first.
        memcpy(st.fb[1 - st.shown], st.fb[st.shown], fb_bytes());
        lv_display_set_buffers(disp, st.fb[1 - st.shown], st.fb[st.shown], fb_bytes(), LV_DISPLAY_RENDER_MODE_DIRECT);
    } else {
        lv_display_set_buffers(disp, st.fb[0], NULL, fb_bytes(), LV_DISPLAY_RENDER_MODE_DIRECT);
    }
    lv_display_set_flush_cb(disp, lv_flush_cb);
    lv_display_set_default(disp);
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(st_ltdc_lv_display_create_obj, 0, 1, st_ltdc_lv_display_create);
#endif

static void dict_store(mp_obj_t d, qstr key, mp_obj_t value) {
    mp_obj_dict_store(d, MP_OBJ_NEW_QSTR(key), value);
}

static mp_obj_t st_ltdc_info(void) {
    mp_obj_t d = mp_obj_new_dict(20);
    dict_store(d, MP_QSTR_running, mp_obj_new_bool(st.running));
    dict_store(d, MP_QSTR_width, MP_OBJ_NEW_SMALL_INT(st.width));
    dict_store(d, MP_QSTR_height, MP_OBJ_NEW_SMALL_INT(st.height));
    dict_store(d, MP_QSTR_buffers, MP_OBJ_NEW_SMALL_INT(st.buffers));
    dict_store(d, MP_QSTR_shown, MP_OBJ_NEW_SMALL_INT(st.shown));
    dict_store(d, MP_QSTR_backlight, MP_OBJ_NEW_SMALL_INT(st.backlight));
    dict_store(d, MP_QSTR_polarity, MP_OBJ_NEW_SMALL_INT(st.polarity));
    dict_store(d, MP_QSTR_pclk_hz, mp_obj_new_int_from_uint(st.pclk_hz));
    dict_store(d, MP_QSTR_pll3_n, MP_OBJ_NEW_SMALL_INT(st.pll3_n));
    dict_store(d, MP_QSTR_pll3_r, MP_OBJ_NEW_SMALL_INT(st.pll3_r));
    if (st.width) {
        // Nominal refresh in mHz: pixel clock / (total width x total height).
        uint64_t mhz = (uint64_t)st.pclk_hz * 1000 / (total_width() * total_height());
        dict_store(d, MP_QSTR_refresh_mhz, mp_obj_new_int_from_uint((uint32_t)mhz));
    }
    dict_store(d, MP_QSTR_frames, mp_obj_new_int_from_uint(st.frames));
    dict_store(d, MP_QSTR_underruns, mp_obj_new_int_from_uint(st.underruns));
    dict_store(d, MP_QSTR_bus_errors, mp_obj_new_int_from_uint(st.bus_errors));
    dict_store(d, MP_QSTR_reload_timeouts, mp_obj_new_int_from_uint(st.reload_timeouts));
    dict_store(d, MP_QSTR_partial, mp_obj_new_bool(st.partial));
    dict_store(d, MP_QSTR_zone_addr, mp_obj_new_int_from_uint((uint32_t)zone_start()));
    dict_store(d, MP_QSTR_zone_bytes, mp_obj_new_int_from_uint(MICROPY_HW_LTDC_FB_BYTES));
    if (st.zone) {
        dict_store(d, MP_QSTR_fb0_addr, mp_obj_new_int_from_uint((uint32_t)st.fb[0]));
        dict_store(d, MP_QSTR_fb1_addr, mp_obj_new_int_from_uint((uint32_t)st.fb[1]));
    }
    if (st.running) {
        // Current scan line, straight from the LTDC.
        dict_store(d, MP_QSTR_cpsr_y, MP_OBJ_NEW_SMALL_INT(LTDC->CPSR & 0xffff));
    }
    return d;
}
static MP_DEFINE_CONST_FUN_OBJ_0(st_ltdc_info_obj, st_ltdc_info);

static const mp_rom_map_elem_t st_ltdc_module_globals_table[] = {
    { MP_ROM_QSTR(MP_QSTR___name__), MP_ROM_QSTR(MP_QSTR_st_ltdc) },
    { MP_ROM_QSTR(MP_QSTR_init), MP_ROM_PTR(&st_ltdc_init_obj) },
    { MP_ROM_QSTR(MP_QSTR_deinit), MP_ROM_PTR(&st_ltdc_deinit_obj) },
    { MP_ROM_QSTR(MP_QSTR_framebuffer), MP_ROM_PTR(&st_ltdc_framebuffer_obj) },
    { MP_ROM_QSTR(MP_QSTR_shown), MP_ROM_PTR(&st_ltdc_shown_obj) },
    { MP_ROM_QSTR(MP_QSTR_swap), MP_ROM_PTR(&st_ltdc_swap_obj) },
    { MP_ROM_QSTR(MP_QSTR_backlight), MP_ROM_PTR(&st_ltdc_backlight_obj) },
    { MP_ROM_QSTR(MP_QSTR_frame_count), MP_ROM_PTR(&st_ltdc_frame_count_obj) },
    { MP_ROM_QSTR(MP_QSTR_underruns), MP_ROM_PTR(&st_ltdc_underruns_obj) },
    { MP_ROM_QSTR(MP_QSTR_wait_vsync), MP_ROM_PTR(&st_ltdc_wait_vsync_obj) },
    { MP_ROM_QSTR(MP_QSTR_info), MP_ROM_PTR(&st_ltdc_info_obj) },
    #if ST_LTDC_LVGL
    { MP_ROM_QSTR(MP_QSTR_lv_tick_install), MP_ROM_PTR(&st_ltdc_lv_tick_install_obj) },
    { MP_ROM_QSTR(MP_QSTR_lv_display_create), MP_ROM_PTR(&st_ltdc_lv_display_create_obj) },
    #endif
    { MP_ROM_QSTR(MP_QSTR_POL_HS), MP_ROM_INT(POL_HS) },
    { MP_ROM_QSTR(MP_QSTR_POL_VS), MP_ROM_INT(POL_VS) },
    { MP_ROM_QSTR(MP_QSTR_POL_DE), MP_ROM_INT(POL_DE) },
    { MP_ROM_QSTR(MP_QSTR_POL_PC), MP_ROM_INT(POL_PC) },
};
static MP_DEFINE_CONST_DICT(st_ltdc_module_globals, st_ltdc_module_globals_table);

const mp_obj_module_t st_ltdc_user_cmodule = {
    .base = { &mp_type_module },
    .globals = (mp_obj_dict_t *)&st_ltdc_module_globals,
};

MP_REGISTER_MODULE(MP_QSTR_st_ltdc, st_ltdc_user_cmodule);

#endif // defined(MICROPY_HW_LTDC_PINS)

// MICROPY_BOARD_END_SOFT_RESET of the boards (see their mpconfigboard.h).
// The scan-out keeps running on the framebuffers, which are outside the GC
// heap. The binding keeps LVGL's state in GC memory behind root pointers that
// a soft reset does not clear: without mp_lv_deinit_gc(), lv.init() after
// Ctrl-D reuses freed memory and hangs.
void st_ltdc_board_end_soft_reset(boardctrl_state_t *state) {
    #if defined(MICROPY_HW_LTDC_PINS)
    dma2d_wait_idle();
    // A PARTIAL LVGL display is gone with the heap; its render buffers are free.
    st.partial = false;
    #endif
    #if ST_LTDC_LVGL
    mp_lv_deinit_gc();
    #endif
    boardctrl_end_soft_reset(state);
}
