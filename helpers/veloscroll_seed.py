#!/usr/bin/env python3

# VeloScroll — seed per-device pointer settings into veloscroll-mouse
# Copyright (C) 2026 Lucas Tippelt
# SPDX-License-Identifier: GPL-3.0-or-later
# Full license: https://www.gnu.org/licenses/gpl-3.0.html
#
# One-shot helper: copies the real mouse's per-device pointer settings from your
# desktop environment into the veloscroll-mouse virtual device, so it starts out
# feeling exactly like the real mouse — and applies them to a running session via
# KWin's D-Bus interface (the same mechanism System Settings' "Apply" uses), since
# KWin does not re-read kcminputrc for devices that are already registered.
# Afterwards tune the veloscroll-mouse entry
# in System Settings -> Mouse & Touchpad (KDE Plasma) directly — those tweaks
# persist across daemon restarts because KWin keys the config by
# [vendor][product][name] and the same IDs are re-advertised on every start.
#
# Run as your desktop user, NOT root (as root it would target /root/.config):
#
#     python3 /opt/veloscroll/helpers/veloscroll_seed.py [--name <NAME>] [--apply-only] [--remove-stale-config]
#
# Re-run at install time and whenever you change mice (update DEVICE_MATCH in
# /etc/veloscroll/config.ini first — not veloscroll.py, which updates would overwrite).

import argparse
import configparser
import glob
import io
import os
import shutil
import subprocess
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Tuple

_EV_REL_BIT = 2          # EV_REL bit in the sysfs EV= capability mask: device has relative axes (a mouse)
_USB_BUS = 3             # BUS_USB in PRODUCT=<bus>/<vendor_hex>/<product_hex>/<version_hex>


class SeedError(Exception):
    """Failure surfaced by the core as a one-line message (exit 1)."""


@dataclass(frozen=True)
class RealDevice:
    name: str
    vendor: int
    product: int
    version: int
    node: str

    @property
    def ids_hex(self):
        return f"0x{self.vendor:x}:0x{self.product:x}"


@dataclass
class SeedReport:
    """What the backend did, reported back to the core for printing."""
    message: str = ""
    target_section: Optional[str] = None
    changes: List[Tuple[str, Optional[str], Optional[str]]] = field(default_factory=list)
    backup_path: Optional[str] = None
    pruned: List[str] = field(default_factory=list)
    live_notes: List[str] = field(default_factory=list)


def kcminputrc_path():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "kcminputrc")


# ---------------------------------------------------------------- core (DE-agnostic)

@dataclass(frozen=True)
class _Candidate:
    name: str
    node: str
    usb: Optional[Tuple[int, int, int]]   # (vendor, product, version); None if not a USB-bus device with real IDs
    rel: bool


def _usb_ids(product_field):
    """Parse PRODUCT=<bus>/<vendor_hex>/<product_hex>/<version_hex>; None unless it is a genuine USB ID set."""
    if not product_field:
        return None
    parts = product_field.split("/")
    if len(parts) != 4:
        return None
    try:
        bus, vendor, product, version = (int(p, 16) for p in parts)
    except ValueError:
        return None
    if bus != _USB_BUS or not vendor or not product:
        return None
    return vendor, product, version


def _scan_devices():
    """Enumerate input devices purely from world-readable sysfs (no root, no evdev)."""
    devices = []
    for event_dir in sorted(glob.glob("/sys/class/input/event*")):
        node = os.path.join("/dev/input", os.path.basename(event_dir))
        dev_path = os.path.join(event_dir, "device")
        try:
            with open(os.path.join(dev_path, "name"), encoding="utf-8") as f:
                name = f.read().strip()
            with open(os.path.join(dev_path, "uevent"), "rb") as f:
                raw = f.read()
        except OSError:
            continue
        env = {}
        for chunk in raw.replace(b"\0", b"\n").split(b"\n"):  # uevent lines are newline-separated (NUL tolerated)
            if b"=" in chunk:
                k, _, v = chunk.partition(b"=")
                env[k.decode("utf-8", "replace")] = v.decode("utf-8", "replace")
        rel_mask = 0
        ev_field = env.get("EV")
        if ev_field:
            try:
                rel_mask = int(ev_field, 16)
            except ValueError:
                pass
        devices.append(_Candidate(
            name=name or env.get("NAME", "").strip('"'),
            node=node,
            usb=_usb_ids(env.get("PRODUCT")),
            rel=bool((rel_mask >> _EV_REL_BIT) & 1),
        ))
    return devices


