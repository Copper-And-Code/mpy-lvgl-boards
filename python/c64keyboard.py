# Commodore 64-style keyboard on a TCA8418, for LVGL (keypad input device).
#
# Wiring: the C64 8x8 matrix with TCA8418 ROW0-7 = C64 rows (PB0-7, read by
# the C64) and COL0-7 = C64 columns (PA0-7, driven by the C64). RESTORE,
# outside the matrix on a C64, goes between ROW0 and COL8. SHIFT LOCK is a
# latching switch in parallel with the left SHIFT. Diodes on the switches
# are recommended (without them three keys pressed together can show a
# fourth, "ghost" key, as on the original).
#
#   kb = C64Keyboard()            # TCA8418 at 0x34 on I2C1
#   kb.lv_register()              # LVGL keypad: text goes to the focused widget
#   for pressed, name, char in kb.read(): ...   # or use the keys directly
#
# read() gives (pressed, name, char): name is the key ("A", "RETURN", "F2",
# "LEFT", ...), char the text it types with the current SHIFT ("a", "A", "!"),
# or None. SHIFT gives upper case and the shifted symbol on number keys,
# as on a C64 in lower case mode; C= and CTRL are reported as modifiers.

import tca8418

# MATRIX[col][row]: key names as printed on the C64 keys
MATRIX = (
    ("DEL", "RETURN", "RIGHT", "F7", "F1", "F3", "F5", "DOWN"),
    ("3", "W", "A", "4", "Z", "S", "E", "LSHIFT"),
    ("5", "R", "D", "6", "C", "F", "T", "X"),
    ("7", "Y", "G", "8", "B", "H", "U", "V"),
    ("9", "I", "J", "0", "M", "K", "O", "N"),
    ("+", "P", "L", "-", ".", ":", "@", ","),
    ("£", "*", ";", "HOME", "RSHIFT", "=", "↑", "/"),
    ("1", "←", "CTRL", "2", "SPACE", "C=", "Q", "STOP"),
)
RESTORE = (0, 8)  # (row, col) on the TCA8418

# Shifted names of keys that are not letters
SHIFTED = {
    "1": "!", "2": '"', "3": "#", "4": "$", "5": "%", "6": "&", "7": "'",
    "8": "(", "9": ")", ":": "[", ";": "]", ",": "<", ".": ">", "/": "?",
    "DEL": "INST", "RIGHT": "LEFT", "DOWN": "UP", "HOME": "CLR",
    "F1": "F2", "F3": "F4", "F5": "F6", "F7": "F8", "STOP": "RUN",
}
# Text typed by non-letter keys; names missing here type nothing
TEXT = {"SPACE": " ", "↑": "^", "←": "_", "£": "£"}
for _k in "0123456789+-.:@,*;=/!\"#$%&'()[]<>?":
    TEXT[_k] = _k

SHIFT_KEYS = ("LSHIFT", "RSHIFT")
MODIFIERS = SHIFT_KEYS + ("C=", "CTRL")


class C64Keyboard:
    def __init__(self, i2c=None, addr=tca8418.ADDR):
        self.chip = tca8418.TCA8418(i2c, addr, rows=8, cols=9)
        self.held = set()        # modifier names held down
        self._down = {}          # (row, col) -> (name, char) given at press
        self._queue = []         # LVGL: (key code, pressed) not reported yet
        self._last = 0           # LVGL: last key code reported
        self.last = None         # last event from read(): (pressed, name, char)

    @property
    def shift(self):
        return any(k in self.held for k in SHIFT_KEYS)

    def name_at(self, row, col):
        if (row, col) == RESTORE:
            return "RESTORE"
        if row < 8 and col < 8:
            return MATRIX[col][row]
        return None

    def _decode(self, name):
        # (name, char) for a key pressed with the current modifiers
        if len(name) == 1 and "A" <= name <= "Z":
            return (name, name if self.shift else name.lower())
        if self.shift and name in SHIFTED:
            name = SHIFTED[name]
        return (name, TEXT.get(name))

    def read(self):
        # Key events since the last call: list of (pressed, name, char)
        out = []
        for pressed, row, col in self.chip.events():
            name = self.name_at(row, col)
            if name is None:
                continue
            if name in MODIFIERS:
                (self.held.add if pressed else self.held.discard)(name)
                out.append((pressed, name, None))
                continue
            if pressed:
                key = self._decode(name)
                self._down[(row, col)] = key
            else:  # the release matches the press, even if SHIFT changed
                key = self._down.pop((row, col), self._decode(name))
            out.append((pressed, key[0], key[1]))
        if out:
            self.last = out[-1]
        return out

    # --- LVGL ---

    def _lv_code(self, name, char):
        import lvgl as lv

        if char is not None:
            return ord(char)
        return {
            "RETURN": lv.KEY.ENTER, "DEL": lv.KEY.BACKSPACE,
            "LEFT": lv.KEY.LEFT, "RIGHT": lv.KEY.RIGHT, "UP": lv.KEY.UP,
            "DOWN": lv.KEY.DOWN, "HOME": lv.KEY.HOME, "CLR": lv.KEY.END,
            "STOP": lv.KEY.ESC, "RUN": lv.KEY.ESC,
        }.get(name)

    def lv_read_cb(self, indev, data):
        import lvgl as lv

        if not self._queue:
            for pressed, name, char in self.read():
                code = self._lv_code(name, char)
                if code is not None:
                    self._queue.append((code, pressed))
        if self._queue:
            self._last, pressed = self._queue.pop(0)
            data.state = lv.INDEV_STATE.PRESSED if pressed else lv.INDEV_STATE.RELEASED
        else:
            data.state = lv.INDEV_STATE.RELEASED
        data.key = self._last
        data.continue_reading = bool(self._queue)

    def lv_register(self, group=None):
        # A keypad input device sending keys to `group` (default: LVGL's
        # default group, created if missing). Widgets created after this
        # (text areas, buttons...) join the default group by themselves.
        import lvgl as lv

        if group is None:
            group = lv.group_get_default()
            if group is None:
                group = lv.group_create()
                group.set_default()
        indev = lv.indev_create()
        indev.set_type(lv.INDEV_TYPE.KEYPAD)
        indev.set_read_cb(self.lv_read_cb)
        indev.set_group(group)
        self.group = group
        return indev
