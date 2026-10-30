# Install & usage on Cinnamon

This guide takes you from an empty system to a verified running daemon, end-to-end, on **Cinnamon** (X11 or Wayland; the commands below were tested as-is on an apt-based install, e.g. Linux Mint/Ubuntu — `sudo apt install python3-evdev`). [VeloScroll](../README.md) is a small Linux daemon that turns one mouse button into variable-velocity hold-to-scroll. It follows the general [installation guide](../docs/INSTALL.md), with only Step 6 (pointer settings) Cinnamon-specific. Like GNOME, Cinnamon exposes only *global* pointer settings that apply to every mouse — so there is nothing to seed: `veloscroll-mouse` inherits your existing sensitivity/acceleration automatically (verified in testing: pointer behavior was unchanged after install).

## Step 1 — Install dependencies

### Python 3 + evdev
```bash
sudo apt install python3-evdev
```

### systemd (soft dependency)
- The script can run standalone without it (python3 veloscroll.py), but the provided install path uses veloscroll.service, a root system unit for automatic restarts — so systemd is needed for that setup.
- Per-user units (systemctl --user) also work but aren't covered here.

## Step 2 — Clone the project

```bash
sudo git clone https://github.com/LucasTippelt/VeloScroll /opt/veloscroll
```

## Step 3 — Create the config file

```bash
sudo mkdir -p /etc/veloscroll && sudo cp /opt/veloscroll/config.ini.example /etc/veloscroll/config.ini
```

All settings go in `/etc/veloscroll/config.ini`, **not** `veloscroll.py` — do not edit `veloscroll.py`, since local edits are lost on the next update. Everything else has a working default; for all tunables see [Customize and reload](../docs/CONFIGURATION.md#customize-and-reload).

## Step 4 — Find your device

List all input devices with their USB IDs:

```bash
sudo python3 /opt/veloscroll/ListDeviceNames.py
```

Set, in `/etc/veloscroll/config.ini`:

- **HIGHLY Recommended:** `DEVICE_MATCH` to your mouse's exact USB ID pair (the last two columns of the list), e.g. `DEVICE_MATCH = 0x46d, 0xc084`. It selects exactly one device (stable across reboots and USB ports) and avoids grabbing other mice that share a name fragment.
- `DPI` to your mouse's *current* DPI setting — not its maximum.

Other options:

- **`NAME_MATCH`** is a simpler fallback: a case-insensitive substring of your mouse's name (e.g. `"Logitech Pro X"`). It is only used when `DEVICE_MATCH` is `None`, so make sure no other device shares the fragment. It is also useful for grabbing virtual devices created by other utilities.
- **Without Python:** `/sys/class/input/event*/device/name`, or `ls -l /dev/input/by-id` for stable symlinks with IDs.

**Two of the same mouse:** identical twins share one USB ID pair, so use a stable path string in `DEVICE_MATCH` instead — `/dev/input/by-id/usb-...-event-mouse` (only disambiguates if the device reports a serial number) or `/dev/input/by-path/pci-...-event-mouse`, which pins the mouse to its USB port (keep it plugged into the same port). Note that while several devices match, they are all grabbed and share one virtual mouse — holding the button on either drives scrolling from movement on either.

## Step 5 — Find your activation button

Print every key event your device emits (movement/scroll events are filtered out; Ctrl-C to stop):

```bash
sudo python3 /opt/veloscroll/ListButtonPresses.py XY
```

`XY` is the node number of your mouse from Step 4 (a full path like `/dev/input/eventX` works too). Press every button once and confirm that **no codes outside 256–287** are reported; if any are, see [Mice with non-standard buttons](../docs/INSTALL.md#mice-with-non-standard-buttons) in the installation guide. Note the button(s) you want to use for vertical/horizontal scrolling down — decimal is easiest (the number, e.g. 275).

Common button keycodes (`ev.type` 1 = EV_KEY):

| Button | Code | evdev constant |
| --- | --- | --- |
| BTN_LEFT | 272 | `e.BTN_LEFT` |
| BTN_RIGHT | 273 | `e.BTN_RIGHT` |
| BTN_MIDDLE | 274 | `e.BTN_MIDDLE` |
| BTN_SIDE | 275 | `e.BTN_SIDE` |
| BTN_EXTRA | 276 | `e.BTN_EXTRA` |
| BTN_FORWARD | 277 | `e.BTN_FORWARD` |
| BTN_BACK | 278 | `e.BTN_BACK` |
| BTN_TASK | 279 | `e.BTN_TASK` |

The constants are available as `evdev.ecodes.BTN_*`; set your choice in `/etc/veloscroll/config.ini`, using either the bare evdev name or a decimal code: e.g. `SCROLL_BTN = 275`.

## Step 6 — Pointer settings (nothing to do) *(Cinnamon-specific)*

Cinnamon's System Settings → Mouse & Touchpad exposes only *global* pointer sensitivity/acceleration — there are no per-device rules, so nothing needs copying or applying: `veloscroll-mouse` starts out feeling exactly like your real mouse because both use the same global values. Verified in testing: pointer settings were unchanged after install and no follow-up step was needed. General notes in [Desktop environment pointer settings](../docs/INSTALL.md#desktop-environment-pointer-settings) of the installation guide.

**Do not run `veloscroll_seed.py` here.** 

## Step 7 — Install the systemd service

```bash
sudo cp /opt/veloscroll/veloscroll.service /etc/systemd/system/
```

## Step 8 — Enable and start the service

```bash
sudo systemctl daemon-reload && sudo systemctl enable --now veloscroll
```

## Step 9 — Verify

```bash
journalctl -u veloscroll
```

should show a line like:

```
grabbed /dev/input/event4 Logitech G Pro X Superlight 2   (or whatever your device is, see Steps 4–5)
```

i.e. `grabbed <path> <device name>`. That's it — from here on, use the sections below for tuning and switching mice. Config changes after this are picked up within ~2 s without a restart.

## Tuning pointer settings (Sensitivity/acceleration mode)

- All input is now routed through the virtual device `veloscroll-mouse`, but sensitivity/acceleration stay *global*: whatever you set in System Settings → Mouse & Touchpad applies to every mouse, including `veloscroll-mouse`.
- While veloscroll runs, the daemon exclusively grabs the real mouse — its own movement is bypassed and only the virtual device's events reach your apps; since both share the same global values, there is nothing to keep in sync.
- Adjust the global settings once under System Settings → Mouse & Touchpad if you want a different feel; there are no per-device entries on Cinnamon, so no stale config accumulates and `veloscroll_seed.py` plays no role at all.

## Switching mice on Cinnamon

- Update `DEVICE_MATCH` and `DPI` in `/etc/veloscroll/config.ini` to the new mouse's USB ID pair and current DPI.
- Re-check `SCROLL_BTN` if the new mouse differs (see Step 5).
- No restart needed — changes are picked up within ~2 s; verify the fresh `grabbed <path> <device name>` line in `journalctl -u veloscroll`.

There is no Cinnamon-specific step: pointer settings are global and keep applying to `veloscroll-mouse` as-is, so nothing gets reset and no config accumulates.

## Updating

Your `/etc/veloscroll/config.ini` is outside the repo and survives updates untouched. Code changes need a restart, not hot-reload — after pulling, re-copy `veloscroll.service` if it changed (`sudo systemctl daemon-reload`) and run `sudo systemctl restart veloscroll`. Full steps: [docs/UPDATING.md](../docs/UPDATING.md).
