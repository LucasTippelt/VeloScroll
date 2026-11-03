# VeloScroll

Variable-velocity scrolling for Linux mice: hold/click a button, move the mouse, and scroll at a speed proportional to how far you have moved from the press point.
**It has an entirely Opt-in Gui at https://github.com/LucasTippelt/VeloScroll-GUI.** This GUI acts as a convenient Frontend to configure the core VeloScroll daemon. It writes to the config file and reads from the new Runtime files `/run/veloscroll/state` and `/run/veloscroll/distance`(these only get written when explicitly set to true in config.ini, false by default).

## Documentation

All command-line only guides live in [`docs/`](docs/).
**You can either follow these or the README at https://github.com/LucasTippelt/VeloScroll-GUI.** That README covers the complete Installation of VeloScroll + VeloScroll GUI frontend, as well as Setup, Configuration and Preset management via the GUI.
If you prefer the CLI only Version, here is the suggested reading order:

1. [Install](docs/INSTALL.md): install, find your device and button, run as a service
2. [Configuration](docs/CONFIGURATION.md): every `config.ini` key and the tuning helper
3. [Presets](docs/PRESETS.md): save and switch named configurations

Reference:

- [Updating](docs/UPDATING.md): fetch a new release, restart, roll back
- [Advanced](docs/ADVANCED.md): fork-level constants and `veloscroll_seed.py` options
- [Testing](docs/TESTING.md): run the full pytest suite and what each test covers

Each guide in the reading order links to the next one at the bottom.

---

## Safety net: keep a second way to drive your mouse (strongly recommended)

