# Speaker of the ESP32-4848S040: beeps and WAV files, in the background.
#
#   import audio
#   audio.beep()                     # 880 Hz, 100 ms
#   audio.beep(440, 500, atten=2)    # atten: quieter by 6 dB a step
#   audio.tone(660)                  # until audio.finish()
#   audio.play("/sound.wav")         # returns at once; PCM, 16 bit, mono or stereo
#   audio.playing()
#   audio.finish()                   # stop feeding: what is buffered still plays
#   audio.stop()                     # silence now
#
# NS4168 on I2S: BCLK GPIO 1, LRCLK GPIO 2, DIN GPIO 40. These are also the relay pins: do not
# use this module on a board with the relays fitted. The amplifier plays one channel, so a
# stereo file loses the other one; mono goes to both.
#
# A sound comes out about 150 ms after the call, the time to cross the buffers.
#
# The next block is written from the I2S interrupt through the scheduler, like the LVGL
# timer: nothing blocks, and a long gc.collect() can make the sound stutter.
import math
import struct

from machine import I2S, Pin

SCK, WS, SD = 1, 2, 40
RATE = 22050
BLOCK = 4096
IBUF = 8192
# Blocks of silence after the last sound, plus one: the I2S must not stop while the sound is
# still in its DMA buffers. With a shorter tail a beep of 60 ms is never heard.
TAIL = 1

_i2s = None
_file = None
_buf = None
_view = None
_left = 0
_atten = 0
_tail = 0

def _start(rate, channels, atten):
    global _i2s, _buf, _view, _atten, _tail
    stop()
    fmt = I2S.MONO if channels == 1 else I2S.STEREO
    _i2s = I2S(0, sck=Pin(SCK), ws=Pin(WS), sd=Pin(SD), mode=I2S.TX, bits=16, format=fmt, rate=rate, ibuf=IBUF)
    _buf = bytearray(BLOCK)
    _view = memoryview(_buf)
    _atten = atten
    _tail = 0
    _i2s.irq(_feed)


def _feed(_=None):
    global _left, _tail
    if _i2s is None:
        return
    if _tail > TAIL:
        stop()
        return
    n = min(_left, len(_buf))
    if _file and n:
        n = _file.readinto(_view[:n])
    _left -= n
    if n == 0:
        # Silence, so that the end of the sound leaves the DMA buffers before the I2S stops.
        if not _tail:
            _buf[:] = bytes(len(_buf))
        _tail += 1
        _i2s.write(_buf)
        return
    if _file and _atten:
        I2S.shift(buf=_view[:n], bits=16, shift=-_atten)
    _i2s.write(_view[:n])


def stop():
    global _i2s, _file, _buf, _view
    i2s, f = _i2s, _file
    _i2s = _file = _buf = _view = None
    if i2s:
        i2s.deinit()
    if f:
        f.close()


def playing():
    return _i2s is not None


def finish():
    global _left
    _left = 0


def _tone(freq, nbytes, atten):
    global _buf, _view, _left
    _start(RATE, 1, atten)
    period = max(2, round(RATE / freq))
    amplitude = 16000 >> atten
    one = bytearray(2 * period)
    for i in range(period):
        struct.pack_into("<h", one, 2 * i, int(amplitude * math.sin(2 * math.pi * i / period)))
    # A block of whole periods, written again and again.
    _buf = bytearray(bytes(one) * (BLOCK // len(one)))
    _view = memoryview(_buf)
    _left = nbytes - nbytes % len(one)
    _feed()


def beep(freq=880, ms=100, atten=1):
    _tone(freq, RATE * ms // 1000 * 2, atten)


def tone(freq=880, atten=1):
    _tone(freq, 1 << 30, atten)


def _wav_data(f):
    """Leave f at the samples; returns (rate, channels, bytes of samples)."""
    head = f.read(12)
    if head[:4] != b"RIFF" or head[8:12] != b"WAVE":
        raise ValueError("not a WAV file")
    channels = rate = None
    while True:
        h = f.read(8)
        if len(h) < 8:
            raise ValueError("no data in the WAV file")
        tag, size = h[:4], struct.unpack("<I", h[4:])[0]
        if tag == b"data":
            if channels is None:
                raise ValueError("no format in the WAV file")
            return rate, channels, size
        if tag == b"fmt ":
            fmt = f.read(size + (size & 1))
            code, channels, rate, _, _, bits = struct.unpack("<HHIIHH", fmt[:16])
            if code != 1 or bits != 16 or channels > 2:
                raise ValueError("only PCM, 16 bit, mono or stereo")
        else:
            f.seek(size + (size & 1), 1)


def play(path, atten=0):
    global _file, _left
    f = open(path, "rb")
    try:
        rate, channels, size = _wav_data(f)
        _start(rate, channels, atten)
    except Exception:
        f.close()
        raise
    _file, _left = f, size
    _feed()
