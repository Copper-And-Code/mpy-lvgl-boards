# Pong: you (left paddle) against the microcontroller (right paddle).
#
#   mpremote run examples/pong.py
#
# Drag your finger up and down anywhere on the screen to move your paddle.
# Where the ball hits a paddle sets its angle; every hit makes it a little
# faster. First to 7 points wins; tap to play again.
#
# The microcontroller's paddle has a top speed and aims with a small random
# error, so it can be beaten.
import math
import random
import lvgl as lv
import buzzer
import display_driver
import ui

SOUND = True  # the board's buzzer, if it has one (buzzer.py)

# Sizes and speeds for a 240 px display, scaled by ui.px() / ui.UNIT.
W, H = display_driver.WIDTH, display_driver.HEIGHT
px_ = ui.px
TICK = 20                      # ms, period of the game timer
WIN = 7                        # points to win

PW, PH = px_(6), H // 5        # paddles
PX_USER, PX_MCU = px_(8), W - px_(8) - PW
BALL = px_(6)
SPEED0, SPEED_MAX = 2.8 * ui.UNIT, 6.0 * ui.UNIT   # px per tick
MCU_SPEED = 2.4 * ui.UNIT      # px per tick, top speed of the MCU paddle
MCU_ERROR = PH // 3            # px, aim error

# --- sound (silent on boards without a buzzer) ---
def beep(freq, ms=40):
    if SOUND:
        buzzer.beep(freq, ms)


# --- screen ---
scr = lv.obj()
scr.set_style_bg_color(lv.color_hex(0x000000), 0)
scr.remove_flag(lv.obj.FLAG.SCROLLABLE)


def box(w, h, color, radius=0):
    o = lv.obj(scr)
    o.remove_style_all()
    o.set_size(w, h)
    o.set_style_bg_color(lv.color_hex(color), 0)
    o.set_style_bg_opa(lv.OPA.COVER, 0)
    o.set_style_radius(px_(radius) if radius != lv.RADIUS_CIRCLE else radius, 0)
    o.remove_flag(lv.obj.FLAG.CLICKABLE)
    return o


