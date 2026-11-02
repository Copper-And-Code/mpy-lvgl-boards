# Tones on the board's buzzer, for games and examples. Silent on boards without
# one: the calls do nothing, so the same code runs everywhere.
#
#   import buzzer
#   buzzer.beep(440, 30)     # 440 Hz for 30 ms (switched off by an LVGL timer)
#   buzzer.tone(880)         # until buzzer.off()
#
# RP2350-Touch-LCD-4: passive buzzer on GPIO1 (PWM). STM32 boards: the "buzzer"
# pin of stm32_board.CONFIG, none so far.

import sys

PIN = None
if sys.platform == "rp2":
    PIN = 1
else:
    try:
        import stm32_board

        PIN = stm32_board.CONFIG.get("buzzer")
    except ImportError:
        pass

AVAILABLE = PIN is not None

_pwm = None
_timer = None


def tone(freq):
    global _pwm
    if PIN is None:
        return
    if freq <= 0:
        off()
        return
    if _pwm is None:
        from machine import PWM, Pin

        _pwm = PWM(Pin(PIN), freq=int(freq), duty_u16=0)
    _pwm.freq(int(freq))
    _pwm.duty_u16(32768)


def off():
    if _pwm is not None:
        _pwm.duty_u16(0)


def _stop(t):
    off()
    t.pause()


def beep(freq, ms=40):
    global _timer
    if PIN is None:
        return
    import lvgl as lv

    tone(freq)
    if _timer is None:
        _timer = lv.timer_create(_stop, ms, None)
    else:
        _timer.set_period(ms)
        _timer.reset()
        _timer.resume()
