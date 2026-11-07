# An ANSI terminal on the display: a character grid drawn on an LVGL canvas, receiving
# everything MicroPython prints (through os.dupterm), so a program only has to write text
# and escape sequences, as on a VT100:
#
#   import ansiterm
#   ansiterm.start()
#   print("\x1b[2J\x1b[H\x1b[1;33mhello\x1b[0m at the top left, in yellow")
#
# The keyboard is the one of the serial port, which keeps receiving the output too. The
# grid is 8x16 cells: 60x30 at 480x480. shell.py runs on it; so can a full-screen editor,
# which gets its size from ansiterm.term.cols and .rows, or by asking with ESC[6n.
#
# Sequences: cursor (A B C D E F G H d f s u, ESC 7/8), erase (J K X), insert and delete
# (L M @ P), scroll region (r, S, T, ESC D/E/M), colours (m: 16 colours, 256 with 38;5 and
# 48;5, bold, reverse), ?25 cursor, ?7 wrap, ?1049 alternate screen, 5n/6n/c reports.
# Text is ASCII: anything else is drawn as a "?".
#
# The font is in ansifont.py, under its own license.
import io
import micropython
import os
from array import array

import lvgl as lv
import display_driver
from ansifont import FONT

CELL_W, CELL_H = 8, 16
FG, BG = 7, 0  # default colours, palette indexes


def palette():
    """The 256 xterm colours as RGB565."""
    base = (
        0x000000, 0xCC3333, 0x33BB33, 0xCCAA22, 0x3366DD, 0xBB44BB, 0x22AAAA, 0xCCCCCC,
        0x666666, 0xFF6666, 0x66EE66, 0xFFEE66, 0x7799FF, 0xFF77FF, 0x66EEEE, 0xFFFFFF,
    )
    rgb = list(base)
    levels = (0, 95, 135, 175, 215, 255)
    for r in levels:
        for g in levels:
            for b in levels:
                rgb.append(r << 16 | g << 8 | b)
    for i in range(24):
        v = 8 + i * 10
        rgb.append(v << 16 | v << 8 | v)
    return array("H", [(c >> 8 & 0xF800) | (c >> 5 & 0x07E0) | (c >> 3 & 0x001F) for c in rgb])


# Viper takes four arguments at most: p is [first pixel, stride, ...].
@micropython.viper
def _paint(fb: ptr16, font: ptr8, p: ptr32):
    """A glyph: p = [first pixel, stride, offset in the font, fg, bg]."""
    o = int(p[0])
    stride = int(p[1])
    g = int(p[2])
    fg = int(p[3])
    bg = int(p[4])
    end = g + 16
    while g < end:
        bits = int(font[g])
        i = o
        last = o + 8
        while i < last:
            if bits & 0x80:
                fb[i] = fg
            else:
                fb[i] = bg
            bits <<= 1
            i += 1
        o += stride
        g += 1


@micropython.viper
def _fill(fb: ptr16, p: ptr32):
    """A rectangle: p = [first pixel, stride, width, height, colour]."""
    o = int(p[0])
    stride = int(p[1])
    w = int(p[2])
    h = int(p[3])
    c = int(p[4])
    while h > 0:
        i = o
        last = o + w
        while i < last:
            fb[i] = c
            i += 1
        o += stride
        h -= 1


