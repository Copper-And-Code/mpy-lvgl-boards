#!/usr/bin/env python3
"""Host side of tests/hil/t10_ctrlc_probe.py: where does a Ctrl-C land while
display_driver serves LVGL? Read only: the board script runs from the raw REPL,
nothing is written to the board's filesystem.

    tests/hil/ctrlc_probe_host.py --port /dev/ttyACM0 --mode sleep|stdin [--trials 60]
                                  [--dtr 0 --boot-wait 5] [--log docs/log/x.txt]

Each trial waits a random time, sends one Ctrl-C and reads what comes back for
--window seconds:
  main       "MAIN <n>": the main program caught KeyboardInterrupt
  driver     "display_driver: stopped by Ctrl-C": the driver's _interrupted()
  scheduler  a KeyboardInterrupt traceback without MAIN: dropped by the scheduler
  lost       nothing at all
The service: the "S <frames> <running>" lines before and after the Ctrl-C (sleep
mode prints one every 100 ms, stdin mode answers an "s").
"""
import argparse
import os
import random
import re
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))
from uart_run import enter_raw, open_port, read_until, soft_reset  # noqa: E402

S_RE = re.compile(rb"S (\d+) ([01])")
P_RE = re.compile(rb"S \d+ [01] (\d+)")


def read_for(s, seconds):
    buf = b""
    end = time.time() + seconds
    while time.time() < end:
        buf += s.read(4096)
    return buf


def statuses(buf):
    return [(int(f), int(r)) for f, r in S_RE.findall(buf)]


