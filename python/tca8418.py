# TCA8418 I2C keypad scan controller (Texas Instruments): up to 8 rows x 10
# columns, with debounce and a 10-event FIFO in the chip.
#
# Polled, no interrupt needed: events() reads the event count and pops the
# FIFO. Each event is (pressed, row, col). The INT pin is optional (its
# interrupt for key events is enabled, so it can be wired later).
#
# On the Waveshare RP2350-Touch-LCD-4 it goes on connector H4: pin 7 I2C_VCC
# (3.3 V by default), 8 GND, 9 SDA, 10 SCL = I2C1, shared with the touch.
#
# Register map from the TCA8418 datasheet (SCPS215).

ADDR = 0x34

REG_CFG = 0x01
REG_INT_STAT = 0x02
REG_KEY_LCK_EC = 0x03
REG_KEY_EVENT_A = 0x04  # reading it pops the oldest event from the FIFO
REG_KP_GPIO1 = 0x1D     # rows 0-7 in the keypad matrix
REG_KP_GPIO2 = 0x1E     # columns 0-7
REG_KP_GPIO3 = 0x1F     # columns 8-9

CFG_AI = 0x80           # register auto-increment
CFG_OVR_FLOW_M = 0x20   # FIFO full: drop the oldest event, keep the new one
CFG_KE_IEN = 0x01       # INT pin on key events

INT_K = 0x01            # key event
INT_OVR_FLOW = 0x08     # FIFO overflowed
INT_ALL = 0x1F

MAX_ROWS, MAX_COLS = 8, 10


class TCA8418:
    def __init__(self, i2c=None, addr=ADDR, rows=MAX_ROWS, cols=MAX_COLS):
        if i2c is None:
            from machine import I2C

            i2c = I2C(1, freq=400_000)
        if not (1 <= rows <= MAX_ROWS and 1 <= cols <= MAX_COLS):
            raise ValueError("matrix is at most 8 x 10")
        self.i2c = i2c
        self.addr = addr
        self.rows = rows
        self.cols = cols
        self.overflows = 0      # times the chip's FIFO lost events
        self._b = bytearray(1)
        if addr not in i2c.scan():
            raise OSError("TCA8418 not found at 0x%02x" % addr)
        col_mask = (1 << cols) - 1
        self._write(REG_KP_GPIO1, (1 << rows) - 1)
        self._write(REG_KP_GPIO2, col_mask & 0xFF)
        self._write(REG_KP_GPIO3, col_mask >> 8)
        self._write(REG_CFG, CFG_AI | CFG_OVR_FLOW_M | CFG_KE_IEN)
        self.flush()

    def _read(self, reg):
        self.i2c.readfrom_mem_into(self.addr, reg, self._b)
        return self._b[0]

    def _write(self, reg, value):
        self._b[0] = value
        self.i2c.writeto_mem(self.addr, reg, self._b)

    def flush(self):
        # Drop the events already in the FIFO (e.g. from before a soft reset)
        for _ in range(self._read(REG_KEY_LCK_EC) & 0x0F):
            self._read(REG_KEY_EVENT_A)
        self._write(REG_INT_STAT, INT_ALL)

    def events(self):
        # Pending key events, oldest first: list of (pressed, row, col).
        # One 1-byte register read when there is nothing to report.
        n = self._read(REG_KEY_LCK_EC) & 0x0F
        if n == 0:
            return []
        out = []
        for _ in range(n):
            e = self._read(REG_KEY_EVENT_A)
            code = e & 0x7F
            if 1 <= code <= MAX_ROWS * MAX_COLS:  # 97+ are GPI events: not used
                out.append((bool(e & 0x80), (code - 1) // MAX_COLS, (code - 1) % MAX_COLS))
        stat = self._read(REG_INT_STAT)
        if stat & INT_OVR_FLOW:
            self.overflows += 1
        self._write(REG_INT_STAT, stat)  # clear what was set
        return out
