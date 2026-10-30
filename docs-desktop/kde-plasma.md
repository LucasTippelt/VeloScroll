# Install & usage on KDE Plasma

This guide takes you from an empty system to a verified running daemon, end-to-end, on **KDE Plasma 5 or 6** (X11 or Wayland). [VeloScroll](../README.md) is a small Linux daemon that turns one mouse button into variable-velocity hold-to-scroll. It follows the general [installation guide](../docs/INSTALL.md); the steps marked KDE-specific are Step 6 (seeding per-device pointer settings) and a Wayland-only re-run note in Step 9. Per-device pointer rules are a KWin **Wayland** feature; under X11, System Settings exposes only *global* pointer settings that apply to every mouse, so Step 6 is a no-op there and tuning happens via the global sliders.

## Step 1 — Install dependencies

### Python 3 + evdev
Distro packages:
  - Debian/Ubuntu: `sudo apt install python3-evdev`
  - Fedora: `sudo dnf install python3-evdev`
  - Arch: `sudo pacman -S python-evdev`
  - openSUSE: `sudo zypper in python3-evdev`
  - Fallback: pip inside a virtualenv (`python3 -m venv <dir>`, activate it, then `pip install evdev`).

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

- **HIGHLY Recommended:** `DEVICE_MATCH` to your mouse's exact USB ID pair (the last two columns of the list), e.g. `DEVICE_MATCH = 0x46d, 0xc084`. It selects exactly one device (stable across reboots and USB ports), avoids grabbing other mice that share a name fragment, and may let per-device pointer rules in your DE/WM apply to the virtual mouse automatically.
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

## Step 6 — Seed per-device pointer settings *(KDE-specific)*

**Wayland, fresh install:** you are seeding before the daemon has started (Steps 7–8), so `veloscroll-mouse` isn't registered with KWin yet and the seed's live apply is skipped — that's expected. Re-run the seed once after Step 8 so the live apply can find `veloscroll-mouse`; the file copy itself already happened.

**X11 sessions:** per-device rules don't exist under X11 — System Settings has only *global* pointer settings, which already apply to `veloscroll-mouse`. Running the seed prints `no per-device settings for <name> in kcminputrc — veloscroll-mouse will use system defaults` and changes nothing; that's the expected outcome, not an error. You can skip this step entirely under X11.

<details>

<summary>Click here to expand if you are running Wayland.</summary><br/>

