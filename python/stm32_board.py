# Per-board settings of the STM32H743 boards that are not in the C board files:
# the GT911 touch wiring (from docs/stm32-inventory.md, the old boards.py).
#
#   import stm32_board
#   stm32_board.NAME          # "STM32H7_CORE V1.3", ...
#   t = stm32_board.touch()   # gt911.GT911 on the board's touch bus
#
# The panel is chosen in /flash/display_config.py (PANEL = "RGB043M2"),
# default IPS1024x600; see panels.py.

import os

# touch: (rst, int, bus); bus is an int for hardware I2C, else (scl, sda) for SoftI2C.
BOARDS = {
    "DEV190806042": {"touch": ("I8", "H7", ("H6", "G7"))},
    "FK743M5-XIH6": {"touch": ("I10", "I11", ("G3", "G7"))},
    "STM32H7_CORE V1.0": {"touch": ("H7", "E3", 4)},
    "STM32H7_CORE V1.3": {"touch": ("B14", "H7", ("B12", "B13"))},
}

# The GT911 is rated for 400 kHz. The port's hardware I2C timings are for a 54 MHz
# kernel clock; these boards clock I2C from PCLK at 120 MHz, so freq=400_000 ran the
# bus at 1.07 MHz. TOUCH_TIMINGR is 400 kHz Fast mode at 120 MHz (PRESC 5, SCLDEL 7,
# SDADEL 2, SCLH 18, SCLL 26). SoftI2C rounds its half period to whole microseconds:
# freq=400_000 gives 500 kHz, 250_000 is the fastest setting within the rating.
# Measured on the V1.0 (docs/stm32h743.md): address NACKs, 1 in about 30 000 to
# 150 000 reads, only seen above 400 kHz.
TOUCH_FREQ = 400_000
TOUCH_TIMINGR = 0x5072121A  # for a 120 MHz I2C kernel clock
TOUCH_SOFT_FREQ = 250_000

NAME = None
for _n in BOARDS:
    if os.uname().machine.startswith(_n + " with"):
        NAME = _n
CONFIG = BOARDS.get(NAME, {})


def panel():
    try:
        from display_config import PANEL

        return PANEL
    except ImportError:
        return "IPS1024x600"


def touch_i2c():
    from machine import I2C, Pin, SoftI2C

    bus = CONFIG["touch"][2]
    if isinstance(bus, int):
        import machine

        if machine.freq()[2] == 120_000_000:  # PCLK, the I2C kernel clock here
            return I2C(bus, freq=TOUCH_FREQ, timingr=TOUCH_TIMINGR)
        return I2C(bus, freq=TOUCH_FREQ)
    return SoftI2C(scl=Pin(bus[0]), sda=Pin(bus[1]), freq=TOUCH_SOFT_FREQ)


def touch(**kw):
    """The board's GT911 (reset, address 0x5D); OSError if it does not answer."""
    import gt911

    if "touch" not in CONFIG:
        raise OSError("no touch wiring known for %r" % os.uname().machine)
    rst, irq, _ = CONFIG["touch"]
    return gt911.GT911(i2c=touch_i2c(), rst=rst, irq=irq, **kw)
