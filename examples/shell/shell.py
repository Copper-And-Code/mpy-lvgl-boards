# A small Linux-like shell: the screen is an ANSI terminal (ansiterm.py), the keyboard is
# the one of a terminal on the serial port, which shows the output too. Runs on every board.
#
#   >>> import shell
#   >>> shell.main()
#
# Copy shell.py, ansiterm.py and ansifont.py to the board first (in Thonny: Save as >
# MicroPython device), then use a real terminal: PuTTY on Windows, picocom or minicom on Linux. Thonny's
# Shell runs it too with `Run`, but it sends whole lines, so arrows, Tab and history are not
# available. Without ansiterm.py it works on the serial port only.
#
#   Keys: left/right, Home/End, Del, up/down (history), Tab (complete), Ctrl-A/E/U/W/L,
#         Ctrl-C (drop the line, or stop a command), Ctrl-D (exit on an empty line)
#   Shell: "quotes", \escapes, *.py and ? wildcards, ~, cmd1 | cmd2, > file, >> file
#
# `help` lists the commands. Files are for real: `rm -r` asks nothing, as on Linux.
#
# Other programs: a word that is not a command runs <word>.py from /bin or /sd/bin, or
# the file itself if it is a path or ends in .py, with `__name__ == "__main__"` and the
# arguments in sys.argv:
#
#   edit notes.txt      runs /bin/edit.py with sys.argv == ["/bin/edit.py", "notes.txt"]
#
# A program can read single keys with sys.stdin.read(1) and take Ctrl-C as a key with
# micropython.kbd_intr(-1); sys.exit() or the end of the file returns to the shell, which
# takes Ctrl-C back. Its print() goes to the terminal: | and > do not catch it. A
# full-screen program writes ANSI sequences and gets the size from ansiterm.term.
import gc
import io
import machine
import micropython
import os
import sys
import time

# ESP32-4848S040: the SD card, mounted on /sd if it is not mounted yet
SD_PINS = {"slot": 2, "sck": 48, "miso": 41, "mosi": 47, "cs": 42, "freq": 10_000_000}

GREEN, BLUE, RESET = "\x1b[1;32m", "\x1b[1;34m", "\x1b[0m"
CHUNK = 512
PATH = ("/bin", "/sd/bin")  # where the Python programs are
ERRORS = {
    1: "Operation not permitted",
    2: "No such file or directory",
    5: "Input/output error",
    13: "Permission denied",
    16: "Device or resource busy",
    17: "File exists",
    19: "No such device",
    20: "Not a directory",
    21: "Is a directory",
    22: "Invalid argument",
    28: "No space left on device",
    30: "Read-only file system",
    39: "Directory not empty",
}

term = None  # the terminal on the display, if there is one
WIDTH = 80  # columns: the line being typed scrolls sideways inside them
history = []
out = None  # where the running command writes: the terminal, a file or the next command
pipe = None  # what the previous command of a pipeline wrote


class Usage(Exception):
    pass


class Exit(Exception):
    pass


def w(s):
    out.write(s)
    if term:
        term.check()


def wl(s=""):
    w(s)
    w("\n")


# ---- Paths ----


def stat(path):
    try:
        return os.stat(path)
    except OSError:
        return None


def is_dir(path):
    st = stat(path)
    return st is not None and st[0] & 0x4000 != 0


def clean(path):
    """Absolute path without . and .. ."""
    if path == "~" or path.startswith("~/"):
        path = "/" + path[1:]
    if not path.startswith("/"):
        path = os.getcwd() + "/" + path
    parts = []
    for p in path.split("/"):
        if p == "..":
            if parts:
                parts.pop()
        elif p and p != ".":
            parts.append(p)
    return "/" + "/".join(parts)


def join(a, b):
    return b if a == "" else (a + b if a.endswith("/") else a + "/" + b)


def split(path):
    i = path.rfind("/")
    if i < 0:
        return "", path
    return path[: i + 1], path[i + 1 :]


def match(pat, s):
    """*, ? as in a shell."""
    if not pat:
        return not s
    if pat[0] == "*":
        return any(match(pat[1:], s[i:]) for i in range(len(s) + 1))
    return bool(s) and (pat[0] == "?" or pat[0] == s[0]) and match(pat[1:], s[1:])


