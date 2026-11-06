# Weather station for the ESP32-4848S040: current weather, wind and 5 days of forecast.
#
# Run it from Thonny, or save it on the board as main.py to start at power-on. The first time
# it asks for the WiFi network, the place and the style; the gear button goes back there.
# Tap the temperature to update now. Ctrl-C stops it.
#
# Data: Open-Meteo (https://open-meteo.com), no account or key, free for non-commercial use.
# Requests are plain HTTP.
#
# The settings go to /sd/weather.json, WiFi password included, in clear. Without a card they
# go to /weather.json in the internal flash: the header shows which, as does the console.
#
# The brightness needs firmware v0.1.4 or later; before it the display stays at full brightness.
#
# At night the display dims by itself, between two times set in the last step. The board has no
# clock: it takes the time from the server's answers, so it dims only after the first update.
#
# The board only: it needs the SD pins and a 480x480 layout. The network runs in the main
# loop, not in LVGL callbacks, and reads without blocking, so the screen stays alive.
import json
import math
import os
import socket
import time

import lvgl as lv
import machine
import network

import display_driver

W, H = display_driver.WIDTH, display_driver.HEIGHT
FILES = ("/sd/weather.json", "/weather.json")
SD_PINS = {"slot": 2, "sck": 48, "miso": 41, "mosi": 47, "cs": 42, "freq": 10_000_000}
RETRY_S = 60  # after a failed update
MIN_BRIGHT = 35  # percent: below this, the panel can no longer be read

THEMES = (  # name, background, card, text, dimmed text, accent
    ("Notte", 0x0E1621, 0x1B2838, 0xF2F5F9, 0x93A4B8, 0x4FA3FF),
    ("Giorno", 0xDCEBF7, 0xFFFFFF, 0x13263A, 0x5B6E82, 0x1F7AE0),
    ("Oceano", 0x06343F, 0x0C4A58, 0xE8FBFF, 0x8CC3CF, 0x3FD6C6),
    ("Tramonto", 0x2B1633, 0x452049, 0xFFF0E6, 0xC7A1B5, 0xFF8A5C),
)
UNITS = (("C", "celsius"), ("F", "fahrenheit"))
WINDS = (("km/h", "kmh"), ("m/s", "ms"), ("nodi", "kn"))
REFRESH = (15, 30, 60)  # minutes
LANGS = ("it", "en")

SUN, MOON = 0xFFC83D, 0xE8E2C0
RAIN, SNOW, BOLT = 0x4FA3FF, 0xBFE6FF, 0xFFD93D

TEXT = {
    "it": {
        "days": ("Lun", "Mar", "Mer", "Gio", "Ven", "Sab", "Dom"),
        "dirs": ("N", "NE", "E", "SE", "S", "SO", "O", "NO"),
        "wifi": "Rete WiFi",
        "password": "Password",
        "scan": "Cerco le reti...",
        "rescan": "Cerca",
        "none": "Nessuna rete: tocca Cerca",
        "pick": "Scegli una rete",
        "next": "Avanti",
        "connecting": "Connessione...",
        "nowifi": "Connessione non riuscita",
        "place": "Luogo",
        "search": "Cerca",
        "searching": "Cerco...",
        "notfound": "Non trovato",
        "style": "Stile",
        "theme": "Tema",
        "temp": "Temperatura",
        "wind": "Vento",
        "every": "Aggiorna ogni",
        "lang": "Lingua",
        "bright": "Luminosita",
        "night": "Notte",
        "dim": "Riduci di notte",
        "from": "Dalle",
        "to": "Alle",
        "save": "Salva",
        "cancel": "Annulla",
        "loading": "Aggiorno...",
        "failed": "Aggiornamento non riuscito",
        "feels": "Percepita",
        "gust": "Raffiche",
        "humidity": "Umidita",
        "rain": "Pioggia",
        "updated": "Agg.",
        "codes": ("Sereno", "Poco nuvoloso", "Parz. nuvoloso", "Coperto", "Nebbia", "Pioggerella",
                  "Pioggia", "Neve", "Rovesci", "Rovesci di neve", "Temporale"),
    },
    "en": {
        "days": ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"),
        "dirs": ("N", "NE", "E", "SE", "S", "SW", "W", "NW"),
        "wifi": "WiFi network",
        "password": "Password",
        "scan": "Looking for networks...",
        "rescan": "Scan",
        "none": "No networks: tap Scan",
        "pick": "Choose a network",
        "next": "Next",
        "connecting": "Connecting...",
        "nowifi": "Could not connect",
        "place": "Place",
        "search": "Search",
        "searching": "Searching...",
        "notfound": "Not found",
        "style": "Style",
        "theme": "Theme",
        "temp": "Temperature",
        "wind": "Wind",
        "every": "Update every",
        "lang": "Language",
        "bright": "Brightness",
        "night": "Night",
        "dim": "Dim at night",
        "from": "From",
        "to": "To",
        "save": "Save",
        "cancel": "Cancel",
        "loading": "Updating...",
        "failed": "Update failed",
        "feels": "Feels like",
        "gust": "Gusts",
        "humidity": "Humidity",
        "rain": "Rain",
        "updated": "Upd.",
        "codes": ("Clear", "Mostly clear", "Partly cloudy", "Overcast", "Fog", "Drizzle",
                  "Rain", "Snow", "Showers", "Snow showers", "Thunderstorm"),
    },
}

