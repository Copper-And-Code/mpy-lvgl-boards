# A small vi for the ANSI terminal of ansiterm.py, or for any terminal on the serial port
# (80x24). Runs from shell.py once copied to /bin/vi.py or /sd/bin/vi.py:
#
#   vi notes.txt
#
# or from the REPL: import vi; vi.main("notes.txt")
#
#   Move    h j k l, arrows, w b e, 0 ^ $, f F t T ; , %, gg G, H M L,
#           Ctrl-F Ctrl-B Ctrl-D Ctrl-U, Page Up/Down, Home, End
#   Insert  i I a A o O s S C, R; Esc or Ctrl-C leaves
#   Change  x X r J ~ D, dd yy cc >> <<, d c y > < + a motion (dw, c$, d3j, yG, dfx),
#           p P, u Ctrl-R, ., a count before most of them (3dd, 5x, 2w)
#   Search  / ? n N *, plain text
#   Lines   :w :w file :q :q! :wq :x ZZ ZQ :e file :e! :r file :42 :d
#           :s/old/new/g :%s/old/new/g :1,5s/old/new/ (plain text too)
#   Options :set nu nonu ai noai ic noic et noet sw=4
#
# Long lines scroll sideways, they do not wrap. Tab inserts `sw` spaces unless :set noet.
import select
import sys

import micropython
import os

SPECIAL = {
    "A": "up", "B": "down", "C": "right", "D": "left",
    "H": "home", "F": "end", "1~": "home", "4~": "end",
    "3~": "del", "5~": "pgup", "6~": "pgdn",
}
BLUE, RESET, REVERSE = "\x1b[1;34m", "\x1b[0m", "\x1b[7m"
MAX_UNDO = 30
ESC = "\x1b"
CTRL_C = "\x03"
BACKSPACE = ("\x7f", "\x08")


def kind(c):
    if c == " " or c == "\t":
        return 0
    return 1 if c.isalpha() or c.isdigit() or c == "_" else 2


def expand(line):
    if "\t" not in line:
        return line
    out = ""
    for c in line:
        out += " " * (8 - len(out) % 8) if c == "\t" else c
    return out


def column(line, i):
    """The screen column of character i, tabs counted."""
    return len(expand(line[:i]))


def printable(text):
    for c in text:
        if c < " " or c == "\x7f":
            return "".join("?" if c < " " or c == "\x7f" else c for c in text)
    return text


def first_blank(line):
    i = 0
    while i < len(line) and kind(line[i]) == 0:
        i += 1
    return i if i < len(line) else max(0, len(line) - 1)


