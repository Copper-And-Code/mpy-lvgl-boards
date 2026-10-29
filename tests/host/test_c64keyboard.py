# Host test of python/tca8418.py and python/c64keyboard.py against a software
# TCA8418 (fake_tca8418.py). Runs on CPython and on the unix port:
#   cd tests/host && python3 test_c64keyboard.py
#   cd tests/host && micropython test_c64keyboard.py
import sys

sys.path.insert(0, "../../python")
sys.path.insert(0, ".")
from fake_tca8418 import FakeTCA8418
import tca8418
import c64keyboard

# rows/cols of some keys (TCA row = C64 row PB, TCA col = C64 column PA)
A, Q, ONE, RETURN, RIGHT = (2, 1), (6, 7), (0, 7), (1, 0), (2, 0)
LSHIFT, RSHIFT, CBM, SPACE, STOP = (7, 1), (4, 6), (5, 7), (4, 7), (7, 7)
POUND, F1 = (0, 6), (4, 0)

# configuration: 8 rows, 9 columns, AI | OVR_FLOW_M | KE_IEN, FIFO flushed
chip = FakeTCA8418()
chip.tap(*A)  # stale event from before the driver starts
kb = c64keyboard.C64Keyboard(chip)
assert chip.regs[0x1D] == 0xFF and chip.regs[0x1E] == 0xFF and chip.regs[0x1F] == 0x01, chip.regs
assert chip.regs[0x01] == 0xA1, chip.regs[0x01]
assert chip.fifo == [] and kb.read() == [], "stale events not flushed"

# every matrix position decodes to the name in the table
for col in range(8):
    for row in range(8):
        assert kb.name_at(row, col) == c64keyboard.MATRIX[col][row]
assert kb.name_at(0, 8) == "RESTORE" and kb.name_at(1, 8) is None

# typing
chip.tap(*A); chip.tap(*ONE); chip.tap(*SPACE); chip.tap(*POUND)
ev = kb.read()
assert ev == [(True, "A", "a"), (False, "A", "a"), (True, "1", "1"), (False, "1", "1"),
              (True, "SPACE", " "), (False, "SPACE", " "), (True, "£", "£"), (False, "£", "£")], ev

# SHIFT: upper case, shifted symbols and keys; either SHIFT works
chip.key(*LSHIFT, True); chip.tap(*A); chip.tap(*ONE)
ev = [e for e in kb.read() if e[0]]  # read before the chip's 10-event FIFO fills
chip.tap(*RIGHT); chip.tap(*F1); chip.key(*LSHIFT, False)
ev += [e for e in kb.read() if e[0]]
chip.key(*RSHIFT, True); chip.tap(*Q); chip.key(*RSHIFT, False)
ev += [e for e in kb.read() if e[0]]
assert ev == [(True, "LSHIFT", None), (True, "A", "A"), (True, "!", "!"), (True, "LEFT", None),
              (True, "F2", None), (True, "RSHIFT", None), (True, "Q", "Q")], ev
assert not kb.shift

# the release matches the press even if SHIFT changed in between
chip.key(*A, True); chip.key(*LSHIFT, True); chip.key(*A, False); chip.key(*LSHIFT, False)
ev = kb.read()
assert ev[0] == (True, "A", "a") and ev[2] == (False, "A", "a"), ev

# modifiers are tracked
chip.key(*CBM, True)
kb.read()
assert "C=" in kb.held
chip.key(*CBM, False)
kb.read()
assert not kb.held

# RESTORE and STOP
chip.tap(0, 8); chip.tap(*STOP)
assert [e[1] for e in kb.read()] == ["RESTORE", "RESTORE", "STOP", "STOP"]

# FIFO overflow: the chip keeps the newest 10 events, the driver counts it
for i in range(6):
    chip.tap(*A)
ev = kb.read()
assert len(ev) == 10 and kb.chip.overflows == 1, (len(ev), kb.chip.overflows)

# no chip on the bus
class Empty:
    def scan(self):
        return []
try:
    tca8418.TCA8418(Empty())
    raise AssertionError("no error without a chip")
except OSError:
    pass

print("test_c64keyboard: OK")
