# VeloScroll Presets

`veloscroll_preset.py` switches between named presets of the VeloScroll daemon keys without hand-editing `config.ini`.

`save <name>` snapshots every key into `<config dir>/presets/<name>.ini`. Each `load` command applies only its own group of keys. A load is an atomic, pre-validated rewrite of only that group's lines (comments and ordering are preserved), so the daemon's normal hot-reload picks it up within ~2 s.

## Contents

1. [Commands](#commands)
2. [Why loads are grouped](#why-loads-are-grouped)
3. [Preset files and bundled presets](#preset-files-and-bundled-presets)
4. [What `save` captures](#what-save-captures)
5. [Backups and recovery](#backups-and-recovery)
6. [Permissions](#permissions)
7. [Shortcut switching (optional)](#shortcut-switching-optional)

---

## Commands

Run them as `python3 /opt/veloscroll/veloscroll_preset.py <command> ...`.

> On a standard install run these as root (`sudo`, or the scoped sudoers rule under [Permissions](#permissions)). With a per-user `VELOSCROLL_CONFIG`, no root is needed.

| Command | Effect |
|---------|--------|
| `save <name>` | Snapshot every daemon key to `/etc/veloscroll/presets/<name>.ini` (`*_H` keys only when set in `config.ini`). |
| `loaddistances <name>` | Apply the physical distance keys present in the preset: `DEADZONE_IN` / `FULL_IN` + `_H`. |
| `loadfeel <name>` | Apply only the 8 feel keys: `MAX_RATE` / `MIN_RATE` / `CURVE` / `OUT_SMOOTH` + their `_H` variants. |
| `loadkeys <name>` | Apply the button bindings: `SCROLL_BTN` / `SCROLL_BTN_H` / `DISABLED_BTN`. |
| `loaddevice <name>` | Apply the device selection keys: `NAME_MATCH` / `DEVICE_MATCH` / `DPI`. |
| `loadscroll <name>` | Apply the scroll-mode flags: `TOGGLE_SCROLL` / `TOGGLE_SCROLL_H` / `VERTICAL_H`. |
| `loadall <name>` | Apply everything present **except** the button and device groups. |
| `list` | Table of every preset's values (absent = not captured). Make sure your terminal is wide enough for the table to render properly. |
| `backups` | Table of every `.bak-<timestamp>` backup, newest first. |
| `restore [BACKUP]` | Put a backup back over its original (default: the newest `config.ini` backup). |

Any number of `COMMAND NAME` pairs run in one invocation, each with its own preset name, applied in order:

```bash
sudo python3 /opt/veloscroll/veloscroll_preset.py loadfeel fast loaddistances quiet
```

---

## Why loads are grouped

Each load command applies only its own group, so one kind of swap can't silently change another machine's choices.

- The **distance keys** (`DEADZONE_IN` / `FULL_IN` + `_H`) describe your physical setup: how far you move the mouse.
- The **button bindings** and **device selection** are per-machine choices.
- A shared "fast" feel preset must not touch any of them, so routine swaps use `loadfeel`. Only an explicit `loaddistances` / `loadkeys` / `loaddevice` (or `loadall`, for the groups it covers) applies the others.
- The **scroll-mode flags** (`TOGGLE_SCROLL` / `TOGGLE_SCROLL_H` / `VERTICAL_H`) are grouped the same way via `loadscroll`.

A load that finds keys outside its group in the preset never applies them. It lists each one with the command that would, so a partial or older preset file works as-is.

You can chain multiple load groups and give each its own preset name, e.g.:

```bash
sudo python3 /opt/veloscroll/veloscroll_preset.py loadfeel fast loaddistances quiet loaddevice MyPreset loadscroll MyPreset
```

---

## Preset files and bundled presets

Preset files live in `<config dir>/presets/`: `/etc/veloscroll/presets/` by default, or next to your config when using `VELOSCROLL_CONFIG`.

The repo bundles the [`TUNING.md`](TUNING.md) cases as partial presets (the vertical feel keys each) in `presets.example/`. Install them with:

```bash
sudo mkdir -p /etc/veloscroll/presets
sudo cp /opt/veloscroll/presets.example/*.ini /etc/veloscroll/presets/
```

Partial and older preset files work as-is: a load only ever applies the keys that are actually present.

---

## What `save` captures

Every daemon key is written (the `config.ini` value, else the built-in default). The exception is `*_H` keys, which are written **only when explicitly set** in `config.ini`. That way an unset axis keeps its fallback-to-vertical relation on any machine, instead of baking a stale number into the preset.

This includes `VERTICAL_H`, `TOGGLE_SCROLL_H` and `SCROLL_BTN_H`: captured only when set, otherwise omitted, and each machine keeps its local value on load (an unset `SCROLL_BTN_H` leaves horizontal scrolling disabled).

Unknown keys in a preset file are warned about and ignored, like unknown `config.ini` keys.

---

## Backups and recovery

**Backups and pruning.** Each load that changes `config.ini` first writes `config.ini.bak-<timestamp>`. A save-overwrite backs up the preset file as `<name>.ini.bak-*`. Both families are pruned per `MAX_BACKUPS` (default 5), the same knob as `veloscroll_seed.py` (see [Advanced](ADVANCED.md#advanced-notes-not-needed-for-normal-use)). A no-op load (values already equal) writes nothing and makes no backup.

**Recovery.** `backups` lists every backup of the config and its presets. `restore [BACKUP]` puts one back over its original:

- with no argument, the newest `config.ini` backup,
- otherwise, any file name exactly as listed (or a path relative to the config dir).

Every restore backs up the current state first, so undoing is itself reversible.

---

## Permissions

`/etc/veloscroll` is root-owned, so on the standard install run the helper via `sudo`, or add a scoped passwordless rule for that one binary only (validate with `visudo -cf` before installing):

```
# /etc/sudoers.d/veloscroll-preset
Cmnd_Alias VELOSCROLL_PRESET = /opt/veloscroll/veloscroll_preset.py
<user> ALL=(root) NOPASSWD: VELOSCROLL_PRESET
```

This grants root for that single command only (any of its subcommands). With a per-user `VELOSCROLL_CONFIG` setup the helper needs no root at all.

---

## Shortcut switching (optional)

Bind a preset load to anything you can bind, press it, then verify with `journalctl -u veloscroll`. For example, set the command (or a short bash script) to:

```bash
/usr/bin/python3 /opt/veloscroll/veloscroll_preset.py loadfeel YourPresetName
```

Test it manually once, then bind it to your preferred keyboard shortcut however your desktop environment implements that.

---

**Next:** [Updating →](UPDATING.md) · [Advanced →](ADVANCED.md)
