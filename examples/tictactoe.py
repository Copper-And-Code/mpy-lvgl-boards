# Tic-tac-toe: you (X) against the microcontroller (O).
#
#   mpremote run examples/tictactoe.py
#
# Tap a cell to play. The microcontroller answers with a minimax search
# (alpha-beta pruning): it never loses. Who starts alternates every game.
# When a game is over, tap the board to start the next one.
import time
import lvgl as lv
import display_driver

W, H = display_driver.WIDTH, display_driver.HEIGHT

LINES = ((0, 1, 2), (3, 4, 5), (6, 7, 8),
         (0, 3, 6), (1, 4, 7), (2, 5, 8),
         (0, 4, 8), (2, 4, 6))
USER, MCU, EMPTY = "X", "O", ""
COLORS = {USER: 0x2196F3, MCU: 0xF44336}

board = [EMPTY] * 9
score = {USER: 0, MCU: 0, "draw": 0}
user_starts = True
game_over = False


def winner(b):
    for i, j, k in LINES:
        if b[i] != EMPTY and b[i] == b[j] == b[k]:
            return b[i]
    return "draw" if EMPTY not in b else None


# Minimax with alpha-beta: score > 0 is good for the MCU, quicker wins score
# more, slower losses score less.
def minimax(b, player, depth, alpha, beta):
    w = winner(b)
    if w == MCU:
        return 10 - depth
    if w == USER:
        return depth - 10
    if w == "draw":
        return 0
    if player == MCU:
        best = -100
        for i in range(9):
            if b[i] == EMPTY:
                b[i] = MCU
                best = max(best, minimax(b, USER, depth + 1, alpha, beta))
                b[i] = EMPTY
                alpha = max(alpha, best)
                if alpha >= beta:
                    break
        return best
    best = 100
    for i in range(9):
        if b[i] == EMPTY:
            b[i] = USER
            best = min(best, minimax(b, MCU, depth + 1, alpha, beta))
            b[i] = EMPTY
            beta = min(beta, best)
            if alpha >= beta:
                break
    return best


def mcu_move():
    # Openings, no need to search: the centre, or a corner if it is taken.
    if board.count(EMPTY) >= 8:
        return 4 if board[4] == EMPTY else 0
    best, move = -100, None
    for i in (4, 0, 2, 6, 8, 1, 3, 5, 7):  # centre and corners first
        if board[i] == EMPTY:
            board[i] = MCU
            s = minimax(board, USER, 1, -100, 100)
            board[i] = EMPTY
            if s > best:
                best, move = s, i
    return move


# --- screen ---
scr = lv.obj()
scr.set_style_bg_color(lv.color_hex(0x202020), 0)
scr.remove_flag(lv.obj.FLAG.SCROLLABLE)

status = lv.label(scr)
status.set_style_text_color(lv.color_hex(0xFFFFFF), 0)
status.align(lv.ALIGN.TOP_LEFT, 8, 4)

points = lv.label(scr)
points.set_style_text_color(lv.color_hex(0xA0A0A0), 0)
points.align(lv.ALIGN.TOP_RIGHT, -8, 4)

top = 24
side = min(W, H - top) - 8
gap = 4
cell = (side - 2 * gap) // 3
x0 = (W - (3 * cell + 2 * gap)) // 2
cells = []
marks = []


def on_cell(e, i):
    global game_over
    if game_over:
        new_game()
        return
    if board[i] != EMPTY:
        return
    play(i, USER)
    if not game_over:
        status.set_text("Thinking...")
        lv.refr_now(None)  # show the user's move before the search
        play(mcu_move(), MCU)


for i in range(9):
    c = lv.button(scr)
    c.set_size(cell, cell)
    c.set_pos(x0 + (i % 3) * (cell + gap), top + (i // 3) * (cell + gap))
    c.set_style_bg_color(lv.color_hex(0xEEEEEE), 0)
    c.set_style_radius(6, 0)
    c.set_style_shadow_width(0, 0)
    m = lv.label(c)
    m.set_style_text_font(lv.font_montserrat_24, 0)
    m.center()
    c.add_event_cb(lambda e, i=i: on_cell(e, i), lv.EVENT.CLICKED, None)
    cells.append(c)
    marks.append(m)


def show_status(text):
    status.set_text(text)
    points.set_text("You %d  MCU %d  = %d" % (score[USER], score[MCU], score["draw"]))


def play(i, player):
    global game_over
    board[i] = player
    marks[i].set_text(player)
    marks[i].set_style_text_color(lv.color_hex(COLORS[player]), 0)
    w = winner(board)
    if w is None:
        show_status("Your turn")
        return
    game_over = True
    score[w] += 1
    if w == "draw":
        show_status("Draw!")
    else:
        for line in LINES:
            if all(board[k] == w for k in line):
                for k in line:
                    cells[k].set_style_bg_color(lv.color_hex(0xFFEB3B), 0)
        show_status("You win!" if w == USER else "I win!")


def new_game():
    global game_over, user_starts
    for i in range(9):
        board[i] = EMPTY
        marks[i].set_text("")
        cells[i].set_style_bg_color(lv.color_hex(0xEEEEEE), 0)
    game_over = False
    if user_starts:
        show_status("Your turn")
    else:
        play(mcu_move(), MCU)
    user_starts = not user_starts


lv.screen_load(scr)
new_game()