# The fonts have no accented letters.
PLAIN = {
    "à": "a", "á": "a", "â": "a", "ä": "a", "ã": "a", "å": "a", "è": "e", "é": "e", "ê": "e",
    "ë": "e", "ì": "i", "í": "i", "î": "i", "ï": "i", "ò": "o", "ó": "o", "ô": "o", "ö": "o",
    "õ": "o", "ù": "u", "ú": "u", "û": "u", "ü": "u", "ç": "c", "ñ": "n", "ß": "ss", "À": "A",
    "È": "E", "É": "E", "Ì": "I", "Ò": "O", "Ù": "U", "Ü": "U", "Ö": "O", "Ä": "A",
}  # fmt: skip

cfg = {
    "ssid": "",
    "password": "",
    "place": "",
    "lat": None,
    "lon": None,
    "theme": 0,
    "unit": 0,
    "wind": 0,
    "refresh": 1,
    "lang": 0,
    "backlight": 70,
    "night": True,
    "night_backlight": 40,
    "night_from": 23 * 60,  # minutes after midnight, local time
    "night_to": 5 * 60 + 30,
}
cfg_file = None  # where the settings were loaded from or saved to
sd_ok = False
sta = network.WLAN(network.STA_IF)
weather = None  # the last forecast
on_main = False
next_update = 0
job = None  # what the main loop must do next
server_date = None  # the Date header of the last answer
clock_ok = False  # the RTC holds the local time
ui = {}  # widgets of the current screen


def t(key):
    return TEXT[LANGS[cfg["lang"]]][key]


def plain(s):
    return "".join(c if ord(c) < 128 else PLAIN.get(c, "") for c in s)


def colors():
    return THEMES[cfg["theme"]][1:]


# --- settings ------------------------------------------------------------------------


def mount_sd():
    global sd_ok
    try:
        if "sd" not in os.listdir("/"):
            os.mount(machine.SDCard(**SD_PINS), "/sd")
        sd_ok = True
    except Exception as e:
        print("SD not available:", repr(e))
        sd_ok = False


def load_settings():
    global cfg_file
    for path in FILES:
        if path.startswith("/sd") and not sd_ok:
            continue
        try:
            with open(path) as f:
                cfg.update(json.load(f))
            cfg_file = path
            print("settings loaded from", path)
            return
        except (OSError, ValueError):
            pass


def save_settings():
    global cfg_file
    for path in FILES:
        if path.startswith("/sd") and not sd_ok:
            continue
        try:
            with open(path, "w") as f:
                json.dump(cfg, f)
            cfg_file = path
            print("settings saved to", path)
            return
        except OSError as e:
            print("cannot write", path, repr(e))


def configured():
    return cfg["ssid"] and cfg["lat"] is not None


# --- brightness ----------------------------------------------------------------------


