# Installing the firmware with DFU (STM32 boards)

DFU uses the bootloader in the STM32's ROM over the board's own USB port: no adapter, no
wiring, and the board cannot be bricked by a failed attempt, because that bootloader cannot
be erased.

Tested on **STM32H7_CORE V1.0** with dfu-util 0.11 on Linux. The other STM32 boards have
the same ROM bootloader, but this procedure has not been run on them. For a board wired for
the UART bootloader see `docs/stm32h743.md` (Bench).

## What you need

- `dfu-util`: `sudo apt install dfu-util` on Debian and Ubuntu.
- A USB **data** cable, on the board's USB port for the MCU. Some boards have a second port
  for a USB-serial chip: that one does not do DFU.
- The firmware as a `.dfu` file, built with `scripts/build.sh`:

  ```bash
  scripts/build.sh stm32 STM32H7_CORE V10    # dist/STM32H7_CORE-V10-<commit>.dfu
  ```

## 1. Put the board in DFU mode

1. Hold **BOOT0**.
2. Press and release **RESET**, or plug in the USB cable.
3. Release BOOT0.

The screen stays dark and the board looks dead: that is normal. Check that the computer sees it:

```bash
lsusb | grep 0483:df11
# ... ID 0483:df11 STMicroelectronics STM Device in DFU Mode

dfu-util -l
# Found DFU: [0483:df11] ... alt=0, name="@Internal Flash   /0x08000000/16*128Kg" ...
```

If `0483:df11` does not appear, repeat the steps: BOOT0 must be held at the moment of the
reset. Then try another cable.

## 2. Write the firmware

```bash
dfu-util -a 0 -d 0483:df11 -D STM32H7_CORE-V10-<commit>.dfu
```

It shows a progress bar and ends with:

```text
Download done.
Done parsing DfuSe file
```

## 3. Start the firmware

The board **stays in DFU mode** after writing. Press **RESET**, without BOOT0.

## 4. Check it

The board comes back as MicroPython, with a serial port and a USB disk:

```bash
lsusb | grep f055:9800
# ... ID f055:9800 MicroPython STM32H7 Virtual Comm Port in FS Mode
```

Open the REPL with any serial terminal, on `/dev/ttyACM0` on Linux:

```bash
picocom /dev/ttyACM0        # Ctrl-A Ctrl-X to leave
```

```python
>>> import os, gc
>>> os.uname().machine, gc.mem_free()
('STM32H7_CORE V1.0 with STM32H743', 28670000)
>>> import display_driver      # the panel and the touch start
```

## What is kept

Only the internal flash is written. The filesystem on the QSPI flash, `/flash`, the disk
that appears on the computer, keeps its files. On a blank QSPI flash MicroPython creates the
filesystem at the first start: if your computer offers to format the disk, refuse.

## Problems

| Symptom | Cause |
|---|---|
| `Cannot open DFU device 0483:df11` or `LIBUSB_ERROR_ACCESS` | No permission on the USB device: on Linux, the `dfu-util` package installs a udev rule; add your user to `plugdev`, log in again, or run it with `sudo`. |
| `dfu-util: No DFU capable USB device available` | Not in DFU mode: repeat step 1. |
| `lsusb` shows `0483:df11` after step 3 | BOOT0 was still held, or RESET was not pressed. |
| Nothing after step 3, no `f055:9800` | The firmware is for another board or variant: back to step 1, with the right file. Check that the `.dfu` file matches the board revision. |

## Boards

| Board | File | Tested with DFU |
|---|---|---|
| STM32H7_CORE V1.0 | `STM32H7_CORE-V10-<commit>.dfu` | yes |
| STM32H7_CORE V1.3 | `STM32H7_CORE-V13-<commit>.dfu` | no |
| DEV190806042 | `DEV190806042-<commit>.dfu` | no |
| FK743M5-XIH6 | `FK743M5-XIH6-<commit>.dfu` | no |

On a board with DTR wired to BOOT0, as the V1.3 on our bench, an open serial adapter can hold
BOOT0: unplug it first.
