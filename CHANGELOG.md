# Changelog

All notable changes to VeloScroll are documented in this file.

## [1.1] - 2026-10-30

### Added

#### Core daemon (`veloscroll.py`)

- `OUT_SMOOTH_H`: per-axis rate-follow speed for horizontal velocity scrolling; unset or `none` falls back to the vertical value, like every other `_H` key (the latency model stays vertical-only by design).
- `TOGGLE_SCROLL` / `TOGGLE_SCROLL_H`: per-axis choice of how SCROLL_BTN/SCROLL_BTN_H engages velocity scrolling — hold (default: button must stay pressed) or tap-to-toggle (tap to engage, tap again to disengage; releasing does nothing while toggled). While engaged the axis behaves exactly like a held session (cursor frozen, same ramp from the tap point, clamp at FULL[_H]). `TOGGLE_SCROLL_H` unset or `none` falls back to the vertical value, like every other `_H` key; hot-reloading either key resets any in-progress session instead of leaving a stuck latch.
- `VERTICAL_H`: optional second *vertical* scroll mode for SCROLL_BTN_H — when true, holding the button drives REL_WHEEL/REL_WHEEL_HI_RES from mouse up/down movement using the horizontal ramp values (`*_H` keys), and left/right movement is swallowed (cursor frozen); false (default) keeps today's behavior. `INVERT` flips it like every other axis; hot-reloading it mid-hold resets any in-progress session instead of leaving a stale accumulator behind.
- `MAX_BACKUPS` default changed from -1 (unlimited) to 5, so routine preset loads and seed runs no longer accumulate `.bak-*` backups forever — only the newest 5 per file family are kept. Affects both helper scripts (`veloscroll_preset.py`, `veloscroll_seed.py`); restore unlimited behavior by editing the `MAX_BACKUPS` constant in `veloscroll.py` (restart required, currently you need to set it in `veloscroll.py` with each update).
- Validation: `SCROLL_BTN` and `DISABLED_BTN` must now be different button codes — previously only the SCROLL_BTN_H conflicts were checked, so a shared code silently let scrolling win over the disable.

#### Preset helper (`veloscroll_preset.py`)

- New stdlib-only CLI helper for named presets of the 12 ramp keys: `save <name>` snapshots all 12 into `<config dir>/presets/<name>.ini` (horizontal keys only when explicitly set, so an unset axis keeps its vertical fallback); `loadfeel <name>` applies only the 8 feel keys present in the preset; `loadall <name>` additionally applies the physical distance keys (`DEADZONE_IN`/`FULL_IN` + `_H`) — routine preset swaps can't silently change a user's ramp distances.
- Presets now also carry the 2 scroll-mode flags: presets hold all 14 keys, with `TOGGLE_SCROLL` always captured and `TOGGLE_SCROLL_H` only when explicitly set in config.ini (same rule as every other `_H` key). The flags are loadall-only — `loadfeel` skips them like distance keys, so a feel preset can't silently switch how the button engages scrolling.
- `VERTICAL_H` joins the presets as the 15th key: captured by `save` only when explicitly set in config.ini (same rule as every other `_H` key), and loadall-only with the other scroll-mode flags — `loadfeel` skips it, so a feel preset can't silently switch what SCROLL_BTN_H does.
- Loads are pre-validated with the daemon's own parsing/validation (single source of truth via importing veloscroll), written atomically (temp file + `os.replace`) after a `config.ini.bak-<timestamp>` backup, and backups pruned per `MAX_BACKUPS` — the same knob as `veloscroll_seed.py`. Unknown preset keys are warned about and ignored; no-op loads write nothing.
- Recovery commands: `backups` lists every `.bak-<timestamp>` backup of the config and its presets (newest first); `restore [BACKUP]` puts one back over its original — default is the newest config.ini backup, otherwise any file name as listed or a path relative to the config dir. Restoring the live config passes the same pre-validation gate as a load, and every restore backs up the current state first (so undoing is itself reversible).
- Five bundled presets mirroring TUNING.md in `presets.example/` (balanced, fast, precise, cruising, snappy — the four vertical feel keys each); copy them into `/etc/veloscroll/presets/`.
- `save` now snapshots every daemon key (currently all 25), not just the ramp keys and scroll-mode flags: the button bindings (`SCROLL_BTN`/`SCROLL_BTN_H`/`DISABLED_BTN`) and device selection (`NAME_MATCH`/`DEVICE_MATCH`, incl. `DPI`) are captured too, so a preset can carry a complete machine profile.
- New per-group load commands alongside `loadfeel`: `loaddistances <name>` (the 4 distance keys), `loadkeys <name>` (the 3 button bindings), `loaddevice <name>` (`NAME_MATCH`/`DEVICE_MATCH`/`DPI`) and `loadscroll <name>` (the 3 scroll-mode flags); `loadall <name>` now applies everything present except the key and device groups. A load never touches keys outside its group — skipped keys are listed with the command that would apply them, so partial or older preset files work as-is with every command.
- Multiple operations in one invocation: any number of `COMMAND NAME` pairs (each with its own preset name) run in order, e.g. `veloscroll_preset.py loadfeel fast loaddistances quiet`; a failure stops the rest while earlier operations stay applied and undoable via `restore`.

