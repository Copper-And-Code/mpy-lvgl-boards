# Speaker on the ESP32-4848S040: audio.py with LVGL animating.
#   scripts/uart_run.py tests/hil/esp32/t07_audio.py --dtr 0 --boot-wait 5 --timeout 40
# Not on a board with the relays fitted: see audio.py.
# Listen, in order: a short beep; 1 s low (mono file); 1 s an octave higher (stereo file);
# 1 s low and quieter, cut after 0.5 s; three short beeps.
import math
import os
import struct
import time

import lvgl as lv

import audio
import display_driver

RATE = 22050
W, H = display_driver.WIDTH, display_driver.HEIGHT
disp = display_driver.disp


def wav(path, channels, period, seconds):
    frame = bytearray()
    for i in range(period):
        v = int(12000 * math.sin(2 * math.pi * i / period))
        frame += struct.pack("<h", v) * channels
    size = len(frame) * (RATE * seconds // period)
    with open(path, "wb") as f:
        f.write(b"RIFF" + struct.pack("<I", 36 + size) + b"WAVEfmt ")
        f.write(struct.pack("<IHHIIHH", 16, 1, channels, RATE, RATE * 2 * channels, 2 * channels, 16))
        f.write(b"LIST" + struct.pack("<I", 4) + b"INFO")  # a chunk to skip
        f.write(b"data" + struct.pack("<I", size))
        for _ in range(size // len(frame)):
            f.write(frame)


scr = lv.obj()
bar = lv.obj(scr)
bar.set_size(16, H)
a = lv.anim_t()
a.init()
a.set_var(bar)
a.set_values(0, W - 16)
a.set_duration(3000)
a.set_repeat_count(lv.ANIM_REPEAT_INFINITE)
a.set_custom_exec_cb(lambda anim, v: bar.set_x(v))
a.start()
stats = [0, 0, 0]


def on_refr(e):
    t = time.ticks_ms()
    if stats[1]:
        stats[2] = max(stats[2], time.ticks_diff(t, stats[1]))
    stats[1] = t
    stats[0] += 1


disp.add_event_cb(on_refr, lv.EVENT.REFR_READY, None)
lv.screen_load(scr)

wav("/t07m.wav", 1, 50, 1)
wav("/t07s.wav", 2, 25, 1)
time.sleep_ms(300)
errors = 0


def run(name, start, seconds=2, cut=None):
    global errors
    stats[2] = 0
    r0 = stats[0]
    t = time.ticks_ms()
    start()
    back = time.ticks_diff(time.ticks_ms(), t)
    while audio.playing():
        if cut and time.ticks_diff(time.ticks_ms(), t) > cut:
            audio.stop()
        if time.ticks_diff(time.ticks_ms(), t) > seconds * 1000:
            print(name, "did not end")
            errors += 1
            audio.stop()
        time.sleep_ms(5)
    dt = time.ticks_diff(time.ticks_ms(), t)
    print("%-6s returned in %d ms, lasted %d ms, LVGL %.1f/s, longest gap %d ms" % (name, back, dt, (stats[0] - r0) * 1000 / dt, stats[2]))
    if back > 50:
        errors += 1


run("beep", audio.beep)
time.sleep_ms(300)
run("mono", lambda: audio.play("/t07m.wav"))
time.sleep_ms(300)
run("stereo", lambda: audio.play("/t07s.wav"))
time.sleep_ms(300)
run("cut", lambda: audio.play("/t07m.wav", atten=2), cut=500)
time.sleep_ms(300)
for i in range(3):
    run("beep", lambda: audio.beep(1000, 60))
    time.sleep_ms(120)

try:
    audio.play("/t07.nope")
except OSError:
    pass
else:
    errors += 1
with open("/t07b.wav", "wb") as f:
    f.write(b"not a wav file at all")
try:
    audio.play("/t07b.wav")
except ValueError as e:
    print("bad file:", e)
else:
    errors += 1
for p in ("/t07m.wav", "/t07s.wav", "/t07b.wav"):
    os.remove(p)
print("RESULT:", "FAILED" if errors else "ok")
