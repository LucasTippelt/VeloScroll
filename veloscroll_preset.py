#!/usr/bin/env python3

# VeloScroll — named presets of the veloscroll daemon keys (save + per-group loads loaddistances / loadfeel / loadkeys / loaddevice / loadscroll / loadall, plus list / backups / restore)
# Copyright (C) 2026 Lucas Tippelt
# SPDX-License-Identifier: GPL-3.0-or-later
# Full license: https://www.gnu.org/licenses/gpl-3.0.html
#
# One-shot helper for switching between named presets without hand-editing
# /etc/veloscroll/config.ini — a load is just an atomic, pre-validated rewrite of that
# group's key lines (comments and ordering preserved), and the daemon hot-reloads within ~2 s:
#
#     veloscroll_preset.py save <name>         snapshot every daemon key -> <config dir>/presets/<name>.ini (*_H keys only when set in config.ini)
#     veloscroll_preset.py loaddistances <n>   apply the physical distance keys (DEADZONE_IN / FULL_IN + _H) present in the preset
#     veloscroll_preset.py loadfeel <n>        apply only the 8 feel keys (MAX_RATE / MIN_RATE / CURVE / OUT_SMOOTH + their _H variants)
#     veloscroll_preset.py loadkeys <n>        apply the button bindings (SCROLL_BTN / SCROLL_BTN_H / DISABLED_BTN)
#     veloscroll_preset.py loaddevice <n>      apply the device selection keys (NAME_MATCH / DEVICE_MATCH / DPI)
#     veloscroll_preset.py loadscroll <n>      apply the scroll-mode flags (TOGGLE_SCROLL / TOGGLE_SCROLL_H / VERTICAL_H)
#     veloscroll_preset.py loadall <n>         apply everything present except the button and device groups
#     veloscroll_preset.py list                table of every preset's values
#     veloscroll_preset.py backups             table of every .bak-<timestamp> backup (config + presets), newest first
#     veloscroll_preset.py restore [BACKUP]    put a backup back over its original (default: the newest config.ini backup)
#
# Any number of `COMMAND NAME` pairs run in one invocation, each with its own preset name and applied in order:
#     veloscroll_preset.py loadfeel fast loaddistances quiet
# list / backups / restore run alone. A load never touches keys outside its group — the distance keys describe your
# physical setup and the button/device groups are per-machine choices, so a shared feel preset can't silently change
# them; every skipped key is noted together with the command that would apply it. Writes are pre-validated with
# the daemon's own parsing/validation (imported from veloscroll — single source of truth),
# backed up (<file>.bak-<timestamp>), pruned per MAX_BACKUPS (same knob as veloscroll_seed.py),
# and applied atomically (temp file + os.replace). A load whose merged values already match
# the current config writes nothing. Any overwrite can be undone with `restore` — which itself
# backs up first, so undoing is also reversible.
#
# Run as root for /etc/veloscroll (optionally via a scoped NOPASSWD sudoers rule — see
# README "Presets"), or as your user with VELOSCROLL_CONFIG pointing at a per-user config,
# where no root is needed at all.

import argparse
import configparser
import glob
import os
import re
import shutil
import sys
from datetime import datetime

NAME_RE = re.compile(r"[A-Za-z0-9._-]+")   # preset name == file name; blocks path traversal by construction (no separators allowed)
BAK_RE = re.compile(r"^(?P<orig>.+)\.bak-(?P<ts>\d{8}-\d{6}\d{6})$")   # well-formed backup name == exactly what _backup() writes; fixed-width timestamp, so lexicographic == chronological

# The five loadable key groups; `save` snapshots every daemon key (veloscroll.DAEMON_KEYS), and each load command applies only its own group.
# A new veloscroll.py key lands in `loadall` automatically — move it into a group here if it should get its own command too.
FEEL_KEYS = ("MAX_RATE", "MIN_RATE", "CURVE", "OUT_SMOOTH",
             "MAX_RATE_H", "MIN_RATE_H", "CURVE_H", "OUT_SMOOTH_H")        # the 8 feel keys — loadfeel
