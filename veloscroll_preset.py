#!/usr/bin/env python3

# VeloScroll — named presets for the 12 ramp keys (save / loadfeel / loadall / list / backups / restore)
# Copyright (C) 2026 Lucas Tippelt
# SPDX-License-Identifier: GPL-3.0-or-later
# Full license: https://www.gnu.org/licenses/gpl-3.0.html
#
# One-shot helper for switching between named presets without hand-editing
# /etc/veloscroll/config.ini — a load is just an atomic, pre-validated rewrite of the
# preset keys' lines, and the daemon hot-reloads config.ini within ~2 s:
#
#     veloscroll_preset.py save <name>      snapshot all 12 ramp keys -> <config dir>/presets/<name>.ini
#     veloscroll_preset.py loadfeel <name>  apply only the feel keys present in the preset (distance keys ignored even if present)
#     veloscroll_preset.py loadall <name>   additionally apply the physical distance keys (DEADZONE_IN / FULL_IN + _H)
#     veloscroll_preset.py list             table of every preset's values
#     veloscroll_preset.py backups          table of every .bak-<timestamp> backup (config + presets), newest first
#     veloscroll_preset.py restore [BACKUP] put a backup back over its original (default: the newest config.ini backup)
#
# The distance keys describe your physical setup, so routine swaps use `loadfeel` and can't
# silently change them; only an explicit `loadall` applies them. Writes are pre-validated with
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

# The 12 ramp keys a preset may carry. Fixed list, forward-compatible: extend this tuple
# plus the parse/validate branches in veloscroll.py when a new ramp key lands.
PRESET_KEYS = ("MAX_RATE", "MIN_RATE", "CURVE", "OUT_SMOOTH",
               "DEADZONE_IN", "FULL_IN",
               "MAX_RATE_H", "MIN_RATE_H", "CURVE_H", "OUT_SMOOTH_H",
               "DEADZONE_IN_H", "FULL_IN_H")
DISTANCE_KEYS = ("DEADZONE_IN", "FULL_IN", "DEADZONE_IN_H", "FULL_IN_H")   # physical setup: loadfeel never applies these


class PresetError(Exception):
    """Failure surfaced as a one-line stderr message (exit 1); no files are written."""


def _fmt(value):
    return "none" if value is None else str(value)


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
            raise PresetError(f"no backups of {vs.CONFIG_PATH} found (created automatically before every overwrite by save/loadfeel/loadall)")
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