def _selected(d: "_Candidate", device_match, name_match: str, name_override: Optional[str]) -> bool:
    if "veloscroll" in d.name.lower():
        return False
    if not d.rel:
        return False
    if name_override is not None:
        # --name skips ID matching; the chosen device's IDs come from its uevent.
        return name_override.lower() in d.name.lower()
    if device_match is None:
        return name_match.lower() in d.name.lower()
    if isinstance(device_match, str):
        return os.path.realpath(d.node) == os.path.realpath(device_match)
    vendor, product = device_match
    if d.usb is None:
        return False
    return (d.usb[0], d.usb[1]) == (vendor, product)


def _has_kcminput_group(d: "_Candidate") -> bool:
    # Ambiguity tiebreak (KDE-specific; a no-op when kcminputrc does not exist): prefer the candidate that already has its own per-device group.
    if d.usb is None:
        return False
    try:
        with open(kcminputrc_path(), encoding="utf-8") as f:
            cp = configparser.ConfigParser(interpolation=None)
            cp.read_file(f)
    except (OSError, configparser.Error):
        return False
    return _libinput_section(d.usb[0], d.usb[1], d.name) in cp.sections()


def discover_real_mouse(device_match, name_match: str, name_override: Optional[str] = None) -> RealDevice:
    candidates = [d for d in _scan_devices() if _selected(d, device_match, name_match, name_override)]
    if not candidates:
        raise SeedError("no matching real mouse found — plug it in or pass --name <NAME> to select by device name")
    if len(candidates) > 1:
        with_group = [d for d in candidates if _has_kcminput_group(d)]
        if len(with_group) == 1:
            candidates = with_group
        else:
            listing = "; ".join(
                f"{d.name} ({f'0x{d.usb[0]:x}:0x{d.usb[1]:x}' if d.usb else 'no USB IDs'}) at {d.node}"
                for d in candidates)
            raise SeedError(f"multiple candidate devices found — set DEVICE_MATCH more precisely or pass --name: {listing}")
    chosen = candidates[0]
    if chosen.usb is None:
        raise SeedError(f"device '{chosen.name}' reports no USB vendor/product — per-device seeding not possible")
    return RealDevice(name=chosen.name, vendor=chosen.usb[0], product=chosen.usb[1], version=chosen.usb[2], node=chosen.node)


def _prune_backups(path: str, max_backups: int) -> List[str]:
    """Keep only the newest `max_backups` files named `<basename>.bak-*` next to path; return deleted names. -1 = unlimited, 0 = backups disabled (no-op)."""
    if not isinstance(max_backups, int) or max_backups < -1:
        raise SeedError(f"invalid MAX_BACKUPS {max_backups!r} — use -1 (unlimited), 0 (backups disabled), or a positive number of backups to keep")
    if max_backups <= 0:
        return []
    prefix = os.path.basename(path) + ".bak-"
    # fixed-width timestamps sort lexicographically == chronologically; oldest first
    candidates = sorted(glob.glob(os.path.join(os.path.dirname(path), prefix + "*")))
    pruned = []
    for f in candidates[: max(0, len(candidates) - max_backups)]:
        try:
            os.remove(f)
        except OSError as exc:
            raise SeedError(f"could not delete old backup {f}: {exc}")
        pruned.append(os.path.basename(f))
    return pruned


# ---------------------------------------------------------------- backends

