# Timings of the RGB panels used with the STM32H743 boards, for st_ltdc.init().
#
#   import st_ltdc, panels
#   st_ltdc.init(**panels.get("IPS1024x600"))
#
# Values from the old lv_micropython driver (panels.py there). Pixel clock: the
# old driver ran both panels at 50 MHz (PLL3 M5 N40 R4); the refresh rates in the
# comments are calculated from it, see st_ltdc.info()["refresh_mhz"].
# polarity bits: st_ltdc.POL_HS (1) HSYNC active high, POL_VS (2) VSYNC active
# high, POL_DE (4) DE active high, POL_PC (8) pixel clock inverted.

PANELS = {
    # 7" IPS 1024x600: total 1344 x 638, 58.3 Hz at 50 MHz.
    "IPS1024x600": {
        "width": 1024,
        "height": 600,
        "hsync": 7,
        "hbp": 164,
        "hfp": 149,
        "vsync": 5,
        "vbp": 22,
        "vfp": 11,
        "polarity": 0,
        "pclk_hz": 50_000_000,
    },
    # 4.3" RGB043M2 800x480: total 884 x 510, 110.9 Hz at 50 MHz.
    "RGB043M2": {
        "width": 800,
        "height": 480,
        "hsync": 4,
        "hbp": 40,
        "hfp": 40,
        "vsync": 4,
        "vbp": 13,
        "vfp": 13,
        "polarity": 8,
        "pclk_hz": 50_000_000,
    },
}


def get(name):
    """Timings of panel `name` as keyword arguments for st_ltdc.init()."""
    try:
        return dict(PANELS[name])
    except KeyError:
        raise ValueError("unknown panel %r, known: %s" % (name, ", ".join(sorted(PANELS))))
