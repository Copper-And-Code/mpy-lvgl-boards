#!/usr/bin/env python3
"""Flash an STM32 through its system bootloader on a UART (AN3155).

The USB-serial adapter drives BOOT0 with DTR and NRST with RTS (STM32H7_CORE V1.3
on the bench). The adapter's modem lines are active low at the connector, so the
logical level each one needs is a parameter (--boot-dtr, --reset-rts).

    scripts/stm32_uart_flash.py probe   [--port /dev/ttyUSB0]
    scripts/stm32_uart_flash.py flash   firmware.hex [--port ...] [--verify]
    scripts/stm32_uart_flash.py reset   [--port ...]          # run the firmware

Only the flash sectors the hex file touches are erased.
"""
import argparse
import sys
import time

import serial

ACK, NACK = 0x79, 0x1F
FLASH_BASE, SECTOR = 0x08000000, 128 * 1024  # STM32H743: 16 sectors of 128 KB


class Boot:
    def __init__(self, port, baud, boot_dtr, reset_rts):
        self.s = serial.Serial(port, baud, parity=serial.PARITY_EVEN, timeout=1)
        self.boot_dtr = boot_dtr  # DTR value that puts BOOT0 high
        self.reset_rts = reset_rts  # RTS value that holds NRST low

    def _reset(self, boot):
        s = self.s
        s.dtr = self.boot_dtr if boot else not self.boot_dtr
        s.rts = self.reset_rts
        time.sleep(0.1)
        s.rts = not self.reset_rts
        time.sleep(0.2 if boot else 0.05)

    def run_firmware(self):
        self._reset(False)

    def enter(self):
        self._reset(True)
        self.s.reset_input_buffer()
        for _ in range(3):
            self.s.write(b"\x7f")
            r = self.s.read(1)
            if r and r[0] in (ACK, NACK):  # NACK: already synchronised
                return True
            time.sleep(0.1)
        return False

    def _ack(self, what, timeout=1):
        self.s.timeout = timeout
        r = self.s.read(1)
        self.s.timeout = 1
        if not r or r[0] != ACK:
            raise IOError("%s: %s" % (what, r.hex() if r else "timeout"))

    def cmd(self, c, timeout=1):
        self.s.write(bytes((c, c ^ 0xFF)))
        self._ack("cmd %02x" % c, timeout)

    def get_id(self):
        self.cmd(0x02)
        n = self.s.read(1)[0]
        pid = self.s.read(n + 1)
        self._ack("get id")
        return int.from_bytes(pid, "big")

    def get_version(self):
        self.cmd(0x00)
        n = self.s.read(1)[0]
        data = self.s.read(n + 1)
        self._ack("get")
        return data[0], data[1:]

    @staticmethod
    def _addr(a):
        b = a.to_bytes(4, "big")
        return b + bytes((b[0] ^ b[1] ^ b[2] ^ b[3],))

    def erase_sectors(self, sectors):
        self.cmd(0x44)
        n = len(sectors) - 1
        payload = n.to_bytes(2, "big") + b"".join(s.to_bytes(2, "big") for s in sectors)
        cs = 0
        for x in payload:
            cs ^= x
        self.s.write(payload + bytes((cs,)))
        self._ack("erase", timeout=10 + 4 * len(sectors))

    def write(self, addr, data):
        self.cmd(0x31)
        self.s.write(self._addr(addr))
        self._ack("write addr %08x" % addr)
        cs = len(data) - 1
        for x in data:
            cs ^= x
        self.s.write(bytes((len(data) - 1,)) + data + bytes((cs,)))
        self._ack("write data %08x" % addr, timeout=2)

    def read(self, addr, n):
        self.cmd(0x11)
        self.s.write(self._addr(addr))
        self._ack("read addr %08x" % addr)
        self.s.write(bytes((n - 1, (n - 1) ^ 0xFF)))
        self._ack("read len")
        return self.s.read(n)


def load_hex(path):
    mem, base = {}, 0
    for line in open(path):
        line = line.strip()
        if not line.startswith(":"):
            continue
        rec = bytes.fromhex(line[1:])
        if sum(rec) & 0xFF:
            raise ValueError("bad checksum: " + line)
        n, off, typ, data = rec[0], int.from_bytes(rec[1:3], "big"), rec[3], rec[4 : 4 + rec[0]]
        if typ == 0:
            for i, x in enumerate(data):
                mem[base + off + i] = x
        elif typ == 4:
            base = int.from_bytes(data, "big") << 16
        elif typ == 2:
            base = int.from_bytes(data, "big") << 4
        elif typ == 1:
            break
    return mem


def blocks(mem, size=256):
    """Yield (addr, bytes) for every size-aligned block that holds data, 0xFF-padded."""
    starts = sorted({a - a % size for a in mem})
    for s in starts:
        yield s, bytes(mem.get(s + i, 0xFF) for i in range(size))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=("probe", "flash", "reset"))
    ap.add_argument("hex", nargs="?")
    ap.add_argument("--port", default="/dev/ttyUSB0")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--boot-dtr", type=int, default=0, help="DTR value for BOOT0 high")
    ap.add_argument("--reset-rts", type=int, default=1, help="RTS value for NRST low")
    ap.add_argument("--verify", action="store_true")
    a = ap.parse_args()

    b = Boot(a.port, a.baud, bool(a.boot_dtr), bool(a.reset_rts))
    if a.action == "reset":
        b.run_firmware()
        print("reset into the firmware")
        return 0
    if not b.enter():
        print("no answer from the bootloader")
        return 1
    ver, cmds = b.get_version()
    print("bootloader v%d.%d, chip id 0x%03x, commands %s" % (ver >> 4, ver & 15, b.get_id(), cmds.hex()))
    if a.action == "probe":
        b.run_firmware()
        return 0

    mem = load_hex(a.hex)
    lo, hi = min(mem), max(mem)
    if lo < FLASH_BASE or hi >= FLASH_BASE + 16 * SECTOR:
        raise SystemExit("hex outside the internal flash: %08x-%08x" % (lo, hi))
    sectors = sorted({(x - FLASH_BASE) // SECTOR for x in mem})
    print("image %08x-%08x (%d bytes), erasing sectors %s" % (lo, hi, len(mem), sectors))
    t = time.time()
    b.erase_sectors(sectors)
    print("erased in %.1f s" % (time.time() - t))
    blk = list(blocks(mem))
    t = time.time()
    for i, (addr, data) in enumerate(blk):
        b.write(addr, data)
        if i % 64 == 0:
            print("\rwrite %3d%%" % (100 * i // len(blk)), end="", flush=True)
    print("\rwritten %d blocks in %.1f s" % (len(blk), time.time() - t))
    if a.verify:
        bad = 0
        for i, (addr, data) in enumerate(blk):
            got = b.read(addr, len(data))
            if got != data:
                bad += 1
                print("verify mismatch at %08x" % addr)
                if bad > 5:
                    break
            if i % 64 == 0:
                print("\rverify %3d%%" % (100 * i // len(blk)), end="", flush=True)
        print("\rverify: %s" % ("ok" if not bad else "FAILED"))
        if bad:
            return 1
    b.run_firmware()
    print("reset into the firmware")
    return 0


if __name__ == "__main__":
    sys.exit(main())
