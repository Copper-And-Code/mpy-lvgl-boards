# Snake: eat the red squares, do not hit the walls or your own tail.
#
#   mpremote run examples/snake.py
#
# Touch control: tap the screen on the side you want to turn to. While the
# snake moves left/right, tap above or below its head; while it moves
# up/down, tap left or right of it. Tap to start, tap after a crash to play
# again. The snake gets faster as it grows.
#
# Each segment is a small LVGL object; at every step the tail object moves to
# the new head, so the cost per step does not grow with the length.
import random
import lvgl as lv
import display_driver
from machine import Pin, PWM

SOUND = True  # buzzer on GPIO1 (PWM)

W, H = display_driver.WIDTH, display_driver.HEIGHT
TOP = 18                       # score bar
CELL = 14
COLS = W // CELL
ROWS = (H - TOP) // CELL
X0 = (W - COLS * CELL) // 2
Y0 = TOP + (H - TOP - ROWS * CELL) // 2

START_MS, MIN_MS = 220, 90     # step period: from START_MS down to MIN_MS
CRASH_MS = 600

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
scr.set_style_bg_color(lv.color_hex(0x101010), 0)
scr.remove_flag(lv.obj.FLAG.SCROLLABLE)

field = lv.obj(scr)
field.remove_style_all()
field.set_size(COLS * CELL, ROWS * CELL)
field.set_pos(X0, Y0)
field.set_style_bg_color(lv.color_hex(0x203020), 0)
field.set_style_bg_opa(lv.OPA.COVER, 0)
field.remove_flag(lv.obj.FLAG.CLICKABLE)

score_label = lv.label(scr)
score_label.set_style_text_color(lv.color_hex(0xFFFFFF), 0)
score_label.align(lv.ALIGN.TOP_LEFT, 6, 1)

msg = lv.label(scr)
msg.set_style_text_color(lv.color_hex(0xFFFF60), 0)
msg.set_style_text_align(lv.TEXT_ALIGN.CENTER, 0)

# One style shared by all segments (less memory than per-object styles)
body_style = lv.style_t()
body_style.init()
body_style.set_bg_color(lv.color_hex(0x40E040))
body_style.set_bg_opa(lv.OPA.COVER)
body_style.set_radius(3)

food = lv.obj(field)
food.remove_style_all()
food.set_size(CELL - 2, CELL - 2)
food.set_style_bg_color(lv.color_hex(0xFF4040), 0)
food.set_style_bg_opa(lv.OPA.COVER, 0)
food.set_style_radius(lv.RADIUS_CIRCLE, 0)
food.remove_flag(lv.obj.FLAG.CLICKABLE)

pool = []      # segment objects, reused across games


def segment(i):
    while len(pool) <= i:
        s = lv.obj(field)
        s.remove_style_all()
        s.add_style(body_style, 0)
        s.set_size(CELL - 2, CELL - 2)
        s.remove_flag(lv.obj.FLAG.CLICKABLE)
        pool.append(s)
    return pool[i]


def place(obj, cell):
    obj.set_pos(cell[0] * CELL + 1, cell[1] * CELL + 1)


# The head: drawn over the head segment, round, with two eyes looking where
# the snake goes.
def disc(parent, size, color):
    o = lv.obj(parent)
    o.remove_style_all()
    o.set_size(size, size)
    o.set_style_bg_color(lv.color_hex(color), 0)
    o.set_style_bg_opa(lv.OPA.COVER, 0)
    o.set_style_radius(lv.RADIUS_CIRCLE, 0)
    o.remove_flag(lv.obj.FLAG.CLICKABLE)
    return o


head_obj = disc(field, CELL + 2, 0x80FF60)
head_obj.set_style_border_width(1, 0)
head_obj.set_style_border_color(lv.color_hex(0x208020), 0)
EYE, PUPIL = CELL // 3, CELL // 6
eyes = [disc(head_obj, EYE, 0xFFFFFF) for _ in range(2)]
pupils = [disc(e, PUPIL, 0x000000) for e in eyes]


