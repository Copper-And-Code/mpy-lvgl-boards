# Phase 1 board check for the STM32H743 boards (firmware without LVGL).
# Run with: mpremote run tests/hil/stm32/t01_board.py
#
# Checks: SDRAM heap, QSPI filesystem size, SD card, LEDs, GT911 on the touch bus.
# The panel (with its GT911) must be plugged in for the I2C part.
import gc
import os
import time
import machine
from machine import Pin

# Expected values per board (from docs/stm32-inventory.md).
# touch: (rst, int, bus); bus is an int for hardware I2C, else (scl, sda) for SoftI2C.
BOARDS = {
    "DEV190806042": {"qspi_mb": 32, "sd": False, "leds": 1, "touch": ("I8", "H7", ("H6", "G7"))},
    "FK743M5-XIH6": {"qspi_mb": 8, "sd": True, "leds": 1, "touch": ("I10", "I11", ("G3", "G7"))},
    "STM32H7_CORE V1.0": {"qspi_mb": 16, "sd": True, "leds": 1, "touch": ("H7", "E3", 4)},
    "STM32H7_CORE V1.3": {"qspi_mb": 16, "sd": True, "leds": 2, "touch": ("B14", "H7", ("B12", "B13"))},
}
results = []


def check(name, ok, detail=""):
    results.append((name, ok))
    print("%-4s %s %s" % ("ok" if ok else "FAIL", name, detail))


u = os.uname()
print("uname:", u)
board = None
for name in BOARDS:
    if u.machine.startswith(name + " with"):
        board = name
check("known board", board is not None, u.machine)
cfg = BOARDS.get(board, {})
print("freq:", machine.freq())
check("cpu 480 MHz", machine.freq()[0] == 480_000_000)

# SDRAM heap: 32 MB minus what the runtime takes; the AXI SRAM heap would be < 512 KB.
gc.collect()
free = gc.mem_free()
total = free + gc.mem_alloc()
check("heap in SDRAM", total > 30 * 1024 * 1024, "total %d free %d" % (total, free))

# QSPI filesystem (the flash itself is printed by machine.info() as well)
fs = os.statvfs("/flash")
fs_size = fs[0] * fs[2]
check(
    "QSPI fs size",
    "qspi_mb" in cfg and cfg["qspi_mb"] * 1024 * 1024 * 0.9 < fs_size <= cfg["qspi_mb"] * 1024 * 1024,
    "%d bytes (expected about %s MB)" % (fs_size, cfg.get("qspi_mb")),
)
print("mounts:", os.listdir("/"))

# SD card (mounted at boot if a card is in the slot)
if cfg.get("sd"):
    has_sd = "sd" in os.listdir("/")
    if has_sd:
        s = os.statvfs("/sd")
        check("SD mounted", True, "%d bytes" % (s[0] * s[2]))
    else:
        print("note SD not mounted: card inserted? (not counted as a failure)")

# LEDs: blink each one; the person running the test watches them
try:
    import pyb

    for n in range(1, cfg.get("leds", 1) + 1):
        led = pyb.LED(n)
        for _ in range(3):
            led.on()
            time.sleep_ms(150)
            led.off()
            time.sleep_ms(150)
        print("LED%d blinked 3 times" % n)
except Exception as e:
    check("LEDs", False, repr(e))

# GT911: reset with INT low (address 0x5D), then scan
if "touch" in cfg:
    rst_name, int_name, bus = cfg["touch"]
    rst = Pin(rst_name, Pin.OUT, value=0)
    tint = Pin(int_name, Pin.OUT, value=0)
    time.sleep_ms(10)
    rst.value(1)
    time.sleep_ms(10)
    tint.init(Pin.IN)
    time.sleep_ms(60)
    if isinstance(bus, int):
        i2c = machine.I2C(bus)
    else:
        i2c = machine.SoftI2C(scl=Pin(bus[0]), sda=Pin(bus[1]), freq=400_000)
    found = i2c.scan()
    print("touch i2c:", i2c, [hex(a) for a in found])
    check("GT911 on touch bus", 0x5D in found or 0x14 in found)
    if 0x5D in found or 0x14 in found:
        addr = 0x5D if 0x5D in found else 0x14
        pid = i2c.readfrom_mem(addr, 0x8140, 4, addrsize=16)
        check("GT911 product id", pid[:1] == b"9", repr(pid))

print()
machine.info()
print()
bad = [n for n, ok in results if not ok]
print("RESULT:", "all %d checks ok" % len(results) if not bad else "FAILED: " + ", ".join(bad))
