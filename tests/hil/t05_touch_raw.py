# Phase 5, raw coordinates (fingers): prints every new GT911 report for 180 s or 5 touches,
# plus every non-zero raw status byte (0x814E) and the INT pin level changes.
# Touch the four corners and the centre, one at a time.
# Run with: mpremote run tests/hil/t05_touch_raw.py
import time
import gt911

t = gt911.GT911(scale=1)
print("product id:", t.product_id(), "addr 0x%02x" % t.addr)
# read() timing
n = 50
t0 = time.ticks_us()
for i in range(n):
    t.read()
print("read() avg us:", time.ticks_diff(time.ticks_us(), t0) // n)

last = None
from machine import Pin
irq = Pin(17, Pin.IN, Pin.PULL_UP)
last_irq = irq()
seen = 0
end = time.ticks_add(time.ticks_ms(), 180_000)
downs = 0
print("touch now: corners and centre")
while time.ticks_diff(end, time.ticks_ms()) > 0:
    st = t.i2c.readfrom_mem(t.addr, gt911.REG_STATUS, 1, addrsize=16)[0]
    if st and seen < 20:
        print("status 0x%02x" % st)
        seen += 1
    if irq() != last_irq:
        last_irq = irq()
        if seen < 40:
            print("INT ->", last_irq)
            seen += 1
    p = t.read()
    if p != last:
        print("%s x=%d y=%d" % ("DOWN" if p[0] else "UP  ", p[1], p[2]))
        if last is not None and p[0] and not last[0]:
            downs += 1
        last = p
        if downs >= 5 and not p[0]:
            break
    time.sleep_ms(10)
print("done")
