# Phase 1 board check. Run with: mpremote run tests/hil/t01_board.py
import gc
import os
import machine

EXPECTED_I2C = {
    0x5D: "GT911 (addr 0x5D)",
    0x14: "GT911 (addr 0x14)",
    0x51: "PCF85063 RTC",
    0x6A: "QMI8658 IMU (0x6A)",
    0x6B: "QMI8658 IMU (0x6B)",
}

print("uname:", os.uname())
print("freq:", machine.freq())
gc.collect()
print("mem_free:", gc.mem_free(), "mem_alloc:", gc.mem_alloc())

i2c = machine.I2C(1)
print("i2c:", i2c)
found = i2c.scan()
print("i2c scan:", [hex(a) for a in found])
for a in found:
    print("  0x%02X %s" % (a, EXPECTED_I2C.get(a, "unknown")))
for a, name in EXPECTED_I2C.items():
    if a not in found and a not in (0x14, 0x6B, 0x6A, 0x5D):
        print("  MISSING", name)
if not any(a in found for a in (0x5D, 0x14)):
    print("  MISSING GT911")
if not any(a in found for a in (0x6A, 0x6B)):
    print("  MISSING QMI8658")

fs = os.statvfs("/")
print("fs total:", fs[0] * fs[2], "free:", fs[0] * fs[3])
