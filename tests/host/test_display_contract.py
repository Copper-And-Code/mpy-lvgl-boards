# Host test: the names of the display_driver contract (docs/display-driver.md) in the
# unix stand-in, as tests and LVGL MPY Studio rely on them.
#   cd tests/host && micropython test_display_contract.py
# Also runs on a board (it then checks the real driver; serve() is skipped there).
import sys

sys.path.insert(0, ".")
import display_driver as dd

failed = []


def check(name, ok):
    print(("ok  " if ok else "FAIL"), name)
    if not ok:
        failed.append(name)


check("CONTRACT == 1", getattr(dd, "CONTRACT", None) == 1)
for name in ("WIDTH", "HEIGHT", "BUFFERS", "PERIOD_MS", "indev", "start", "stop", "running", "backlight"):
    check("has " + name, hasattr(dd, name))
check("WIDTH, HEIGHT > 0", dd.WIDTH > 0 and dd.HEIGHT > 0)
check("BUFFERS 1 or 2", dd.BUFFERS in (1, 2))

check("running after import", dd.running())
dd.start()
check("start() when running: still running", dd.running())
dd.stop()
check("stop(): not running", not dd.running())
dd.stop()
check("stop() twice: not running", not dd.running())
dd.start()
check("start() again: running", dd.running())

level = dd.backlight()
dd.backlight(50)
check("backlight(50) reads back > 0", dd.backlight() > 0)
dd.backlight(level)

if hasattr(dd, "serve"):  # the unix stand-in: a KeyboardInterrupt reaches the caller
    import lvgl as lv

    def _cb(t):
        raise KeyboardInterrupt

    t = lv.timer_create(_cb, 0, None)
    got = False
    try:
        dd.serve()
    except KeyboardInterrupt:
        got = True
    t.delete()
    # The binding may print and drop an exception in a callback: then this documents it.
    print("info: KeyboardInterrupt in an LVGL timer callback reaches serve()'s caller:", got)

print("RESULT:", "FAILED " + ", ".join(failed) if failed else "OK")