DISTANCE_KEYS = ("DEADZONE_IN", "FULL_IN", "DEADZONE_IN_H", "FULL_IN_H")  # physical setup (mouse travel) — loaddistances
KEY_KEYS = ("SCROLL_BTN", "SCROLL_BTN_H", "DISABLED_BTN")                 # button bindings — loadkeys
DEVICE_KEYS = ("NAME_MATCH", "DEVICE_MATCH", "DPI")                       # which device + its DPI — loaddevice
SCROLL_MODE_KEYS = ("TOGGLE_SCROLL", "TOGGLE_SCROLL_H", "VERTICAL_H")     # scroll-mode flags — loadscroll

LOAD_GROUPS = {"loaddistances": DISTANCE_KEYS, "loadfeel": FEEL_KEYS, "loadkeys": KEY_KEYS,
               "loaddevice": DEVICE_KEYS, "loadscroll": SCROLL_MODE_KEYS}  # command -> the keys it applies (canonical order)
LOADALL_EXCLUDED = set(KEY_KEYS) | set(DEVICE_KEYS)                        # `loadall` = every daemon key except these two groups


class PresetError(Exception):
    """Failure surfaced as a one-line stderr message (exit 1); no files are written."""


class UsageError(Exception):
    """Malformed command line; reported before any import or file access."""


def _fmt(value):
    if value is None:
        return "none"
    if isinstance(value, tuple):       # DEVICE_MATCH vendor/product pair -> hex like config.ini.example ("0x12d, 0x3456"); the daemon parses it back to the same tuple
        v, p = value
        return f"0x{v:x}, 0x{p:x}"
    return str(value)


def _preset_dir(config_path):
    # presets always live next to the active config (/etc/veloscroll/presets by default; <config dir>/presets under VELOSCROLL_CONFIG / --config)
    return os.path.join(os.path.dirname(os.path.abspath(config_path)), "presets")


def _check_max_backups(vs):
    # validated before any write: an invalid value must never leave a backup behind (mirrors the seed's pruner check)
    mb = vs.MAX_BACKUPS
    if not isinstance(mb, int) or mb == 0 or mb < -1:
        raise PresetError(f"invalid MAX_BACKUPS {mb!r} — use -1 (unlimited) or a positive number of backups to keep")


def _prune_backups(path, max_backups):
    """Keep only the newest `max_backups` files named `<basename>.bak-*` next to path; return deleted names. -1 = unlimited.

    Duplicated from veloscroll_seed._prune_backups (veloscroll_seed.py:185) so this helper stays self-contained."""
    if not isinstance(max_backups, int) or max_backups == 0 or max_backups < -1:
        raise PresetError(f"invalid MAX_BACKUPS {max_backups!r} — use -1 (unlimited) or a positive number of backups to keep")
    if max_backups < 0:
        return []
    prefix = os.path.basename(path) + ".bak-"
    # fixed-width timestamps sort lexicographically == chronologically; oldest first
    candidates = sorted(glob.glob(os.path.join(os.path.dirname(path), prefix + "*")))
    pruned = []
    for f in candidates[: max(0, len(candidates) - max_backups)]:
        try:
            os.remove(f)
        except OSError as exc:
            raise PresetError(f"could not delete old backup {f}: {exc}") from exc
        pruned.append(os.path.basename(f))
    return pruned


def _pruned_note(pruned, max_backups):
    # make the reason explicit: these files were deleted because MAX_BACKUPS caps how many backups are kept
    return ", ".join(pruned) + f" — deleted because MAX_BACKUPS={max_backups} keeps only the newest {max_backups} backup(s)"


def _backup(path):
    # %f keeps rapid successive writes (keybinding-driven loads within one second) in distinct backups; still fixed-width, so lexicographic == chronological
    bak = path + ".bak-" + datetime.now().strftime("%Y%m%d-%H%M%S%f")
    shutil.copy2(path, bak)
    return bak


def _backup_files(config_path):
    """Every well-formed .bak-<timestamp> file next to config.ini or in its presets/ dir, newest first."""
    found = []
    for d in (os.path.dirname(os.path.abspath(config_path)), _preset_dir(config_path)):
        try:
            entries = os.listdir(d)
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise PresetError(f"cannot read {d}: {exc}") from exc
        for e in entries:
            m = BAK_RE.match(e)
            if m and os.path.isfile(os.path.join(d, e)):
                found.append((m.group("ts"), os.path.join(d, e)))
    return [p for _, p in sorted(found, reverse=True)]