#### Tuning aid (`veloscroll_tuning_helper.py`)

- New terminal tuning aid for the physical distance keys: with the daemon stopped it exclusively grabs every matching device (full daemon parity) plus a temporary UInput pass-through virtual mouse, and measures real hand movement per hold — in-place distance gauge with the would-be target rate (the daemon's exact ramp formula), a line each time you leave or re-enter the deadzone and each time you cross the full-rate boundary either way, plus a copy-pasteable release summary (elapsed time, peak distance in inches + counts). Movement below/left of the start point is printed negative with a direction label (`(downwards)`/`(upwards)`, `(leftwards)`/`(rightwards)` for horizontal holds without `VERTICAL_H`). No scroll is ever emitted; while held the cursor stays put, between holds the mouse behaves exactly as normal.
- Reads config.ini hot-reloadable like the daemon (1 s poller mirroring `_maybe_reload_config`): a live edit switches the thresholds mid-session (`config reloaded:` per key), a rejected edit keeps the old values; `--config PATH` overrides the config path like every other helper.

#### Device discovery helpers (`ListDeviceNames.py`, `ListButtonPresses.py`)

- Two standalone scripts replacing the inline snippets in the README's "Finding your device name & activation button" section: `ListDeviceNames.py` lists every `/dev/input/event*` node with its name and USB vendor/product ID pair (for reading off `DEVICE_MATCH`/`NAME_MATCH`; unopenable devices are skipped with a note), and `ListButtonPresses.py 30` opens `/dev/input/event30` (a full path works too) and prints every key event as `code value` while you press buttons, so activation button codes can be read off — movement/scroll events are filtered out, Ctrl-C stops cleanly.

#### Documentation

- README: new Presets section under "Customize & reload" (usage, per-group load semantics — distance/feel/key/device/scroll plus `loadall` and multi-operation invocations — backup/pruning behavior, optional scoped sudoers rule) and key-table rows for `TOGGLE_SCROLL`/`TOGGLE_SCROLL_H`/`VERTICAL_H`; TLDR and SCROLL_BTN_H docs mention the new modes; DE-agnostic shortcut binding guidance. New "Tuning aid: veloscroll_tuning_helper.py" section with the stop-daemon → measure → edit-config workflow and sample output. "Finding your device name & activation button" now calls the two discovery scripts instead of inline snippets.
- TUNING.md: `VERTICAL_H` note in the horizontal section. config.ini.example: logging/latency sections moved to end, comment cleanups, and a first-class `DISABLED_BTN = none` entry (previously only mentioned inside the SCROLL_BTN_H comment).


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