def sync_clock(offset):
    """Set the RTC to local time: the Date header, in UTC, plus the place's offset."""
    global clock_ok
    w = server_date.split()  # Date: Fri, 06 Nov 2026 06:40:54 GMT
    month = "JanFebMarAprMayJunJulAugSepOctNovDec".index(w[3]) // 3 + 1
    h, m, s = [int(n) for n in w[5].split(":")]
    now = time.localtime(time.mktime((int(w[4]), month, int(w[2]), h, m, s, 0, 0)) + offset)
    machine.RTC().datetime((now[0], now[1], now[2], now[6], now[3], now[4], now[5], 0))
    clock_ok = True


def is_night(minutes):
    start, end = cfg["night_from"], cfg["night_to"]
    if start <= end:
        return start <= minutes < end
    return minutes >= start or minutes < end  # across midnight


def brightness():
    """The brightness for now, never below what can be read, whatever the file says."""
    night = False
    if cfg["night"] and clock_ok:
        now = time.localtime()
        night = is_night(now[3] * 60 + now[4])
    return max(MIN_BRIGHT, cfg["night_backlight" if night else "backlight"])


def apply_brightness():
    b = brightness()
    if b != display_driver.backlight():
        display_driver.backlight(b)


# --- network -------------------------------------------------------------------------


def scan():
    sta.active(True)
    best = {}
    for entry in sta.scan():
        try:
            name = entry[0].decode()
        except ValueError:
            continue
        if name and (name not in best or entry[3] > best[name]):
            best[name] = entry[3]
    return sorted(best, key=lambda n: -best[n])


def wifi_up(ssid=None, password=None, seconds=20):
    fresh = ssid is not None
    if not fresh and sta.isconnected():
        return True
    sta.active(True)
    try:
        sta.disconnect()
        sta.connect(ssid if fresh else cfg["ssid"], password if fresh else cfg["password"])
    except OSError as e:
        print("wifi:", repr(e))
        return False
    t0 = time.ticks_ms()
    while not sta.isconnected():
        if time.ticks_diff(time.ticks_ms(), t0) > seconds * 1000:
            return False
        time.sleep_ms(50)
    return True


def http_get(host, path, seconds=15):
    """The body of an HTTP response, as text. Reads without blocking: see the file header."""
    addr = socket.getaddrinfo(host, 80)[0][-1]
    s = socket.socket()
    s.settimeout(8)
    try:
        s.connect(addr)
        s.write(("GET %s HTTP/1.0\r\nHost: %s\r\nUser-Agent: mpy-lvgl-weather\r\n\r\n" % (path, host)).encode())
        s.settimeout(0)
        data = bytearray()
        buf = bytearray(1024)
        t0 = time.ticks_ms()
        while True:
            n = s.readinto(buf)
            if n == 0:
                break
            if n is None:
                if time.ticks_diff(time.ticks_ms(), t0) > seconds * 1000:
                    raise OSError("timeout")
                time.sleep_ms(2)
            else:
                data += buf[:n]
    finally:
        s.close()
    end = data.find(b"\r\n\r\n")
    if end < 0 or b" 200 " not in data[:20]:
        raise OSError("HTTP " + bytes(data[:20]).decode())
    global server_date
    for line in bytes(data[:end]).decode().split("\r\n"):
        if line.startswith("Date:"):
            server_date = line
    return bytes(data[end + 4 :]).decode()


def quote(s):
    out = ""
    for b in s.encode():
        c = chr(b)
        out += c if c.isalpha() and b < 128 or c.isdigit() else "%%%02X" % b
    return out


def geocode(name):
    body = http_get(
        "geocoding-api.open-meteo.com",
        "/v1/search?count=6&format=json&language=%s&name=%s" % (LANGS[cfg["lang"]], quote(name)),
    )
    return json.loads(body).get("results", [])