def _resolve_backup(vs, ref):
    """Resolve a restore reference to exactly one existing backup file. No ref = newest backup of the live config."""
    all_b = _backup_files(vs.CONFIG_PATH)
    base_dir = os.path.dirname(os.path.abspath(vs.CONFIG_PATH))
    if ref is None:
        cands = [p for p in all_b if os.path.dirname(p) == base_dir and os.path.basename(p).startswith(os.path.basename(vs.CONFIG_PATH) + ".bak-")]
        if not cands:
            raise PresetError(f"no backups of {vs.CONFIG_PATH} found (created automatically before every overwrite by the save / load commands)")
        return cands[0]                                    # newest first
    if os.sep in ref:                                       # explicit path relative to the config dir
        p = os.path.normpath(os.path.join(base_dir, ref))
        allowed = {base_dir, _preset_dir(vs.CONFIG_PATH)}
        if os.path.dirname(p) not in allowed or not BAK_RE.match(os.path.basename(p)) or not os.path.isfile(p):
            raise PresetError(f"no such backup: {ref} (must be a .bak-<timestamp> file in the config dir or its presets/ subdir)")
        return p
    cands = [p for p in all_b if os.path.basename(p) == ref]
    if not cands:
        raise PresetError(f"no backup named {ref!r} (see `veloscroll_preset.py backups`)")
    if len(cands) > 1:
        raise PresetError(f"{ref!r} is ambiguous — matches: " + "; ".join(os.path.relpath(p, base_dir) for p in cands))
    return cands[0]


def _atomic_write(path, text):
    """Write via temp file + os.replace in the same directory: the daemon (mtime+size hot-reload) never parses a partial file."""
    d = os.path.dirname(os.path.abspath(path))
    tmp = os.path.join(d, "." + os.path.basename(path) + f".tmp-{os.getpid()}")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
        if os.path.exists(path):      # keep the original file's mode after replace (a root-owned config.ini stays root-owned)
            os.chmod(tmp, os.stat(path).st_mode & 0o7777)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):       # cleanup on failure only — a successful replace already moved tmp away
            try:
                os.remove(tmp)
            except OSError:
                pass


def _read_ini_keys(path):
    """The [veloscroll] keys of an ini file as {key: raw value}; {} when the file or section is missing."""
    cp = configparser.ConfigParser(interpolation=None)
    cp.optionxform = str              # keys are exact Python names (MAX_RATE, ...)
    try:
        with open(path, "r", encoding="utf-8") as f:
            cp.read_string(f.read())
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise PresetError(f"cannot read {path}: {exc}") from exc
    except configparser.Error as exc:
        raise PresetError(f"malformed INI in {path}: {exc}") from exc
    if not cp.has_section("veloscroll"):
        return {}
    return dict(cp["veloscroll"].items())


def _rewrite_config_lines(text, updates, key_order):
    """Rewrite only the `KEY = ...` lines of `updates` inside [veloscroll] — line-based (preserves comments/ordering; not a configparser round-trip); absent keys are appended at section end in key_order. Returns the new full text."""
    lines = text.split("\n") if text.strip() else []     # lossless: "\n".join(lines) == text for non-empty files
    sec = next((i for i, line in enumerate(lines) if line.strip() == "[veloscroll]"), None)
    end = len(lines)
    if sec is not None:                                  # the section ends at the next [header] or EOF
        for j in range(sec + 1, len(lines)):
            s = lines[j].strip()
            if s.startswith("[") and s.endswith("]"):
                end = j
                break
    else:                                                # no [veloscroll] section (or empty file): create it at the end
        lines += ([""] if lines else []) + ["[veloscroll]"]
        sec, end = len(lines) - 1, len(lines)
    for key in (k for k in key_order if k in updates):     # daemon registry order -> deterministic appended order
        pat = re.compile(rf"^(\s*){re.escape(key)}\s*=.*$")
        idx = next((j for j in range(sec + 1, end) if pat.match(lines[j])), None)
        if idx is not None:
            lines[idx] = f"{pat.match(lines[idx]).group(1)}{key} = {updates[key]}"
        else:
            lines.insert(end, f"{key} = {updates[key]}")
            end += 1
    if lines and lines[-1] != "":
        lines.append("")                                 # keep a trailing newline
    return "\n".join(lines)


