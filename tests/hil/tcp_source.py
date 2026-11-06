#!/usr/bin/env python3
"""Far end of a board's network test: copies the test's output from stdin to stdout, and on
a line "LISTEN <address> <port>" connects there and sends data as fast as the board reads.

    scripts/uart_run.py ... tests/hil/esp32/t06_wifi.py ... | tests/hil/tcp_source.py
"""
import socket
import sys
import threading

BLOCK = bytes(range(256)) * 64


def send(address, port):
    sent = 0
    try:
        with socket.create_connection((address, port), timeout=10) as s:
            while True:
                s.sendall(BLOCK)
                sent += len(BLOCK)
    except OSError as e:
        print("tcp_source: %d KB sent, %s" % (sent // 1024, e), flush=True)


for line in sys.stdin:
    sys.stdout.write(line)
    sys.stdout.flush()
    w = line.split()
    if len(w) == 3 and w[0] == "LISTEN":
        threading.Thread(target=send, args=(w[1], int(w[2])), daemon=True).start()
