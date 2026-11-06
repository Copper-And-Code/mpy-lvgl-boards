# WiFi on the ESP32-4848S040 with LVGL animating: does the network cost frames?
#   scripts/uart_run.py wifi_cfg.py tests/hil/esp32/t06_wifi.py --dtr 0 --boot-wait 5 \
#       --timeout 180 | tests/hil/tcp_source.py
# The board listens and the PC connects when it prints LISTEN: a firewall on the PC lets
# that through. The PC must reach the board's network.
# wifi_cfg.py stays out of the repo and off the board's filesystem; the raw REPL keeps its
# globals for the next script:
#   WIFI_SSID = "..."
#   WIFI_PASS = "..."
#
# Each phase runs the same animation and reports LVGL refreshes/s, panel fps and the longest
# gap between two refreshes: idle, connected, TCP downloads, then a reconnect and a DNS + HTTP
# request to the internet. Watch the panel: the bar must stay straight.
import gc
import socket
import time

import esp32
import esp_rgb
import lvgl as lv
import network

import display_driver

PORT = 5201
SECONDS = 10
W, H = display_driver.WIDTH, display_driver.HEIGHT
disp = display_driver.disp

scr = lv.obj()
scr.set_style_bg_color(lv.color_hex(0x101820), 0)
bar = lv.obj(scr)
bar.set_size(16, H)
bar.set_style_bg_color(lv.color_hex(0xFFFFFF), 0)
bar.set_style_border_width(0, 0)
bar.set_style_radius(0, 0)
a = lv.anim_t()
a.init()
a.set_var(bar)
a.set_values(0, W - 16)
a.set_duration(3000)
a.set_repeat_count(lv.ANIM_REPEAT_INFINITE)
a.set_custom_exec_cb(lambda anim, v: bar.set_x(v))
a.start()
s = lv.spinner(scr)
s.set_size(100, 100)
s.align(lv.ALIGN.TOP_RIGHT, -20, 20)
stats = [0, 0, 0]  # refreshes, tick of the last one, longest gap


def on_refr(e):
    t = time.ticks_ms()
    if stats[1]:
        stats[2] = max(stats[2], time.ticks_diff(t, stats[1]))
    stats[1] = t
    stats[0] += 1


disp.add_event_cb(on_refr, lv.EVENT.REFR_READY, None)
lv.screen_load(scr)
time.sleep_ms(500)


def heap():
    # (total, free, largest block, minimum free) of each block that is not the PSRAM heap
    return max(h[2] for h in esp32.idf_heap_info(esp32.HEAP_DATA) if h[0] < 1000000)


def phase(name, work=None):
    gc.collect()
    time.sleep_ms(200)
    stats[2] = 0
    r0, f0, t0 = stats[0], esp_rgb.frame_count(), time.ticks_ms()
    extra = work() if work else time.sleep_ms(SECONDS * 1000)
    dt = time.ticks_diff(time.ticks_ms(), t0)
    print(
        "%-10s LVGL %.1f/s, panel %.2f fps, longest gap %d ms, internal block %d KB%s"
        % (
            name,
            (stats[0] - r0) * 1000 / dt,
            (esp_rgb.frame_count() - f0) * 1000 / dt,
            stats[2],
            heap() // 1024,
            extra or "",
        )
    )


def connect(sta):
    t = time.ticks_ms()
    sta.connect(WIFI_SSID, WIFI_PASS)
    while not sta.isconnected():
        if time.ticks_diff(time.ticks_ms(), t) > 20000:
            print("no connection, status", sta.status())
            print("RESULT: FAILED")
            raise SystemExit
        time.sleep_ms(50)
    return time.ticks_diff(time.ticks_ms(), t)


def download(blocking):
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", PORT))
    srv.listen(1)
    srv.settimeout(20)
    print("LISTEN", sta.ifconfig()[0], PORT)
    c = srv.accept()[0]
    c.settimeout(5 if blocking else 0)
    buf = bytearray(4096)
    n = 0
    end = ""
    t = time.ticks_ms()
    try:
        while time.ticks_diff(time.ticks_ms(), t) < SECONDS * 1000:
            r = c.readinto(buf)
            if r is None:
                time.sleep_ms(1)
            else:
                n += r
    except OSError as e:
        end = ", stopped: %s" % e
    dt = time.ticks_diff(time.ticks_ms(), t)
    c.close()
    srv.close()
    return ", %.2f Mbit/s (%d KB)%s" % (n * 8 / dt / 1000, n // 1024, end)


phase("no wifi")

sta = network.WLAN(network.STA_IF)
sta.active(True)
print("connect ms", connect(sta), "rssi", sta.status("rssi"), "channel", sta.config("channel"))
phase("connected")
for i in range(3):
    phase("blocking", lambda: download(True))
    phase("non-block", lambda: download(False))
phase("connected")

sta.disconnect()
while sta.isconnected():
    time.sleep_ms(50)
print("reconnect ms", connect(sta))

t = time.ticks_ms()
addr = socket.getaddrinfo("example.com", 80)[0][-1]
c = socket.socket()
c.settimeout(10)
c.connect(addr)
c.write(b"GET / HTTP/1.0\r\nHost: example.com\r\n\r\n")
line = c.readline()
c.close()
print("http ms", time.ticks_diff(time.ticks_ms(), t), line)

sta.active(False)
phase("wifi off")
gc.collect()
print("mem_free", gc.mem_free())
print("RESULT: ok" if b" 200 " in line else "RESULT: FAILED")