def _current_values(vs):
    """Effective values for all daemon keys (built-in defaults overlaid with config.ini at import time)."""
    return {k: getattr(vs, k) for k in vs.DAEMON_KEYS}


def cmd_save(vs, name):
    """Snapshot every daemon key into presets/<name>.ini; *_H keys (incl. VERTICAL_H/TOGGLE_SCROLL_H/SCROLL_BTN_H) only when explicitly set in config.ini."""
    _check_max_backups(vs)
    preset_dir = _preset_dir(vs.CONFIG_PATH)
    preset_path = os.path.join(preset_dir, name + ".ini")
    current = _current_values(vs)
    ini_keys = _read_ini_keys(vs.CONFIG_PATH)     # which *_H keys are explicitly present (non-empty) in config.ini

    body, captured_h = [], []
    for key in vs.DAEMON_KEYS:
        if key.endswith("_H"):
            raw = ini_keys.get(key, "").strip()
            if not raw:                            # unset _H key stays local to each machine instead of baking a stale value (ramp keys fall back to vertical; TOGGLE_SCROLL_H/VERTICAL_H keep their local values / defaults)
                continue
            captured_h.append(key)
        body.append(f"{key} = {_fmt(current[key])}")

    text = (f"# VeloScroll preset '{name}' — created by veloscroll_preset.py save "
            f"(all {len(vs.DAEMON_KEYS)} daemon keys; *_H keys only when set in config.ini)\n"
            f"[veloscroll]\n" + "\n".join(body) + "\n")

    try:
        with open(preset_path, "r", encoding="utf-8") as f:
            existing = f.read()
    except FileNotFoundError:
        existing = None
    if existing == text:
        print(f"no change — {preset_path} already matches the current config")
        return 0

    backup_path = _backup(preset_path) if existing is not None else None
    pruned = _prune_backups(preset_path, vs.MAX_BACKUPS) if backup_path else []
    os.makedirs(preset_dir, exist_ok=True)
    _atomic_write(preset_path, text)

    print(f"saved {preset_path} ({len(body)} keys)")
    if backup_path:
        print(f"backup     : {backup_path}")
    if pruned:
        print("pruned     : " + _pruned_note(pruned, vs.MAX_BACKUPS))
    omitted_h = [k for k in vs.DAEMON_KEYS if k.endswith("_H") and k not in captured_h]
    if omitted_h:
        print("keys not set in config.ini (omitted — each machine keeps its own value on load; unset *_H ramp keys fall back to their vertical counterparts, TOGGLE_SCROLL_H/VERTICAL_H keep their local values / defaults, an unset SCROLL_BTN_H leaves horizontal scrolling disabled locally): " + ", ".join(omitted_h))
    return 0


def _covering_cmds(skipped):
    """The load commands that would apply each skipped key — canonical group order first, then `loadall` for keys outside every named group (INVERT/TICK/LOG_LEVEL/LATENCY_LOG)."""
    group_of = {}
    for cmd, keys in LOAD_GROUPS.items():
        for k in keys:
            group_of[k] = cmd
    out = [cmd for cmd in LOAD_GROUPS if any(group_of.get(k) == cmd for k in skipped)]
    if any(k not in group_of and k not in LOADALL_EXCLUDED for k in skipped):
        out.append("loadall")
    return out