class PointerSettingsBackend(ABC):
    """DE-specific strategy for copying per-device pointer settings into veloscroll-mouse.

    Encapsulates everything DE-specific: where the settings live (path + format), how the real mouse's entry is keyed/located in that format, which keys are copied, and backup/write mechanics. Implementations must be idempotent; "nothing to seed" is a legitimate success outcome — a no-op backend is acceptable for DEs with only *global* pointer settings (those already apply to veloscroll-mouse).
    """

    @abstractmethod
    def seed(self, real: RealDevice, virtual_name: str, max_backups: int) -> SeedReport:
        ...

    @abstractmethod
    def apply_only(self, real: RealDevice, virtual_name: str) -> SeedReport:
        ...

    @abstractmethod
    def remove_stale(self, real: RealDevice, virtual_name: str, max_backups: int) -> SeedReport:
        ...


class KdePlasmaBackend(PointerSettingsBackend):
    # Plasma 6 stores per-device pointer settings in kcminputrc, one group per device:
    # [Libinput][<vendor_dec>][<product_dec>][<device name>] with keys like PointerAcceleration.

    def seed(self, real: RealDevice, virtual_name: str, max_backups: int) -> SeedReport:
        path = kcminputrc_path()
        if not os.path.exists(path):
            return SeedReport(message=f"no per-device settings for {real.name} in kcminputrc — {virtual_name} will use system defaults")

        cp = configparser.ConfigParser(interpolation=None)
        cp.optionxform = str  # preserve CamelCase keys
        try:
            with open(path, encoding="utf-8") as f:
                cp.read_file(f)
        except (OSError, configparser.Error) as exc:
            raise SeedError(f"could not read {path}: {exc}")

        source = _libinput_section(real.vendor, real.product, real.name)
        target = _libinput_section(real.vendor, real.product, virtual_name)
        if source not in cp.sections():
            return SeedReport(message=f"no per-device settings for {real.name} in kcminputrc — {virtual_name} will use system defaults")

        # Copy all keys from the source group except Enabled (a disabled real mouse must not disable the virtual device).
        new_options = [(k, v) for k, v in cp.items(source) if k != "Enabled"]
        old_options = dict(cp.items(target)) if target in cp.sections() else {}

        changes: List[Tuple[str, Optional[str], Optional[str]]] = []
        new_map = dict(new_options)
        for key in list(dict.fromkeys(list(new_map) + list(old_options))):
            old, new = old_options.get(key), new_map.get(key)
            if old != new:
                changes.append((key, old, new))

        backup_path = None
        pruned = []
        if changes:
            # Overwrite semantics: replace the target group (existing tweaks are reset; recoverable from the backup while backups are enabled).
            if max_backups != 0:     # MAX_BACKUPS = 0 disables backups entirely — no .bak-* file is written, existing ones stay untouched
                backup_path = path + ".bak-" + datetime.now().strftime("%Y%m%d-%H%M%S")
                shutil.copy2(path, backup_path)
                pruned = _prune_backups(path, max_backups)
            if target in cp.sections():
                for key in old_options:
                    cp.remove_option(target, key)
            else:
                cp.add_section(target)
            for key, value in new_options:
                cp.set(target, key, value)
            self._write_inplace(cp, path)

        # Live-apply to the running session through KWin's D-Bus interface — the same mechanism System Settings' "Apply" uses.
        # KWin does not re-read kcminputrc for a device it already registered (its file watcher is unreliable on Plasma 6 Wayland; KDE bug 513879), so writing the file alone never changes how a running session feels.
        live_notes = self._live_apply(virtual_name, new_options)

        message = f"seeded {target} from {source}" if changes else f"{target} already matches {source}"
        return SeedReport(message=message, target_section=target, changes=changes, backup_path=backup_path, pruned=pruned, live_notes=live_notes)

    def apply_only(self, real: RealDevice, virtual_name: str) -> SeedReport:
        # Push the existing veloscroll-mouse group from kcminputrc to the running session (e.g. hand-edited values); the file is left untouched.
        path = kcminputrc_path()
        if not os.path.exists(path):
            raise SeedError(f"no kcminputrc at {path} — nothing to apply; run without --apply-only first")

        cp = configparser.ConfigParser(interpolation=None)
        cp.optionxform = str  # preserve CamelCase keys
        try:
            with open(path, encoding="utf-8") as f:
                cp.read_file(f)
        except (OSError, configparser.Error) as exc:
            raise SeedError(f"could not read {path}: {exc}")

        target = _libinput_section(real.vendor, real.product, virtual_name)
        if target not in cp.sections():
            raise SeedError(f"no per-device group for {virtual_name} ({target}) in kcminputrc — run without --apply-only first to create it")

        live_notes = self._live_apply(virtual_name, list(cp.items(target)))
        return SeedReport(message=f"applied existing {target} from kcminputrc (no file changes)", live_notes=live_notes)

    def remove_stale(self, real: RealDevice, virtual_name: str, max_backups: int) -> SeedReport:
        # Delete [Libinput][...][veloscroll-mouse] groups keyed by IDs other than the current real mouse's (dead config from old mice / pre-ID-copy runs). No live apply needed — no device advertises those IDs.
        path = kcminputrc_path()
        if not os.path.exists(path):
            return SeedReport(message=f"no kcminputrc at {path} — nothing to remove")

        cp = configparser.ConfigParser(interpolation=None)
        cp.optionxform = str  # preserve CamelCase keys
        try:
            with open(path, encoding="utf-8") as f:
                cp.read_file(f)
        except (OSError, configparser.Error) as exc:
            raise SeedError(f"could not read {path}: {exc}")

        live = _libinput_section(real.vendor, real.product, virtual_name)
        suffix = f"][{virtual_name}"
        stale = [s for s in cp.sections() if s.startswith("Libinput][") and s.endswith(suffix) and s != live]
        if not stale:
            return SeedReport(message="no stale veloscroll-mouse groups found — nothing to remove")

        backup_path = None
        pruned = []
        if max_backups != 0:     # MAX_BACKUPS = 0 disables backups entirely — no .bak-* file is written, existing ones stay untouched
            backup_path = path + ".bak-" + datetime.now().strftime("%Y%m%d-%H%M%S")
            shutil.copy2(path, backup_path)
            pruned = _prune_backups(path, max_backups)
        for s in stale:
            cp.remove_section(s)
        self._write_inplace(cp, path)
        message = f"removed {len(stale)} stale veloscroll-mouse group(s) from kcminputrc: " \
                  + ", ".join(f"[{s}]" for s in sorted(stale))
        return SeedReport(message=message, backup_path=backup_path, pruned=pruned)

    @staticmethod
    def _write_inplace(parser: configparser.ConfigParser, path: str):
        # Rewrite in place (same inode), like KConfig's own saves — renaming the file would kill any inotify watch KWin holds on it.
        buf = io.StringIO()
        parser.write(buf, space_around_delimiters=False)  # match KConfig's key=value style
        content = buf.getvalue()
        if content.endswith("\n\n"):
            content = content[:-1]  # KConfig files end with a single trailing newline
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    _DBUS_SERVICE = "org.kde.KWin"
    _DBUS_IFACE = "org.kde.KWin.InputDevice"
    # kcminputrc ScrollMethod value -> (D-Bus property, KWin supports* flag)
    _SCROLL_METHODS = {1: ("scrollEdge", "supportsScrollEdge"),
                       2: ("scrollTwoFinger", "supportsScrollTwoFinger"),
                       3: ("scrollOnButtonDown", "supportsScrollOnButtonDown")}

    def _live_apply(self, virtual_name: str, options) -> List[str]:
        """Push the copied settings to veloscroll-mouse's KWin InputDevice object (what GUI Apply does). Returns report lines."""
        busctl = shutil.which("busctl")
        if not os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
            return ["no D-Bus session bus — live apply skipped; the settings take effect when the device next registers (or after re-login)"]
        if busctl is None:
            return ["busctl not found — live apply skipped; the settings are in kcminputrc only"]
        node = self._virtual_node(virtual_name)
        if node is None:
            return [f"{virtual_name} not registered with KWin (is veloscroll running?) — live apply skipped; re-run after starting it"]
        path = f"/org/kde/KWin/InputDevice/{node}"
        if self._dbus_get(busctl, path, "name") != virtual_name:
            return [f"{virtual_name} not found among KWin's input devices — live apply skipped; the settings are in kcminputrc only"]

        applied = []
        failed = []

        def set_prop(prop: str, typ: str, value: str):
            # busctl scans its whole argv with getopt; '--' keeps negative values like -0.4 from being parsed as options.
            r = subprocess.run([busctl, "--user", "call", self._DBUS_SERVICE, path,
                                "org.freedesktop.DBus.Properties", "Set", "ssv",
                                self._DBUS_IFACE, prop, typ, "--", value],
                               capture_output=True, text=True, timeout=10)
            if r.returncode == 0:
                applied.append(f"{prop}={value}")
            else:
                failed.append(f"{prop}: {r.stderr.strip() or 'set failed'}")

        for key, value in options:
            if key == "PointerAcceleration":
                set_prop("pointerAcceleration", "d", value)
            elif key == "PointerAccelerationProfile":
                # kcminputrc int -> KWin's two booleans (1 = flat, 2 = adaptive; verified against KWin's write-back format).
                if value == "1":
                    set_prop("pointerAccelerationProfileFlat", "b", "true")
                    set_prop("pointerAccelerationProfileAdaptive", "b", "false")
                elif value == "2":
                    set_prop("pointerAccelerationProfileAdaptive", "b", "true")
                    set_prop("pointerAccelerationProfileFlat", "b", "false")
            elif key == "ScrollFactor":
                set_prop("scrollFactor", "d", value)
            elif key == "MiddleButtonEmulation":
                set_prop("middleEmulation", "b", value.lower())
            elif key in ("NaturalScroll", "LeftHanded"):
                set_prop(key[0].lower() + key[1:], "b", value.lower())
            elif key == "ScrollMethod":
                try:
                    method = int(value)
                except ValueError:
                    continue
                if method not in self._SCROLL_METHODS:
                    continue  # 0 = none (KWin's default); unknown values are file-only
                supported = {m: self._dbus_get(busctl, path, flag) == "true" for m, (_p, flag) in self._SCROLL_METHODS.items()}
                for m, (prop, _flag) in self._SCROLL_METHODS.items():
                    if not supported[m]:
                        continue  # the device cannot do this method; its property is already false there
                    set_prop(prop, "b", "true" if m == method else "false")
                    if m == 3 and method == 3:
                        button = dict(options).get("ScrollButton")
                        if button:
                            set_prop("scrollButton", "u", button)
            # Any other key (TapToClick etc.) is persisted to kcminputrc; no D-Bus mapping here.

        notes = []
        if applied:
            notes.append(f"applied live via KWin: {', '.join(applied)}")
        for msg in failed:
            notes.append(f"LIVE APPLY FAILED — {msg} (the value is still saved to kcminputrc)")
        return notes

    @staticmethod
    def _virtual_node(virtual_name: str) -> Optional[str]:
        """sysfs node name (eventN) of the device whose name matches virtual_name, or None."""
        for event_dir in sorted(glob.glob("/sys/class/input/event*")):
            try:
                with open(os.path.join(event_dir, "device", "name"), encoding="utf-8") as f:
                    if f.read().strip() == virtual_name:
                        return os.path.basename(event_dir)
            except OSError:
                continue
        return None

    def _dbus_get(self, busctl: str, path: str, prop: str) -> Optional[str]:
        r = subprocess.run([busctl, "--user", "get-property", self._DBUS_SERVICE, path, self._DBUS_IFACE, prop],
                           capture_output=True, text=True, timeout=10)
        if r.returncode != 0:
            return None
        typ, _, rest = r.stdout.strip().partition(" ")
        if not rest:
            return None
        if typ == "s":
            return rest.strip('"')
        return rest