def place_head(cell, d):
    head_obj.set_pos(cell[0] * CELL - 1, cell[1] * CELL - 1)
    head_obj.move_foreground()
    c = (CELL + 2) // 2
    px, py = -d[1], d[0]  # perpendicular to the direction
    for k, side in enumerate((-1, 1)):
        ex = c + d[0] * (CELL // 6) + side * px * (CELL // 4) - EYE // 2
        ey = c + d[1] * (CELL // 6) + side * py * (CELL // 4) - EYE // 2
        eyes[k].set_pos(ex, ey)
        m = (EYE - PUPIL) // 2  # the pupil looks forward
        pupils[k].set_pos(m + d[0] * m, m + d[1] * m)


# --- game ---
# State: "idle", "run", "over". body[0] is the tail, body[-1] the head;
# segs[k] is the object drawn at body[k].
state = "idle"
body = []
segs = []
occupied = set()
direction = (1, 0)
turns = []     # taps not applied yet (at most 2)
food_cell = None
score = 0
best = 0
period = START_MS
elapsed = 0
crash_left = 0


def show_score():
    score_label.set_text("Score %d   Best %d" % (score, best))


def show_msg(text):
    msg.set_text(text)
    msg.center()
    msg.remove_flag(lv.obj.FLAG.HIDDEN)


def new_food():
    global food_cell
    free = [(x, y) for x in range(COLS) for y in range(ROWS) if (x, y) not in occupied]
    if not free:
        return False
    food_cell = random.choice(free)
    place(food, food_cell)
    return True


def new_game():
    global state, body, segs, direction, score, period, elapsed
    for s in pool:
        s.add_flag(lv.obj.FLAG.HIDDEN)
    y = ROWS // 2
    body = [(2, y), (3, y), (4, y)]
    segs = [segment(k) for k in range(3)]
    occupied.clear()
    for c, s in zip(body, segs):
        occupied.add(c)
        place(s, c)
        s.remove_flag(lv.obj.FLAG.HIDDEN)
    direction = (1, 0)
    turns.clear()
    place_head(body[-1], direction)
    score, period, elapsed = 0, START_MS, 0
    new_food()
    show_score()
    msg.add_flag(lv.obj.FLAG.HIDDEN)
    state = "run"


def crash():
    global state, best, crash_left
    state = "over"
    best = max(best, score)
    show_score()
    show_msg("Game over\nScore %d\nTap to play" % score)
    crash_left = CRASH_MS


def step():
    global direction, score, period
    if turns:
        direction = turns.pop(0)
    hx, hy = body[-1]
    head = (hx + direction[0], hy + direction[1])
    eat = head == food_cell
    if not (0 <= head[0] < COLS and 0 <= head[1] < ROWS) or (head in occupied and (eat or head != body[0])):
        crash()
        return
    if eat:
        s = segment(len(segs))  # grow: a new object for the head
        s.remove_flag(lv.obj.FLAG.HIDDEN)
        score += 1
        period = max(MIN_MS, START_MS - 8 * score)
        show_score()
        tone(880)
    else:
        occupied.discard(body.pop(0))  # move: the tail object becomes the head
        s = segs.pop(0)
        quiet()
    body.append(head)
    segs.append(s)
    occupied.add(head)
    place(s, head)
    place_head(head, direction)
    if eat and not new_food():
        crash()  # the field is full: you won


def on_tick(timer):
    global elapsed, crash_left
    if state == "over":
        if crash_left > 0:  # crash sound: broken siren falling from 1000 to 200 Hz
            crash_left = max(0, crash_left - 20)
            if crash_left and (crash_left // 60) % 2:
                tone(200 + 800 * crash_left // CRASH_MS)
            else:
                quiet()
        return
    if state != "run":
        return
    elapsed += 20
    if elapsed >= period:
        elapsed = 0
        step()


point = lv.point_t()


def on_press(e):
    if state != "run":
        if state == "idle" or crash_left == 0:
            new_game()
        return
    if len(turns) >= 2:
        return
    lv.indev_active().get_point(point)
    hx, hy = body[-1]
    dx = point.x - (X0 + hx * CELL + CELL // 2)
    dy = point.y - (Y0 + hy * CELL + CELL // 2)
    cur = turns[-1] if turns else direction
    if cur[0]:  # moving left/right: turn up or down
        turns.append((0, 1 if dy > 0 else -1))
    else:       # moving up/down: turn left or right
        turns.append((1 if dx > 0 else -1, 0))


scr.add_event_cb(on_press, lv.EVENT.PRESSED, None)

show_score()
show_msg("Snake\nTap to start")
timer = lv.timer_create(on_tick, 20, None)
lv.screen_load(scr)
