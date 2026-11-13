#!/usr/bin/env python3
"""Ctrl-C in the shell (examples/shell) on a board that autostarts it from main.py, through
its serial port: read only, the shell commands used write nothing.

    tests/hil/shell_ctrlc_host.py --port /dev/ttyUSB0 [--dtr 0 --boot-wait 6] [--log x.txt]

Cases, each repeated:
  long     Ctrl-C at a random moment of `sleep 2`: "^C" and the prompt back, soon
  output   Ctrl-C during `cat FILE` (a long output to the display): the same
  line     Ctrl-C while typing a line (the editor gets it as a key): a new prompt
  edge     Ctrl-C around the end of `sleep 0.3`, when the shell goes back to read_line()
           with Ctrl-C as a key (micropython.kbd_intr(-1)): the shell must stay alive
After every case the shell must answer `echo alive-<n>`.
"""
import argparse
import random
import re
import time

import serial

# the shell's coloured prompt, mpy@<host>:<path>$ (shell.prompt()), not a "$ " in a file
PROMPT = rb"mpy@\w+\x1b\[0m:\x1b\[1;34m[^\x1b]*\x1b\[0m\$ "


def read_for(s, seconds):
    buf = b""
    end = time.time() + seconds
    while time.time() < end:
        buf += s.read(4096)
    return buf


def until(s, pattern, timeout):
    buf = b""
    end = time.time() + timeout
    while time.time() < end:
        buf += s.read(4096)
        if re.search(pattern, buf):
            return buf, True
    return buf, False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", required=True)
    ap.add_argument("--dtr", type=int, default=1)
    ap.add_argument("--boot-wait", type=float, default=6)
    ap.add_argument("--file", default="/shell.py", help="a long file for `cat`")
    ap.add_argument("--repeat", type=int, default=15)
    ap.add_argument("--log")
    ap.add_argument("--start", help="REPL line that starts the shell, when main.py does not")
    ap.add_argument("--cases", default="long,output,line,edge", help="which cases, comma separated")
    a = ap.parse_args()
    log = open(a.log, "w") if a.log else None
    rnd = random.Random(1)

    def out(line):
        print(line)
        if log:
            log.write(line + "\n")
            log.flush()

    s = serial.Serial()
    s.port, s.baudrate, s.timeout = a.port, 115200, 0.05
    s.dtr, s.rts = bool(a.dtr), False
    s.open()
    boot = read_for(s, a.boot_wait)
    if a.start:
        s.write(b"\r\x03\x03")
        boot += read_for(s, 0.5)
        s.write(a.start.encode() + b"\r")
        boot += read_for(s, 4)
    s.write(b"\r")
    head, ok = until(s, PROMPT, 5)
    out("# %s port=%s file=%s repeat=%d start=%r" % (time.strftime("%Y-%m-%d %H:%M:%S"), a.port, a.file, a.repeat, a.start))
    out("# boot: " + (boot + head).decode(errors="replace").replace("\r\n", " | ")[-300:])
    if not ok:
        out("RESULT: FAILED (no shell prompt)")
        return 1
    s.write(b"echo start\r")  # a history entry: a single Ctrl-C at an empty line then stays
    until(s, rb"start\r\n(.|\n|\r)*" + PROMPT, 5)

    failures = 0
    n = 0

    def alive(case):
        nonlocal failures, n
        n += 1
        tag = b"alive-%d" % n
        s.write(b"echo " + tag + b"\r")
        buf, ok = until(s, tag + rb"\r\n", 5)
        if not ok or b"Traceback" in buf:
            failures += 1
            out("  FAIL %s: shell did not answer (%r)" % (case, buf[-200:]))
            return False
        until(s, PROMPT, 2)
        return True

    stats = {}
    for case, cmd, wait in (
        ("long", b"sleep 2", (0.2, 1.6)),
        ("output", b"cat " + a.file.encode(), (0.1, 0.8)),
        ("line", b"abc", (0.1, 0.3)),
        ("edge", b"sleep 0.3", (0.25, 0.4)),
    ):
        if case not in a.cases.split(","):
            continue
        lat = []
        tb = 0
        for i in range(a.repeat):
            read_for(s, 0.1)
            if case == "line":
                s.write(cmd)
                until(s, re.escape(cmd) + rb"$", 2)  # the line editor has drawn it
            else:
                s.write(cmd + b"\r")
                until(s, re.escape(cmd) + rb"\r\n", 3)  # the line is entered: the command runs
            time.sleep(rnd.uniform(*wait))
            s.read(65536)  # from here on, only what follows the Ctrl-C
            t0 = time.time()
            s.write(b"\x03")
            buf, ok = until(s, PROMPT, 5)
            lat.append(time.time() - t0)
            if b"Traceback" in buf:
                tb += 1
                k = buf.index(b"Traceback")
                out("  %s %d traceback: %r" % (case, i, buf[max(0, k - 200):k + 800]))
            if not ok:
                failures += 1
                out("  FAIL %s %d: no prompt after Ctrl-C (%r)" % (case, i, buf[-200:]))
            elif case in ("long", "output") and b"^C" not in buf:
                failures += 1
                out("  FAIL %s %d: prompt without ^C (%r)" % (case, i, buf[-200:]))
            if case == "edge":
                time.sleep(rnd.uniform(0, 0.05))
            if not alive(case):
                break
            time.sleep(3.2 if case in ("line", "edge") else 0.2)  # LEAVE_MS: no "second Ctrl-C"
        stats[case] = (len(lat), max(lat) if lat else 0, sum(lat) / len(lat) if lat else 0, tb)
        out("%-7s %2d Ctrl-C, prompt back in %.2f s on average, %.2f s at most, tracebacks %d" % (
            case, stats[case][0], stats[case][2], stats[case][1], tb))

    s.close()
    ok = failures == 0 and all(v[3] == 0 for v in stats.values())
    out("RESULT: " + ("OK" if ok else "FAILED (%d failures)" % failures))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
