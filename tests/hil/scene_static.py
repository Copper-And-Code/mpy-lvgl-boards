# Static LVGL scene shared by the target and the unix port (Phase 4 pixel check).
# No animation, no time dependence: both must render the same pixels.
import lvgl as lv


def build(scr):
    scr.set_style_bg_color(lv.color_hex(0x203040), 0)
    btn = lv.button(scr)
    btn.set_size(150, 50)
    btn.align(lv.ALIGN.CENTER, 0, -40)
    lbl = lv.label(btn)
    lbl.set_text("Hello RP2350")
    lbl.center()
    bar = lv.bar(scr)
    bar.set_size(180, 16)
    bar.align(lv.ALIGN.CENTER, 0, 30)
    bar.set_value(65, False)  # no animation
    t = lv.label(scr)
    t.set_text("LVGL %d.%d  240x240" % (lv.version_major(), lv.version_minor()))
    t.align(lv.ALIGN.BOTTOM_MID, 0, -12)
    arc = lv.arc(scr)
    arc.set_size(60, 60)
    arc.align(lv.ALIGN.TOP_LEFT, 8, 8)
    arc.set_value(40)


def tile_crcs(buf, w, h, tile=32):
    # buf: bytes-like RGB565 framebuffer (w*h*2 bytes). One CRC32 per tile, row major.
    import binascii
    mv = memoryview(buf)
    out = []
    for ty in range(0, h, tile):
        for tx in range(0, w, tile):
            crc = 0
            x1 = min(tx + tile, w)
            for y in range(ty, min(ty + tile, h)):
                crc = binascii.crc32(mv[(y * w + tx) * 2:(y * w + x1) * 2], crc)
            out.append(crc)
    return out
