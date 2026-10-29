# GT911 capacitive touch controller, for LVGL (pointer input device).
#
# Polled, no interrupt: read() looks at the status register and only reads the
# point data when the controller has a new report ("buffer ready" bit), then
# clears it. Between reports the last state is kept, so a finger held still
# stays pressed.
#
# Reset/address selection as in the Waveshare demo (bsp_gt911.c): INT held low
# while RST rises selects address 0x5D. The command register is then set to 0.

import time
from machine import I2C, Pin

REG_COMMAND = 0x8040
REG_PRODUCT_ID = 0x8140
REG_STATUS = 0x814E
REG_POINT1 = 0x8150  # x lo, x hi, y lo, y hi, size lo, size hi, reserved

ADDR = 0x5D


class GT911:
    def __init__(self, i2c=None, rst=16, irq=17, addr=ADDR, scale=1, reset=True):
        self.i2c = i2c if i2c is not None else I2C(1, freq=400_000)
        self.addr = addr
        self.scale = scale
        self.rst = Pin(rst, Pin.OUT, value=1)
        self.irq_pin = irq
        self.x = 0
        self.y = 0
        self.pressed = False
        self._status = bytearray(1)
        self._point = bytearray(4)
        self._zero = b"\x00"
        if reset:
            self.reset()
        pid = self.product_id()
        if pid != "911":
            raise OSError("GT911 not found (product id %r)" % pid)
        # Command 0 = report coordinates. On this board the register reads 0xFF
        # after reset and the controller reports no touches until it is written.
        self.i2c.writeto_mem(self.addr, REG_COMMAND, b"\x00", addrsize=16)

    def reset(self):
        # INT low while RST rises: address 0x5D. Then release INT (input).
        irq = Pin(self.irq_pin, Pin.OUT, value=0)
        self.rst(1)
        time.sleep_ms(50)
        self.rst(0)
        time.sleep_ms(50)
        self.rst(1)
        time.sleep_ms(250)
        irq.init(Pin.IN, Pin.PULL_UP)

    def product_id(self):
        return self.i2c.readfrom_mem(self.addr, REG_PRODUCT_ID, 4, addrsize=16).rstrip(b"\x00").decode()

    def read(self):
        # Returns (pressed, x, y) in panel pixels divided by scale.
        i2c = self.i2c
        i2c.readfrom_mem_into(self.addr, REG_STATUS, self._status, addrsize=16)
        st = self._status[0]
        if st & 0x80:
            if st & 0x0F:
                i2c.readfrom_mem_into(self.addr, REG_POINT1, self._point, addrsize=16)
                p = self._point
                self.x = (p[0] | (p[1] << 8)) // self.scale
                self.y = (p[2] | (p[3] << 8)) // self.scale
                self.pressed = True
            else:
                self.pressed = False
            i2c.writeto_mem(self.addr, REG_STATUS, self._zero, addrsize=16)
        return self.pressed, self.x, self.y

    def lv_read_cb(self, indev, data):
        import lvgl as lv

        pressed, x, y = self.read()
        data.point.x = x
        data.point.y = y
        data.state = lv.INDEV_STATE.PRESSED if pressed else lv.INDEV_STATE.RELEASED

    def lv_register(self):
        import lvgl as lv

        indev = lv.indev_create()
        indev.set_type(lv.INDEV_TYPE.POINTER)
        indev.set_read_cb(self.lv_read_cb)
        return indev
