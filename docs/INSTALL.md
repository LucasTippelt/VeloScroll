# VeloScroll Installation Guide

## Contents

1. [Installation](#installation)
2. [Mice with non-standard buttons](#mice-with-non-standard-buttons)
3. [Desktop environment pointer settings](#desktop-environment-pointer-settings)
4. [Feeding another tool's virtual device into VeloScroll](#feeding-another-tools-virtual-device-into-veloscroll)

---

## Installation

### 1. Install dependencies

VeloScroll needs **Python 3 + evdev**. Install the distro package:

| Distribution  | Command |
|---------------|---------|
| Debian/Ubuntu | `sudo apt install python3-evdev` |
| Fedora        | `sudo dnf install python3-evdev` |
| Arch          | `sudo pacman -S python-evdev` |
| openSUSE      | `sudo zypper in python3-evdev` |

**Fallback:** pip inside a virtualenv: `python3 -m venv <dir>`, activate it, then `pip install evdev`.

### 2. Clone the project

Clone the repository to a stable location:

```bash
sudo git clone <repository-url> /opt/veloscroll
```

### 3. Create the config file

```bash
sudo mkdir -p /etc/veloscroll
sudo cp /opt/veloscroll/config.ini.example /etc/veloscroll/config.ini
```

All settings below go in `/etc/veloscroll/config.ini`, **not** in `veloscroll.py`.

### 4. Find your device

List all input devices with their USB IDs:

```bash
sudo python3 /opt/veloscroll/ListDeviceNames.py
```

Set `DEVICE_MATCH` to your mouse's USB ID pair (the last two columns of the list), and `DPI` to its current DPI:

```ini
DEVICE_MATCH = 0x46d, 0xc084
```

This is **highly recommended**: it selects exactly one device (stable across reboots and USB ports), avoids grabbing other mice that share a name fragment, and may let per-device pointer rules in your DE/WM apply to the virtual mouse automatically.

- **`NAME_MATCH`** is a simpler fallback: a case-insensitive substring of your mouse's name (e.g. `"Logitech Pro X"`). It is only used when `DEVICE_MATCH` is `None`, so make sure no other device shares the fragment. It is also useful for grabbing virtual devices created by other utilities.
- **Without Python:** `/sys/class/input/event*/device/name`, or `ls -l /dev/input/by-id` for stable symlinks with IDs.
- **Two identical mice** share one USB ID pair. Use a stable path in `DEVICE_MATCH` instead: `/dev/input/by-id/usb-...-event-mouse` (only works if the device reports a serial number) or `/dev/input/by-path/pci-...-event-mouse` (pins the mouse to its USB port). If several devices match, they are **all** grabbed and share one virtual mouse, so holding the button on either drives scrolling from movement on either.

### 5. Find your activation button

Print every key event your device emits (movement and scroll events are filtered out; Ctrl-C to stop):

```bash
sudo python3 /opt/veloscroll/ListButtonPresses.py 30
```

`30` is your mouse's node number from the device list (a full path works too). Press every button once and verify that **no codes outside 256–287** are reported. Expected output looks like:

```
272 0
273 1
274 1
```

Standard codes: `BTN_LEFT` 272, `BTN_RIGHT` 273, `BTN_MIDDLE` 274, `BTN_SIDE` 275, `BTN_EXTRA` 276, `BTN_FORWARD` 277, `BTN_BACK` 278, `BTN_TASK` 279 (available as `evdev.ecodes.BTN_*`).

Set your choice in `config.ini`, using either an evdev button name or a decimal code:

```ini
SCROLL_BTN = BTN_SIDE
# or equivalently
SCROLL_BTN = 275
```

### 6. (Optional) Seed per-device pointer settings

> **If you are unsure about this step, skip it.** It is not required.

If your desktop environment has per-device pointer settings, seed them so that `veloscroll-mouse` starts out feeling exactly like your real mouse. Run the seed script (`veloscroll_seed.py`, [options](ADVANCED.md#veloscroll_seedpy-options)) **as your user, not root**, following your desktop environment's guide (see [Desktop environment pointer settings](#desktop-environment-pointer-settings)). If your desktop environment is not yet supported by `veloscroll_seed.py`, you will adjust the settings manually in step 9.

### 7. Install the systemd service

```bash
sudo cp /opt/veloscroll/veloscroll.service /etc/systemd/system/
```

### 8. Enable and start the service

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now veloscroll
```

### 9. Verify

```bash
journalctl -u veloscroll
```

You should see a line like `grabbed <path> <device name>`.

If step 6 applied to you (your desktop has per-device pointer settings and seeding is not supported for it), open your system settings now and adjust the `veloscroll-mouse` pointer settings to your liking. This is a one-time setup; your desktop environment should save it.

### 10. Tweak your configuration

Adjust `/etc/veloscroll/config.ini` to your preference. See the [`config.ini` keys reference](CONFIGURATION.md#configini-keys-hot-reloaded) (settings are **hot-reloaded**, so no restart is needed).

---

## Mice with non-standard buttons

Each button can be mapped to at most one role, and the three role codes must be distinct (enforced by `check_config`). Everything else passes through.

| Key             | Behavior |
|-----------------|----------|
| `SCROLL_BTN`    | Hold to scroll, or tap-to-toggle while `TOGGLE_SCROLL = true` (tap again to disengage; releasing does nothing while latched). In both modes its press and release edges are consumed and never reach the OS, so **that button loses its normal click action while the daemon runs.** |
| `SCROLL_BTN_H`  | Optional second axis. Horizontal by default: mouse X movement drives `REL_HWHEEL`/`REL_HWHEEL_HI_RES` through the vertical ramp, unless overridden by the `_H` keys. With `VERTICAL_H = true` it scrolls vertically instead (up/down movement drives `REL_WHEEL`, same `_H`-key values). Has its own toggle mode via `TOGGLE_SCROLL_H`; unset or `none` falls back to `TOGGLE_SCROLL`. Set `none` to disable the feature. |
| `DISABLED_BTN`  | Swallowed entirely (does nothing). Set `none` to disable this feature. |

All remaining buttons pass through as-is, whatever their codes, subject to the behavior below while a scroll session is active.

### While a scroll session is active

- The cursor stays put.
- Movement on the active axis is consumed for velocity math.
- Wheel events from the physical mouse are swallowed.
- Releasing the button (or tapping it off) restores normal behavior immediately.

### Using both scroll buttons

If both scroll buttons are held at once, the last press owns the active axis. Releasing it reactivates the other fresh (LIFO).

### Supported button code range

The virtual device advertises `EV_KEY` codes `0x100`–`0x11F` (decimal **256–287**): `BTN_MISC`/`BTN_0`–`BTN_9` and `BTN_LEFT`…`BTN_TASK` (the `cap` dict at the top of `veloscroll.py`). Extra side/top buttons on many-button mice, such as DPI or back/forward keys reported as `BTN_SIDE`, `BTN_EXTRA`, `BTN_TASK`, or `BTN_5`–`BTN_9`, pass through and work without code edits.

Codes **outside** 256–287 are not advertised, so such buttons might do nothing:

- Keyboard/media keycodes below 256 (gaming-mouse media/macro keys sometimes report as keyboard keycodes)
- Gamepad codes ≥ `0x130`
- Extended "special" mouse button codes `BTN_TRIGGER`/`BTN_THUMB*`/`BTN_TOP*`/`BTN_PINKIE`/`BTN_BASE*` at decimal 288–299

This is fine for normal mice. If a button you need reports outside 256–287 and stops working with VeloScroll, please open an issue.

---

## Desktop environment pointer settings

Follow your desktop environment's guide end-to-end for the full commands and explanations:

| Desktop environment               | Guide                        |
|-----------------------------------|------------------------------|
| KDE Plasma (5/6, X11 or Wayland)  | [docs-desktop/kde-plasma.md](docs-desktop/kde-plasma.md) |
| Fedora Workstation 44 (GNOME)     | [docs-desktop/gnome.md](docs-desktop/gnome.md)      |
| Cinnamon                          | [docs-desktop/cinnamon.md](docs-desktop/cinnamon.md)   |

Notes:

- **Seeding** (`veloscroll_seed.py`) is currently supported on **KDE Plasma (Wayland) only**. X11 has Global Pointer Settings.
- On desktop environments with **Global Pointer Settings**, running `veloscroll_seed.py` is not necessary. Your pointer settings should stay consistent out of the box.
- If your desktop environment has **per-device pointer settings** and seeding is not supported, adjust the pointer settings for the virtual device (default name: `veloscroll-mouse`) in your system settings once after install, so they match how your actual mouse feels. This is a one-time setup.

---

## Feeding another tool's virtual device into VeloScroll

VeloScroll doesn't care where events come from. Any evdev input node that advertises `REL_X` and matches your selector is a valid source, including `uinput` devices created by other tools (e.g. the virtual mouse of [input-remapper](https://github.com/sezanzeb/input-remapper)).

The pipeline becomes:

```
physical mouse → remapper (exclusively grabs it) → its virtual device → veloscroll → veloscroll-mouse
```

Guidelines:

- **Point your selector at the virtual node, not the physical one.** A `NAME_MATCH` fragment of the remapper's device name is the stable option. `uinput` devices get no USB `by-id`/`by-path` links on most systems, and bare `/dev/input/eventN` numbers change across reboots.
- **Beware selectors that also match the physical mouse.** The remapper's forwarding clone keeps the source's name and often its USB IDs. In that case VeloScroll grabs the virtual node and logs periodic `device busy` lines for the physical one the remapper holds. This is harmless but noisy.
- **Start order:** enable the remapper *before* starting VeloScroll so it wins the grab on the physical mouse. A remapper started later is picked up automatically on the next ~2 s scan (no restart needed).
- **Buttons:** `SCROLL_BTN`/`DISABLED_BTN` accept any code the remapper emits. Pass-through mouse buttons work across the full standard button range (`0x100`–`0x11F`, see [above](#supported-button-code-range)).
- **Motion:** relative motion passes through unscaled, so the same `DPI` value applies.

> **Tested: no.** This combination is supported by design but has not been verified with input-remapper or any other remapper. Please report what you find in an issue or PR.

---

**Next:** [Configuration →](CONFIGURATION.md)