def forecast():
    path = (
        "/v1/forecast?latitude=%.4f&longitude=%.4f&timezone=auto&forecast_days=5"
        "&temperature_unit=%s&wind_speed_unit=%s"
        "&current=temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,"
        "wind_speed_10m,wind_direction_10m,wind_gusts_10m,is_day"
        "&daily=weather_code,temperature_2m_max,temperature_2m_min,"
        "precipitation_probability_max,wind_speed_10m_max"
    ) % (cfg["lat"], cfg["lon"], UNITS[cfg["unit"]][1], WINDS[cfg["wind"]][1])
    return json.loads(http_get("api.open-meteo.com", path))


# --- drawing -------------------------------------------------------------------------


def bare(parent, x, y, w, h):
    o = lv.obj(parent)
    o.remove_style_all()
    o.remove_flag(lv.obj.FLAG.CLICKABLE)
    o.remove_flag(lv.obj.FLAG.SCROLLABLE)
    o.set_pos(x, y)
    o.set_size(w, h)
    return o


def block(parent, x, y, w, h, radius, color):
    o = bare(parent, x, y, w, h)
    o.set_style_bg_opa(lv.OPA.COVER, 0)
    o.set_style_bg_color(lv.color_hex(color), 0)
    o.set_style_radius(radius, 0)
    return o