class Terminal(io.IOBase):
    def __init__(self):
        self.cols = display_driver.WIDTH // CELL_W
        self.rows = display_driver.HEIGHT // CELL_H
        self.w, self.h = self.cols * CELL_W, self.rows * CELL_H
        self.fb = bytearray(self.w * self.h * 2)
        self.mv = memoryview(self.fb)
        self.chars = bytearray(b" " * (self.cols * self.rows))
        self.fgs = bytearray(bytes((FG,)) * (self.cols * self.rows))
        self.bgs = bytearray(bytes((BG,)) * (self.cols * self.rows))
        self.pal = palette()
        self.p = array("I", [0] * 5)
        self.build()
        self.ox = (display_driver.WIDTH - self.w) // 2
        self.oy = (display_driver.HEIGHT - self.h) // 2
        self.area = lv.area_t()
        self.replies = bytearray()  # answers to the reports, read by MicroPython as keys
        self.busy = False
        self.interrupted = False  # a Ctrl-C landed in write(), see there
        self.reset()

    def build(self):
        self.screen = lv.obj()
        self.screen.set_style_bg_color(lv.color_hex(0), 0)
        self.screen.set_style_pad_all(0, 0)
        self.screen.remove_flag(lv.obj.FLAG.SCROLLABLE)
        self.canvas = lv.canvas(self.screen)
        self.canvas.set_buffer(self.fb, self.w, self.h, lv.COLOR_FORMAT.RGB565)
        self.canvas.center()

    def show(self):
        try:
            lv.screen_load(self.screen)
        except Exception:  # a program with its own screens deleted this one
            self.build()
            lv.screen_load(self.screen)
            self.d0, self.d1 = 0, self.rows - 1
            self.flush()

    def reset(self):
        self.x = self.y = 0
        self.fg, self.bg = FG, BG
        self.bold = self.reverse = False
        self.top, self.bottom = 0, self.rows - 1
        self.wrap = True
        self.pending_wrap = False
        self.cursor_on = True
        self.saved = (0, 0, FG, BG, False, False)
        self.alt = None
        self.state = 0
        self.params = ""
        self.d0, self.d1 = self.rows, -1
        self.erase(0, self.cols * self.rows)
        self.show_cursor()
        self.flush()

    # ---- Stream: this is what os.dupterm calls ----

    def write(self, buf):
        # A KeyboardInterrupt leaving this method would make dupterm drop the terminal for
        # good, so it stops here. Whoever can raise it again does: see check().
        n = len(buf)
        if self.busy:  # printing from a callback that interrupted a write
            return n
        self.busy = True
        try:
            self.feed(buf)
        except KeyboardInterrupt:
            self.interrupted = True
        try:
            self.show_cursor()
            self.flush()
        except KeyboardInterrupt:
            self.interrupted = True
        self.busy = False
        return n

    def text(self, s):
        """Straight to the display: full-screen programs want this, the serial port is
        slow (print() takes 1 s to fill the screen) and it cannot show their sequences."""
        self.write(s.encode() if isinstance(s, str) else s)

    def readinto(self, buf):
        if not self.replies:
            return None
        n = min(len(buf), len(self.replies))
        buf[:n] = self.replies[:n]
        self.replies = self.replies[n:]
        return n

    def ioctl(self, op, arg):
        return 0

    def check(self):
        """Raises the KeyboardInterrupt that write() had to keep."""
        if self.interrupted:
            self.interrupted = False
            raise KeyboardInterrupt

    # ---- Drawing ----

    def touch(self, row0, row1):
        if row0 < self.d0:
            self.d0 = row0
        if row1 > self.d1:
            self.d1 = row1

    def flush(self):
        if self.d1 < self.d0:
            return
        a = self.area
        a.x1, a.x2 = self.ox, self.ox + self.w - 1
        a.y1, a.y2 = self.oy + self.d0 * CELL_H, self.oy + (self.d1 + 1) * CELL_H - 1
        self.d0, self.d1 = self.rows, -1
        try:
            self.canvas.invalidate_area(a)
        except Exception:
            pass  # a program deleted the screen: show() will build it again

    def paint(self, x, y, c, fg, bg):
        p = self.p
        p[0] = y * CELL_H * self.w + x * CELL_W
        p[1] = self.w
        p[2] = (c - 32) * CELL_H
        p[3] = self.pal[fg]
        p[4] = self.pal[bg]
        _paint(self.fb, FONT, p)

    def repaint(self, i, inverted):
        y, x = divmod(i, self.cols)
        fg, bg = self.fgs[i], self.bgs[i]
        if inverted:
            fg, bg = bg, fg
        self.paint(x, y, self.chars[i], fg, bg)
        self.touch(y, y)

    def hide_cursor(self):
        if self.cursor_on:
            self.repaint(self.y * self.cols + self.x, False)

    def show_cursor(self):
        if self.cursor_on:
            self.repaint(self.y * self.cols + self.x, True)

    def erase(self, start, end):
        """Blanks the cells from start to end, row by row, with the current background."""
        cols = self.cols
        p = self.p
        while start < end:
            y, x = divmod(start, cols)
            n = min(cols - x, end - start)
            self.chars[start : start + n] = b" " * n
            self.fgs[start : start + n] = bytes((self.fg,)) * n
            self.bgs[start : start + n] = bytes((self.bg,)) * n
            p[0] = y * CELL_H * self.w + x * CELL_W
            p[1] = self.w
            p[2] = n * CELL_W
            p[3] = CELL_H
            p[4] = self.pal[self.bg]
            _fill(self.fb, p)
            self.touch(y, y)
            start += n

    def move_rows(self, src, dst, n):
        """n rows from src to dst, in the grid and in the pixels."""
        cols = self.cols
        for a in (self.chars, self.fgs, self.bgs):
            m = memoryview(a)
            m[dst * cols : (dst + n) * cols] = m[src * cols : (src + n) * cols]
        row = self.w * CELL_H * 2
        self.mv[dst * row : (dst + n) * row] = self.mv[src * row : (src + n) * row]

    def scroll(self, n, top=None):
        """n > 0: up, n < 0: down, between top and the bottom margin."""
        top = self.top if top is None else top
        size = self.bottom - top + 1
        count = min(abs(n), size)
        if n > 0:
            if count < size:
                self.move_rows(top + count, top, size - count)
            first = self.bottom - count + 1
        else:
            if count < size:
                self.move_rows(top, top + count, size - count)
            first = top
        self.erase(first * self.cols, (first + count) * self.cols)
        self.touch(top, self.bottom)

    def line_feed(self):
        if self.y == self.bottom:
            self.scroll(1)
        elif self.y < self.rows - 1:
            self.y += 1

    def reverse_feed(self):
        if self.y == self.top:
            self.scroll(-1)
        elif self.y > 0:
            self.y -= 1

    def put(self, c):
        if self.pending_wrap:
            self.pending_wrap = False
            self.x = 0
            self.line_feed()
        i = self.y * self.cols + self.x
        self.chars[i], self.fgs[i], self.bgs[i] = c, self.fg, self.bg
        self.paint(self.x, self.y, c, self.fg, self.bg)
        self.touch(self.y, self.y)
        if self.x < self.cols - 1:
            self.x += 1
        elif self.wrap:
            self.pending_wrap = True

    # ---- Parser ----

    def feed(self, buf):
        self.hide_cursor()
        for c in buf:
            if self.state == 0:
                if 32 <= c < 127:
                    self.put(c)
                elif c == 27:
                    self.state = 1
                elif c >= 0xC0:  # the first byte of a UTF-8 character
                    self.put(63)
                elif c < 32:
                    self.control(c)
            elif c == 24 or c == 26:  # CAN, SUB
                self.state = 0
            elif self.state == 1:
                self.escape(c)
            elif self.state == 2:
                if 0x40 <= c <= 0x7E:
                    self.state = 0
                    self.csi(c)
                else:
                    self.params += chr(c)
            elif self.state == 3:  # OSC: until BEL or ESC \
                if c == 7:
                    self.state = 0
                elif c == 27:
                    self.state = 1
            else:  # the character set after ESC ( or ESC )
                self.state = 0

    def control(self, c):
        self.pending_wrap, wrapping = False, self.pending_wrap
        if c == 13:
            self.x = 0
        elif c == 10 or c == 11 or c == 12:
            self.line_feed()
        elif c == 8:
            self.x = max(0, self.x - 1)
        elif c == 9:
            self.x = min(self.cols - 1, (self.x // 8 + 1) * 8)
        else:
            self.pending_wrap = wrapping

    def escape(self, c):
        self.state = 0
        if c == 0x5B:  # [
            self.state = 2
            self.params = ""
        elif c == 0x5D:  # ]
            self.state = 3
        elif c == 0x28 or c == 0x29:  # ( )
            self.state = 4
        elif c == 0x37:  # 7
            self.save()
        elif c == 0x38:  # 8
            self.restore()
        elif c == 0x44:  # D
            self.line_feed()
        elif c == 0x45:  # E
            self.x = 0
            self.line_feed()
        elif c == 0x4D:  # M
            self.reverse_feed()
        elif c == 0x63:  # c
            self.reset()
            self.hide_cursor()

    def save(self):
        self.saved = (self.x, self.y, self.fg, self.bg, self.bold, self.reverse)

    def restore(self):
        self.x, self.y, self.fg, self.bg, self.bold, self.reverse = self.saved
        self.pending_wrap = False

    def goto(self, x, y):
        self.x = max(0, min(self.cols - 1, x))
        self.y = max(0, min(self.rows - 1, y))
        self.pending_wrap = False

    def csi(self, final):
        private = self.params.startswith("?")
        text = self.params[1:] if private else self.params
        args = []
        for a in text.split(";"):
            try:
                args.append(int(a))
            except ValueError:
                args.append(0)
        n = args[0]
        count = max(1, n)
        second = args[1] if len(args) > 1 else 0
        f = chr(final)
        if private:
            if f in "hl":
                self.mode(args, f == "h")
            return
        cols = self.cols
        pos = self.y * cols + self.x
        if f == "A":
            self.goto(self.x, max(self.y - count, self.top if self.y >= self.top else 0))
        elif f == "B":
            limit = self.bottom if self.y <= self.bottom else self.rows - 1
            self.goto(self.x, min(self.y + count, limit))
        elif f == "C":
            self.goto(self.x + count, self.y)
        elif f == "D":
            self.goto(self.x - count, self.y)
        elif f == "E":
            self.goto(0, self.y + count)
        elif f == "F":
            self.goto(0, self.y - count)
        elif f == "G":
            self.goto(count - 1, self.y)
        elif f == "d":
            self.goto(self.x, count - 1)
        elif f in "Hf":
            self.goto(max(1, second) - 1, count - 1)
        elif f == "J":
            start, end = ((pos, cols * self.rows), (0, pos + 1), (0, cols * self.rows))[min(n, 2)]
            self.erase(start, end)
        elif f == "K":
            row = self.y * cols
            start, end = ((pos, row + cols), (row, pos + 1), (row, row + cols))[min(n, 2)]
            self.erase(start, end)
        elif f == "X":
            self.erase(pos, min(pos + count, self.y * cols + cols))
        elif f == "m":
            self.sgr(args)
        elif f == "L" or f == "M":
            if self.top <= self.y <= self.bottom:
                self.scroll(-count if f == "L" else count, self.y)
                self.x = 0
        elif f == "S":
            self.scroll(count)
        elif f == "T":
            self.scroll(-count)
        elif f == "@" or f == "P":
            self.shift_cells(count, f == "@")
        elif f == "r":
            top, bottom = count - 1, (second or self.rows) - 1
            if top < bottom < self.rows:
                self.top, self.bottom = top, bottom
                self.goto(0, 0)
        elif f == "s":
            self.save()
        elif f == "u":
            self.restore()
        elif f == "n":
            if n == 5:
                self.replies += b"\x1b[0n"
            elif n == 6:
                self.replies += ("\x1b[%d;%dR" % (self.y + 1, self.x + 1)).encode()
        elif f == "c":
            self.replies += b"\x1b[?1;2c"

    def shift_cells(self, n, right):
        """Insert or delete n cells at the cursor; the rest of the row moves."""
        i = self.y * self.cols + self.x
        end = self.y * self.cols + self.cols
        n = min(n, end - i)
        for a in (self.chars, self.fgs, self.bgs):
            m = memoryview(a)
            if right:
                m[i + n : end] = m[i : end - n]
            else:
                m[i : end - n] = m[i + n : end]
        for k in range(i, end):
            self.repaint(k, False)
        self.erase(i, i + n) if right else self.erase(end - n, end)

    def sgr(self, args):
        i = 0
        while i < len(args):
            a = args[i]
            if a == 0:
                self.bold = self.reverse = False
                self.base_fg, self.base_bg = FG, BG
            elif a == 1:
                self.bold = True
            elif a == 22:
                self.bold = False
            elif a == 7:
                self.reverse = True
            elif a == 27:
                self.reverse = False
            elif 30 <= a <= 37:
                self.base_fg = a - 30
            elif a == 39:
                self.base_fg = FG
            elif 40 <= a <= 47:
                self.base_bg = a - 40
            elif a == 49:
                self.base_bg = BG
            elif 90 <= a <= 97:
                self.base_fg = a - 82
            elif 100 <= a <= 107:
                self.base_bg = a - 92
            elif (a == 38 or a == 48) and i + 2 < len(args) and args[i + 1] == 5:
                if a == 38:
                    self.base_fg = args[i + 2] & 255
                else:
                    self.base_bg = args[i + 2] & 255
                i += 2
            i += 1
        fg = self.base_fg
        if self.bold and fg < 8:
            fg += 8
        self.fg, self.bg = (self.base_bg, fg) if self.reverse else (fg, self.base_bg)

    base_fg, base_bg = FG, BG

    def mode(self, args, on):
        for a in args:
            if a == 25:
                self.cursor_on = on
            elif a == 7:
                self.wrap = on
            elif a == 1049 or a == 47 or a == 1047:
                self.alternate(on)

    def alternate(self, on):
        if on and self.alt is None:
            self.alt = (bytes(self.chars), bytes(self.fgs), bytes(self.bgs), bytes(self.fb),
                        self.x, self.y)
            self.erase(0, self.cols * self.rows)
            self.goto(0, 0)
        elif not on and self.alt is not None:
            chars, fgs, bgs, pixels, x, y = self.alt
            self.alt = None
            self.chars[:], self.fgs[:], self.bgs[:], self.mv[:] = chars, fgs, bgs, pixels
            self.touch(0, self.rows - 1)
            self.goto(x, y)


term = None


# Ctrl-C during lv.timer_handler(): the driver's task stops the display, which is not what
# a terminal wants. This one leaves it to check(). The VM raises a pending interrupt only at
# a jump, and C code runs for most of the time here: without the `if` that would be after
# the try, where the scheduler swallows it and the timer is not armed again.
def _task(_):
    try:
        lv.timer_handler()
        if term:
            pass
    except KeyboardInterrupt:
        term.interrupted = True
    if display_driver._timer is not None:
        display_driver._arm()


def start():
    """Shows the terminal and sends it what MicroPython prints. Can be called again."""
    global term
    if term is None:
        term = Terminal()
    term.show()
    display_driver._task = _task
    display_driver.start()
    display_driver._arm()  # a one shot timer: this also revives one that did not rearm
    os.dupterm(term)
    return term


def stop():
    """Stops sending the output to the display."""
    os.dupterm(None)