def glob(pat):
    """Wildcards in the last part of a path only; no match leaves the word as it is."""
    if "*" not in pat and "?" not in pat:
        return [pat]
    d, name = split(pat)
    try:
        names = sorted(os.listdir(d or "."))
    except OSError:
        return [pat]
    hits = [d + n for n in names if (n[0] != "." or name[0] == ".") and match(name, n)]
    return hits or [pat]


# ---- Options ----


def flags(args, known):
    """Splits "-la" style options from the other arguments; "--" ends them."""
    opts, rest = "", []
    for i, a in enumerate(args):
        if a == "--":
            rest += args[i + 1 :]
            break
        if len(a) > 1 and a[0] == "-" and (a[1] in known or not a[1].isdigit()):
            for c in a[1:]:
                if c not in known:
                    raise Usage("invalid option -- '%s'" % c)
            opts += a[1:]
        else:
            rest.append(a)
    return opts, rest


def count_option(args, default):
    """-n 5 or -5, for head and tail."""
    n, rest, i = default, [], 0
    while i < len(args):
        a = args[i]
        if a == "-n" and i + 1 < len(args):
            n = args[i + 1]
            i += 1
        elif len(a) > 1 and a[0] == "-" and a[1:].isdigit():
            n = a[1:]
        else:
            rest.append(a)
        i += 1
    try:
        return int(n), rest
    except ValueError:
        raise Usage("invalid number: %s" % n)


def inputs(args):
    """The streams a text command reads: its files, or the previous command of the pipe."""
    if args:
        return [(a, None) for a in args]
    if pipe is None:
        raise Usage("missing file operand")
    return [("", io.BytesIO(pipe))]


def lines(name, stream):
    f = stream or open(name, "rb")
    try:
        while True:
            line = f.readline()
            if not line:
                return
            yield line
    finally:
        if stream is None:
            f.close()


# ---- Commands: directories and files ----


def size_text(n):
    for unit in ("", "K", "M", "G"):
        if n < 1024:
            return "%d%s" % (n, unit)
        n //= 1024
    return "%dT" % n


def date_text(t):
    d = time.localtime(t)
    return "%04d-%02d-%02d %02d:%02d" % d[:5]


def ls_entry(path, name, opts):
    st = stat(path)
    if st is None:
        return name
    folder = st[0] & 0x4000 != 0
    shown = name
    if out is TERMINAL and folder:
        shown = BLUE + name + RESET
    elif "F" in opts and folder:
        shown = name + "/"
    if "l" not in opts:
        return shown
    n = 0 if folder else st[6]  # the value for a directory means nothing on littlefs
    size = size_text(n) if "h" in opts else str(n)
    return "%s %8s %s %s" % ("drwxr-xr-x" if folder else "-rw-r--r--", size, date_text(st[8]), shown)


def cmd_ls(args):
    opts, paths = flags(args, "lahF1")
    for i, p in enumerate(paths or ["."]):
        full = clean(p)
        st = os.stat(full)
        if st[0] & 0x4000 == 0:
            wl(ls_entry(full, p, opts))
            continue
        if len(paths) > 1:
            wl("%s%s:" % ("\n" if i else "", p))
        names = sorted(n for n in os.listdir(full) if "a" in opts or n[0] != ".")
        entries = [ls_entry(join(full, n), n, opts) for n in names]
        if "l" in opts or "1" in opts or out is not TERMINAL:
            for e in entries:
                wl(e)
        elif entries:
            wl("  ".join(entries))


def cmd_cd(args):
    if len(args) > 1:
        raise Usage("too many arguments")
    os.chdir(clean(args[0] if args else "/"))


def cmd_pwd(args):
    wl(os.getcwd() or "/")


def cmd_mkdir(args):
    opts, paths = flags(args, "p")
    if not paths:
        raise Usage("missing operand")
    for p in paths:
        p = clean(p)
        if "p" not in opts:
            os.mkdir(p)
            continue
        part = ""
        for name in p.split("/")[1:]:
            part += "/" + name
            if not is_dir(part):
                os.mkdir(part)


