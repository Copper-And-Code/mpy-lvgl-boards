# Sizes and fonts for LVGL screens that fit any display resolution.
#
#   import ui
#   b.set_size(ui.px(140), ui.px(60))     # 140x60 on a 240 px display
#   scr.set_style_text_font(ui.font(14), 0)
#
# Sizes are written for a 240 px display (the RP2350 board's) and scaled by the
# shorter side of the actual one: px(n) is n on 240x240 and 2.5 n on 1024x600.
# font(size) is the compiled-in Montserrat closest to the scaled size.

import lvgl as lv

import display_driver

W, H = display_driver.WIDTH, display_driver.HEIGHT
UNIT = min(W, H) / 240

_FONTS = [(s, getattr(lv, "font_montserrat_%d" % s, None)) for s in (8, 10, 12, 14, 16, 18, 20, 22, 24, 26, 28, 30, 32, 34, 36, 38, 40, 42, 44, 46, 48)]
_FONTS = [(s, f) for s, f in _FONTS if f is not None]


def px(n):
    """n pixels of a 240 px display, scaled to this one (rounded, at least 1 if n > 0)."""
    v = n * UNIT
    r = int(v + 0.5) if v >= 0 else -int(-v + 0.5)
    return 1 if r == 0 and n > 0 else r


def font(size=14):
    """The Montserrat font closest to `size` points on a 240 px display, scaled."""
    want = size * UNIT
    return min(_FONTS, key=lambda sf: abs(sf[0] - want))[1]