def _rewrite_config_lines(text, updates):
    """Rewrite only the `KEY = ...` lines of `updates` inside [veloscroll] — line-based (preserves comments/ordering; not a configparser round-trip); absent keys are appended at section end. Returns the new full text."""
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
    for key in (k for k in PRESET_KEYS if k in updates):   # registry order -> deterministic appended order
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
    """Snapshot all 12 ramp keys into presets/<name>.ini; horizontal keys only when explicitly set in config.ini."""
    _check_max_backups(vs)
    preset_dir = _preset_dir(vs.CONFIG_PATH)
    preset_path = os.path.join(preset_dir, name + ".ini")
    current = _current_values(vs)
    ini_keys = _read_ini_keys(vs.CONFIG_PATH)     # which horizontal keys are explicitly present (non-empty) in config.ini

    body, captured_h = [], []
    for key in PRESET_KEYS:
        if key.endswith("_H"):
            raw = ini_keys.get(key, "").strip()
            if not raw:                            # unset axis keeps its fallback-to-vertical relation on any machine instead of baking a stale number
                continue
            captured_h.append(key)
        body.append(f"{key} = {_fmt(current[key])}")

    text = (f"# VeloScroll preset '{name}' — created by veloscroll_preset.py save "
            f"(12 ramp keys; horizontal only when set in config.ini)\n"
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
        print(f"pruned     : " + ", ".join(pruned))
    omitted_h = [k for k in PRESET_KEYS if k.endswith("_H") and k not in captured_h]
    if omitted_h:
        print("horizontal keys not set in config.ini (kept as vertical fallback): " + ", ".join(omitted_h))
    return 0


def _cmd_load(vs, name, tier):
    """Apply preset <name> to config.ini. tier 'feel' = the 8 feel keys only; 'all' = all 12."""
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

    base = _current_values(vs)                      # dict(_DEFAULTS) <- current config.ini values (import-time overlay)
    merged = dict(base)
    skipped_distance, unknown = [], []
    for key, raw in (cp["veloscroll"].items() if cp.has_section("veloscroll") else ()):
        if key not in PRESET_KEYS:
            unknown.append(key)                     # forward-compat: warn + ignore, like the daemon does with config.ini keys (veloscroll.py:163)
            continue
        raw = raw.strip()
        if not raw:                                 # empty value = not captured
            continue
        try:
            value = vs._parse_ini_value(key, raw)   # same parse rules as the daemon — no duplicated logic
        except vs.ConfigError as exc:
            raise PresetError(f"{preset_path}: {exc}") from exc
        if tier == "feel" and key in DISTANCE_KEYS:  # distance keys describe the physical setup — loadfeel never applies them, even when present
            skipped_distance.append(key)
            continue
        merged[key] = value

    for key in unknown:
        print(f"warning: unknown key {key} in {preset_path} — ignored", file=sys.stderr)
    if skipped_distance:
        print(f"note: distance keys present in '{name}' are not applied by loadfeel (physical setup): "
              + ", ".join(skipped_distance) + f" — use `veloscroll_preset.py loadall {name}` to apply them")

    errors = vs.check_config(merged)                # same validation as the daemon's hot-reload — a rejected reload can never happen
    if errors:
        raise PresetError(f"{preset_path} does not validate against the current config: " + "; ".join(errors))

    changes = [(k, base[k], merged[k]) for k in PRESET_KEYS if base[k] != merged[k]]
    if not changes:
        print(f"no change — {vs.CONFIG_PATH} already matches preset '{name}' ({tier})")
        return 0

    try:
        with open(vs.CONFIG_PATH, "r", encoding="utf-8") as f:
            text = f.read()
    except FileNotFoundError:
        text = ""
    new_text = _rewrite_config_lines(text, {k: _fmt(v) for k, _, v in changes})

    backup_path = _backup(vs.CONFIG_PATH) if os.path.exists(vs.CONFIG_PATH) else None
    pruned = _prune_backups(vs.CONFIG_PATH, vs.MAX_BACKUPS) if backup_path else []
    _atomic_write(vs.CONFIG_PATH, new_text)

    print(f"applied preset '{name}' ({tier}) to {vs.CONFIG_PATH}")
    for key, old, new in changes:
        print(f"{key}: {_fmt(old)} -> {_fmt(new)}")
    if backup_path:
        print(f"backup     : {backup_path}")
    if pruned:
        print(f"pruned     : " + ", ".join(pruned))
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
    cols = [(c, max([len(c)] + [len(cell(n, c)) for n in names])) for c in PRESET_KEYS]
    print(f"{'preset':<{name_w}}" + "".join(f" {c:<{w}}" for c, w in cols))
    for n in names:
        print(f"{n:<{name_w}}" + "".join(f" {cell(n, c):<{w}}" for c, w in cols))
    print("(absent = not captured; unset horizontal keys fall back to vertical)")
    return 0


def cmd_backups(vs):
    """Table of every .bak-<timestamp> backup next to the config or in its presets/ dir, newest first."""
    base_dir = os.path.dirname(os.path.abspath(vs.CONFIG_PATH))
    files = _backup_files(vs.CONFIG_PATH)
    if not files:
        print("no backups found (created automatically before every overwrite by save/loadfeel/loadall)")
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
        print("pruned     : " + ", ".join(pruned))
    if target == os.path.abspath(vs.CONFIG_PATH):
        print("the daemon applies the change within ~2 s — verify with: journalctl -u veloscroll")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="veloscroll_preset.py",
        description="Named presets for the 12 veloscroll ramp keys (see README 'Presets'). "
                    "`save` snapshots them; `loadfeel` applies only the feel keys; `loadall` also applies the physical distance keys.")
    parser.add_argument("--config", metavar="PATH",
                        help="path to config.ini (default: $VELOSCROLL_CONFIG or /etc/veloscroll/config.ini); "
                             "presets live in <config dir>/presets/")
    sub = parser.add_subparsers(dest="command", required=True, metavar="{save,loadfeel,loadall,list,backups,restore}")
    p_save = sub.add_parser("save", help="snapshot all 12 ramp keys into presets/<name>.ini (horizontal only when set in config.ini)")
    p_save.add_argument("name", help="preset name [A-Za-z0-9._-]+ — used directly as the file name")
    p_loadfeel = sub.add_parser("loadfeel", help="apply only the feel keys present in preset <name>; distance keys (DEADZONE_IN/FULL_IN + _H) ignored even if present")
    p_loadfeel.add_argument("name", help="preset name [A-Za-z0-9._-]+ — used directly as the file name")
    p_loadall = sub.add_parser("loadall", help="apply all 12 keys present in preset <name>, including the physical distance keys")
    p_loadall.add_argument("name", help="preset name [A-Za-z0-9._-]+ — used directly as the file name")
    sub.add_parser("list", help="table of every preset's values (absent = not captured)")
    sub.add_parser("backups", help="table of every .bak-<timestamp> backup (config.ini + preset files), newest first")
    p_restore = sub.add_parser("restore", help="put a backup back over its original (default: newest config.ini backup; the restore itself is backed up)")
    p_restore.add_argument("backup", nargs="?", metavar="BACKUP",
                           help="backup file name as shown by `backups` (or a path relative to the config dir); default = newest config.ini.bak-*")
    args = parser.parse_args(argv)

    if args.command in ("save", "loadfeel", "loadall") and not NAME_RE.fullmatch(args.name):
        print(f"veloscroll-preset: invalid preset name {args.name!r} — use only letters, digits, '.', '_' or '-'", file=sys.stderr)
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
        if args.command == "save":
            cmd_save(veloscroll, args.name)
        elif args.command in ("loadfeel", "loadall"):
            _cmd_load(veloscroll, args.name, "all" if args.command == "loadall" else "feel")
        elif args.command == "backups":
            cmd_backups(veloscroll)
        elif args.command == "restore":
            cmd_restore(veloscroll, args.backup)
        else:
            cmd_list(veloscroll)
    except PresetError as exc:
        print(f"veloscroll-preset: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"veloscroll-preset: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
