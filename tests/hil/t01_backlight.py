# Phase 1 backlight polarity check (needs eyes on the board).
# Run with: mpremote run tests/hil/t01_backlight.py
# The panel is not initialised, so only the backlight glow is visible.
import time
from machine import Pin, PWM

bl = PWM(Pin(40), freq=20_000)
for label, duty in (("A: duty 0 %", 0), ("B: duty 50 %", 32768), ("C: duty 100 %", 65535)):
    bl.duty_u16(duty)
    print(label, "- look at the screen for 5 s")
    time.sleep(5)
bl.duty_u16(65535)
print("done, left at duty 100 %")
