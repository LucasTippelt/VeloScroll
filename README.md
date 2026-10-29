# VeloScroll

Variable-velocity scrolling for Linux mice: hold a button, move the mouse, and scroll at a speed proportional to how far you have moved from the press point.

## Documentation

All guides live in [`documentation/`](documentation/). Suggested reading order:

1. [Install](documentation/INSTALL.md): install, find your device and button, run as a service
2. [Configuration](documentation/CONFIGURATION.md): every `config.ini` key and the tuning helper
3. [Presets](documentation/PRESETS.md): save and switch named configurations

Reference:

- [Updating](documentation/UPDATING.md): fetch a new release, restart, roll back
- [Advanced](documentation/ADVANCED.md): fork-level constants and `veloscroll_seed.py` options

Each guide in the reading order links to the next one at the bottom.

---

## Features

### 🖱️ Core scrolling mechanism

- **Variable-velocity scrolling:** While you hold a configured mouse button, moving the mouse scrolls at a speed proportional to your distance from the initial press point.
- **Configurable activation button:** Map any mouse button (not just the middle one) to trigger scrolling via `SCROLL_BTN`, using an evdev name like `BTN_SIDE` or a decimal code.
- **Hold or toggle mode:** By default you hold the button to scroll. Setting `TOGGLE_SCROLL = true` switches to tap-to-toggle (tap to start, tap again to stop).
- **Cursor lock during scroll:** While a scroll session is active, the cursor stays put and movement is consumed for velocity math rather than moving the pointer. Releasing the button restores normal behavior immediately.
- **Dual-axis support:** An optional second button (`SCROLL_BTN_H`) enables horizontal scrolling (driven by mouse X movement). With `VERTICAL_H = true` it acts as a second vertical scroll with its own curve, driven by mouse up/down movement.

### ⚙️ Deep configuration and tuning

- **Text-based configuration:** All settings live in `/etc/veloscroll/config.ini`, which is hot-reloaded within ~2 seconds without restarting the daemon.
- **Precise speed ramp control:** Tune the acceleration curve with granular parameters:

  | Key | Effect |
  |-----|--------|
  | `DEADZONE_IN` | Distance (inches) below which nothing scrolls |
  | `FULL_IN` | Distance at which `MAX_RATE` is reached |
  | `MAX_RATE` / `MIN_RATE` | Top and floor scroll speeds (notches/second) |
  | `CURVE` | Shape of the speed ramp: `>1` gentle start, `=1` linear, `<1` steep start |

- **Independent horizontal tuning:** Parameters have `_H` variants (e.g. `DEADZONE_IN_H`, `CURVE_H`) so the horizontal axis can be tuned separately.
- **Output smoothing:** `OUT_SMOOTH` (0..1) controls how quickly the emitted scroll rate follows your target speed. Lower values are smoother, higher values are snappier.
- **Direction inversion:** `INVERT = true` flips the scroll direction (useful for natural scrolling).
- **DPI-aware:** You set your mouse's current DPI so distance calculations (in inches) are accurate.
- **Ticker rate:** `TICK` (default `0.004` s ≈ 250 Hz) controls how often the scroll rate is recomputed and hi-res events are emitted.

See the [Configuration Guide](documentation/CONFIGURATION.md) for the full key reference.

### 🎛️ Preset and workflow tools

- **Preset system (`veloscroll_preset.py`):** Save named snapshots of your configuration and load them back. Loads are grouped (`loadfeel`, `loaddistances`, `loadkeys`, `loaddevice`, `loadscroll`), so swapping a "feel" preset doesn't accidentally change your button bindings or device selection. Multiple load groups can be chained in one command. See [Presets](documentation/PRESETS.md).
- **Tuning assistant (`veloscroll_tuning_helper.py`):** With the daemon stopped, this script exclusively grabs your mouse and measures your actual hand movement. It prints an in-place distance gauge with the would-be target rate, helping you set `DEADZONE_IN` and `FULL_IN` from real distances instead of guesswork.
- **Device discovery scripts:**
  - `ListDeviceNames.py`: lists all input devices with their USB IDs.
  - `ListButtonPresses.py`: prints every key event a device emits, so you can find the code for your activation button.

### 🖥️ System integration and compatibility

- **Universal compatibility:** Works identically on X11 and Wayland, across GNOME, KDE, XFCE, Sway, i3 and others, because it operates below the compositor via `/dev/input` (evdev + uinput).
- **Precise device selection:**
  - `DEVICE_MATCH`: the recommended selector, using an exact USB ID pair (e.g. `0x46d, 0xc084`) or a path like `/dev/input/by-id/...`. Stable across reboots and USB ports.
  - `NAME_MATCH`: a simpler fallback using a case-insensitive substring of the device name.
- **Virtual device (`veloscroll-mouse`):** VeloScroll creates a virtual mouse. On KDE Plasma (Wayland), a seeding script (`veloscroll_seed.py`) can copy your real mouse's per-device pointer settings to this virtual device, so it feels identical without opening system settings.
- **Button pass-through:** All other mouse buttons (side, extra, DPI, etc.) pass through as-is. The virtual device advertises a wide range of standard button codes (`0x100`–`0x11F`) to maximize compatibility.
- **Swallow a button:** `DISABLED_BTN` lets you completely disable a specific mouse button.
- **Chaining with other tools:** Feed another tool's virtual device (e.g. from input-remapper) into VeloScroll by pointing `NAME_MATCH` at the virtual node (set `DEVICE_MATCH` to `None`).

### 🔧 Debugging and maintenance

- **Latency logging:** Setting `LATENCY_LOG = true` emits per-second summary lines with measured latencies (input p50/p95/max, tick period, press→emit, crossing→emit, `uinput_write_max`) plus a theoretical model line at startup. See [Latency & debugging](documentation/ADVANCED.md#latency--debugging).
- **Log levels:** `LOG_LEVEL` (0–3) controls verbosity, from errors-only to debug.
- **Systemd service:** Ships with `veloscroll.service`, a root system unit for automatic restarts. Can also run standalone or as a per-user unit.
- **Hot-reload for device changes:** Switching mice requires no restart. The daemon applies the new `DEVICE_MATCH` within ~2 seconds and releases the old device automatically.
- **Backup system:** The preset helper and seed script create `.bak-<timestamp>` backups, with `MAX_BACKUPS` controlling how many are kept.
