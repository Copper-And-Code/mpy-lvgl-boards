# A friendly editor for the ANSI terminal of ansiterm.py, or for any terminal on the
# serial port: no modes, you type and the text changes, the keys are on the screen. Runs
# from shell.py once copied to /bin/edit.py or /sd/bin/edit.py:
#
#   edit notes.txt
#
# or from the REPL: import edit; edit.main("notes.txt")
#
#   Ctrl-S save      Ctrl-Q quit      Ctrl-Z undo      Ctrl-Y redo
#   Ctrl-F find      Ctrl-N next      Ctrl-R replace   Ctrl-G go to line
#   Ctrl-X cut line  Ctrl-C copy line Ctrl-V paste     Ctrl-L line numbers
#
# Pressing Ctrl-X or Ctrl-C again adds the next line to what will be pasted. Search ignores
# case. Enter keeps the indentation, Tab is 4 spaces, Backspace on spaces goes back by 4.
#
# In PuTTY the serial flow control must be None, or Ctrl-S and Ctrl-Q stop the terminal.
import select
import sys

import micropython
import os

SPECIAL = {
    "A": "up", "B": "down", "C": "right", "D": "left",
    "H": "home", "F": "end", "1~": "home", "4~": "end",
    "3~": "del", "5~": "pgup", "6~": "pgdn",
}
HELP = (
    (("^S", "Save"), ("^Q", "Quit"), ("^F", "Find"), ("^N", "Next"), ("^R", "Replace")),
    (("^X", "Cut"), ("^C", "Copy"), ("^V", "Paste"), ("^Z", "Undo"), ("^G", "Go to")),
)
BLUE, RESET, REVERSE = "\x1b[1;34m", "\x1b[0m", "\x1b[7m"
ESC = "\x1b"
BACKSPACE = ("\x7f", "\x08")
CANCEL = (ESC, "\x03")
ENTER = ("\r", "\n")
TAB = 4
MAX_UNDO = 30
# top bar, text, message line, two rows of keys
ROWS_AROUND_TEXT = 4


def expand(line):
    if "\t" not in line:
        return line
    out = ""
    for c in line:
        out += " " * (8 - len(out) % 8) if c == "\t" else c
    return out


def printable(text):
    for c in text:
        if c < " " or c == "\x7f":
            return "".join("?" if c < " " or c == "\x7f" else c for c in text)
    return text