def cmd_rmdir(args):
    if not args:
        raise Usage("missing operand")
    for p in args:
        os.rmdir(clean(p))


def remove_tree(path):
    if is_dir(path):
        for n in os.listdir(path):
            remove_tree(join(path, n))
        os.rmdir(path)
    else:
        os.remove(path)


def cmd_rm(args):
    opts, paths = flags(args, "rRf")
    if not paths and "f" not in opts:
        raise Usage("missing operand")
    for p in paths:
        full = clean(p)
        if stat(full) is None:
            if "f" not in opts:
                raise OSError(2)
        elif full == "/":
            raise Usage("refusing to remove /")
        elif "r" in opts or "R" in opts:
            remove_tree(full)
        elif is_dir(full):
            raise OSError(21)
        else:
            os.remove(full)


def copy_file(src, dst):
    if clean(src) == clean(dst):
        raise Usage("'%s' and '%s' are the same file" % (src, dst))
    buf = bytearray(CHUNK)
    with open(src, "rb") as a, open(dst, "wb") as b:
        while True:
            n = a.readinto(buf)
            if not n:
                return
            b.write(buf[:n])


def copy_tree(src, dst):
    if is_dir(src):
        if clean(dst + "/").startswith(clean(src) + "/"):
            raise Usage("cannot copy '%s' into itself" % src)
        if not is_dir(dst):
            os.mkdir(dst)
        for n in os.listdir(src):
            copy_tree(join(src, n), join(dst, n))
    else:
        copy_file(src, dst)


def targets(paths):
    """cp and mv: (source, destination) pairs; the last path is a file or a directory."""
    if len(paths) < 2:
        raise Usage("missing destination file operand")
    dst = clean(paths[-1])
    if is_dir(dst):
        return [(clean(p), join(dst, split(clean(p))[1])) for p in paths[:-1]]
    if len(paths) > 2:
        raise OSError(20)
    return [(clean(paths[0]), dst)]


def cmd_cp(args):
    opts, paths = flags(args, "rR")
    for src, dst in targets(paths):
        if "r" not in opts and "R" not in opts and is_dir(src):
            raise Usage("-r not specified; omitting directory '%s'" % src)
        copy_tree(src, dst)


def cmd_mv(args):
    for src, dst in targets(args):
        if stat(src) is None:
            raise OSError(2)
        try:
            os.rename(src, dst)
        except OSError:
            # from a filesystem to another (flash to SD), or the target exists
            copy_tree(src, dst)
            remove_tree(src)


def cmd_touch(args):
    if not args:
        raise Usage("missing file operand")
    for p in args:
        open(clean(p), "ab").close()


def cmd_stat(args):
    if not args:
        raise Usage("missing operand")
    for p in args:
        st = os.stat(clean(p))
        wl("  File: %s" % clean(p))
        if st[0] & 0x4000:
            wl("  Type: directory")
        else:
            wl("  Size: %d  regular file" % st[6])
        wl("Modify: %s" % date_text(st[8]))


def tree(path, prefix):
    names = sorted(os.listdir(path))
    for i, n in enumerate(names):
        last = i == len(names) - 1
        full = join(path, n)
        wl("%s%s%s" % (prefix, "`-- " if last else "|-- ", n))
        if is_dir(full):
            tree(full, prefix + ("    " if last else "|   "))


def cmd_tree(args):
    path = clean(args[0]) if args else clean(".")
    wl(args[0] if args else ".")
    tree(path, "")


def walk(path, shown, name):
    if name is None or match(name, split(path)[1]):
        wl(shown)
    if is_dir(path):
        for n in sorted(os.listdir(path)):
            walk(join(path, n), join(shown, n), name)


def cmd_find(args):
    name = None
    start = "."
    i = 0
    while i < len(args):
        if args[i] == "-name" and i + 1 < len(args):
            name = args[i + 1]
            i += 1
        else:
            start = args[i]
        i += 1
    os.stat(clean(start))
    walk(clean(start), start, name)


def disk_usage(path):
    if not is_dir(path):
        return os.stat(path)[6]
    return sum(disk_usage(join(path, n)) for n in os.listdir(path))