def classify(buf):
    kinds = []
    mains = buf.count(b"MAIN ")
    if mains:
        kinds.append("main")
    if mains > 1:
        kinds.append("double")
    if b"display_driver: stopped" in buf:
        kinds.append("driver")
    # every traceback that ends in KeyboardInterrupt: printed and dropped by the scheduler
    for tb in buf.split(b"Traceback")[1:]:
        if b"KeyboardInterrupt" in tb:
            if b"_busy_cb" in tb:
                kinds.append("app-cb")  # the application's callback: not covered (docs/display-driver.md)
            elif b"lv_read_cb" in tb:
                kinds.append("lvgl-cb")  # the touch read callback
            else:
                kinds.append("scheduler")
    return kinds or ["lost"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", required=True)
    ap.add_argument("--mode", choices=("sleep", "stdin", "cb"), required=True)
    ap.add_argument("--candidate", choices=("", "base", "A", "AB", "A2", "AB2"), default="", help="a candidate _task, in RAM")
    ap.add_argument("--trials", type=int, default=60)
    ap.add_argument("--window", type=float, default=0.8)
    ap.add_argument("--dtr", type=int, default=1)
    ap.add_argument("--boot-wait", type=float, default=0.5)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--log")
    ap.add_argument("--expect", choices=("contract",), help="exit 1 unless every Ctrl-C reached the "
                    "program once and the service never stopped (docs/display-driver.md)")
    ap.add_argument("--start-delay", type=float, default=0, help="seconds before the first trial (time to start touching)")
    a = ap.parse_args()
    seed = a.seed if a.seed is not None else int(time.time())
    rnd = random.Random(seed)
    log = open(a.log, "w") if a.log else None

    def out(line):
        print(line)
        if log:
            log.write(line + "\n")
            log.flush()

    code = open(os.path.join(os.path.dirname(__file__), "t10_ctrlc_probe.py"), "rb").read()
    seconds = int(a.trials * (1.2 + a.window + 0.3)) + 20
    code = b'MODE = "%s"\nSECONDS = %d\nCANDIDATE = "%s"\n' % (
        a.mode.encode(), seconds, a.candidate.encode()) + code

    s = open_port(a.port, 115200, bool(a.dtr))
    enter_raw(s, a.boot_wait)
    soft_reset(s)
    for i in range(0, len(code), 256):
        s.write(code[i : i + 256])
        time.sleep(0.01)
    s.write(b"\x04")
    head = read_until(s, b"OK", 5).split(b"OK", 1)[1]
    if b"READY" not in head:
        head += read_until(s, b"READY", 40)
    head += read_for(s, 2.0)  # settle; first status lines
    for line in head.splitlines():
        if line.startswith((b"SPECIAL", b"FPS")):
            out("# " + line.decode(errors="replace").strip())
    out("# %s mode=%s candidate=%s trials=%d window=%.2fs seed=%d port=%s" % (
        time.strftime("%Y-%m-%d %H:%M:%S"), a.mode, a.candidate, a.trials, a.window, seed, a.port))
    out("# board: " + head.split(b"READY", 1)[1].split(b"\r\n", 1)[0].decode(errors="replace").strip())

    if a.start_delay:
        print("touch the screen now; trials start in %.0f s" % a.start_delay)
        read_for(s, a.start_delay)
    last_presses = None
    counts = {"main": 0, "double": 0, "driver": 0, "scheduler": 0, "lvgl-cb": 0, "app-cb": 0, "lost": 0}
    continued = stopped = unknown = paused = 0
    pre = b""
    for k in range(1, a.trials + 1):
        pre = read_for(s, rnd.uniform(0.2, 1.2))
        if a.mode == "stdin":
            s.write(b"s")
            pre += read_for(s, 0.2)
        before = statuses(pre)
        late = classify(pre)
        s.write(b"\x03")
        if a.mode == "stdin":
            post = read_for(s, a.window / 2)
            s.write(b"s")
            post += read_for(s, a.window / 4)
            s.write(b"s")
            post += read_for(s, a.window / 4)
        else:
            post = read_for(s, a.window)
        kinds = classify(post)
        for kind in set(kinds):
            counts[kind] += 1
        after = statuses(post)
        pp = P_RE.findall(post)
        if pp:
            last_presses = int(pp[-1])
        if after and after[-1][1] == 0 or (any(r == 0 for _, r in after) and after[-1][0] <= after[0][0]):
            service = "stopped"
            stopped += 1
        elif any(r == 0 for _, r in after):
            service = "paused"  # stopped for a moment, then served again
            paused += 1
        elif len(after) >= 2 and after[-1][0] > after[0][0]:
            service = "continued"
            continued += 1
        else:
            service = "?"
            unknown += 1
        fps = ""
        if len(after) >= 2:
            fps = " frames+%d" % (after[-1][0] - after[0][0])
        out("%3d %-16s service=%-9s before=%s after=%s%s%s" % (
            k, "+".join(kinds), service, before[-1:] , after, fps,
            "  [late in pre-window: %s]" % "+".join(late) if late != ["lost"] else ""))
        if b"Traceback" in post or b"Error" in post:
            out("    text: " + post.decode(errors="replace").strip().replace("\r\n", " | ")[:300])

    if a.mode == "stdin":
        s.write(b"q")  # noqa
        tail = read_for(s, 1.0)
    else:
        tail = read_until(s, b"END", seconds + 10)
    tail += read_for(s, 0.5)
    n = a.trials
    out("# status reports with a finger on the screen (every 100 ms), during the trials: %s" % last_presses)
    out("# summary mode=%s trials=%d" % (a.mode, n))
    for kind in ("main", "double", "driver", "scheduler", "lvgl-cb", "app-cb", "lost"):
        out("#   %-9s %3d  %5.1f%%" % (kind, counts[kind], 100.0 * counts[kind] / n))
    out("#   service continued %d, paused and resumed %d, stopped %d, unknown %d" % (continued, paused, stopped, unknown))
    out("# end: " + tail.decode(errors="replace").strip().replace("\r\n", " | ")[-200:])
    s.write(b"\x02")
    s.close()
    if a.expect == "contract":
        # A Ctrl-C in the application's own LVGL callback (cb mode) is the case the
        # contract leaves out: reported, not a failure.
        ok = counts["main"] + counts["app-cb"] == n and stopped == unknown == 0 and all(
            counts[k] == 0 for k in ("double", "driver", "scheduler", "lvgl-cb", "lost"))
        if counts["app-cb"]:
            out("# %d Ctrl-C in the application's callback (not covered by the contract)" % counts["app-cb"])
        out("RESULT: " + ("OK" if ok else "FAILED"))
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
