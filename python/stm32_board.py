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

TOUCH_FREQ = 400_000

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
        return I2C(bus, freq=TOUCH_FREQ)
    return SoftI2C(scl=Pin(bus[0]), sda=Pin(bus[1]), freq=TOUCH_FREQ)


def touch(**kw):
    """The board's GT911 (reset, address 0x5D); OSError if it does not answer."""
    import gt911

    if "touch" not in CONFIG:
        raise OSError("no touch wiring known for %r" % os.uname().machine)
    rst, irq, _ = CONFIG["touch"]
    return gt911.GT911(i2c=touch_i2c(), rst=rst, irq=irq, **kw)
