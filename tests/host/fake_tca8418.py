# A software TCA8418 for host tests: implements the I2C calls the driver uses
# (scan, readfrom_mem_into, writeto_mem) and the registers it touches.


class FakeTCA8418:
    def __init__(self, addr=0x34):
        self.addr = addr
        self.regs = {}
        self.fifo = []           # event bytes, oldest first (max 10)
        self.int_stat = 0
        self.writes = []         # (reg, value) in order

    # test side
    def key(self, row, col, pressed):
        code = row * 10 + col + 1
        if len(self.fifo) == 10:  # OVR_FLOW_M set: drop the oldest
            self.fifo.pop(0)
            self.int_stat |= 0x08
        self.fifo.append(code | (0x80 if pressed else 0))
        self.int_stat |= 0x01

    def tap(self, row, col):
        self.key(row, col, True)
        self.key(row, col, False)

    # machine.I2C side
    def scan(self):
        return [self.addr]

    def readfrom_mem_into(self, addr, reg, buf):
        assert addr == self.addr and len(buf) == 1
        if reg == 0x03:
            buf[0] = len(self.fifo)
        elif reg == 0x04:
            buf[0] = self.fifo.pop(0) if self.fifo else 0
        elif reg == 0x02:
            buf[0] = self.int_stat
        else:
            buf[0] = self.regs.get(reg, 0)

    def writeto_mem(self, addr, reg, buf):
        assert addr == self.addr
        v = buf[0]
        self.writes.append((reg, v))
        if reg == 0x02:
            self.int_stat &= ~v  # write 1 to clear
        else:
            self.regs[reg] = v