VeloScroll exclusively grabs your physical mouse and replaces it with its own virtual one while it runs. That is reliable — but if it ever misbehaves (a bad config, a stuck session, an unusual device), you can temporarily lose normal mouse control while the daemon holds the grab. **Strongly advised: set up [KDE Connect](https://kdeconnect.kde.org/)** (or any similar remote-input app) on your phone *before* you start using VeloScroll, so you can send mouse clicks and movement over your local network as a fallback. If something goes wrong, a phone-driven cursor gets you back to a terminal or system settings fast — fixing whatever went wrong becomes much easier than rebooting blind.

- **KDE Connect:** install `kdeconnect` on the desktop and the KDE Connect app on your phone; pair them once and set up permissions for the remote-input feature, then use that whenever you need it.
- **Alternatives:** anything that injects mouse events from another device works — a cheap second USB/Bluetooth mouse, a remote-desktop session, or similar.

---

## Features

### 🖱️ Core scrolling mechanism

- **Variable-velocity scrolling:** While you hold a configured mouse button, moving the mouse scrolls at a speed proportional to your distance from the initial press point.
- **Configurable activation button:** Map any mouse button (not just the middle one) to trigger scrolling via `SCROLL_BTN`, using an evdev name like `BTN_SIDE` or a decimal code.
- **Hold or toggle mode:** By default you hold the button to scroll. Setting `TOGGLE_SCROLL = true` switches to tap-to-toggle (tap to start, tap again to stop).
- **Cursor lock during scroll:** While a scroll session is active, the cursor stays put and movement is consumed for velocity math rather than moving the pointer. Releasing the button restores normal behavior immediately — except while `BTN_LEFT` is held, which moves the cursor normally (click/drag works, e.g. text selection) with velocity output paused until it is released. On left release mid-session you can choose between a fresh origin (`LEFT_CLICK_RESET = true`, default: the next movement scrolls from zero again) or keeping the current distance so scrolling continues at its old speed (`LEFT_CLICK_RESET = false`).
- **Dual-axis support:** An optional second button (`SCROLL_BTN_H`) enables horizontal scrolling (driven by mouse X movement). With `VERTICAL_H = true` it acts as a second vertical scroll with its own curve, driven by mouse up/down movement — the bundled [`two-vertical`](presets.example/two-vertical.ini) preset is exactly that use case (slow-to-medium + medium-to-fast vertical), see [Presets](docs/PRESETS.md#two-vertical-modes-use-case).

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
- **Direction inversion:** `INVERT = true` flips the scroll direction (useful for natural scrolling); `INVERT_H` inverts just the H axis, falling back to `INVERT` when unset.
- **DPI-aware:** You set your mouse's current DPI so distance calculations (in inches) are accurate.
- **Ticker rate:** `TICK` (default `0.004` s ≈ 250 Hz) controls how often the scroll rate is recomputed and hi-res events are emitted.

See the [Configuration Guide](docs/CONFIGURATION.md) for the full key reference.

### 🎛️ Preset and workflow tools

- **Preset system (`veloscroll_preset.py`):** Save named snapshots of your configuration and load them back. Loads are grouped (`loadfeel`, `loaddistances`, `loadkeys`, `loaddevice`, `loadscroll`), so swapping a "feel" preset doesn't accidentally change your button bindings or device selection. Multiple load groups can be chained in one command. Root usage runs the deployed copy at `/usr/lib/veloscroll/veloscroll_preset.py`. See [Presets](docs/PRESETS.md).
- **Tuning assistant (`helpers/veloscroll_tuning_helper.py`):** With the daemon stopped, this script exclusively grabs your mouse and measures your actual hand movement. It prints an in-place distance gauge with the would-be target rate, helping you set `DEADZONE_IN` and `FULL_IN` from real distances instead of guesswork. Root usage runs the deployed copy at `/usr/lib/veloscroll/helpers/veloscroll_tuning_helper.py`.
- **Device discovery scripts (in `helpers/`):**
  - `ListDeviceNames.py`: lists all input devices with their USB IDs.
  - `ListButtonPresses.py`: prints every key event a device emits, so you can find the code for your activation button.

All helper scripts live in the [`helpers/`](helpers/) directory; only `veloscroll.py` and `veloscroll_preset.py` sit at the repo root.

### 🖥️ System integration and compatibility

- **Universal compatibility:** Works identically on X11 and Wayland, across GNOME, KDE, XFCE, Sway, i3 and others, because it operates below the compositor via `/dev/input` (evdev + uinput). Explicitly tested on Kubuntu 26.10 (Plasma 6.7.5 – X11 and Wayland),GNOME (Wayland) and Mint Cinnamon (X11).
- **Precise device selection:**
  - `DEVICE_MATCH`: the recommended selector, using an exact USB ID pair (e.g. `0x46d, 0xc084`) or a path like `/dev/input/by-id/...`. Stable across reboots and USB ports.
  - `NAME_MATCH`: a simpler fallback using a case-insensitive substring of the device name.
- **Virtual device (`veloscroll-mouse`):** VeloScroll creates a virtual mouse. On KDE Plasma (Wayland), a seeding script (`veloscroll_seed.py`) can copy your real mouse's per-device pointer settings to this virtual device, so it feels identical without opening system settings.
- **Button pass-through:** All other mouse buttons (side, extra, DPI, etc.) pass through as-is. The virtual device advertises a wide range of standard button codes (`0x100`–`0x11F`) to maximize compatibility.
- **Swallow a button:** `DISABLED_BTN` lets you completely disable a specific mouse button.
- **Chaining with other tools:** Feed another tool's virtual device (e.g. from input-remapper) into VeloScroll by pointing `NAME_MATCH` at the virtual node (set `DEVICE_MATCH` to `None`).

### 🔧 Debugging and maintenance

- **Latency logging:** Setting `LATENCY_LOG = true` emits per-second summary lines with measured latencies (input p50/p95/max, tick period, press→emit, crossing→emit, `uinput_write_max`) plus a theoretical model line at startup. See [Latency & debugging](docs/ADVANCED.md#latency--debugging).
- **Log levels:** `LOG_LEVEL` (0–3) controls verbosity, from errors-only to debug.
- **Systemd service:** Ships with `veloscroll.service`, a sandboxed root system unit for automatic restarts (hardened with protection directives and crash-loop start limits). It executes the *deployed* copy in `/usr/lib/veloscroll` — never the checkout: the repo is uniformly user-owned source, and new code reaches root only through an explicit deploy ([Installation](docs/INSTALL.md#installation) step 4, [Updating](docs/UPDATING.md)). Can also run standalone or as a per-user unit.
- **Hot-reload for device changes:** Switching mice requires no restart. The daemon applies the new `DEVICE_MATCH` within ~2 seconds and releases the old device automatically.
- **Backup system:** The preset helper and seed script create `.bak-<timestamp>` backups. `MAX_BACKUPS` in `config.ini` (hot-reloaded) controls the policy: `-1` = unlimited, `N ≥ 1` = keep only the newest N per file family, `0` = backups disabled entirely (no backup files are written; existing ones stay untouched).