for y in range(0, H, px_(12)):  # dashed centre line
    box(px_(2), px_(6), 0x404040).set_pos(W // 2 - px_(1), y + px_(3))


def score_label(x_offset):
    lbl = lv.label(scr)
    lbl.set_style_text_color(lv.color_hex(0x808080), 0)
    lbl.set_style_text_font(ui.font(24), 0)
    lbl.align(lv.ALIGN.TOP_MID, x_offset, px_(6))
    return lbl


user_label = score_label(-W // 6)
mcu_label = score_label(W // 6)

msg = lv.label(scr)
msg.set_style_text_color(lv.color_hex(0xFFFF60), 0)
msg.set_style_text_align(lv.TEXT_ALIGN.CENTER, 0)
msg.set_style_text_font(ui.font(14), 0)

user_paddle = box(PW, PH, 0x40C0FF, 2)
mcu_paddle = box(PW, PH, 0xFF6040, 2)
ball = box(BALL, BALL, 0xFFFFFF, lv.RADIUS_CIRCLE)

# --- game ---
# State: "wait" (pause before a serve), "play", "over".
state = "wait"
uy = my = (H - PH) / 2         # paddle tops
bx = by = 0.0                  # ball top-left
vx = vy = 0.0
speed = SPEED0
points = [0, 0]                # user, MCU
wait = 0                       # ms left in "wait" / before a restart in "over"
serve_dir = -1                 # -1: towards the user, 1: towards the MCU
mcu_aim = 0                    # aim error for the current rally


def show_scores():
    user_label.set_text(str(points[0]))
    mcu_label.set_text(str(points[1]))


def show_msg(text):
    if text:
        msg.set_text(text)
        msg.align(lv.ALIGN.CENTER, 0, 0)
        msg.remove_flag(lv.obj.FLAG.HIDDEN)
    else:
        msg.add_flag(lv.obj.FLAG.HIDDEN)


def draw():
    user_paddle.set_pos(PX_USER, int(uy))
    mcu_paddle.set_pos(PX_MCU, int(my))
    ball.set_pos(int(bx), int(by))


def new_point(direction):
    global state, bx, by, vx, vy, speed, wait, serve_dir, mcu_aim
    state, wait, serve_dir = "wait", 1000, direction
    speed = SPEED0
    bx, by = (W - BALL) / 2, (H - BALL) / 2
    vx = vy = 0.0
    mcu_aim = random.randint(-MCU_ERROR, MCU_ERROR)
    draw()


def new_game():
    points[0] = points[1] = 0
    show_scores()
    show_msg("")
    new_point(random.choice((-1, 1)))


def bounce(paddle_y, direction):
    # new velocity after a paddle hit: the angle depends on where it hit
    global vx, vy, speed, mcu_aim
    speed = min(SPEED_MAX, speed * 1.06)
    hit = ((by + BALL / 2) - (paddle_y + PH / 2)) / (PH / 2)  # -1 .. 1
    angle = math.radians(55 * max(-1.0, min(1.0, hit)))
    vx, vy = direction * speed * math.cos(angle), speed * math.sin(angle)
    mcu_aim = random.randint(-MCU_ERROR, MCU_ERROR)


def move_mcu():
    global my
    if vx > 0 and bx > W * 0.35:   # ball coming: follow it, with the aim error
        target = by + BALL / 2 - PH / 2 + mcu_aim
    else:                          # otherwise drift back to the middle
        target = (H - PH) / 2
    d = max(-MCU_SPEED, min(MCU_SPEED, target - my))
    my = max(0, min(H - PH, my + d))


def on_tick(timer):
    global state, bx, by, vx, vy, wait
    wait = max(0, wait - TICK)
    if state == "wait":
        if wait == 0:  # serve, 30 degrees up or down
            state = "play"
            a = math.radians(random.choice((-30, -20, 20, 30)))
            vx, vy = serve_dir * speed * math.cos(a), speed * math.sin(a)
        move_mcu()
        draw()
        return
    if state != "play":
        return
    move_mcu()
    nx, ny = bx + vx, by + vy
    if ny < 0:                      # top and bottom walls
        ny, vy = -ny, -vy
        beep(220, 20)
    elif ny > H - BALL:
        ny, vy = 2 * (H - BALL) - ny, -vy
        beep(220, 20)
    bx, by = nx, ny
    # paddles: when the ball crosses their inner edge
    if vx < 0 and bx <= PX_USER + PW <= bx - vx and uy - BALL < by < uy + PH:
        bx = PX_USER + PW
        bounce(uy, 1)
        beep(440, 30)
    elif vx > 0 and bx + BALL >= PX_MCU >= bx + BALL - vx and my - BALL < by < my + PH:
        bx = PX_MCU - BALL
        bounce(my, -1)
        beep(330, 30)
    # points
    if bx < -BALL or bx > W:
        who = 1 if bx < 0 else 0
        points[who] += 1
        show_scores()
        if points[who] >= WIN:
            state, wait = "over", 1000
            show_msg(("You win!" if who == 0 else "I win!") + "\nTap to play")
            beep(880 if who == 0 else 110, 400)
            return
        beep(660 if who == 0 else 165, 150)
        new_point(1 if who == 0 else -1)  # serve towards whoever lost the point
        return
    draw()


point = lv.point_t()


def on_touch(e):
    global uy
    code = e.get_code()
    if state == "over":
        if code == lv.EVENT.RELEASED and wait == 0:
            new_game()
        return
    if code == lv.EVENT.RELEASED:
        return
    indev = lv.indev_active()
    if indev is None:
        return
    indev.get_point(point)
    uy = max(0, min(H - PH, point.y - PH // 2))
    user_paddle.set_pos(PX_USER, int(uy))


scr.add_event_cb(on_touch, lv.EVENT.PRESSED, None)
scr.add_event_cb(on_touch, lv.EVENT.PRESSING, None)
scr.add_event_cb(on_touch, lv.EVENT.RELEASED, None)

new_game()
timer = lv.timer_create(on_tick, TICK, None)
lv.screen_load(scr)
