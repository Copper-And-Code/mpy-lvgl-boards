# Breakout: break all the bricks with the ball, do not let it fall.
#
#   mpremote run examples/breakout.py
#
# Drag your finger anywhere on the screen to move the paddle; lift it to
# launch the ball. Where the ball hits the paddle sets its angle: the edges
# send it sideways. 3 lives; every cleared wall comes back faster.
import math
import lvgl as lv
import buzzer
import display_driver
import ui

SOUND = True  # the board's buzzer, if it has one (buzzer.py)

# Sizes for a 240 px display, scaled by ui.px(); the wall gets more columns on
# a wide display, speeds scale with the display.
W, H = display_driver.WIDTH, display_driver.HEIGHT
px_ = ui.px
TOP = px_(18)                  # score bar
TICK = 20                      # ms, period of the game timer

COLS, ROWS = max(8, int(8 * W / H + 0.5)), 5
MARGIN, GAP = px_(4), px_(2)
BW = (W - 2 * MARGIN - (COLS - 1) * GAP) // COLS
BH = px_(10)
BX0 = (W - (COLS * BW + (COLS - 1) * GAP)) // 2
BY0 = TOP + px_(14)
ROW_COLORS = (0xF44336, 0xFF9800, 0xFFEB3B, 0x4CAF50, 0x2196F3)
ROW_NOTES = (880, 784, 659, 587, 523)

PW, PH = W // 5, px_(6)        # paddle
PY = H - px_(16)
BALL = px_(6)
SPEED0 = 2.6 * ui.UNIT         # px per tick at level 1

# --- sound (silent on boards without a buzzer) ---
def beep(freq, ms=40):
    if SOUND:
        buzzer.beep(freq, ms)


# --- screen ---
scr = lv.obj()
scr.set_style_bg_color(lv.color_hex(0x000010), 0)
scr.remove_flag(lv.obj.FLAG.SCROLLABLE)
scr.set_style_text_font(ui.font(14), 0)


def box(w, h, color, radius=2):
    o = lv.obj(scr)
    o.remove_style_all()
    o.set_size(w, h)
    o.set_style_bg_color(lv.color_hex(color), 0)
    o.set_style_bg_opa(lv.OPA.COVER, 0)
    o.set_style_radius(px_(radius) if radius != lv.RADIUS_CIRCLE else radius, 0)
    o.remove_flag(lv.obj.FLAG.CLICKABLE)
    return o


score_label = lv.label(scr)
score_label.set_style_text_color(lv.color_hex(0xFFFFFF), 0)
score_label.align(lv.ALIGN.TOP_LEFT, px_(6), px_(1))

msg = lv.label(scr)
msg.set_style_text_color(lv.color_hex(0xFFFF60), 0)
msg.set_style_text_align(lv.TEXT_ALIGN.CENTER, 0)

bricks = []    # bricks[row][col]: the object, or None once broken
for r in range(ROWS):
    row = []
    for c in range(COLS):
        b = box(BW, BH, ROW_COLORS[r])
        b.set_pos(BX0 + c * (BW + GAP), BY0 + r * (BH + GAP))
        row.append(b)
    bricks.append(row)
alive = [[True] * COLS for _ in range(ROWS)]

paddle = box(PW, PH, 0xE0E0E0, 3)
ball = box(BALL, BALL, 0xFFFFFF, lv.RADIUS_CIRCLE)

# --- game ---
# State: "serve" (ball on the paddle), "play", "over".
state = "serve"
px = (W - PW) / 2              # paddle left edge
bx = by = 0.0                  # ball top-left
vx = vy = 0.0
speed = SPEED0
level = 1
score = 0
lives = 3
left = ROWS * COLS             # bricks still standing
over_wait = 0                  # ms before a tap restarts after game over


def show_score():
    score_label.set_text("Score %d   Lives %d   Level %d" % (score, lives, level))


def show_msg(text):
    if text:
        msg.set_text(text)
        msg.align(lv.ALIGN.CENTER, 0, px_(30))
        msg.remove_flag(lv.obj.FLAG.HIDDEN)
    else:
        msg.add_flag(lv.obj.FLAG.HIDDEN)


def draw():
    paddle.set_pos(int(px), PY)
    ball.set_pos(int(bx), int(by))


