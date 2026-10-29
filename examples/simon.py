# Simon: repeat the sequence of colours, one more at every round.
#
#   mpremote run examples/simon.py
#
# Tap the centre to start. The microcontroller plays the sequence (pads light
# up, the buzzer on GPIO1 plays a note for each colour); then tap the pads in
# the same order. A mistake ends the game. The sequence gets faster as it grows.
#
# Timing runs from an LVGL timer, so the screen and touch stay responsive.
import random
import lvgl as lv
import display_driver
from machine import Pin, PWM

SOUND = True  # buzzer on GPIO1 (PWM)

W, H = display_driver.WIDTH, display_driver.HEIGHT

# colour when off, colour when lit, note (Hz)
PADS = (
    (0x006000, 0x30FF30, 415),  # green, top left
    (0x700000, 0xFF3030, 310),  # red, top right
    (0x706000, 0xFFF040, 252),  # yellow, bottom left
    (0x000070, 0x4060FF, 209),  # blue, bottom right
)
ERROR_MS = 600  # error sound: a broken siren falling from 1000 to 200 Hz

# --- sound ---
buzzer = None


def tone(freq):
    global buzzer
    if not SOUND:
        return
    if buzzer is None:
        buzzer = PWM(Pin(1), freq=freq, duty_u16=0)
    buzzer.freq(freq)
    buzzer.duty_u16(32768)


def quiet():
    if buzzer is not None:
        buzzer.duty_u16(0)


# --- screen ---
scr = lv.obj()
scr.set_style_bg_color(lv.color_hex(0x000000), 0)
scr.remove_flag(lv.obj.FLAG.SCROLLABLE)

size = min(W, H)
gap = size // 30
pad_size = (size - 3 * gap) // 2
x0 = (W - size) // 2 + gap
y0 = (H - size) // 2 + gap
pads = []

for i, (off, on, note) in enumerate(PADS):
    p = lv.button(scr)
    p.set_size(pad_size, pad_size)
    p.set_pos(x0 + (i % 2) * (pad_size + gap), y0 + (i // 2) * (pad_size + gap))
    p.set_style_radius(pad_size // 4, 0)
    p.set_style_bg_color(lv.color_hex(off), 0)
    p.set_style_bg_color(lv.color_hex(on), lv.STATE.PRESSED)
    p.set_style_shadow_width(0, 0)
    pads.append(p)

centre = lv.button(scr)
centre.set_size(size // 3, size // 3)
centre.center()
centre.set_style_radius(lv.RADIUS_CIRCLE, 0)
centre.set_style_bg_color(lv.color_hex(0x303030), 0)
centre.set_style_border_width(gap, 0)
centre.set_style_border_color(lv.color_hex(0x000000), 0)
centre.set_style_shadow_width(0, 0)
centre_label = lv.label(centre)
centre_label.set_style_text_color(lv.color_hex(0xFFFFFF), 0)
centre_label.set_style_text_align(lv.TEXT_ALIGN.CENTER, 0)
centre_label.center()


def light(i, on):
    pads[i].set_style_bg_color(lv.color_hex(PADS[i][1 if on else 0]), 0)
    if on:
        tone(PADS[i][2])
    else:
        quiet()


# --- game ---
# States: "idle" (waiting for the centre), "show" (the MCU plays the
# sequence), "input" (the player repeats it), "over".
state = "idle"
sequence = []
pos = 0       # next step to show or to repeat
best = 0
wait = 0      # ms left before the next "show" step
lit = False   # a pad is lit during "show"
TICK = 20     # ms, period of the game timer


def step_times():
    # (lit, dark) in ms: faster after rounds 5, 9 and 13
    n = len(sequence)
    if n < 5:
        return 420, 180
    if n < 9:
        return 320, 130
    if n < 13:
        return 240, 100
    return 180, 80


def set_centre(text):
    centre_label.set_text(text)
    centre_label.center()


def next_round():
    global state, pos, wait, lit
    sequence.append(random.randrange(4))
    set_centre(str(len(sequence)))
    state, pos, wait, lit = "show", 0, 700, False


def game_over():
    global state, best
    state = "over"
    best = max(best, len(sequence) - 1)
    set_centre("Score %d\nBest %d\nTap" % (len(sequence) - 1, best))
    for i in range(4):
        light(i, False)


def on_tick(timer):
    global state, pos, wait, lit
    if state == "over" and wait == 0:
        return
    wait = max(0, wait - TICK)
    if state == "over":  # error sound, then silence
        if wait and (wait // 60) % 2:
            tone(200 + 800 * wait // ERROR_MS)
        else:
            quiet()
        return
    if wait:
        return
    if state != "show":
        return
    on_ms, off_ms = step_times()
    if lit:  # switch the pad off, then wait
        light(sequence[pos], False)
        lit = False
        pos += 1
        wait = off_ms
        if pos == len(sequence):
            state, pos = "input", 0
            set_centre("Go!")
    else:
        light(sequence[pos], True)
        lit = True
        wait = on_ms


def on_pad(e, i):
    global state, pos, wait
    if state != "input":
        return
    code = e.get_code()
    if code == lv.EVENT.PRESSED:
        tone(PADS[i][2])
        return
    quiet()  # RELEASED
    if i != sequence[pos]:
        wait = ERROR_MS
        game_over()
        return
    pos += 1
    if pos == len(sequence):
        next_round()


def on_centre(e):
    global state
    if state in ("idle", "over"):
        sequence.clear()
        quiet()
        next_round()


for i, p in enumerate(pads):
    p.add_event_cb(lambda e, i=i: on_pad(e, i), lv.EVENT.PRESSED, None)
    p.add_event_cb(lambda e, i=i: on_pad(e, i), lv.EVENT.RELEASED, None)
centre.add_event_cb(on_centre, lv.EVENT.CLICKED, None)

set_centre("Simon\nTap")
timer = lv.timer_create(on_tick, TICK, None)
lv.screen_load(scr)