def _libinput_section(vendor: int, product: int, name: str) -> str:
    return f"Libinput][{vendor}][{product}][{name}"


# Registry: exact DE_WM value -> backend instance. When a second real backend lands, split the backends out of this file into their own modules.
BACKENDS = {
    "kde-plasma": KdePlasmaBackend(),
}


# ---------------------------------------------------------------- entry point

def _print_report(real: RealDevice, reports: List[SeedReport]):
    print(f"real mouse : {real.name} ({real.ids_hex}) at {real.node}")
    for report in reports:
        for note in report.live_notes:
            print(f"live       : {note}")
    for report in reports:
        if report.target_section is None:
            print(report.message)
        else:
            print(f"{report.target_section}:")
            if not report.changes:
                print("  (no changes)")
            else:
                for key, old, new in report.changes:
                    old_s = "(none)" if old is None else old
                    new_s = "(removed)" if new is None else new
                    print(f"  {key}: {old_s} -> {new_s}")
    for report in reports:
        if report.backup_path:
            print(f"backup     : {report.backup_path}")
    for report in reports:
        if report.pruned:
            print(f"pruned     : " + ", ".join(report.pruned))


def main(argv=None) -> int:
    if os.geteuid() == 0:
        print("veloscroll-seed: refusing to run as root — it would target /root/.config; "
              "run this as your desktop user instead", file=sys.stderr)
        return 1

    parser = argparse.ArgumentParser(
        description="Copy the real mouse's per-device pointer settings into veloscroll-mouse (one-shot; see README). "
                    "With --apply-only, push the existing veloscroll-mouse group from kcminputrc instead.")
    parser.add_argument("--name", metavar="NAME",
                        help="select the real mouse by case-insensitive substring of its device name "
                             "(skips DEVICE_MATCH); IDs are taken from that device's uevent")
    parser.add_argument("--apply-only", action="store_true",
                        help="push the existing veloscroll-mouse group from kcminputrc to the running session "
                             "(e.g. hand-edited values) without re-seeding or modifying the file; "
                             "combinable with --remove-stale-config (apply runs first)")
    parser.add_argument("--remove-stale-config", action="store_true",
                        help="delete [Libinput][...][veloscroll-mouse] groups in kcminputrc that don't match your "
                             "current mouse's USB IDs (dead config from old mice / pre-ID-copy runs); writes a .bak-* backup first; "
                             "combinable with --apply-only, which runs before it")
    args = parser.parse_args(argv)

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # repo root (this script lives in helpers/)
    try:
        import veloscroll  # also loads/validates /etc/veloscroll/config.ini on import — the seed fails fast on a broken config
    except ImportError as exc:
        print(f"veloscroll-seed: cannot import veloscroll (is evdev installed? see README): {exc}", file=sys.stderr)
        return 1

    try:
        real = discover_real_mouse(veloscroll.DEVICE_MATCH, veloscroll.NAME_MATCH, args.name)
    except SeedError as exc:
        print(f"veloscroll-seed: {exc}", file=sys.stderr)
        return 1

    backend = BACKENDS.get(veloscroll.DE_WM)
    if backend is None:
        supported = ", ".join(repr(v) for v in sorted(BACKENDS))
        print(f"veloscroll-seed: unsupported DE_WM {veloscroll.DE_WM!r} — supported values: {supported}", file=sys.stderr)
        return 1

    try:
        if args.apply_only or args.remove_stale_config:
            reports = []
            # Apply before removal so a cleanup failure can't leave the requested values unapplied; both are idempotent.
            if args.apply_only:
                reports.append(backend.apply_only(real, veloscroll.VIRTUAL_NAME))
            if args.remove_stale_config:
                reports.append(backend.remove_stale(real, veloscroll.VIRTUAL_NAME, veloscroll.MAX_BACKUPS))
        else:
            reports = [backend.seed(real, veloscroll.VIRTUAL_NAME, veloscroll.MAX_BACKUPS)]
    except SeedError as exc:
        print(f"veloscroll-seed: {exc}", file=sys.stderr)
        return 1

    _print_report(real, reports)
    return 0


if __name__ == "__main__":
    sys.exit(main())
