#!/usr/bin/env python3
"""Run scripts on a MicroPython board through its UART REPL (raw REPL), with the
adapter's DTR/RTS held at "run" (BOOT0 low, NRST released).

    scripts/uart_run.py a.py [b.py ...] [--port /dev/ttyUSB0] [--timeout 120]
                        [--soft-reset]

STM32H7_CORE V1.3 on the bench: a CH340 adapter on UART1 with DTR -> BOOT0 and
RTS -> NRST (DTR=1 BOOT0 low, RTS=1 NRST low; see scripts/stm32_uart_flash.py).
Linux raises DTR and RTS for a moment whenever the port is opened, before any
setting applies, so **every open hard-resets the board**: this script waits for the
boot to finish and then runs all the scripts in the same session. Tests that need
state to survive a soft reset must therefore be given as several scripts in one
call (as with `mpremote run a.py run a.py`), never as separate calls.

Over a board's own USB port (STM32H7_CORE V1.0 on /dev/ttyACM0, ESP32 boards with
--dtr 0) opening the port resets nothing: the first script runs on whatever the last
call left, a display driver already imported, callbacks still registered.

--soft-reset soft-resets the board (Ctrl-D in the raw REPL, as `mpremote run`
does) before every script, the first one too, so each starts from a clean heap
whatever port it came through.
Exit status: 0 if every script ran without an exception and printed no
"RESULT: FAILED", else 1 (2 on a timeout).
"""
import argparse
import sys
import time

import serial

RAW_PROMPT = b"raw REPL; CTRL-B to exit\r\n>"


def open_port(port, baud, dtr=True):
    s = serial.Serial()
    s.port, s.baudrate, s.timeout = port, baud, 0.1
    s.dtr, s.rts = dtr, False  # BOOT0 low, NRST released (after the open glitch)
    s.open()
    return s


def read_until(s, marker, timeout):
    buf = b""
    end = time.time() + timeout
    while time.time() < end:
        buf += s.read(4096)
        if marker in buf:
            return buf
    raise TimeoutError("waiting for %r, got %r" % (marker, buf[-200:]))


def enter_raw(s, boot_wait):
    time.sleep(boot_wait)  # the open reset the board: let boot.py/main.py start
    s.write(b"\r\x03\x03")
    time.sleep(0.2)
    s.reset_input_buffer()
    s.write(b"\r\x01")
    read_until(s, RAW_PROMPT, 5)


def soft_reset(s):
    s.write(b"\x04")
    # One wait: over USB "soft reboot" and the prompt can arrive in the same read.
    read_until(s, RAW_PROMPT, 20)


def run(s, path, timeout):
    """Run one script in the raw REPL; the board stays at the raw prompt."""
    code = open(path, "rb").read()
    for i in range(0, len(code), 256):
        s.write(code[i : i + 256])
        time.sleep(0.01)
    s.write(b"\x04")
    out = read_until(s, b"OK", 5).split(b"OK", 1)[1]
    sys.stdout.write(out.replace(b"\x04", b"").decode(errors="replace"))
    end = time.time() + timeout
    while out.count(b"\x04") < 2 and time.time() < end:
        chunk = s.read(4096)
        if chunk:
            sys.stdout.write(chunk.replace(b"\x04", b"").decode(errors="replace"))
            sys.stdout.flush()
            out += chunk
    if out.count(b"\x04") < 2:
        print("\n[timeout]")
        return 2
    err = out.split(b"\x04")[1]
    return 1 if err.strip() or b"RESULT: FAILED" in out else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scripts", nargs="+")
    ap.add_argument("--port", default="/dev/ttyUSB0")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--timeout", type=float, default=120, help="per script")
    ap.add_argument("--boot-wait", type=float, default=3.0)
    ap.add_argument("--soft-reset", action="store_true")
    # ESP32 boards with the usual auto-reset circuit: DTR high would hold IO0 low.
    ap.add_argument("--dtr", type=int, default=1, help="level of DTR, 0 on ESP32 boards")
    a = ap.parse_args()

    s = open_port(a.port, a.baud, bool(a.dtr))
    enter_raw(s, a.boot_wait)
    worst = 0
    for i, path in enumerate(a.scripts):
        if a.soft_reset:
            soft_reset(s)
        if len(a.scripts) > 1:
            print("\n== %s (%d/%d)" % (path, i + 1, len(a.scripts)))
        rc = run(s, path, a.timeout)
        worst = max(worst, rc)
        if rc == 2:
            break
    s.write(b"\x02")  # back to the friendly REPL
    print()
    return worst


if __name__ == "__main__":
    sys.exit(main())