def _cmd_load(vs, name, cmd, keys):
    """Apply the `keys` present in preset <name> to config.ini; command `cmd` never touches keys outside its group."""
    _check_max_backups(vs)
    preset_path = os.path.join(_preset_dir(vs.CONFIG_PATH), name + ".ini")
    try:
        with open(preset_path, "r", encoding="utf-8") as f:
            preset_text = f.read()
    except FileNotFoundError:
        raise PresetError(f"no preset named '{name}' at {preset_path} (see `veloscroll_preset.py list`)")

    cp = configparser.ConfigParser(interpolation=None)
    cp.optionxform = str
    try:
        cp.read_string(preset_text)
    except configparser.Error as exc:
        raise PresetError(f"malformed INI in {preset_path}: {exc}") from exc

    keyset = set(keys)
    base = _current_values(vs)                      # dict(_DEFAULTS) <- current config.ini values (import-time overlay)
    merged = dict(base)
    skipped, unknown = [], []
    for key, raw in (cp["veloscroll"].items() if cp.has_section("veloscroll") else ()):
        if key not in vs.DAEMON_KEYS:
            unknown.append(key)                     # forward-compat: warn + ignore, like the daemon does with config.ini keys (veloscroll.py:177)
            continue
        raw = raw.strip()
        if not raw:                                 # empty value = not captured
            continue
        try:
            value = vs._parse_ini_value(key, raw)   # same parse rules as the daemon — no duplicated logic
        except vs.ConfigError as exc:
            raise PresetError(f"{preset_path}: {exc}") from exc
        if key not in keyset:                       # present in the preset but outside this command's group — never applied silently
            skipped.append(key)
            continue
        merged[key] = value

    for key in unknown:
        print(f"warning: unknown key {key} in {preset_path} — ignored", file=sys.stderr)
    if skipped:
        hints = " / ".join(f"`veloscroll_preset.py {c} {name}`" for c in _covering_cmds(skipped))
        print(f"note: keys present in '{name}' that {cmd} does not apply: " + ", ".join(skipped) + f" — use {hints} to apply them")

    errors = vs.check_config(merged)                # same validation as the daemon's hot-reload — a rejected reload can never happen
    if errors:
        raise PresetError(f"{preset_path} does not validate against the current config: " + "; ".join(errors))

    changes = [(k, base[k], merged[k]) for k in vs.DAEMON_KEYS if base[k] != merged[k]]
    if not changes:
        print(f"no change — {vs.CONFIG_PATH} already matches preset '{name}' ({cmd})")
        return 0

    try:
        with open(vs.CONFIG_PATH, "r", encoding="utf-8") as f:
            text = f.read()
    except FileNotFoundError:
        text = ""
    new_text = _rewrite_config_lines(text, {k: _fmt(v) for k, _, v in changes}, vs.DAEMON_KEYS)

    backup_path = _backup(vs.CONFIG_PATH) if os.path.exists(vs.CONFIG_PATH) else None
    pruned = _prune_backups(vs.CONFIG_PATH, vs.MAX_BACKUPS) if backup_path else []
    _atomic_write(vs.CONFIG_PATH, new_text)

    print(f"applied preset '{name}' ({cmd}) to {vs.CONFIG_PATH}")
    for key, old, new in changes:
        print(f"{key}: {_fmt(old)} -> {_fmt(new)}")
    if backup_path:
        print(f"backup     : {backup_path}")
    if pruned:
        print("pruned     : " + _pruned_note(pruned, vs.MAX_BACKUPS))
    print("the daemon applies the change within ~2 s — verify with: journalctl -u veloscroll")
    return 0


def cmd_list(vs):
    preset_dir = _preset_dir(vs.CONFIG_PATH)
    try:
        entries = os.listdir(preset_dir)
    except FileNotFoundError:
        print(f"no presets found in {preset_dir} (create one with `veloscroll_preset.py save <name>`)")
        return 0
    except OSError as exc:
        raise PresetError(f"cannot read {preset_dir}: {exc}") from exc
    names = sorted(e[:-4] for e in entries
                   if e.endswith(".ini") and os.path.isfile(os.path.join(preset_dir, e)) and NAME_RE.fullmatch(e[:-4]))
    if not names:
        print(f"no presets found in {preset_dir} (create one with `veloscroll_preset.py save <name>`)")
        return 0

    values = {}
    for n in names:
        raws = _read_ini_keys(os.path.join(preset_dir, n + ".ini"))
        values[n] = {k: v.strip() for k, v in raws.items()}

    def cell(n, c):
        return values[n].get(c) or "-"

    name_w = max([len("preset")] + [len(n) for n in names])
    cols = [(c, max([len(c)] + [len(cell(n, c)) for n in names])) for c in vs.DAEMON_KEYS]
    print(f"{'preset':<{name_w}}" + "".join(f" {c:<{w}}" for c, w in cols))
    for n in names:
        print(f"{n:<{name_w}}" + "".join(f" {cell(n, c):<{w}}" for c, w in cols))
    print("(absent = not captured; an unset *_H key falls back to its vertical counterpart or local default on load)")
    return 0