def disc(parent, cx, cy, d, color):
    return block(parent, cx - d // 2, cy - d // 2, d, d, lv.RADIUS_CIRCLE, color)


def stroke(parent, points, width, color):
    o = lv.line(parent)
    o.set_points([{"x": x, "y": y} for x, y in points], len(points))
    o.set_style_line_width(width, 0)
    o.set_style_line_color(lv.color_hex(color), 0)
    o.set_style_line_rounded(True, 0)
    return o


def label(parent, text, size, color, x=0, y=0):
    o = lv.label(parent)
    o.set_text(text)
    o.set_style_text_font(getattr(lv, "font_montserrat_%d" % size), 0)
    o.set_style_text_color(lv.color_hex(color), 0)
    o.set_pos(x, y)
    return o


def button(parent, text, x, y, w, h, callback):
    b = lv.button(parent)
    b.set_pos(x, y)
    b.set_size(w, h)
    b.set_style_bg_color(lv.color_hex(colors()[4]), 0)
    b.set_style_shadow_width(0, 0)
    n = lv.label(b)
    n.set_text(text)
    n.set_style_text_font(lv.font_montserrat_16, 0)
    n.set_style_text_color(lv.color_hex(0xFFFFFF), 0)
    n.center()
    b.add_event_cb(lambda e: callback(), lv.EVENT.CLICKED, None)
    return b


def sun(p, cx, cy, s):
    for i in range(8):
        a = i * math.pi / 4
        c, d = math.cos(a), math.sin(a)
        stroke(
            p,
            ((int(cx + c * s * 0.31), int(cy + d * s * 0.31)), (int(cx + c * s * 0.44), int(cy + d * s * 0.44))),
            max(2, s // 28),
            SUN,
        )
    disc(p, cx, cy, s * 44 // 100, SUN)


def moon(p, cx, cy, s, back):
    disc(p, cx, cy, s * 60 // 100, MOON)
    disc(p, cx + s * 16 // 100, cy - s * 10 // 100, s * 50 // 100, back)


def cloud(p, s, color, y=0):
    block(p, s * 14 // 100, y + s * 44 // 100, s * 72 // 100, s * 24 // 100, s // 8, color)
    disc(p, s * 36 // 100, y + s * 46 // 100, s * 34 // 100, color)
    disc(p, s * 60 // 100, y + s * 42 // 100, s * 44 // 100, color)


def icon(parent, code, x, y, s, night, back):
    """Draw the WMO weather code as a picture of s x s pixels, made of LVGL objects."""
    p = bare(parent, x, y, s, s)
    grey = 0xC4CEDA if THEMES[cfg["theme"]][0] != "Giorno" else 0x9FB0C2
    if code <= 1:
        if night:
            moon(p, s // 2, s // 2, s, back)
        else:
            sun(p, s // 2, s // 2, s)
    elif code == 2:
        if night:
            moon(p, s * 66 // 100, s * 32 // 100, s * 3 // 4, back)
        else:
            sun(p, s * 66 // 100, s * 34 // 100, s * 3 // 4)
        cloud(p, s, grey, s // 10)
    elif code == 3:
        cloud(p, s, grey, s // 12)
    elif code in (45, 48):
        cloud(p, s, grey, -s // 10)
        w = max(2, s // 18)
        for i in (0, 1, 2):
            stroke(p, ((s * (14 + 6 * i) // 100, s * (68 + 11 * i) // 100), (s * (86 - 6 * i) // 100, s * (68 + 11 * i) // 100)), w, grey)
    elif code >= 95:
        cloud(p, s, grey, -s // 8)
        pts = (
            (s * 56 // 100, s * 54 // 100),
            (s * 42 // 100, s * 74 // 100),
            (s * 54 // 100, s * 74 // 100),
            (s * 44 // 100, s * 94 // 100),
        )
        stroke(p, pts, max(3, s // 16), BOLT)
    elif 71 <= code <= 77 or code in (85, 86):
        cloud(p, s, grey, -s // 8)
        for i, dy in ((0, 0), (1, 16), (2, 0)):
            disc(p, s * (30 + 20 * i) // 100, s * (68 + dy) // 100, max(4, s // 9), SNOW)
    else:  # drizzle, rain, showers
        cloud(p, s, grey, -s // 8)
        drops = 2 if code < 60 else 3
        for i in range(drops):
            x0 = s * (36 + 60 // drops * i) // 100
            stroke(p, ((x0, s * 64 // 100), (x0 - s // 10, s * 86 // 100)), max(2, s // 18), RAIN)
    return p


def describe(code):
    table = ((1, 1), (2, 2), (3, 3), (48, 4), (57, 5), (67, 6), (77, 7), (82, 8), (86, 9), (99, 10))
    if code == 0:
        return t("codes")[0]
    for top, i in table:
        if code <= top:
            return t("codes")[i]
    return ""


def compass(parent, x, y, d, degrees):
    c = colors()
    p = bare(parent, x, y, d, d)
    ring = bare(p, 0, 0, d, d)
    ring.set_style_radius(lv.RADIUS_CIRCLE, 0)
    ring.set_style_border_width(3, 0)
    ring.set_style_border_color(lv.color_hex(c[3]), 0)
    # The arrow shows where the wind goes, the opposite of where it comes from.
    a = math.radians(degrees + 180)
    r = d // 2 - 10
    sx, sy = math.sin(a), -math.cos(a)
    m = d // 2
    tip = (int(m + sx * r), int(m + sy * r))
    tail = (int(m - sx * r), int(m - sy * r))
    side = []
    for da in (2.6, -2.6):
        side.append((int(tip[0] + math.sin(a + da) * r * 0.6), int(tip[1] - math.cos(a + da) * r * 0.6)))
    stroke(p, (tail, tip), 4, c[4])
    stroke(p, (side[0], tip, side[1]), 4, c[4])
    return p


# --- screens -------------------------------------------------------------------------


def show(build):
    """Replace the screen. Call it from the main loop, never from an LVGL callback."""
    global on_main
    old = lv.screen_active()
    ui.clear()
    scr = lv.obj()
    scr.remove_flag(lv.obj.FLAG.SCROLLABLE)
    scr.set_style_bg_color(lv.color_hex(colors()[0]), 0)
    scr.set_style_pad_all(0, 0)
    scr.set_style_text_color(lv.color_hex(colors()[2]), 0)
    on_main = build is main_screen
    build(scr)
    lv.screen_load(scr)
    old.delete()


def later(fn):
    global job
    job = fn


def status(text):
    if "status" in ui:
        ui["status"].set_text(text)
        lv.refr_now(lv.display_get_default())  # a network call comes next


def title(scr, text, step):
    c = colors()
    label(scr, text, 24, c[2], 16, 14)
    label(scr, step + "/4", 14, c[3], 16, 46)
    ui["status"] = label(scr, "", 14, c[4], 60, 46)


def keyboard(scr, ta, ready):
    kb = lv.keyboard(scr)
    kb.set_size(W, 220)
    kb.align(lv.ALIGN.BOTTOM_MID, 0, 0)
    kb.set_textarea(ta)
    kb.add_event_cb(lambda e: ready(), lv.EVENT.READY, None)
    ui["kb"] = kb


def fill_list(box, names, pick):
    box.clean()
    for name in names:
        b = box.add_button(None, plain(name))
        b.add_event_cb(lambda e, n=name: pick(n), lv.EVENT.CLICKED, None)


def wifi_screen(scr):
    title(scr, t("wifi"), "1")
    if configured():
        button(scr, lv.SYMBOL.CLOSE, 190, 12, 52, 44, lambda: later(update))
    button(scr, t("rescan"), 250, 12, 100, 44, lambda: later(do_scan))
    button(scr, t("next"), 360, 12, 104, 44, lambda: later(do_connect))
    box = lv.list(scr)
    box.set_pos(10, 66)
    box.set_size(W - 20, 134)
    ui["list"] = box
    ta = lv.textarea(scr)
    ta.set_pos(10, 206)
    ta.set_size(W - 20, 46)
    ta.set_one_line(True)
    ta.set_password_mode(True)
    ta.set_placeholder_text(t("password"))
    ta.set_text(cfg["password"])
    ui["ta"] = ta
    ui["ssid"] = cfg["ssid"]
    keyboard(scr, ta, lambda: later(do_connect))


def pick_network(name):
    ui["ssid"] = name
    status(plain(name))


def do_scan():
    status(t("scan"))
    names = scan()
    fill_list(ui["list"], names, pick_network)
    status(plain(ui["ssid"]) if ui["ssid"] else t("pick") if names else t("none"))


def do_connect():
    if not ui.get("ssid"):
        status(t("pick"))
        return
    status(t("connecting"))
    ssid, password = ui["ssid"], ui["ta"].get_text()
    same = ssid == cfg["ssid"] and password == cfg["password"] and sta.isconnected()
    if same or wifi_up(ssid, password):
        cfg["ssid"], cfg["password"] = ssid, password
        show(place_screen)
    else:
        status(t("nowifi"))


def place_screen(scr):
    title(scr, t("place"), "2")
    if configured():
        button(scr, t("next"), 360, 12, 104, 44, lambda: later(lambda: show(style_screen)))
    button(scr, t("search"), 250, 12, 100, 44, lambda: later(do_search))
    ta = lv.textarea(scr)
    ta.set_pos(10, 66)
    ta.set_size(W - 20, 46)
    ta.set_one_line(True)
    ta.set_placeholder_text(t("place"))
    ta.set_text(cfg["place"])
    ui["ta"] = ta
    box = lv.list(scr)
    box.set_pos(10, 118)
    box.set_size(W - 20, 134)
    ui["list"] = box
    keyboard(scr, ta, lambda: later(do_search))


def do_search():
    status(t("searching"))
    try:
        results = geocode(ui["ta"].get_text().strip())
    except (OSError, ValueError) as e:
        print("geocode:", repr(e))
        status(t("failed"))
        return
    status("" if results else t("notfound"))
    names = {}
    for r in results:
        where = ", ".join(r[k] for k in ("name", "admin1", "country") if k in r)
        names[where] = r
    fill_list(ui["list"], names, lambda n: later(lambda: pick_place(names[n])))


def pick_place(r):
    cfg["place"], cfg["lat"], cfg["lon"] = r["name"], r["latitude"], r["longitude"]
    show(style_screen)


def choice(scr, text, y, options, key):
    c = colors()
    label(scr, text, 16, c[2], 20, y + 12)
    d = lv.dropdown(scr)
    d.set_pos(230, y)
    d.set_size(230, 46)
    d.set_options("\n".join(options))
    d.set_selected(cfg[key])
    ui[key] = d


def style_screen(scr):
    title(scr, t("style"), "3")
    button(scr, t("next"), 360, 12, 104, 44, lambda: later(style_next))
    choice(scr, t("theme"), 80, [th[0] for th in THEMES], "theme")
    choice(scr, t("temp"), 140, ["%s" % u[0] for u in UNITS], "unit")
    choice(scr, t("wind"), 200, [v[0] for v in WINDS], "wind")
    choice(scr, t("every"), 260, ["%d min" % m for m in REFRESH], "refresh")
    choice(scr, t("lang"), 320, ("Italiano", "English"), "lang")
    slider(scr, t("bright"), 392, "backlight")


def slider(scr, text, y, key):
    """A brightness in percent, shown on the panel while it moves."""
    c = colors()
    name = label(scr, "", 16, c[2], 20, y)
    s = lv.slider(scr)
    s.set_pos(236, y + 4)
    s.set_size(214, 14)
    s.set_range(MIN_BRIGHT, 100)
    s.set_value(max(MIN_BRIGHT, cfg[key]), False)
    s.set_style_bg_color(lv.color_hex(c[4]), lv.PART.INDICATOR)
    s.set_style_bg_color(lv.color_hex(c[4]), lv.PART.KNOB)

    def moved(e=None):
        display_driver.backlight(s.get_value())
        name.set_text("%s %d%%" % (text, s.get_value()))

    s.add_event_cb(moved, lv.EVENT.VALUE_CHANGED, None)
    moved()
    ui[key] = s


def style_next():
    for key in ("theme", "unit", "wind", "refresh", "lang"):
        cfg[key] = ui[key].get_selected()
    cfg["backlight"] = ui["backlight"].get_value()
    show(night_screen)


def time_choice(scr, text, y, key):
    c = colors()
    label(scr, text, 16, c[2], 20, y + 12)
    hours, minutes = lv.dropdown(scr), lv.dropdown(scr)
    hours.set_pos(230, y)
    hours.set_size(110, 46)
    hours.set_options("\n".join("%02d" % h for h in range(24)))
    hours.set_selected(cfg[key] // 60)
    minutes.set_pos(350, y)
    minutes.set_size(110, 46)
    minutes.set_options("\n".join("%02d" % m for m in range(0, 60, 15)))
    minutes.set_selected(cfg[key] % 60 // 15)
    ui[key] = (hours, minutes)


def night_screen(scr):
    c = colors()
    title(scr, t("night"), "4")
    button(scr, t("save"), 360, 12, 104, 44, lambda: later(do_save))
    label(scr, t("dim"), 16, c[2], 20, 92)
    sw = lv.switch(scr)
    sw.set_pos(230, 84)
    sw.set_size(76, 40)
    sw.set_style_bg_color(lv.color_hex(c[4]), lv.PART.INDICATOR | lv.STATE.CHECKED)
    if cfg["night"]:
        sw.add_state(lv.STATE.CHECKED)
    ui["night"] = sw
    time_choice(scr, t("from"), 150, "night_from")
    time_choice(scr, t("to"), 210, "night_to")
    slider(scr, t("bright"), 292, "night_backlight")


def do_save():
    cfg["night"] = ui["night"].has_state(lv.STATE.CHECKED)
    for key in ("night_from", "night_to"):
        hours, minutes = ui[key]
        cfg[key] = hours.get_selected() * 60 + minutes.get_selected() * 15
    cfg["night_backlight"] = ui["night_backlight"].get_value()
    save_settings()
    apply_brightness()
    update()


def open_setup():
    later(setup)


def setup():
    show(wifi_screen)
    do_scan()


def main_screen(scr):
    c = colors()
    label(scr, plain(cfg["place"]), 24, c[2], 16, 12)
    where = lv.SYMBOL.SD_CARD if cfg_file and cfg_file.startswith("/sd") else lv.SYMBOL.HOME
    gear = button(scr, lv.SYMBOL.SETTINGS, W - 62, 8, 52, 44, open_setup)
    ui["status"] = label(scr, "", 14, c[3], 16, 44)
    label(scr, where, 14, c[3], W - 90, 22)
    gear.set_style_bg_color(lv.color_hex(c[1]), 0)
    gear.get_child(0).set_style_text_color(lv.color_hex(c[2]), 0)
    if not weather:
        ui["status"].set_text(t("loading"))
        return
    now, days = weather["current"], weather["daily"]
    ui["status"].set_text("%s %s" % (t("updated"), now["time"][11:16]))
    unit = "°" + UNITS[cfg["unit"]][0]
    speed = WINDS[cfg["wind"]][0]

    hero = block(scr, 10, 68, W - 20, 176, 16, c[1])
    hero.add_flag(lv.obj.FLAG.CLICKABLE)
    hero.add_event_cb(lambda e: later(update), lv.EVENT.CLICKED, None)
    icon(hero, now["weather_code"], 14, 14, 148, not now["is_day"], c[1])
    n = label(hero, "%d%s" % (round(now["temperature_2m"]), unit), 40, c[2], 190, 26)
    n.set_style_transform_scale(400, 0)
    n.set_style_transform_pivot_x(0, 0)
    n.set_style_transform_pivot_y(0, 0)
    label(hero, describe(now["weather_code"]), 24, c[2], 190, 94)
    label(hero, "%s %d%s" % (t("feels"), round(now["apparent_temperature"]), unit), 16, c[3], 190, 130)

    card = block(scr, 10, 252, W - 20, 96, 16, c[1])
    compass(card, 12, 8, 80, now["wind_direction_10m"])
    dirs = t("dirs")[int((now["wind_direction_10m"] + 22.5) // 45) % 8]
    label(card, "%d %s %s" % (round(now["wind_speed_10m"]), speed, dirs), 24, c[2], 106, 12)
    label(card, "%s %d %s" % (t("gust"), round(now["wind_gusts_10m"]), speed), 16, c[3], 106, 56)
    label(card, "%s %d%%" % (t("humidity"), now["relative_humidity_2m"]), 16, c[3], 300, 18)
    label(card, "%s %d%%" % (t("rain"), days["precipitation_probability_max"][0] or 0), 16, c[3], 300, 56)

    for i in range(5):
        day = days["time"][i]
        wday = time.localtime(time.mktime((int(day[:4]), int(day[5:7]), int(day[8:10]), 12, 0, 0, 0, 0)))[6]
        col = block(scr, 10 + i * 93, 356, 87, 116, 12, c[1])
        d = label(col, t("days")[wday], 16, c[2], 0, 4)
        d.set_width(87)
        d.set_style_text_align(lv.TEXT_ALIGN.CENTER, 0)
        icon(col, days["weather_code"][i], 18, 24, 50, False, c[1])
        m = label(col, "%d / %d" % (round(days["temperature_2m_max"][i]), round(days["temperature_2m_min"][i])), 16, c[2], 0, 74)
        m.set_width(87)
        m.set_style_text_align(lv.TEXT_ALIGN.CENTER, 0)
        v = label(col, "%d %s" % (round(days["wind_speed_10m_max"][i]), speed), 14, c[3], 0, 96)
        v.set_width(87)
        v.set_style_text_align(lv.TEXT_ALIGN.CENTER, 0)


def update():
    global weather, next_update
    if on_main:
        status(t("loading"))
    else:
        show(main_screen)
    try:
        if not wifi_up():
            raise OSError("no WiFi")
        weather = forecast()
        sync_clock(weather["utc_offset_seconds"])
    except (OSError, ValueError, KeyError, IndexError, AttributeError) as e:
        print("update:", repr(e))
        next_update = time.ticks_add(time.ticks_ms(), RETRY_S * 1000)
        status(t("failed"))
        return
    next_update = time.ticks_add(time.ticks_ms(), REFRESH[cfg["refresh"]] * 60000)
    apply_brightness()
    show(main_screen)


def main():
    global job
    mount_sd()
    load_settings()
    apply_brightness()
    print("SD", "ok" if sd_ok else "not available")
    later(update if configured() else setup)
    next_check = time.ticks_ms()
    while True:
        fn, job = job, None
        try:
            if fn:
                fn()
            elif on_main and time.ticks_diff(time.ticks_ms(), next_update) >= 0:
                update()
            elif on_main and time.ticks_diff(time.ticks_ms(), next_check) >= 0:
                next_check = time.ticks_add(time.ticks_ms(), 20000)
                apply_brightness()
        except Exception as e:
            print("error:", repr(e))
        time.sleep_ms(50)


if __name__ == "__main__":
    main()
