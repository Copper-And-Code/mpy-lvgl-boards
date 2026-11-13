#!/usr/bin/env python3
"""Ctrl-C inside vi and edit (examples/shell) through the serial port: Ctrl-C is a key
there. Opens /shell.py, never saves (vi :q!, edit Ctrl-Q, and "n" if it asks).

    tests/hil/editor_ctrlc_host.py PORT REPETITIONS LOG

The shell must be at its prompt on PORT, with vi.py and edit.py in /bin. The editors
draw on the display only: while one runs the serial port is silent, and the shell
prompt on it means the editor has ended."""
import random, re, sys, time
import serial

PROMPT = rb"mpy@\w+\x1b\[0m:\x1b\[1;34m[^\x1b]*\x1b\[0m\$ "
port, reps, logp = sys.argv[1], int(sys.argv[2]), sys.argv[3]
log = open(logp, "w")
rnd = random.Random(2)


def out(l):
    print(l); log.write(l + "\n"); log.flush()


s = serial.Serial(); s.port, s.baudrate, s.timeout = port, 115200, 0.05
s.dtr, s.rts = True, False; s.open()


def until(p, t):
    b = b""; e = time.time() + t
    while time.time() < e:
        b += s.read(4096)
        if re.search(p, b):
            return b, True
    return b, False


def drain(t):
    e = time.time() + t
    while time.time() < e:
        s.read(4096)


s.write(b"\r"); _, ok = until(PROMPT, 5)
if not ok:
    out("RESULT: FAILED (no prompt)"); sys.exit(1)
out("# %s port=%s reps=%d" % (time.strftime("%Y-%m-%d %H:%M:%S"), port, reps))
fail = 0
n = 0


def alive(tag):
    global fail, n
    n += 1
    t = b"alive-%d" % n
    s.write(b"echo " + t + b"\r")
    b, ok = until(t + rb"\r\n" + rb"(.|\r|\n)*" + PROMPT, 5)
    if not ok or b"Traceback" in b:
        fail += 1; out("  FAIL %s: shell %r" % (tag, b[-200:])); return False
    return True


cases = {"vi-normal": 0, "vi-insert": 0, "edit-copy": 0, "vi-startup": 0, "edit-startup": 0}
counts = {"key": 0, "stopped": 0}
# the editors draw on the display only: while one runs, the serial port is silent, and the
# shell prompt on it means the editor has ended


def leave(ed):
    s.write(b"\x1b:q!\r" if ed == b"vi" else b"\x11")
    b, ok = until(PROMPT, 3)
    if not ok and ed == b"edit":  # "Save changes?": no
        s.write(b"n"); b2, ok = until(PROMPT, 3); b += b2
    return b, ok


for i in range(reps):
    for case in cases:
        drain(0.1)
        ed = b"vi" if case.startswith("vi") else b"edit"
        s.write(ed + b" /shell.py\r")
        until(re.escape(ed) + rb" /shell.py\r\n", 3)
        if case.endswith("startup"):
            # Ctrl-C at a random moment of the start: before kbd_intr(-1) it stops the
            # command, after it it is a key; either way the shell must stay alive
            time.sleep(rnd.uniform(0, 0.6))
            s.write(b"\x03")
            b, stopped = until(PROMPT, 1.5)
            how = "stopped" if stopped else "key"
            counts[how] += 1
            ok = True
            if not stopped:
                b2, ok = leave(ed); b += b2
            if b"Traceback" in b or not ok:
                fail += 1; out("  FAIL %s %d (%s): %r" % (case, i, how, b[-300:]))
        else:
            time.sleep(rnd.uniform(1.0, 1.8))  # the editor is up
            if case == "vi-normal":
                s.write(b"\x03"); time.sleep(rnd.uniform(0, 0.3)); s.write(b"j\x03")
            elif case == "vi-insert":
                s.write(b"iabc"); time.sleep(rnd.uniform(0, 0.3)); s.write(b"\x03")
                time.sleep(0.2); s.write(b"u")
            else:
                s.write(b"\x03"); time.sleep(rnd.uniform(0, 0.3)); s.write(b"\x03")
            b, out_ = until(PROMPT, 0.8)
            if out_ or b"Traceback" in b:
                fail += 1; out("  FAIL %s %d: Ctrl-C left the editor %r" % (case, i, b[-300:]))
                continue
            b, ok = leave(ed)
            if not ok or b"Traceback" in b:
                fail += 1; out("  FAIL %s %d: no clean exit %r" % (case, i, b[-300:]))
        if case.endswith("startup"):
            time.sleep(3.2)  # LEAVE_MS: a Ctrl-C at the prompt would count as the first
        if not alive(case):
            break
        cases[case] += 1
out("# startup Ctrl-C: a key in the editor %(key)d, stopped the command %(stopped)d" % counts)
out("# done per case: %r" % cases)
out("RESULT: " + ("OK" if fail == 0 else "FAILED (%d)" % fail))