def cmd_backups(vs):
    """Table of every .bak-<timestamp> backup next to the config or in its presets/ dir, newest first."""
    base_dir = os.path.dirname(os.path.abspath(vs.CONFIG_PATH))
    files = _backup_files(vs.CONFIG_PATH)
    if not files:
        print("no backups found (created automatically before every overwrite by the save / load commands)")
        return 0
    rows = []
    for p in files:
        orig = BAK_RE.match(os.path.basename(p)).group("orig")
        rel_target = os.path.relpath(os.path.join(os.path.dirname(p), orig), base_dir)
        mtime = datetime.fromtimestamp(os.path.getmtime(p)).strftime("%Y-%m-%d %H:%M:%S")
        rows.append((os.path.basename(p), rel_target, mtime, str(os.path.getsize(p))))
    headers = ("backup", "target", "modified", "size")
    widths = [max(len(h), max(len(r[i]) for r in rows)) for i, h in enumerate(headers)]
    print(" ".join(f"{h:<{w}}" for h, w in zip(headers, widths)))
    for row in rows:
        print(" ".join(f"{c:<{w}}" for c, w in zip(row, widths)))
    return 0


def cmd_restore(vs, ref=None):
    """Put a .bak-<timestamp> file back over its original. No ref = newest backup of the live config."""
    _check_max_backups(vs)
    bak = _resolve_backup(vs, ref)
    target = os.path.join(os.path.dirname(bak), BAK_RE.match(os.path.basename(bak)).group("orig"))

    try:
        with open(bak, "r", encoding="utf-8") as f:
            text = f.read()
    except OSError as exc:
        raise PresetError(f"cannot read {bak}: {exc}") from exc

    cp = configparser.ConfigParser(interpolation=None)
    cp.optionxform = str
    try:
        cp.read_string(text)
    except configparser.Error as exc:
        raise PresetError(f"{bak} is not a valid INI file — refusing to restore it: {exc}") from exc

    if target == os.path.abspath(vs.CONFIG_PATH):
        # restoring the live config gets the same pre-validation gate as a load — a rejected reload can never happen
        merged = _current_values(vs)
        unknown = []
        for key, raw in (cp["veloscroll"].items() if cp.has_section("veloscroll") else ()):
            if key not in vs.DAEMON_KEYS:
                unknown.append(key)
                continue
            raw = raw.strip()
            if not raw:                                   # empty value = not captured
                continue
            try:
                merged[key] = vs._parse_ini_value(key, raw)   # same parse rules as the daemon — no duplicated logic
            except vs.ConfigError as exc:
                raise PresetError(f"{bak}: {exc}") from exc
        for key in unknown:
            print(f"warning: unknown key {key} in {bak} — ignored", file=sys.stderr)
        errors = vs.check_config(merged)
        if errors:
            raise PresetError(f"refusing to restore {bak} over {vs.CONFIG_PATH} — it does not validate against the current config: " + "; ".join(errors))

    backup_path = _backup(target) if os.path.exists(target) else None   # a restore is itself undoable
    pruned = _prune_backups(target, vs.MAX_BACKUPS) if backup_path else []
    _atomic_write(target, text)

    print(f"restored {target} from {bak}")
    if backup_path:
        print(f"backup of previous state: {backup_path}")
    if pruned:
        print("pruned     : " + _pruned_note(pruned, vs.MAX_BACKUPS))
    if target == os.path.abspath(vs.CONFIG_PATH):
        print("the daemon applies the change within ~2 s — verify with: journalctl -u veloscroll")
    return 0