Run `veloscroll_seed.py` ([options](../docs/ADVANCED.md#veloscroll_seedpy-options)) **as your desktop user, not root** — run as root it would target `/root/.config`:

```bash
python3 /opt/veloscroll/veloscroll_seed.py
```

What it does: it finds your real mouse (via `DEVICE_MATCH`) and copies its per-device pointer settings from the `[Libinput][<vendor>][<product>][<name>]` group in `~/.config/kcminputrc` into a matching group for the virtual device — `[Libinput][<vendor>][<product>][veloscroll-mouse]` (decimal IDs) — then **applies them to your running session through KWin's D-Bus interface**, the same mechanism System Settings' "Apply" uses. After seeding, `veloscroll-mouse` starts out feeling exactly like your real mouse.

A successful run prints something like (values depend on your current settings):

```
real mouse : Logitech G Pro X Superlight 2 (0x46d:0xc084) at /dev/input/event4
live       : applied live via KWin: pointerAcceleration=-0.4, scrollFactor=1.0
Libinput][1133][49284][veloscroll-mouse]:
  PointerAcceleration: (none) -> -0.4
backup     : /home/<you>/.config/kcminputrc.bak-20261028-123456
```

Notes on the output:

- The section line is missing its leading `[` — in `kcminputrc` the group is `[Libinput][<vendor>][<product>][veloscroll-mouse]`.
- If the target group already matches, it prints `<group> already matches <source>` instead; a backup file is written only when something actually changed.
- If your real mouse has no per-device entry in `kcminputrc` — the normal situation on **X11** sessions (see above) — you get `no per-device settings for <name> in kcminputrc — veloscroll-mouse will use system defaults`.
- If `veloscroll-mouse` isn't registered with KWin yet (daemon not running), the live apply is skipped with a note to re-run after starting it; the file copy itself already happened.

If discovery picks the wrong device (e.g. two mice match your selector), select explicitly with `python3 /opt/veloscroll/veloscroll_seed.py --name <NAME>`. Re-run it whenever you change mice — update `DEVICE_MATCH` in `/etc/veloscroll/config.ini` first (see [Switching mice on Plasma](#switching-mice-on-plasma) below). To push hand-edited values from `kcminputrc` to a running session without re-seeding, run it with `--apply-only` instead (see [Tuning pointer settings](#tuning-pointer-settings-sensitivityacceleration-mode)).

</details>

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

**Wayland:** if you seeded in Step 6 before the daemon started (the normal case with this guide's ordering), re-run `python3 /opt/veloscroll/veloscroll_seed.py` now so the live apply can find `veloscroll-mouse`.

## Tuning pointer settings (Sensitivity/acceleration mode)

- All input is now routed through the virtual device `veloscroll-mouse`. 
- Sensitivity/acceleration are not properties of the mouse — they're applied by KDE, either as one *global* value for all mice (X11) or via *per-device rules* matched to a device's USB vendor/product ID (Wayland/Kwin). The virtual device copies your mouse's IDs, so:
### On **Wayland** ###
- Tune the `veloscroll-mouse` entry in System Settings → Mouse & Touchpad: after seeding it starts with your real mouse's values
- While veloscroll runs, the daemon exclusively grabs the real mouse — its own KDE entry is bypassed and only the virtual device's settings apply. 
- Tweaks you make to `veloscroll-mouse` survive restarts and reboots because KWin keys the config by `[vendor][product][name]` and the same IDs are re-advertised on every daemon start. Re-running the seed script resets that entry back to your real mouse's values — that is how you switch mice (see [Switching mice on Plasma](#switching-mice-on-plasma) below).
- **Gotcha on Wayland:** hand-editing `kcminputrc` alone will **not** change how a running session feels — KWin only applies per-device settings to an already-registered device through its D-Bus interface, and its file watcher is unreliable on Plasma 6 Wayland (KDE bug 513879). Re-running the seed does not help either: it overwrites the `veloscroll-mouse` group with your real mouse's values.
- To apply hand-edited values, close and reopen System Settings → Mouse & Touchpad first (with the module open, Apply pushes stale in-memory values and can clobber your edit), then click Apply — or run `python3 /opt/veloscroll/veloscroll_seed.py --apply-only`, which pushes the file's current `veloscroll-mouse` group to KWin without modifying it. As a last resort, re-login (KWin reads `kcminputrc` when the device registers).
### On **X11** ###
- there is no per-device entry — adjust the *global* Mouse & Touchpad settings once instead; they apply to both mice.

## Stale config

**Wayland only:** under X11, no such groups ever exist. Stale `[Libinput][…][veloscroll-mouse]` groups in `kcminputrc` — e.g. `[Libinput][1][1][veloscroll-mouse]` from pre-ID-copy runs (before the daemon advertised your mouse's real USB IDs on the virtual device), or groups left behind by previous mice — are dead config:

- To remove them, run `python3 /opt/veloscroll/veloscroll_seed.py --remove-stale-config`: it deletes every such group except the one keyed by your current mouse's USB IDs (from `DEVICE_MATCH`; use `--name` to disambiguate), and writes a `.bak-*` backup first. It combines with `--apply-only` in a single run — e.g. right after hand-editing values on a just-switched mouse: the file's current `veloscroll-mouse` group is pushed live first, then stale groups are removed; if the second part fails, the first has already taken effect (both parts are idempotent — just re-run).
- Re-running the seed resets the live `veloscroll-mouse` entry back to your real mouse's values, so a broken tweak is always recoverable that way too (and from the `.bak-*` backup files).

## Switching mice on Plasma

- Update `DEVICE_MATCH` and `DPI` in `/etc/veloscroll/config.ini` to the new mouse's USB ID pair and current DPI.
- Re-check `SCROLL_BTN` if the new mouse differs (see Step 5).
- No restart needed — changes are picked up within ~2 s; verify the fresh `grabbed <path> <device name>` line in `journalctl -u veloscroll`.

KDE specifics for re-running the seed:

### On **Wayland** ###
- Re-running the seed (Step 6) creates a new `veloscroll-mouse` group for the new mouse's IDs and resets any tweaks you made to `veloscroll-mouse` back to the new real mouse's values.
- Groups from previous mice accumulate in `kcminputrc` as dead config — remove them with `--remove-stale-config` if desired (see [Stale config](#stale-config)).

### On **X11** ###
- No KDE-specific step — the seed is a no-op there, so nothing gets reset and no groups accumulate; just follow the checklist above.

## Updating

Your `/etc/veloscroll/config.ini` is outside the repo and survives updates untouched. Code changes need a restart, not hot-reload — after pulling, re-copy `veloscroll.service` if it changed (`sudo systemctl daemon-reload`) and run `sudo systemctl restart veloscroll`. Full steps: [docs/UPDATING.md](../docs/UPDATING.md).
