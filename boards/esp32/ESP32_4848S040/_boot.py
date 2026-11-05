import gc
import vfs
from flashbdev import bdev

try:
    if bdev:
        vfs.mount(bdev, "/")
except OSError:
    import inisetup

    inisetup.setup()

gc.collect()

# LVGL's state must be forgotten at every soft reset, whoever used LVGL: see esp_rgb.c.
import esp_rgb

esp_rgb.lvgl_guard()
del esp_rgb