def _parse_ops(ops):
    """Split the argv operations into (mode, payload). Modes 'list'/'backups'/'restore' run alone; anything else is a list of (command, name) pairs applied in order. Raises UsageError on a malformed invocation."""
    if ops[0] in ("list", "backups"):
        if len(ops) != 1:
            raise UsageError(f"`{ops[0]}` takes no arguments — run it alone")
        return ops[0], None
    if ops[0] == "restore":
        if len(ops) > 2:
            raise UsageError("`restore` takes at most one argument (a backup name from `backups`)")
        return "restore", (ops[1] if len(ops) > 1 else None)
    if len(ops) % 2 != 0:
        raise UsageError("expected pairs of `COMMAND NAME`, e.g. `loadfeel fast loaddistances quiet`")
    pairs = []
    for i in range(0, len(ops), 2):
        cmd, name = ops[i], ops[i + 1]
        if cmd not in LOAD_GROUPS and cmd not in ("save", "loadall"):
            raise UsageError(f"unknown command {cmd!r} — use one of save/loaddistances/loadfeel/loadkeys/loaddevice/loadscroll/loadall (list/backups/restore run alone)")
        if not NAME_RE.fullmatch(name):
            raise UsageError(f"invalid preset name {name!r} — use only letters, digits, '.', '_' or '-'")
        pairs.append((cmd, name))
    return "apply", pairs


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="veloscroll_preset.py",
        description="Named presets of the veloscroll daemon keys — `save` snapshots every key; each load command applies only its own group: loaddistances (DEADZONE_IN/FULL_IN + _H), loadfeel (the 8 rate/curve/smoothing feel keys), loadkeys (SCROLL_BTN/SCROLL_BTN_H/DISABLED_BTN), loaddevice (NAME_MATCH/DEVICE_MATCH/DPI), loadscroll (TOGGLE_SCROLL/TOGGLE_SCROLL_H/VERTICAL_H) or loadall (everything except the key and device groups). "
                    "Any number of `COMMAND NAME` pairs run in one invocation, each with its own preset name, applied in order; list/backups/restore run alone.",
        epilog="examples:\n"
               "  veloscroll_preset.py save fast                        snapshot every daemon key -> presets/fast.ini\n"
               "  veloscroll_preset.py loadfeel fast                    apply only the feel keys of 'fast'\n"
               "  veloscroll_preset.py loadfeel a loaddistances b       multiple loads in one run, each with its own preset (applied in order)\n"
               "  veloscroll_preset.py list                             table of every preset's values\n"
               "  veloscroll_preset.py backups                          table of every .bak-<timestamp> backup, newest first\n"
               "  veloscroll_preset.py restore [BACKUP]                 put a backup back over its original (default: the newest config.ini backup)\n\n"
               "operations run in order; if one fails the rest are skipped — earlier ones stay applied and can be undone with `restore`",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", metavar="PATH",
                        help="path to config.ini (default: $VELOSCROLL_CONFIG or /etc/veloscroll/config.ini); "
                             "presets live in <config dir>/presets/")
    parser.add_argument("ops", nargs="+",
                        metavar="{save,loaddistances,loadfeel,loadkeys,loaddevice,loadscroll,loadall} NAME | list | backups | restore [BACKUP]",
                        help="operations to run: any number of `COMMAND NAME` pairs (each command with its own preset name), or one of the standalone commands list / backups / restore [BACKUP]")
    args = parser.parse_args(argv)

    try:
        mode, payload = _parse_ops(args.ops)
    except UsageError as exc:
        print(f"veloscroll-preset: {exc}", file=sys.stderr)
        return 1

    if args.config:
        os.environ["VELOSCROLL_CONFIG"] = args.config   # veloscroll reads it at import time; the explicit flag wins over the env var
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        import veloscroll  # also loads/validates config.ini on import — fail-fast like veloscroll_seed.py (module-level load is intended)
    except ImportError as exc:
        print(f"veloscroll-preset: cannot import veloscroll (is evdev installed? see README): {exc}", file=sys.stderr)
        return 1

    try:
        if mode == "list":
            cmd_list(veloscroll)
        elif mode == "backups":
            cmd_backups(veloscroll)
        elif mode == "restore":
            cmd_restore(veloscroll, payload)
        else:                                          # 'apply': the (command, name) pairs in order — a failure stops the rest, earlier operations stay applied and undoable
            for cmd, name in payload:
                if cmd == "save":
                    cmd_save(veloscroll, name)
                elif cmd == "loadall":
                    _cmd_load(veloscroll, name, "loadall", tuple(k for k in veloscroll.DAEMON_KEYS if k not in LOADALL_EXCLUDED))
                else:
                    _cmd_load(veloscroll, name, cmd, LOAD_GROUPS[cmd])
    except PresetError as exc:
        print(f"veloscroll-preset: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"veloscroll-preset: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
