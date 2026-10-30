# VeloScroll Configuration Guide

## Contents

1. [Customize and reload](#customize-and-reload)
2. [config.ini keys (hot-reloaded)](#configini-keys-hot-reloaded)
3. [Starting points and presets](#starting-points-and-presets)
4. [Tuning aid: `veloscroll_tuning_helper.py`](#tuning-aid-veloscroll_tuning_helperpy)

---

## Customize and reload

**Do not edit `veloscroll.py` to change your settings.** Every daemon tunable can be set in `/etc/veloscroll/config.ini`, which is hot-reloaded within ~2 s and lives outside the repo, so your configuration survives updates. Local edits to `veloscroll.py` are lost (or conflict) on the next update, and require a manual restart anyway.

- **Two config sources:** per key, a non-empty value in `/etc/veloscroll/config.ini` overrides the built-in default at the top of `/opt/veloscroll/veloscroll.py`.
- **Supported way:** editing `/etc/veloscroll/config.ini` is the only supported way to configure the daemon.
- **Fallbacks:** a missing or empty key falls back to the built-in default. Every `config.ini` key exists in `veloscroll.py` as its fallback.

---

## config.ini keys (hot-reloaded)

Keys with an `_H` suffix are horizontal variants. Where noted, an unset or `none` value falls back to the vertical value.

### Device and buttons

| Key | Meaning / units | Tuning hint |
|-----|-----------------|-------------|
| `NAME_MATCH` | Case-insensitive substring of your mouse's name that selects it. Used only when `DEVICE_MATCH` is `None` (fallback). | Use a short unique fragment from the device list; if any other device shares it, prefer `DEVICE_MATCH`. Recommended if you want to pipe another virtual device into VeloScroll. |
| `DEVICE_MATCH` | Recommended precise selector for a physical device; overrides `NAME_MATCH`. An exact USB ID pair (`0x46d, 0xc084`) or a stable path string (e.g. `/dev/input/by-id/...`) for two identical mice. | Set it to your mouse's USB IDs: stable across reboots/ports, and lets per-device pointer rules apply automatically. See [Installation](INSTALL.md#installation), step 4. |
| `DPI` | Your mouse's current DPI (counts/inch). Converts inches to raw counts. | Set it to your mouse's current DPI setting, not its maximum. |
| `SCROLL_BTN` | Key code of the button to hold for scrolling (evdev name like `BTN_SIDE`, or decimal code, e.g. `275`). | Find it with `ListButtonPresses.py` (see [Installation](INSTALL.md#installation), step 5). Names are `evdev.ecodes.BTN_*`. |
| `SCROLL_BTN_H` | Optional second button to hold for velocity scrolling. By default horizontal, driven by mouse X movement (emits `REL_HWHEEL`/`REL_HWHEEL_HI_RES`), using the vertical ramp unless overridden by the `_H` keys. With `VERTICAL_H = true` it emits vertical wheel events from up/down movement instead, at the same `_H`-key values. Evdev name or decimal code, or `none` to disable (default). | Must differ from `SCROLL_BTN` and `DISABLED_BTN`. `INVERT` flips both axes; see the hardware docs for direction notes. |
| `DISABLED_BTN` | Key code that is swallowed and does nothing, or `none` to disable this feature. | Set `none` if you don't want to disable a button. |

### Engagement mode

| Key | Meaning / units | Tuning hint |
|-----|-----------------|-------------|
| `TOGGLE_SCROLL` | How `SCROLL_BTN` engages velocity scrolling. `False` (default) = hold-to-scroll, the button must stay pressed. `True` = tap to toggle on, tap again to toggle off (releasing does nothing while toggled). | While toggled on, movement is captured exactly as in hold mode (cursor stays put, same ramp from the tap point). Set `true` if you prefer a latched scroll mode over holding. |
| `TOGGLE_SCROLL_H` | Horizontal variant of `TOGGLE_SCROLL` for `SCROLL_BTN_H`. Unset or `none` falls back to the vertical value. | Only if horizontal scrolling should use a different engagement mode than vertical (e.g. hold vertically, toggle horizontally). |
| `VERTICAL_H` | `True`/`False`. With `true`, holding `SCROLL_BTN_H` becomes a second vertical velocity scroll instead of horizontal: mouse up/down movement drives `REL_WHEEL`/`REL_WHEEL_HI_RES` using the horizontal ramp values (`*_H` keys), and left/right movement does nothing. `false` (default) = horizontal behavior. | Only takes effect when `SCROLL_BTN_H` is set. `INVERT` flips it like every other axis. Flipping it live mid-hold ends any in-progress session. |

### Scroll ramp (vertical)

| Key | Meaning / units | Tuning hint |
|-----|-----------------|-------------|
| `DEADZONE_IN` | Distance from the press point (inches) below which nothing scrolls. | Raise if scrolling starts before you've moved the mouse at all. |
| `FULL_IN` | Distance (inches) from the press point where `MAX_RATE` is reached. Must be > `DEADZONE_IN`. | The span over which speed ramps up. |
| `MAX_RATE` | Scroll rate in notches/second at `FULL_IN` and beyond. | Your top scrolling speed. |
| `MIN_RATE` | Scroll rate in notches/second just past the deadzone. | The floor of the ramp; keep above 0. |
| `CURVE` | Shape of the speed ramp: `>1` gentle near the start, `=1` linear, `<1` steep near the start. | Tune feel: `<1` reacts fast to small movements, `>1` is more forgiving. |
| `OUT_SMOOTH` | `0..1`: how quickly the rate follows the target. Lower = smoother, higher = snappier. | Lower it if scrolling feels steppy or jumpy. |

### Scroll ramp (horizontal variants)

Used only while `SCROLL_BTN_H` is held.

| Key | Meaning / units | Tuning hint |
|-----|-----------------|-------------|
| `DEADZONE_IN_H` | Horizontal variant of `DEADZONE_IN` (inches). Unset or `none` falls back to the vertical value. | Only if horizontal scrolling should start at a different distance than vertical. |
| `FULL_IN_H` | Horizontal variant of `FULL_IN`. Must be greater than the effective horizontal deadzone (per-key fallback). | The span over which horizontal speed ramps up. |
| `MAX_RATE_H` | Horizontal variant of `MAX_RATE`. Must be >= the effective horizontal `MIN_RATE`. | Your top horizontal scrolling speed. |
| `MIN_RATE_H` | Horizontal variant of `MIN_RATE` (notches/second). Unset or `none` falls back to the vertical value. | The floor of the horizontal ramp; keep > 0. |
| `CURVE_H` | Horizontal variant of `CURVE` (ramp shape). Unset or `none` falls back to the vertical value. | Same semantics as `CURVE`. |
| `OUT_SMOOTH_H` | Horizontal variant of `OUT_SMOOTH`. Unset or `none` falls back to the vertical value. | Same semantics as `OUT_SMOOTH`: how quickly the horizontal rate follows. |

### Direction and timing

| Key | Meaning / units | Tuning hint |
|-----|-----------------|-------------|
| `INVERT` | `True`/`False`. Flip scroll direction. | Set `true` if your DE has "natural scrolling" enabled. |
| `TICK` | Ticker loop period in seconds; `0.004` s ≈ 250 Hz. How often the scroll rate is recomputed and hi-res events are emitted. | Not a feel setting (that's `OUT_SMOOTH`/`MAX_RATE`). Only lower it if scrolling still looks steppy, at the cost of more CPU. |

### Logging and debugging

| Key | Meaning / units | Tuning hint |
|-----|-----------------|-------------|
| `LOG_LEVEL` | What the daemon writes to its log (`journalctl -u veloscroll`). Integer `0..3`, higher = more verbose: `0` errors only, `1` + events (`grabbed …`), `2` + config detail (default: unknown keys ignored, reload rejected, config reloaded old→new), `3` + debug. | Set `0` on a healthy system for silence; raise to `3` temporarily when debugging device selection. Lowering below `2` also hides the `config reloaded:` confirmation line itself. |
| `LATENCY_LOG` | `True`/`False`. Per-second measured latency summary lines plus a computed model line at startup/config change. Independent of `LOG_LEVEL` (see [Latency & debugging](ADVANCED.md#latency--debugging)). | Debugging only: set `true`, watch `journalctl -u veloscroll`, then leave it `false`. |

### Backups (helper scripts)

| Key | Meaning / units | Tuning hint |
|-----|-----------------|-------------|
| `MAX_BACKUPS` | How many `.bak-<timestamp>` backups the preset helper (`config.ini.bak-*`, `<name>.ini.bak-*`) and the seed script (`kcminputrc.bak-*`) keep per file family. `-1` = unlimited, `N ≥ 1` = keep only the newest N after each run that writes a backup, `0` = backups disabled entirely (no backup files are written; existing ones stay untouched). | Hot-reloaded like every other key — each helper run reads the current value. Set `0` if you don't want any `.bak-*` files at all (note: with `0`, `restore` no longer backs up the state it overwrites — see [Presets → Backups and recovery](PRESETS.md#backups-and-recovery)). |

---

## Starting points and presets

For `MAX_RATE` / `MIN_RATE` / `CURVE` / `OUT_SMOOTH`, [`TUNING.md`](TUNING.md) has ready-to-paste value sets by use case: **balanced**, **fast**, **precise**, **cruising**, **snappy**, **firefox**.

They hot-reload like every other key: edit `/etc/veloscroll/config.ini`, and the change applies live within ~2 s. Verify with:

```bash
journalctl -u veloscroll
```

Or apply a preset in one command with the preset helper (see the [Presets guide](PRESETS.md)).

---

## Tuning aid: `veloscroll_tuning_helper.py`

`veloscroll_tuning_helper.py` measures your actual hand movement so you can set the physical distance keys (`DEADZONE_IN`/`FULL_IN` + `_H`) from real distances instead of guesswork, and sanity-check `DPI`, `MAX_RATE`, `MIN_RATE` and `CURVE`.

With the daemon stopped, it exclusively grabs the configured mouse (all matching devices, full daemon parity). Each hold prints:

- an in-place distance gauge with the would-be target rate (the daemon's exact ramp formula),
- a line each time you leave or re-enter the deadzone, and each time you cross the full-rate boundary in either direction,
- a copy-pasteable release summary.

### Workflow

```bash
sudo systemctl stop veloscroll
sudo python3 /opt/veloscroll/helpers/veloscroll_tuning_helper.py   # --config PATH for a per-user config
# hold the scroll button and move; read the milestone + summary lines
# set DEADZONE_IN / FULL_IN (+ _H) in /etc/veloscroll/config.ini to your liking
# the helper also hot-reloads config.ini, so you can set -> test in one workflow
sudo systemctl start veloscroll
```

### Notes

- The gauge (`[v] … | target N notches/s`) updates in place while you hold or are toggled. The `[h]` lines work the same for `SCROLL_BTN_H` (mouse X movement, or up/down with `VERTICAL_H = true`).
- The helper never starts or stops the daemon and never emits scroll.
- If the grab fails with `device busy`, stop whatever else holds the mouse (usually the daemon) first, then re-run the helper.

---

**Next:** [Presets →](PRESETS.md)
