# Host test, unix port with LVGL: keys from a software TCA8418 reach a
# focused lv.textarea through C64Keyboard.lv_register().
#   cd tests/host && micropython-lvgl test_c64keyboard_lvgl.py
# Also runs on the board (mpremote cp fake_tca8418.py first): there LVGL's
# tick is the real clock, so run() also sleeps.
import sys
import time

sys.path.insert(0, "../../python")
sys.path.insert(0, ".")
import lvgl as lv
import display_driver  # unix stand-in in this directory
from fake_tca8418 import FakeTCA8418
import c64keyboard

LSHIFT, DEL, RETURN = (7, 1), (0, 0), (1, 0)
KEYS = {}
for col in range(8):
    for row in range(8):
        KEYS[c64keyboard.MATRIX[col][row]] = (row, col)

chip = FakeTCA8418()
kb = c64keyboard.C64Keyboard(chip)
kb.lv_register()

scr = lv.obj()
ta = lv.textarea(scr)  # joins the default group created by lv_register()
lv.screen_load(scr)
lv.group_focus_obj(ta)


def run(ms=200):
    for _ in range(ms // 10):
        lv.tick_inc(10)
        lv.timer_handler()
        time.sleep_ms(10)


def type_text(text):
    for ch in text:
        if ch == "\n":
            chip.tap(*RETURN)
        elif ch == "\b":
            chip.tap(*DEL)
        elif ch.isupper() or ch in '!"#$%&\'()[]<>?':
            base = {"!": "1", '"': "2", "#": "3", "$": "4", "%": "5", "&": "6", "'": "7",
                    "(": "8", ")": "9", "[": ":", "]": ";", "<": ",", ">": ".", "?": "/"}.get(ch, ch)
            chip.key(*LSHIFT, True)
            chip.tap(*KEYS[base.upper()])
            chip.key(*LSHIFT, False)
        else:
            chip.tap(*KEYS["SPACE" if ch == " " else ch.upper()])
        run(60)


type_text("Hello, C64!\nready.\bX")
text = ta.get_text()
print(repr(text))
assert text == "Hello, C64!\nreadyX", text
print("test_c64keyboard_lvgl: OK")
