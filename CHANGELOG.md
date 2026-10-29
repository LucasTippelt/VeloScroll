# Changelog

All notable changes to VeloScroll are documented in this file.

## [1.0] - 2026-10-29

Initial release.

### Added

#### Core daemon (`veloscroll.py`)

- Hold-button velocity scrolling: hold a configurable mouse button and moving the mouse scrolls at a speed proportional to distance from the press point; releasing restores normal mouse behavior.
- Compositor-independent operation via `/dev/input` (evdev) + `/dev/uinput`, so behavior is identical under X11, Wayland, and any desktop environment.
- Configurable velocity ramp: `DEADZONE_IN`, `FULL_IN`, `MIN_RATE`, `MAX_RATE`, `CURVE` (ramp shape), `OUT_SMOOTH` (rate smoothing), `TICK` (~250 Hz ticker).
- Optional horizontal velocity scrolling via a second hold button (`SCROLL_BTN_H`), emitting hi-res wheel events, with per-axis overrides (`DEADZONE_IN_H`, `FULL_IN_H`, `MIN_RATE_H`, `MAX_RATE_H`, `CURVE_H`) that fall back to the vertical values.
- `DISABLED_BTN`: optionally swallow a button so it does nothing. Not set by default.
- All other buttons pass through unchanged; the virtual device (`veloscroll-mouse`) advertises every standard mouse button code (0x100–0x11F: `BTN_MISC`/`BTN_0`–`BTN_9` through `BTN_TASK`) for maximum compatability.
- Device selection: `DEVICE_MATCH` (exact USB ID pair or stable path string) with `NAME_MATCH` as case-insensitive substring fallback; supports feeding another tool's virtual device (e.g. input-remapper), but this is currently untested.
- Supervisor loop with hotplug support: a matching device plugged in after startup is picked up within ~2 s, no restart needed; on grab failure the daemon logs `device busy` and keeps retrying until the device frees up.

#### Configuration & logging

- All configuration lives in `/etc/veloscroll/config.ini`, bundled as `config.ini.example`; every key hot-reloads within ~2 s and survives updates (local edits to `veloscroll.py` are not needed or supported).
- Two-layer config: a non-empty config.ini value overrides the built-in default; missing/empty keys fall back to defaults.
- `VELOSCROLL_CONFIG` environment variable override for tests / per-user setups.
- `LOG_LEVEL` 0–3 (errors → events → config detail → debug), hot-reloaded.
- `LATENCY_LOG`: optional per-second measured latency summary (`input p50/p95/max`, tick period, overruns, press→emit, crossing→emit, uinput write) plus a computed latency model line at startup/config change — see README "Latency & debugging".

#### systemd integration (`veloscroll.service`)

- Root system unit for automatic restarts (`Restart=on-failure`), installed to `/etc/systemd/system/`.
- Versioning added to the unit: `Description` now `Veloscroll v1.0 - hold-button velocity scrolling`, so the running unit's version is visible (e.g. via `systemctl status`). When a release changes this file, re-copy it into `/etc/systemd/system/` and run `sudo systemctl daemon-reload`.

#### Pointer-settings seed script (`veloscroll_seed.py`)

- One-shot helper that copies your real mouse's per-device pointer settings into the `veloscroll-mouse` virtual device (KDE Plasma Wayland backend), so it starts out feeling exactly like the real mouse; applies to a running session via KWin's D-Bus interface.
- Options: `--name <NAME>` (select the real mouse by name substring), `--apply-only` (push existing config without re-seeding), `--remove-stale-config` (delete stale `[…][veloscroll-mouse]` groups, writing a `.bak-*` backup first); all modes idempotent.
- Backups of changed `kcminputrc` files with an optional cap via the `MAX_BACKUPS` constant; seed-script constants (`DE_WM`, `VIRTUAL_NAME`, `MAX_BACKUPS`) intentionally kept out of config.ini.

#### Documentation & tuning

- README: TLDR, compatibility/permissions/caveats, dependencies, device & button discovery (with evdev snippets and keycode table), general installation guide, latency model + measured-metrics reference, troubleshooting table, switching mice, hot-reload rules with full key reference, manual update/rollback procedure.
- `TUNING.md`: five ready-to-paste feel presets for the four "feel" keys — Balanced (shipped default), Fast, Precise, Cruising, Snappy.
- Per-desktop guides: KDE Plasma 5/6 (`docs-desktop/kde-plasma.md`), GNOME / Fedora Workstation 44 (`docs-desktop/gnome.md`), Cinnamon (`docs-desktop/cinnamon.md`).
- Hardware notes with verified device IDs and side-button keycodes: Logitech PRO X (G Pro X Superlight) (`docs-hardware/logitech/Logitech_PRO_X.md`).