def reset_wall():
    global left
    for r in range(ROWS):
        for c in range(COLS):
            alive[r][c] = True
            bricks[r][c].remove_flag(lv.obj.FLAG.HIDDEN)
    left = ROWS * COLS


def serve():
    global state, bx, by
    state = "serve"
    bx = px + (PW - BALL) / 2
    by = PY - BALL - 1
    draw()


def new_game():
    global score, lives, level, speed
    score, lives, level, speed = 0, 3, 1, SPEED0
    reset_wall()
    show_score()
    show_msg("Drag to move\nlift to launch")
    serve()


def launch():
    global state, vx, vy
    state = "play"
    angle = math.radians(60)   # 30 degrees from vertical, to the right
    vx, vy = speed * math.cos(angle), -speed * math.sin(angle)
    show_msg("")


def brick_at(x, y):
    # (row, col) of a standing brick containing the point, or None
    c = int((x - BX0) // (BW + GAP))
    r = int((y - BY0) // (BH + GAP))
    if 0 <= r < ROWS and 0 <= c < COLS and alive[r][c]:
        if x - BX0 - c * (BW + GAP) < BW and y - BY0 - r * (BH + GAP) < BH:
            return r, c
    return None


def on_tick(timer):
    global bx, by, vx, vy, state, score, lives, level, speed, left
    global over_wait
    over_wait = max(0, over_wait - TICK)
    if state != "play":
        return
    nx, ny = bx + vx, by + vy
    # walls
    if nx < 0:
        nx, vx = -nx, -vx
        beep(220, 20)
    elif nx > W - BALL:
        nx, vx = 2 * (W - BALL) - nx, -vx
        beep(220, 20)
    if ny < TOP:
        ny, vy = 2 * TOP - ny, -vy
        beep(220, 20)
    # paddle: only when falling and crossing its top edge
    if vy > 0 and by + BALL <= PY <= ny + BALL and px - BALL < nx < px + PW:
        hit = ((nx + BALL / 2) - (px + PW / 2)) / (PW / 2)  # -1 .. 1
        hit = max(-1.0, min(1.0, hit))
        angle = math.radians(90 - 60 * hit)                   # 30..150 degrees
        vx, vy = speed * math.cos(angle), -speed * math.sin(angle)
        ny = PY - BALL
        beep(440, 30)
    # bricks: test the ball's centre, bounce on the side it came from
    cx, cy = nx + BALL / 2, ny + BALL / 2
    hit = brick_at(cx, cy)
    if hit:
        r, c = hit
        alive[r][c] = False
        bricks[r][c].add_flag(lv.obj.FLAG.HIDDEN)
        left -= 1
        score += (ROWS - r) * level
        left_x = BX0 + c * (BW + GAP)
        if left_x <= bx + BALL / 2 <= left_x + BW:
            vy = -vy  # came from above or below
        else:
            vx = -vx  # came from the side
        nx, ny = bx, by
        beep(ROW_NOTES[r], 40)
        show_score()
        if left == 0:  # wall cleared: next level, faster
            level += 1
            speed = SPEED0 * (1 + 0.15 * (level - 1))
            reset_wall()
            show_score()
            show_msg("Level %d" % level)
            serve()
            return
    bx, by = nx, ny
    # lost the ball
    if by > H:
        lives -= 1
        show_score()
        beep(110, 300)
        if lives == 0:
            state, over_wait = "over", 1000
            show_msg("Game over\nScore %d\nTap to play" % score)
            return
        serve()
        return
    draw()


point = lv.point_t()


def on_touch(e):
    global px
    code = e.get_code()
    if state == "over":
        if code == lv.EVENT.RELEASED and over_wait == 0:
            new_game()
        return
    indev = lv.indev_active()
    if indev is None:
        return
    if code == lv.EVENT.RELEASED:
        if state == "serve":
            launch()
        return
    indev.get_point(point)
    px = max(0, min(W - PW, point.x - PW // 2))
    if state == "serve":
        serve()
    else:
        paddle.set_pos(int(px), PY)


scr.add_event_cb(on_touch, lv.EVENT.PRESSED, None)
scr.add_event_cb(on_touch, lv.EVENT.PRESSING, None)
scr.add_event_cb(on_touch, lv.EVENT.RELEASED, None)

new_game()
timer = lv.timer_create(on_tick, TICK, None)
lv.screen_load(scr)
