# Install & usage on Fedora Workstation 44 (GNOME)

This guide takes you from an empty system to a verified running daemon, end-to-end, on **Fedora Workstation 44 with GNOME** (Wayland by default; the daemon behaves identically under X11). [VeloScroll](../README.md) is a small Linux daemon that turns one mouse button into variable-velocity hold-to-scroll; the general README covers the project overview, compatibility notes, and all post-install tuning options. Unlike KDE Plasma's per-device pointer rules, GNOME exposes only *global* pointer settings that apply to every mouse — so there is nothing to seed: `veloscroll-mouse` inherits your existing sensitivity/acceleration automatically (verified on Fedora Workstation 44: pointer behavior was unchanged after install).

## Step 1 — Install dependencies

### Python 3 + evdev
```bash
sudo dnf install python3-evdev
```

### systemd (soft dependency)
- The script can run standalone without it (python3 veloscroll.py), but the provided install path uses veloscroll.service, a root system unit for automatic restarts — so systemd is needed for that setup.
- Per-user units (systemctl --user) also work but aren't covered here.

## Step 2 — Clone & install the unit

```bash
sudo git clone https://github.com/LucasTippelt/VeloScroll /opt/veloscroll
sudo cp /opt/veloscroll/veloscroll.service /etc/systemd/system/
sudo systemctl daemon-reload; sudo systemctl enable --now veloscroll
```

This also starts the daemon. Until `DEVICE_MATCH` in `/etc/veloscroll/config.ini` points at your mouse (Step 4), it just waits and logs `no matching device yet — waiting`.

## Step 3 — Find your device name & activation button

List all input devices with their USB IDs (uses the evdev package you already installed):

```bash
sudo python3 -c "import evdev; [print(p, '->', d.name, hex(d.info.vendor), hex(d.info.product)) for p in evdev.list_devices() if (d := evdev.InputDevice(p))]"
```

- **Recommended: set `DEVICE_MATCH` in `/etc/veloscroll/config.ini` to your mouse's exact USB ID pair** — e.g. `DEVICE_MATCH = 0x46d, 0xc084` (in veloscroll.py the same value uses Python tuple syntax `(0x46d, 0xc084)`), read off from the last two columns above. It selects exactly one device (stable across reboots and USB ports) and avoids grabbing other mice that share a name fragment.
- `NAME_MATCH` is a simpler fallback: any case-insensitive substring of your mouse's name from that list (e.g. `"Logitech Pro X"`); it is only used when `DEVICE_MATCH` is None, so make sure no other device shares the fragment or set `DEVICE_MATCH`.
- Alternative for names without Python: `/sys/class/input/event*/device/name`; stable symlinks with IDs: `ls -l /dev/input/by-id`.

**Two of the same mouse:** identical twins share one USB ID pair, so use a stable path string in `DEVICE_MATCH` instead — `/dev/input/by-id/usb-...-event-mouse` (only disambiguates if the device reports a serial number) or `/dev/input/by-path/pci-...-event-mouse`, which pins the mouse to its USB port (keep it plugged into the same port). Note that while several devices match, they are all grabbed and share one virtual mouse — holding the button on either drives scrolling from movement on either.

To find the activation button code, open your device and print every event — press the candidate side buttons and read off their codes (Ctrl-C to stop):

```bash
sudo python3 - <<'EOF'
import evdev
path = "/dev/input/eventX"  # replace with your mouse's node from the list above
dev = evdev.InputDevice(path)
print("press the candidate side buttons; Ctrl-C to stop")
for ev in dev.read_loop():
    print(ev.type, ev.code, ev.value)
EOF
```

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

The constants are available as `evdev.ecodes.BTN_*`; in `/etc/veloscroll/config.ini` use the bare name or decimal code (e.g. `SCROLL_BTN = BTN_SIDE`), in veloscroll.py set e.g. `SCROLL_BTN = e.BTN_SIDE`.

- **Set `DEVICE_MATCH` to your mouse's USB ID pair from the list above (or fall back to a unique name fragment in `NAME_MATCH`) and your preferred scroll button to `SCROLL_BTN` — in `/etc/veloscroll/config.ini`, or directly in veloscroll.py.**

## Step 4 — Configure the daemon

Create the config file from the bundled example (skip this if you already did it during install), then open `/etc/veloscroll/config.ini`:

```bash
sudo mkdir -p /etc/veloscroll && sudo cp /opt/veloscroll/config.ini.example /etc/veloscroll/config.ini
```

Set, in the `[veloscroll]` section:

- `DEVICE_MATCH` to your mouse's USB ID pair from Step 3 (e.g. `DEVICE_MATCH = 0x46d, 0xc084`),
- `SCROLL_BTN` to the button code you found in Step 3 (e.g. `BTN_SIDE`),
- `DPI` to your mouse's *current* DPI setting — not its maximum.

No restart needed: the daemon picks up changes within ~2 s and grabs the mouse automatically. Verify with `journalctl -u veloscroll` — a `config reloaded:` line (if any value differs from the built-in default) followed by `grabbed <path> <device name>`.

Everything else has a working default; for all tunables and tuning hints see [Customize & reload](../README.md#customize--reload) in the README.

## Step 5 — Pointer settings (nothing to do)

GNOME's Settings → Mouse & Touchpad exposes only *global* pointer sensitivity/acceleration — there are no per-device rules, so nothing needs copying or applying: `veloscroll-mouse` starts out feeling exactly like your real mouse because both use the same global values. Verified on Fedora Workstation 44 (Wayland): pointer settings were unchanged after install and no follow-up step was needed.

**Do not run `veloscroll_seed.py` here.** It has no GNOME backend — its registry (`BACKENDS`) currently contains only `kde-plasma`, and with the default `DE_WM = "kde-plasma"` it would try to operate on KDE's `~/.config/kcminputrc`, which doesn't exist on a GNOME system.

## Step 6 — Verify

```bash
journalctl -u veloscroll
```

should show a line like:

```
grabbed /dev/input/event4 Logitech G Pro X Superlight 2   (or whatever your device is, see Finding your device name & activation button)
```

i.e. `grabbed <path> <device name>`. That's it — from here on, use the sections below for tuning and switching mice.

## Tuning pointer settings (Sensitivity/acceleration mode)

- All input is now routed through the virtual device `veloscroll-mouse`, but sensitivity/acceleration stay *global*: whatever you set in Settings → Mouse & Touchpad applies to every mouse, including `veloscroll-mouse`.
- While veloscroll runs, the daemon exclusively grabs the real mouse — its own movement is bypassed and only the virtual device's events reach your apps; since both share the same global values, there is nothing to keep in sync.
- Adjust the global settings once under Settings → Mouse & Touchpad if you want a different feel; there are no per-device entries on GNOME, so no stale config accumulates and `veloscroll_seed.py` plays no role at all.

## Switching mice on GNOME

Follow the general checklist in [README → Switching mice](../README.md#switching-mice). There is no GNOME-specific step: pointer settings are global and keep applying to `veloscroll-mouse` as-is, so nothing gets reset and no config accumulates — just update `DEVICE_MATCH`/`DPI` (and re-check `SCROLL_BTN`) in `/etc/veloscroll/config.ini` and verify the new `grabbed ...` line.