def cmd_du(args):
    opts, paths = flags(args, "hs")
    for p in paths or ["."]:
        n = disk_usage(clean(p))
        wl("%s\t%s" % (size_text(n) if "h" in opts else n, p))


# ---- Commands: text ----


def cmd_cat(args):
    opts, files = flags(args, "n")
    n = 0
    for name, stream in inputs(files):
        if "n" in opts:
            for line in lines(name and clean(name), stream):
                n += 1
                w("%6d  " % n)
                w(line)
        elif stream:
            w(stream.read())
        else:
            with open(clean(name), "rb") as f:
                while True:
                    data = f.read(CHUNK)
                    if not data:
                        break
                    w(data)


def cmd_head(args):
    n, files = count_option(args, 10)
    for name, stream in inputs(files):
        if len(files) > 1:
            wl("==> %s <==" % name)
        for i, line in enumerate(lines(name and clean(name), stream)):
            if i >= n:
                break
            w(line)


def cmd_tail(args):
    n, files = count_option(args, 10)
    for name, stream in inputs(files):
        if len(files) > 1:
            wl("==> %s <==" % name)
        last = []
        for line in lines(name and clean(name), stream):
            last.append(line)
            if len(last) > n:
                last.pop(0)
        for line in last:
            w(line)


def cmd_wc(args):
    opts, files = flags(args, "lwc")
    total = [0, 0, 0]
    for name, stream in inputs(files):
        c = [0, 0, 0]
        for line in lines(name and clean(name), stream):
            c[0] += 1
            c[1] += len(line.split())
            c[2] += len(line)
        total = [a + b for a, b in zip(total, c)]
        wc_line(c, opts, name)
    if len(files) > 1:
        wc_line(total, opts, "total")


def wc_line(c, opts, name):
    shown = [str(v) for v, o in zip(c, "lwc") if not opts or o in opts]
    wl(" ".join("%7s" % v for v in shown) + (" " + name if name else ""))


def cmd_grep(args):
    opts, rest = flags(args, "invc")
    if not rest:
        raise Usage("usage: grep [-invc] text [file...]")
    needle = rest[0].encode()
    if "i" in opts:
        needle = needle.lower()
    many = len(rest) > 2
    for name, stream in inputs(rest[1:]):
        hits = 0
        for i, line in enumerate(lines(name and clean(name), stream)):
            found = needle in (line.lower() if "i" in opts else line)
            if found == ("v" in opts):
                continue
            hits += 1
            if "c" in opts:
                continue
            if many:
                w(name + ":")
            if "n" in opts:
                w("%d:" % (i + 1))
            w(line)
        if "c" in opts:
            wl("%s%d" % (name + ":" if many else "", hits))


def cmd_sort(args):
    opts, files = flags(args, "r")
    all_lines = []
    for name, stream in inputs(files):
        all_lines += list(lines(name and clean(name), stream))
    all_lines.sort(reverse="r" in opts)
    for line in all_lines:
        w(line)


def cmd_hexdump(args):
    for name, stream in inputs(args):
        f = stream or open(clean(name), "rb")
        pos = 0
        while True:
            data = f.read(16)
            if not data:
                break
            text = "".join(chr(b) if 32 <= b < 127 else "." for b in data)
            codes = " ".join("%02x" % b for b in data)
            wl("%08x  %-47s  |%s|" % (pos, codes, text))
            pos += len(data)
        if stream is None:
            f.close()


def cmd_echo(args):
    opts = ""
    if args and args[0] == "-n":
        opts, args = "n", args[1:]
    w(" ".join(args))
    if not opts:
        w("\n")


# ---- Commands: system ----