class Editor:
    def __init__(self, path, term):
        self.term = term
        self.cols = term.cols if term else 80
        self.rows = term.rows if term else 24
        self.height = self.rows - ROWS_AROUND_TEXT
        self.poll = select.poll()
        self.poll.register(sys.stdin, select.POLLIN)
        self.pushed = ""
        self.path = path
        self.lines = [""]
        self.y = self.x = self.want = self.top = self.left = 0
        self.crlf = self.dirty = self.done = self.numbers = False
        self.message = ""
        self.prompt = None  # the question being answered, with what was typed so far
        self.pattern = ""
        self.clip = []
        self.collecting = False  # Ctrl-X and Ctrl-C in a row build one block
        self.undo_stack, self.redo_stack = [], []
        self.last_edit = None
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
        self.shown_bar = self.shown_message = None
        self.shown_top = self.shown_left = None
        self.keys_drawn = False

    def gutter(self):
        return 6 if self.numbers else 0

    def column(self, line, i):
        return len(expand(line[:i]))

    def follow_cursor(self):
        if self.y < self.top:
            self.top = self.y
        elif self.y >= self.top + self.height:
            self.top = self.y - self.height + 1
        width = self.cols - self.gutter() - 1
        c = self.column(self.lines[self.y], self.x)
        if c < self.left:
            self.left = max(0, c - width // 2)
        elif c >= self.left + width:
            self.left = c - width // 2

    def scroll_screen(self, out):
        if self.shown_top is None or self.shown_left != self.left:
            return
        d = self.top - self.shown_top
        if d == 0 or abs(d) >= self.height // 2:
            return
        out.append("\x1b[2;%dr\x1b[%d%s\x1b[r" % (self.height + 1, abs(d), "S" if d > 0 else "T"))
        if d > 0:
            self.shown = self.shown[d:] + [None] * d
        else:
            self.shown = [None] * -d + self.shown[:d]

    def row_text(self, i, line):
        head = "%s%5d%s " % (BLUE, i + 1, RESET) if self.numbers else ""
        width = self.cols - self.gutter()
        text = printable(expand(line)[self.left : self.left + width])
        return head + text + ("\x1b[K" if len(text) < width else "")

    def bar_text(self):
        name = self.path or "New file"
        left = " " + name + (" (modified)" if self.dirty else "")
        right = "Line %d/%d  Col %d " % (self.y + 1, len(self.lines), self.x + 1)
        room = self.cols - len(right)
        if len(left) > room:
            left = left[-room:]
        return left + " " * (room - len(left)) + right

    def keys_text(self, row):
        width = self.cols // len(HELP[row])
        out = ""
        for key, name in HELP[row]:
            out += "%s%s%s %-*s" % (REVERSE, key, RESET, width - 3, name)
        return out

    def refresh(self):
        self.follow_cursor()
        out = []
        if not self.keys_drawn:
            self.keys_drawn = True
            for i in range(2):
                out.append("\x1b[%d;1H%s\x1b[K" % (self.height + 3 + i, self.keys_text(i)))
        self.scroll_screen(out)
        self.shown_top, self.shown_left = self.top, self.left
        bar = self.bar_text()
        if bar != self.shown_bar:
            self.shown_bar = bar
            out.append("\x1b[1;1H%s%s%s" % (REVERSE, printable(bar), RESET))
        numbers = self.numbers
        for r in range(self.height):
            i = self.top + r
            if i < len(self.lines):
                key = (self.lines[i], i) if numbers else self.lines[i]
                if self.shown[r] != key:
                    self.shown[r] = key
                    out.append("\x1b[%d;1H%s" % (r + 2, self.row_text(i, self.lines[i])))
            elif self.shown[r] != 0:
                self.shown[r] = 0
                out.append("\x1b[%d;1H\x1b[K" % (r + 2))
        text = self.prompt if self.prompt is not None else self.message
        text = printable(text)[-(self.cols - 1) :]
        if text != self.shown_message:
            self.shown_message = text
            out.append("\x1b[%d;1H%s\x1b[K" % (self.height + 2, text))
        if self.prompt is not None:
            where = (self.height + 2, len(text) + 1)
        else:
            c = self.column(self.lines[self.y], self.x) - self.left + self.gutter()
            where = (self.y - self.top + 2, c + 1)
        out.append("\x1b[%d;%dH" % where)
        self.send("".join(out))

    # ---- Keys and questions ----

    def waiting(self, ms=0):
        return bool(self.poll.poll(ms))

    def read_key(self):
        if self.pushed:
            c, self.pushed = self.pushed, ""
            return c
        c = sys.stdin.read(1)
        if c != ESC or not self.waiting(25):
            return c
        c = sys.stdin.read(1)
        if c != "[" and c != "O":
            self.pushed = c
            return ESC
        seq = ""
        while True:
            c = sys.stdin.read(1)
            seq += c
            if c.isalpha() or c == "~":
                return SPECIAL.get(seq, "")

    def key(self):
        while True:
            if not self.pushed and not self.waiting():  # keep up with a paste
                self.refresh()
            k = self.read_key()
            if k:
                return k

    def ask(self, question, text=""):
        """A line of text; None if the answer was Esc."""
        while True:
            self.prompt = question + text
            k = self.key()
            if k in ENTER:
                self.prompt = None
                return text
            if k in CANCEL:
                self.prompt = None
                self.message = "Cancelled"
                return None
            if k in BACKSPACE:
                text = text[:-1]
            elif len(k) == 1 and k >= " ":
                text += k

    def choice(self, question, answers):
        """One of the letters of answers; None if the answer was Esc."""
        self.prompt = question
        while True:
            k = self.key()
            if k in CANCEL:
                self.prompt = None
                self.message = "Cancelled"
                return None
            if len(k) == 1 and k.lower() in answers:
                self.prompt = None
                return k.lower()

    # ---- Files ----

    def load(self, path):
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError as e:
            if e.args[0] != 2:
                raise
            self.message = "New file"
            return
        try:
            text = data.decode()
        except UnicodeError:
            raise ValueError("%s is not a text file" % path)
        self.crlf = "\r\n" in text
        self.lines = text.split("\n")
        if self.crlf:
            self.lines = [s[:-1] if s.endswith("\r") else s for s in self.lines]
        if len(self.lines) > 1 and not self.lines[-1]:
            self.lines.pop()
        self.message = "Opened %d lines" % len(self.lines)

    def save(self):
        """True if saved. Through a temporary file: a full disk must not cost the old one."""
        path = self.path or self.ask("Save as: ")
        if not path:
            return False
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
        self.path = path
        self.dirty = False
        self.message = "Saved %d lines" % len(self.lines)
        return True

    def quit(self):
        if self.dirty:
            answer = self.choice("Save changes? y = yes, n = no, Esc = keep editing", "yn")
            if answer is None or (answer == "y" and not self.save()):
                return
        self.done = True

    # ---- Undo ----

    def edit(self, what):
        """Before a change. Keys of one kind in a row are undone together."""
        if what is None or what != self.last_edit:
            self.undo_stack.append((self.lines[:], self.y, self.x))
            del self.undo_stack[:-MAX_UNDO]
        self.redo_stack = []
        self.last_edit = what
        self.dirty = True

    def swap_state(self, source, target, empty):
        if not source:
            self.message = empty
            return
        target.append((self.lines[:], self.y, self.x))
        self.lines, self.y, self.x = source.pop()
        self.want = self.x
        self.dirty = True
        self.last_edit = None

    # ---- Typing ----

    def type_char(self, text):
        self.edit("type")
        line = self.lines[self.y]
        self.lines[self.y] = line[: self.x] + text + line[self.x :]
        self.x += len(text)

    def new_line(self):
        self.edit(None)
        line = self.lines[self.y]
        indent = ""
        if not self.waiting():  # a paste brings its own indentation
            indent = line[: min(self.x, len(line) - len(line.lstrip()))]
        self.lines[self.y : self.y + 1] = [line[: self.x], indent + line[self.x :]]
        self.y += 1
        self.x = len(indent)

    def backspace(self):
        line = self.lines[self.y]
        if self.x:
            self.edit("delete")
            n = 1
            if self.x % TAB == 0 and not line[: self.x].strip():
                n = TAB
            self.lines[self.y] = line[: self.x - n] + line[self.x :]
            self.x -= n
        elif self.y:
            self.edit(None)
            self.y -= 1
            self.x = len(self.lines[self.y])
            self.lines[self.y : self.y + 2] = [self.lines[self.y] + line]

    def delete(self):
        line = self.lines[self.y]
        if self.x < len(line):
            self.edit("delete")
            self.lines[self.y] = line[: self.x] + line[self.x + 1 :]
        elif self.y + 1 < len(self.lines):
            self.edit(None)
            self.lines[self.y : self.y + 2] = [line + self.lines[self.y + 1]]

    def collect(self, line):
        if not self.collecting:
            self.clip = []
        self.clip.append(line)
        self.collecting = True

    def cut_line(self):
        self.collect(self.lines[self.y])
        self.edit(None)
        del self.lines[self.y]
        self.lines = self.lines or [""]
        self.y = min(self.y, len(self.lines) - 1)
        self.x = 0
        self.message = "%d lines to paste" % len(self.clip)

    def copy_line(self):
        self.collect(self.lines[self.y])
        self.y = min(self.y + 1, len(self.lines) - 1)
        self.x = 0
        self.message = "%d lines to paste" % len(self.clip)

    def paste(self):
        if not self.clip:
            self.message = "Nothing to paste: Ctrl-X or Ctrl-C first"
            return
        self.edit(None)
        self.lines[self.y : self.y] = self.clip
        self.y += len(self.clip)
        self.x = 0

    # ---- Moving ----

    def move_row(self, rows):
        self.y = max(0, min(len(self.lines) - 1, self.y + rows))
        self.x = min(self.want, len(self.lines[self.y]))

    def left_key(self):
        if self.x:
            self.x -= 1
        elif self.y:
            self.y -= 1
            self.x = len(self.lines[self.y])

    def right_key(self):
        if self.x < len(self.lines[self.y]):
            self.x += 1
        elif self.y + 1 < len(self.lines):
            self.y += 1
            self.x = 0

    def go_to_line(self):
        text = self.ask("Go to line: ")
        if text:
            if not text.isdigit():
                raise ValueError("Not a line number: " + text)
            self.y = max(0, min(len(self.lines), int(text)) - 1)
            self.x = 0

    # ---- Find and replace ----

    def next_match(self, text, y, x):
        """The first match from (y, x) to the end of the file, ignoring case."""
        while y < len(self.lines):
            at = self.lines[y].lower().find(text, x)
            if at >= 0:
                return y, at
            y += 1
            x = 0
        return None

    def find_next(self):
        if not self.pattern:
            self.find()
            return
        text = self.pattern.lower()
        found = self.next_match(text, self.y, self.x + 1)
        if found is None:
            found = self.next_match(text, 0, 0)
            if found:
                self.message = "Back to the top"
        if found is None:
            self.message = "Not found: " + self.pattern
            return
        self.y, self.x = found

    def find(self):
        text = self.ask("Find: ", self.pattern)
        if text:
            self.pattern = text
            self.find_next()

    def replace(self):
        old = self.ask("Replace: ", self.pattern)
        if not old:
            return
        new = self.ask("With: ")
        if new is None:
            return
        self.pattern = old
        size = len(self.undo_stack)
        self.edit(None)
        y, x = self.y, self.x
        count = 0
        everything = False
        while True:
            found = self.next_match(old.lower(), y, x)
            if found is None:
                break
            y, x = found
            self.y, self.x = y, x
            answer = "y"
            if not everything:
                answer = self.choice("Replace this? y = yes, n = no, a = all, Esc = stop", "yna")
            if answer is None:
                break
            everything = everything or answer == "a"
            if answer == "n":
                x += len(old)
                continue
            line = self.lines[y]
            self.lines[y] = line[:x] + new + line[x + len(old) :]
            x += len(new)
            count += 1
        if not count:
            del self.undo_stack[size:]
        self.message = "%d replaced" % count

    # ---- Keys ----

    def handle(self, k):
        collecting, self.collecting = self.collecting, False
        moved = True
        if k == "up":
            self.move_row(-1)
        elif k == "down":
            self.move_row(1)
        elif k == "pgup":
            self.move_row(-self.height)
        elif k == "pgdn":
            self.move_row(self.height)
        else:
            moved = False
        if moved:
            self.last_edit = None
            return
        if k == "left":
            self.left_key()
        elif k == "right":
            self.right_key()
        elif k == "home":
            self.x = 0
        elif k == "end":
            self.x = len(self.lines[self.y])
        elif k in ENTER:
            self.new_line()
        elif k in BACKSPACE:
            self.backspace()
        elif k == "del":
            self.delete()
        elif k == "\t":
            self.type_char(" " * (TAB - self.x % TAB))
        elif k == "\x13":  # Ctrl-S
            self.save()
        elif k == "\x11":  # Ctrl-Q
            self.quit()
        elif k == "\x1a":  # Ctrl-Z
            self.swap_state(self.undo_stack, self.redo_stack, "Nothing to undo")
        elif k == "\x19":  # Ctrl-Y
            self.swap_state(self.redo_stack, self.undo_stack, "Nothing to redo")
        elif k == "\x06":  # Ctrl-F
            self.find()
        elif k == "\x0e":  # Ctrl-N
            self.find_next()
        elif k == "\x12":  # Ctrl-R
            self.replace()
        elif k == "\x07":  # Ctrl-G
            self.go_to_line()
        elif k == "\x18":  # Ctrl-X
            self.collecting = collecting
            self.cut_line()
        elif k == "\x03":  # Ctrl-C
            self.collecting = collecting
            self.copy_line()
        elif k == "\x16":  # Ctrl-V
            self.paste()
        elif k == "\x0c":  # Ctrl-L
            self.numbers = not self.numbers
            self.left = 0
            self.forget_screen()
        elif len(k) == 1 and k >= " " and k != "\x7f":
            self.type_char(k)
        self.want = self.x

    def run(self):
        while not self.done:
            k = self.key()
            self.message = ""
            try:
                self.handle(k)
            except (ValueError, OSError, UnicodeError) as e:
                self.prompt = None
                self.message = "Error: %s" % (e if str(e) else "disk")


def terminal():
    """The terminal on the display, started if it is not, or None on a serial port only."""
    try:
        import ansiterm
    except ImportError:
        return None
    return ansiterm.term or ansiterm.start()


def main(path=None):
    term = terminal()
    editor = Editor(path, term)
    micropython.kbd_intr(-1)  # Ctrl-C is a key here
    editor.send("\x1b[?1049h\x1b[0m\x1b[2J")
    try:
        editor.run()
    finally:
        editor.send("\x1b[?1049l")
        micropython.kbd_intr(3)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