class Vi:
    def __init__(self, path, term):
        self.term = term
        self.cols = term.cols if term else 80
        self.rows = term.rows if term else 24
        self.height = self.rows - 1
        self.poll = select.poll()
        self.poll.register(sys.stdin, select.POLLIN)
        self.lines = [""]
        self.y = self.x = self.top = self.left = 0
        self.path = path
        self.crlf = False
        self.dirty = False
        self.mode = self.message = ""
        self.typing = None  # the : or / line being typed
        self.register = (False, [""])
        self.undo_stack, self.redo_stack = [], []
        self.pattern, self.backwards = "", False
        self.last_find = None
        self.queue, self.keys, self.last_change = [], [], []
        self.pushed = ""
        self.changed = False
        self.done = False
        self.number = self.autoindent = self.ignorecase = False
        self.expandtab = True
        self.shiftwidth = 4
        self.forget_screen()
        if path:
            self.load(path)

    # ---- Screen ----

    def send(self, text):
        if self.term:
            self.term.text(text)
        else:
            sys.stdout.write(text)

    def forget_screen(self):
        self.shown = [None] * self.height
        self.shown_status = None
        self.shown_top = self.shown_left = None

    def gutter(self):
        return 5 if self.number else 0

    def follow_cursor(self):
        self.y = max(0, min(self.y, len(self.lines) - 1))
        if self.y < self.top:
            self.top = self.y
        elif self.y >= self.top + self.height:
            self.top = self.y - self.height + 1
        width = self.cols - self.gutter()
        c = column(self.lines[self.y], self.x)
        if c < self.left:
            self.left = max(0, c - width // 4)
        elif c >= self.left + width:
            self.left = c - width + width // 4

    def scroll_screen(self, out):
        """Moves the rows that are still good: much faster than writing them again."""
        if self.shown_top is None or self.shown_left != self.left:
            return
        d = self.top - self.shown_top
        if d == 0 or abs(d) >= self.height // 2:
            return
        out.append("\x1b[1;%dr\x1b[%d%s\x1b[r" % (self.height, abs(d), "S" if d > 0 else "T"))
        if d > 0:
            self.shown = self.shown[d:] + [None] * d
        else:
            self.shown = [None] * -d + self.shown[:d]

    def row_text(self, i, line):
        if self.number:
            head, width = "%s%4d%s " % (BLUE, i + 1, RESET), self.cols - 5
        else:
            head, width = "", self.cols
        text = printable(expand(line)[self.left : self.left + width])
        return head + text + ("\x1b[K" if len(text) < width else "")

    def status(self):
        if self.typing is not None:
            return self.typing[-(self.cols - 1) :]
        text = self.message or self.mode
        ruler = "%d,%d" % (self.y + 1, self.x + 1)
        room = self.cols - len(ruler) - 2
        return text[: self.cols - 1] if len(text) > room else "%-*s%s" % (room + 1, text, ruler)

    def refresh(self):
        self.follow_cursor()
        out = []
        self.scroll_screen(out)
        self.shown_top, self.shown_left = self.top, self.left
        number = self.number
        for r in range(self.height):
            i = self.top + r
            if i < len(self.lines):
                line = self.lines[i]
                key = (line, i) if number else line
                if self.shown[r] != key:
                    self.shown[r] = key
                    out.append("\x1b[%d;1H%s" % (r + 1, self.row_text(i, line)))
            elif self.shown[r] != 0:
                self.shown[r] = 0
                out.append("\x1b[%d;1H%s~%s\x1b[K" % (r + 1, BLUE, RESET))
        text = self.status()
        if text != self.shown_status:
            self.shown_status = text
            out.append("\x1b[%d;1H%s\x1b[K" % (self.rows, printable(text)))
        if self.typing is not None:
            where = (self.rows, min(len(self.typing), self.cols - 2) + 1)
        else:
            c = column(self.lines[self.y], self.x) - self.left + self.gutter()
            where = (self.y - self.top + 1, c + 1)
        out.append("\x1b[%d;%dH" % where)
        self.send("".join(out))

    # ---- Keys ----

    def waiting(self, ms=0):
        return bool(self.poll.poll(ms))

    def read_key(self):
        if self.pushed:
            c, self.pushed = self.pushed, ""
            return c
        c = sys.stdin.read(1)
        if c != ESC or not self.waiting(25):  # nothing behind it: the Esc key
            return c
        c = sys.stdin.read(1)
        if c != "[" and c != "O":
            self.pushed = c  # a fast typist: Esc and then a key of its own
            return ESC
        seq = ""
        while True:
            c = sys.stdin.read(1)
            seq += c
            if c.isalpha() or c == "~":
                return SPECIAL.get(seq, "")

    def key(self):
        while True:
            if self.queue:
                k = self.queue.pop(0)
            else:
                if not self.pushed and not self.waiting():  # keep up with a paste
                    self.refresh()
                k = self.read_key()
            if k:
                self.keys.append(k)
                return k

    def line_input(self, prefix):
        """The line after : / ?, or None if left with Esc."""
        text = ""
        while True:
            self.typing = prefix + text
            k = self.key()
            if k == "\r" or k == "\n":
                self.typing = None
                return text
            if k == ESC or k == CTRL_C:
                self.typing = None
                return None
            if k in BACKSPACE:
                if not text:
                    self.typing = None
                    return None
                text = text[:-1]
            elif len(k) == 1 and k >= " ":
                text += k

    # ---- Files ----

    def load(self, path):
        self.path = path
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError as e:
            if e.args[0] != 2:
                raise
            self.lines = [""]
            self.message = '"%s" [New File]' % path
            return
        try:
            text = data.decode()
        except UnicodeError:
            raise ValueError("not a text file")
        self.crlf = "\r\n" in text
        self.lines = text.split("\n")
        if self.crlf:
            self.lines = [s[:-1] if s.endswith("\r") else s for s in self.lines]
        if len(self.lines) > 1 and not self.lines[-1]:
            self.lines.pop()
        self.message = '"%s" %dL, %dB' % (path, len(self.lines), len(data))

    def save(self, path=None):
        """Through a temporary file: a full disk must not cost the file being saved."""
        path = path or self.path
        if not path:
            raise ValueError("No file name")
        eol = "\r\n" if self.crlf else "\n"
        data = (eol.join(self.lines) + eol).encode()
        tmp = path + ".~"
        try:
            with open(tmp, "wb") as f:
                f.write(data)
        except OSError:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise
        try:
            os.remove(path)
        except OSError:
            pass
        os.rename(tmp, path)
        if path == self.path or not self.path:
            self.path = path
            self.dirty = False
        self.message = '"%s" %dL, %dB written' % (path, len(self.lines), len(data))

    # ---- Changes ----

    def begin(self):
        """Call before changing the text: this is the state `u` goes back to."""
        self.undo_stack.append((self.lines[:], self.y, self.x))
        del self.undo_stack[:-MAX_UNDO]
        self.redo_stack = []
        self.changed = self.dirty = True

    def swap_state(self, source, target, name):
        if not source:
            self.message = "Already at %s change" % name
            return
        target.append((self.lines[:], self.y, self.x))
        self.lines, self.y, self.x = source.pop()
        self.dirty = True

    def delete_chars(self, n):
        line = self.lines[self.y]
        if line:
            self.begin()
            self.register = (False, [line[self.x : self.x + n]])
            self.lines[self.y] = line[: self.x] + line[self.x + n :]

    def open_line(self, below):
        indent = ""
        if self.autoindent:
            line = self.lines[self.y]
            indent = line[: len(line) - len(line.lstrip())]
        self.begin()
        self.y += 1 if below else 0
        self.lines.insert(self.y, indent)
        self.x = len(indent)
        self.insert()

    def insert_text(self, text):
        line = self.lines[self.y]
        self.lines[self.y] = line[: self.x] + text + line[self.x :]
        self.x += len(text)

    def insert(self, overwrite=False):
        self.mode = "-- REPLACE --" if overwrite else "-- INSERT --"
        while True:
            k = self.key()
            line = self.lines[self.y]
            if k == ESC or k == CTRL_C:
                break
            if k == "\r" or k == "\n":
                indent = line[: len(line) - len(line.lstrip())] if self.autoindent else ""
                self.lines[self.y : self.y + 1] = [line[: self.x], indent + line[self.x :]]
                self.y += 1
                self.x = len(indent)
            elif k in BACKSPACE:
                if self.x:
                    self.lines[self.y] = line[: self.x - 1] + line[self.x :]
                    self.x -= 1
                elif self.y:
                    self.y -= 1
                    self.x = len(self.lines[self.y])
                    self.lines[self.y : self.y + 2] = [self.lines[self.y] + line]
            elif k == "del":
                self.lines[self.y] = line[: self.x] + line[self.x + 1 :]
            elif k == "\t":
                self.insert_text(" " * self.shiftwidth if self.expandtab else "\t")
            elif k == "left":
                self.x = max(0, self.x - 1)
            elif k == "right":
                self.x = min(len(line), self.x + 1)
            elif k == "up" or k == "down" or k == "pgup" or k == "pgdn":
                step = self.height if len(k) == 4 else 1
                self.y += step if k[-1] == "n" else -step
                self.y = max(0, min(self.y, len(self.lines) - 1))
                self.x = min(self.x, len(self.lines[self.y]))
            elif k == "home":
                self.x = 0
            elif k == "end":
                self.x = len(line)
            elif len(k) == 1 and k >= " ":
                if overwrite and self.x < len(line):
                    self.lines[self.y] = line[: self.x] + line[self.x + 1 :]
                self.insert_text(k)
        self.mode = ""
        self.x = max(0, self.x - 1)

    def put(self, after, n):
        whole, text = self.register
        self.begin()
        if whole:
            at = self.y + 1 if after else self.y
            self.lines[at:at] = text * n
            self.y = at
            self.x = first_blank(self.lines[at])
            return
        line = self.lines[self.y]
        at = self.x + 1 if after and line else self.x
        if len(text) == 1:
            piece = text[0] * n
            self.lines[self.y] = line[:at] + piece + line[at:]
            self.x = at + len(piece) - 1
        else:
            block = text[:]
            block[0] = line[:at] + block[0]
            block[-1] += line[at:]
            self.lines[self.y : self.y + 1] = block
            self.x = at

    def join_lines(self, n):
        self.begin()
        for _ in range(max(1, n - 1)):
            if self.y + 1 >= len(self.lines):
                return
            a = self.lines[self.y].rstrip()
            b = self.lines[self.y + 1].lstrip()
            self.x = len(a)
            self.lines[self.y : self.y + 2] = [a + " " + b if a and b else a + b]

    def operate(self, op, y1, x1, y2, x2, whole):
        """d c y > < on the text between two positions; x2 is not included."""
        if (y2, x2) < (y1, x1):
            y1, x1, y2, x2 = y2, x2, y1, x1
        if op == ">" or op == "<":
            self.indent(op, y1, y2)
            return
        if whole:
            self.register = (True, self.lines[y1 : y2 + 1])
        elif y1 == y2:
            self.register = (False, [self.lines[y1][x1:x2]])
        else:
            middle = self.lines[y1 + 1 : y2]
            self.register = (False, [self.lines[y1][x1:]] + middle + [self.lines[y2][:x2]])
        self.y, self.x = y1, 0 if whole else x1
        if op == "y":
            return
        self.begin()
        if whole:
            if op == "c":
                self.lines[y1 : y2 + 1] = [""]
            else:
                del self.lines[y1 : y2 + 1]
                self.lines = self.lines or [""]
                self.y = min(y1, len(self.lines) - 1)
                self.x = first_blank(self.lines[self.y])
        else:
            self.lines[y1 : y2 + 1] = [self.lines[y1][:x1] + self.lines[y2][x2:]]
        if op == "c":
            self.insert()

    def indent(self, op, y1, y2):
        self.begin()
        for i in range(y1, y2 + 1):
            line = self.lines[i]
            if op == ">":
                if line:
                    self.lines[i] = " " * self.shiftwidth + line
            else:
                spaces = len(line) - len(line.lstrip())
                self.lines[i] = line[min(spaces, self.shiftwidth) :]
        self.y = y1
        self.x = first_blank(self.lines[y1])

    # ---- Motions ----

    def next_word(self, y, x):
        line = self.lines[y]
        if x < len(line):
            k = kind(line[x])
            while k and x < len(line) and kind(line[x]) == k:
                x += 1
        while True:
            line = self.lines[y]
            while x < len(line) and kind(line[x]) == 0:
                x += 1
            if x < len(line):
                return y, x
            if y + 1 == len(self.lines):
                return y, len(line)
            y += 1
            x = 0
            if not self.lines[y]:
                return y, 0

    def word_end(self, y, x):
        x += 1
        while True:
            line = self.lines[y]
            while x < len(line) and kind(line[x]) == 0:
                x += 1
            if x < len(line):
                break
            if y + 1 == len(self.lines):
                return y, max(0, len(line) - 1)
            y += 1
            x = 0
        k = kind(line[x])
        while x + 1 < len(line) and kind(line[x + 1]) == k:
            x += 1
        return y, x

    def previous_word(self, y, x):
        x -= 1
        while True:
            if x < 0:
                if y == 0:
                    return 0, 0
                y -= 1
                x = len(self.lines[y]) - 1
                if x < 0:
                    return y, 0
            elif kind(self.lines[y][x]) == 0:
                x -= 1
            else:
                break
        line = self.lines[y]
        k = kind(line[x])
        while x > 0 and kind(line[x - 1]) == k:
            x -= 1
        return y, x

    def find_char(self, how, c, n):
        line = self.lines[self.y]
        x = self.x
        forward = how == "f" or how == "t"
        step = 1 if forward else -1
        if how in "tT" and n == 1 and 0 <= x + step < len(line) and line[x + step] == c:
            x += step  # ; next to the character must move on
        for _ in range(n):
            x += step
            while 0 <= x < len(line) and line[x] != c:
                x += step
            if not 0 <= x < len(line):
                return None
        if how == "t":
            x -= 1
        elif how == "T":
            x += 1
        return x

    def match_bracket(self):
        pairs = "()[]{}"
        line = self.lines[self.y]
        x = self.x
        while x < len(line) and line[x] not in pairs:
            x += 1
        if x == len(line):
            return None
        i = pairs.index(line[x])
        mine, other = line[x], pairs[i ^ 1]
        step = 1 if i % 2 == 0 else -1
        y, depth = self.y, 0
        while 0 <= y < len(self.lines):
            line = self.lines[y]
            while 0 <= x < len(line):
                if line[x] == mine:
                    depth += 1
                elif line[x] == other:
                    depth -= 1
                    if depth == 0:
                        return y, x
                x += step
            y += step
            if 0 <= y < len(self.lines):
                x = 0 if step > 0 else len(self.lines[y]) - 1
        return None

    def motion(self, k, n, count):
        """Where a motion goes: (y, x, whole lines, last character included), or None."""
        y, x = self.y, self.x
        line = self.lines[y]
        if k == "h" or k == "left" or k in BACKSPACE:
            return y, max(0, x - n), False, False
        if k == "l" or k == "right" or k == " ":
            return y, min(len(line), x + n), False, False
        if k == "j" or k == "down" or k == "+" or k == "\r" or k == "\n":
            return min(len(self.lines) - 1, y + n), x, True, False
        if k == "k" or k == "up" or k == "-":
            return max(0, y - n), x, True, False
        if k == "0" or k == "home":
            return y, 0, False, False
        if k == "^":
            return y, first_blank(line), False, False
        if k == "$" or k == "end":
            y = min(len(self.lines) - 1, y + n - 1)
            return y, max(0, len(self.lines[y]) - 1), False, True
        if k == "w" or k == "b" or k == "e":
            f = {"w": self.next_word, "b": self.previous_word, "e": self.word_end}[k]
            for _ in range(n):
                y, x = f(y, x)
            return y, x, False, k == "e"
        if k == "G":
            y = min(len(self.lines), count or len(self.lines)) - 1
            return y, first_blank(self.lines[y]), True, False
        if k == "g":
            if self.key() != "g":
                return None
            y = min(len(self.lines), count or 1) - 1
            return y, first_blank(self.lines[y]), True, False
        if k == "H" or k == "M" or k == "L":
            last = min(self.top + self.height, len(self.lines)) - 1
            y = {"H": self.top, "M": (self.top + last) // 2, "L": last}[k]
            return y, first_blank(self.lines[y]), True, False
        if k in ("f", "F", "t", "T"):
            self.last_find = (k, self.key())
        if k in ("f", "F", "t", "T", ";", ","):
            if not self.last_find:
                return None
            how, c = self.last_find
            if k == ",":
                how = how.upper() if how.islower() else how.lower()
            x = self.find_char(how, c, n)
            return None if x is None else (y, x, False, how in "ft")
        if k == "%":
            found = self.match_bracket()
            return found and (found[0], found[1], False, True)
        return None

    def operator(self, op, n):
        count = 0
        k = self.key()
        while k in "123456789" or (k == "0" and count):
            count = count * 10 + int(k)
            k = self.key()
        n *= count or 1
        if k == op:
            self.operate(op, self.y, 0, min(len(self.lines) - 1, self.y + n - 1), 0, True)
            return
        if k == ESC or k == CTRL_C:
            return
        line = self.lines[self.y]
        if op == "c" and k == "w" and self.x < len(line) and kind(line[self.x]):
            k = "e"  # cw stops at the end of the word
        target = self.motion(k, n, count)
        if target is None:
            return
        y, x, whole, included = target
        if k == "w" and y > self.y:  # dw on the last word leaves the next line alone
            y -= 1
            x = len(self.lines[y])
        if included:
            x += 1
        self.operate(op, self.y, self.x, y, x, whole)

    # ---- Search ----

    def search(self, back):
        text = self.pattern
        if not text:
            self.message = "No previous search"
            return
        fold = self.ignorecase
        if fold:
            text = text.lower()
        total = len(self.lines)
        step = -1 if back else 1
        for i in range(total + 1):
            y = (self.y + step * i) % total
            line = self.lines[y].lower() if fold else self.lines[y]
            at = self.find_in(line, text, back, y == self.y, i)
            if at >= 0:
                if (y < self.y) != back and y != self.y:
                    self.message = "search wrapped"
                self.y, self.x = y, at
                return
        self.message = "Pattern not found: " + self.pattern

    def find_in(self, line, text, back, here, i):
        """The search goes round the file: on the first pass stay on the right of the
        cursor, on the last one (back on its line) take what was skipped."""
        if not back:
            return line.find(text, self.x + 1 if here and i == 0 else 0)
        last = self.x if here and i == 0 else len(line)
        return line.rfind(text, 0, max(0, last + len(text) - 1))

    def word_under_cursor(self):
        line = self.lines[self.y]
        a = b = self.x
        if a >= len(line) or kind(line[a]) != 1:
            return ""
        while a > 0 and kind(line[a - 1]) == 1:
            a -= 1
        while b < len(line) and kind(line[b]) == 1:
            b += 1
        return line[a:b]

    # ---- Ex commands ----

    def address(self, s):
        """Reads a line number from the start of s: (index or None, the rest)."""
        if s[:1] == ".":
            return self.y, s[1:]
        if s[:1] == "$":
            return len(self.lines) - 1, s[1:]
        i = 0
        while i < len(s) and s[i].isdigit():
            i += 1
        return (int(s[:i]) - 1, s[i:]) if i else (None, s)

    def ex(self, cmd):
        cmd = cmd.strip()
        a = b = None
        if cmd[:1] == "%":
            a, b, cmd = 0, len(self.lines) - 1, cmd[1:]
        else:
            a, cmd = self.address(cmd)
            if a is not None and cmd[:1] == ",":
                b, cmd = self.address(cmd[1:])
                if b is None:
                    raise ValueError("Invalid range")
        if not cmd:
            if a is not None:
                self.y = b if b is not None else a
                self.x = first_blank(self.lines[max(0, min(self.y, len(self.lines) - 1))])
            return
        i = 0
        while i < len(cmd) and cmd[i].isalpha():
            i += 1
        name, rest = cmd[:i], cmd[i:]
        force = rest[:1] == "!"
        arg = rest[1 if force else 0 :].strip()
        y1 = self.y if a is None else a
        y2 = y1 if b is None else b
        if not 0 <= y1 <= y2 < len(self.lines):
            raise ValueError("Invalid range")
        if name == "w":
            self.save(arg)
        elif name == "wq" or name == "x":
            self.save(arg)
            self.done = True
        elif name == "q":
            if self.dirty and not force:
                raise ValueError("No write since last change (add ! to override)")
            self.done = True
        elif name == "e":
            self.edit(arg, force)
        elif name == "r":
            self.read_file(arg, y1)
        elif name == "d":
            self.operate("d", y1, 0, y2, 0, True)
        elif name == "s":
            self.substitute(rest, y1, y2)
        elif name == "set":
            for word in arg.split():
                self.option(word)
        else:
            raise ValueError("Not an editor command: " + cmd)

    def edit(self, path, force):
        if self.dirty and not force:
            raise ValueError("No write since last change (add ! to override)")
        path = path or self.path
        if not path:
            raise ValueError("No file name")
        self.load(path)
        self.y = self.x = self.top = self.left = 0
        self.dirty = False
        self.undo_stack, self.redo_stack = [], []

    def read_file(self, path, y):
        with open(path) as f:
            text = f.read().split("\n")
        if not text[-1]:
            text.pop()
        self.begin()
        self.lines[y + 1 : y + 1] = text
        self.y = y + 1
        self.x = 0

    def substitute(self, rest, y1, y2):
        if len(rest) < 2:
            raise ValueError("Usage: s/old/new/g")
        parts = rest[1:].split(rest[0])
        if len(parts) < 2 or not parts[0]:
            raise ValueError("Usage: s/old/new/g")
        old, new = parts[0], parts[1]
        every = len(parts) > 2 and "g" in parts[2]
        done = 0
        self.begin()
        for i in range(y1, y2 + 1):
            line = self.lines[i]
            hits = line.count(old)
            if hits:
                self.lines[i] = line.replace(old, new) if every else line.replace(old, new, 1)
                done += hits if every else 1
                self.y = i
        if done:
            self.message = "%d substitutions" % done
        else:
            self.undo_stack.pop()
            self.message = "Pattern not found: " + old

    def option(self, word):
        if word in ("nu", "number"):
            self.number = True
        elif word in ("nonu", "nonumber"):
            self.number = False
        elif word in ("ai", "autoindent"):
            self.autoindent = True
        elif word in ("noai", "noautoindent"):
            self.autoindent = False
        elif word in ("ic", "ignorecase"):
            self.ignorecase = True
        elif word in ("noic", "noignorecase"):
            self.ignorecase = False
        elif word in ("et", "expandtab"):
            self.expandtab = True
        elif word in ("noet", "noexpandtab"):
            self.expandtab = False
        elif word[:3] == "sw=" and word[3:].isdigit() and int(word[3:]):
            self.shiftwidth = int(word[3:])
        else:
            raise ValueError("Unknown option: " + word)
        self.forget_screen()
        self.left = 0

    # ---- Normal mode ----

    def change_case(self, n):
        line = self.lines[self.y]
        if not line:
            return
        self.begin()
        for _ in range(n):
            if self.x < len(line):
                c = line[self.x]
                c = c.lower() if c.isupper() else c.upper()
                line = line[: self.x] + c + line[self.x + 1 :]
                self.x += 1
        self.lines[self.y] = line

    def replace_char(self, n):
        c = self.key()
        line = self.lines[self.y]
        if c == ESC or c == CTRL_C or len(c) != 1 or self.x + n > len(line):
            return
        self.begin()
        self.lines[self.y] = line[: self.x] + c * n + line[self.x + n :]
        self.x += n - 1

    def page(self, rows):
        last = len(self.lines) - 1
        self.y = max(0, min(last, self.y + rows))
        self.top = max(0, min(last, self.top + rows))

    def command(self):
        k = self.key()
        self.message = ""
        count = 0
        while k in "123456789" or (k == "0" and count):
            count = count * 10 + int(k)
            k = self.key()
        n = count or 1
        line = self.lines[self.y]
        if k == "i":
            self.begin()
            self.insert()
        elif k == "I":
            self.begin()
            self.x = first_blank(line) if line.strip() else len(line)
            self.insert()
        elif k == "a":
            self.begin()
            self.x = min(len(line), self.x + 1)
            self.insert()
        elif k == "A":
            self.begin()
            self.x = len(line)
            self.insert()
        elif k == "o" or k == "O":
            self.open_line(k == "o")
        elif k == "R":
            self.begin()
            self.insert(True)
        elif k == "x" or k == "del":
            self.delete_chars(n)
        elif k == "X":
            n = min(n, self.x)
            if n:
                self.x -= n
                self.delete_chars(n)
        elif k == "s":
            self.operate("c", self.y, self.x, self.y, min(len(line), self.x + n), False)
        elif k == "S":
            self.operate("c", self.y, 0, min(len(self.lines) - 1, self.y + n - 1), 0, True)
        elif k == "D" or k == "C":
            self.operate(k.lower(), self.y, self.x, self.y, len(line), False)
        elif k == "Y":
            self.operate("y", self.y, 0, min(len(self.lines) - 1, self.y + n - 1), 0, True)
        elif k in ("d", "c", "y", ">", "<"):
            self.operator(k, n)
        elif k == "p" or k == "P":
            self.put(k == "p", n)
        elif k == "J":
            self.join_lines(n)
        elif k == "r":
            self.replace_char(n)
        elif k == "~":
            self.change_case(n)
        elif k == "u":
            for _ in range(n):
                self.swap_state(self.undo_stack, self.redo_stack, "oldest")
        elif k == "\x12":  # Ctrl-R
            for _ in range(n):
                self.swap_state(self.redo_stack, self.undo_stack, "newest")
        elif k == ".":
            self.queue = self.last_change[:] + self.queue
            self.keys = []
        elif k == "/" or k == "?":
            text = self.line_input(k)
            if text is not None:
                self.pattern = text or self.pattern
                self.backwards = k == "?"
                self.search(self.backwards)
        elif k == "n":
            self.search(self.backwards)
        elif k == "N":
            self.search(not self.backwards)
        elif k == "*":
            self.pattern = self.word_under_cursor() or self.pattern
            self.backwards = False
            self.search(False)
        elif k == ":":
            text = self.line_input(":")
            if text:
                self.ex(text)
        elif k == "Z":
            second = self.key()
            if second == "Z":
                self.ex("x")
            elif second == "Q":
                self.ex("q!")
        elif k == "\x06" or k == "pgdn":  # Ctrl-F
            self.page(n * (self.height - 2))
        elif k == "\x02" or k == "pgup":  # Ctrl-B
            self.page(-n * (self.height - 2))
        elif k == "\x04":  # Ctrl-D
            self.page(n * (self.height // 2))
        elif k == "\x15":  # Ctrl-U
            self.page(-n * (self.height // 2))
        elif k == "\x0c":  # Ctrl-L
            self.send("\x1b[2J")
            self.forget_screen()
        elif k == "\x07":  # Ctrl-G
            name = self.path or "[No Name]"
            mark = " [Modified]" if self.dirty else ""
            self.message = '"%s"%s %d lines' % (name, mark, len(self.lines))
        elif k == CTRL_C:
            self.message = "Type :q! to leave without saving"
        elif k != ESC:
            target = self.motion(k, n, count)
            if target:
                self.y, self.x = target[0], target[1]

    def clamp(self):
        self.y = max(0, min(self.y, len(self.lines) - 1))
        self.x = max(0, min(self.x, len(self.lines[self.y]) - 1))

    def run(self):
        while not self.done:
            self.keys = []
            self.changed = False
            try:
                self.command()
            except (ValueError, OSError, UnicodeError) as e:
                self.typing = None
                self.mode = ""
                self.message = "E: %s" % (e if str(e) else "error")
            if self.changed:
                self.last_change = self.keys
            self.clamp()


def terminal():
    """The terminal on the display, started if it is not, or None on a serial port only."""
    try:
        import ansiterm
    except ImportError:
        return None
    return ansiterm.term or ansiterm.start()


def main(path=None):
    term = terminal()
    editor = Vi(path, term)
    micropython.kbd_intr(-1)  # Ctrl-C is a key here
    editor.send("\x1b[?1049h\x1b[0m\x1b[2J")
    try:
        editor.run()
    finally:
        editor.send("\x1b[?1049l")
        micropython.kbd_intr(3)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