def cmd_df(args):
    opts, _ = flags(args, "h")
    wl("Mounted on         Size        Used       Avail  Use%")
    root = os.statvfs("/")
    mounts = ["/"] + [
        "/" + n for n in os.listdir("/") if is_dir("/" + n) and os.statvfs("/" + n) != root
    ]
    for m in mounts:
        s = os.statvfs(m)
        size, free = s[1] * s[2], s[1] * s[3]
        used = size - free
        v = [size_text(x) if "h" in opts else str(x) for x in (size, used, free)]
        wl("%-12s %10s  %10s  %10s  %3d%%" % (m, v[0], v[1], v[2], used * 100 // (size or 1)))


def cmd_free(args):
    gc.collect()
    used, free = gc.mem_alloc(), gc.mem_free()
    wl("Python heap: total %d  used %d  free %d" % (used + free, used, free))


def cmd_uname(args):
    u = os.uname()
    if "-a" in args:
        wl(" ".join((u.sysname, u.nodename, u.release, u.version, u.machine)))
    else:
        wl(u.sysname)


def cmd_date(args):
    d = time.localtime()
    wl("%04d-%02d-%02d %02d:%02d:%02d" % d[:6])


def cmd_uptime(args):
    s = time.ticks_ms() // 1000  # wraps after some days
    wl("up %d:%02d:%02d" % (s // 3600, s // 60 % 60, s % 60))


def cmd_sleep(args):
    if not args:
        raise Usage("missing operand")
    time.sleep(float(args[0]))


def cmd_history(args):
    for i, line in enumerate(history):
        wl("%5d  %s" % (i + 1, line))


def cmd_clear(args):
    w("\x1b[2J\x1b[H")


def find_program(name):
    if "/" in name or name.endswith(".py"):
        path = clean(name)
        return path if stat(path) and not is_dir(path) else None
    for d in PATH:
        path = "%s/%s.py" % (d, name)
        if stat(path):
            return path
    return None


def programs():
    names = []
    for d in PATH:
        try:
            names += [n[:-3] for n in os.listdir(d) if n.endswith(".py")]
        except OSError:
            pass
    return names


def checked_print(*args, **kw):
    print(*args, **kw)
    if term:
        term.check()  # or a loop of print() would keep every Ctrl-C in the terminal


def run_program(path, args):
    with open(path) as f:
        code = f.read()
    saved = sys.argv[:]
    sys.argv[:] = [path] + args
    try:
        exec(code, {"__name__": "__main__", "__file__": path, "print": checked_print})
    except SystemExit:
        pass
    except Exception as e:
        sys.print_exception(e)
    finally:
        sys.argv[:] = saved
        micropython.kbd_intr(3)  # the program may have taken Ctrl-C


def cmd_python(args):
    if not args:
        raise Usage("usage: python file.py [arguments] (Ctrl-C stops it)")
    run_program(clean(args[0]), args[1:])


def cmd_which(args):
    for name in args:
        path = find_program(name)
        if name in COMMANDS:
            wl("%s: shell built-in" % name)
        elif path:
            wl(path)
        else:
            wl("%s not found" % name)


def cmd_reboot(args):
    machine.reset()


def cmd_exit(args):
    raise Exit


def cmd_help(args):
    wl("Files:  ls [-lahF1] cd pwd mkdir [-p] rmdir rm [-rf]")
    wl("        cp [-r] mv touch stat tree du [-hs]")
    wl("        find [dir] [-name pat]")
    wl("Text:   cat [-n] head tail [-n N] wc [-lwc] grep [-invc]")
    wl("        sort [-r] hexdump echo [-n]")
    wl("System: df [-h] free uname [-a] date uptime sleep history")
    wl("        clear which python reboot exit")
    wl("Programs: name.py in /bin or /sd/bin, or python file.py")
    wl("Also:   * ?   cmd | cmd   cmd > file   cmd >> file   ~ is /")


COMMANDS = {}
for _name, _f in list(globals().items()):
    if _name.startswith("cmd_"):
        COMMANDS[_name[4:]] = _f
COMMANDS["hd"] = cmd_hexdump
COMMANDS["cls"] = cmd_clear

# ---- Parsing and running ----


def parse(line):
    """Words as (text, quoted); | > >> as (operator, None). None if a quote stays open."""
    words, cur, quoted, started = [], "", False, False
    i, q = 0, None
    while i < len(line):
        c = line[i]
        if q:
            if c == q:
                q = None
            elif c == "\\" and q == '"' and i + 1 < len(line):
                i += 1
                cur += line[i]
            else:
                cur += c
        elif c in "'\"":
            q, quoted, started = c, True, True
        elif c == "\\" and i + 1 < len(line):
            i += 1
            cur += line[i]
            quoted, started = True, True
        elif c in " \t|>":
            if started:
                words.append((cur, quoted))
                cur, quoted, started = "", False, False
            if c == "|":
                words.append(("|", None))
            elif c == ">":
                if line[i + 1 : i + 2] == ">":
                    i += 1
                    words.append((">>", None))
                else:
                    words.append((">", None))
        else:
            cur += c
            started = True
        i += 1
    if q:
        return None
    if started:
        words.append((cur, quoted))
    return words


def expand(word, quoted):
    if quoted:
        return [word]
    if word == "~" or word.startswith("~/"):
        word = clean(word)
    return glob(word)


def stages(words):
    """[(arguments, redirect file, append)], one for each command of the pipeline."""
    result = []
    args, target, append, i = [], None, False, 0
    while i < len(words):
        word, quoted = words[i]
        if quoted is not None:
            args += expand(word, quoted)
        elif word == "|":
            if not args:
                raise Usage("syntax error near '|'")
            result.append((args, target, append))
            args, target, append = [], None, False
        else:
            i += 1
            if i == len(words) or words[i][1] is None:
                raise Usage("syntax error near '%s'" % word)
            target, append = clean(words[i][0]), word == ">>"
        i += 1
    if not args:
        raise Usage("syntax error: command expected")
    result.append((args, target, append))
    return result


class Capture:
    def __init__(self):
        self.parts = []

    def write(self, s):
        self.parts.append(s if isinstance(s, bytes) else s.encode())

    def take(self):
        return b"".join(self.parts)


def fail(name, e):
    if isinstance(e, OSError) and e.args:
        text = ERRORS.get(e.args[0], "error %s" % e.args[0])
    else:
        text = str(e) or type(e).__name__
    print("%s: %s" % (name, text))


def run_stage(args, target, append, sink):
    global out
    name = args[0]
    f = COMMANDS.get(name)
    program = None if f else find_program(name)
    if f is None and program is None:
        print("%s: command not found" % name)
        return False
    file = None
    try:
        if target:
            file = open(target, "ab" if append else "wb")
        out = file or sink
        if f:
            f(args[1:])
        else:
            run_program(program, args[1:])
        return True
    except Exit:
        raise
    except Exception as e:
        fail(name, e)
        return False
    finally:
        if file:
            file.close()
        out = TERMINAL


def run_line(line):
    global pipe
    words = parse(line)
    if words is None:
        print("syntax error: unterminated quote")
        return
    if not words:
        return
    try:
        pipeline = stages(words)
    except Usage as e:
        print(e)
        return
    pipe = None
    try:
        for i, (args, target, append) in enumerate(pipeline):
            sink = TERMINAL if i == len(pipeline) - 1 else Capture()
            ok = run_stage(args, target, append, sink)
            pipe = sink.take() if sink is not TERMINAL else None
            gc.collect()
            if not ok:
                break
    finally:
        pipe = None


# ---- The line editor ----


def prompt():
    """The prompt, and how many columns it takes."""
    host, path = os.uname().sysname, os.getcwd() or "/"
    text = "%smpy@%s%s:%s%s%s$ " % (GREEN, host, RESET, BLUE, path, RESET)
    return text, len(host) + len(path) + 7


def key():
    """One key: a character, or the name of an escape sequence."""
    c = sys.stdin.read(1)
    if c != "\x1b":
        return c
    c = sys.stdin.read(1)
    if c not in "[O":
        return ""
    s = ""
    while True:
        c = sys.stdin.read(1)
        s += c
        if c.isalpha() or c == "~":
            break
    return {
        "A": "up", "B": "down", "C": "right", "D": "left",
        "H": "home", "F": "end", "1~": "home", "4~": "end", "3~": "delete",
    }.get(s, "")


def common_prefix(names):
    p = names[0]
    for n in names:
        while not n.startswith(p):
            p = p[:-1]
    return p


def complete(text):
    """Tab on the last word: commands for the first word, paths for the others."""
    word = text[text.rfind(" ") + 1 :]
    if " " not in text:
        return word, sorted(n for n in list(COMMANDS) + programs() if n.startswith(word))
    d, name = split(word)
    try:
        names = os.listdir(clean(d) if d else ".")
    except OSError:
        return word, []
    hits = []
    for n in sorted(names):
        if n.startswith(name) and (name or n[0] != "."):
            hits.append(d + n + ("/" if is_dir(clean(d + n)) else ""))
    return word, hits


def read_line():
    line, pos = "", 0
    back = len(history)  # position in the history, the end being the new line
    last_crlf = False

    def redraw():
        text, used = prompt()
        room = max(8, WIDTH - used - 1)
        first = max(0, pos - room)
        shown = line[first : first + room]
        sys.stdout.write("\r\x1b[K" + text + shown)
        if pos - first < len(shown):
            sys.stdout.write("\x1b[%dD" % (len(shown) - (pos - first)))

    redraw()
    while True:
        k = key()
        if k == "\n" and last_crlf:  # \r\n is one Enter
            last_crlf = False
            continue
        last_crlf = k == "\r"
        if k in ("\r", "\n"):
            sys.stdout.write("\n")
            return line
        if k == "\x03":  # Ctrl-C
            sys.stdout.write("^C\n")
            return ""
        if k == "\x04":  # Ctrl-D
            if not line:
                sys.stdout.write("exit\n")
                return None
            k = "delete"
        if k in ("\x7f", "\x08"):
            if pos:
                line = line[: pos - 1] + line[pos:]
                pos -= 1
        elif k == "delete":
            line = line[:pos] + line[pos + 1 :]
        elif k == "left":
            pos = max(0, pos - 1)
        elif k == "right":
            pos = min(len(line), pos + 1)
        elif k in ("home", "\x01"):
            pos = 0
        elif k in ("end", "\x05"):
            pos = len(line)
        elif k == "\x15":  # Ctrl-U
            line, pos = line[pos:], 0
        elif k == "\x17":  # Ctrl-W
            start = line[:pos].rstrip().rfind(" ") + 1
            line, pos = line[:start] + line[pos:], start
        elif k == "\x0c":  # Ctrl-L
            sys.stdout.write("\x1b[2J\x1b[H")
        elif k in ("up", "down"):
            back = max(0, min(len(history), back + (-1 if k == "up" else 1)))
            line = history[back] if back < len(history) else ""
            pos = len(line)
        elif k == "\t":
            word, hits = complete(line[:pos])
            if hits:
                p = common_prefix(hits)
                if len(hits) == 1 and not p.endswith("/"):
                    p += " "
                line = line[: pos - len(word)] + p + line[pos:]
                pos += len(p) - len(word)
                if len(hits) > 1:
                    sys.stdout.write("\n" + "  ".join(hits) + "\n")
        elif len(k) == 1 and k >= " ":
            line = line[:pos] + k + line[pos:]
            pos += 1
        redraw()


def mount_sd():
    """The 4848S040 card; its bus works only with the display started, see docs."""
    if "4848S040" not in os.uname().machine or "sd" in os.listdir("/"):
        return
    try:
        import display_driver  # noqa: F401

        os.mount(machine.SDCard(**SD_PINS), "/sd")
        print("SD card mounted on /sd")
    except Exception as e:
        print("no SD card (%r)" % e)


class Terminal:
    def write(self, s):
        sys.stdout.write(s)


TERMINAL = Terminal()
out = TERMINAL


def start_terminal():
    global term, WIDTH
    try:
        import ansiterm
    except ImportError as e:
        print("no terminal on the display (%s)" % e)
        return None
    term = ansiterm.start()
    WIDTH = term.cols
    return ansiterm


def main():
    screen = start_terminal()
    print("MicroPython shell, `help` lists the commands,")
    print("`exit` or Ctrl-D ends it")
    mount_sd()
    try:
        while True:
            if screen:
                screen.start()  # a program may have shown its own screen
                term.interrupted = False
            micropython.kbd_intr(-1)  # Ctrl-C reaches the editor as a key
            line = read_line()
            micropython.kbd_intr(3)  # and it stops the commands
            if line is None:
                return
            line = line.strip()
            if line and (not history or history[-1] != line):
                history.append(line)
                del history[:-50]
            try:
                run_line(line)
            except KeyboardInterrupt:
                print("^C")
    except Exit:
        pass
    finally:
        micropython.kbd_intr(3)
        if screen:
            screen.stop()


if __name__ == "__main__":
    main()
