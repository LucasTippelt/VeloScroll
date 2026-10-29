#!/usr/bin/env python3

# VeloScroll — manual tuning aid for the ramp distance keys (hold-button velocity scroll)
# Copyright (C) 2026 Lucas Tippelt
# SPDX-License-Identifier: GPL-3.0-or-later
# Full license: https://www.gnu.org/licenses/gpl-3.0.html
#
# Terminal helper for setting DEADZONE_IN / FULL_IN (+ _H) from your real hand movement, and
# sanity-checking DPI / MAX_RATE / MIN_RATE / CURVE. With the daemon stopped it exclusively
# grabs the configured mouse (all matching devices, full daemon parity) plus a temporary
# UInput pass-through virtual mouse: while you hold the scroll button the cursor stays put
# and no scroll is ever emitted; between holds the mouse behaves exactly as normal. Each
# hold prints an in-place distance gauge with the would-be target rate (the daemon's exact
# ramp formula; movement below/left of the start point is negative and gets a direction label),
# a line each time you leave or re-enter the deadzone and each time you cross the full-rate
# boundary either way, plus a copy-pasteable release summary:
#
#     sudo systemctl stop veloscroll
#     sudo python3 /opt/veloscroll/veloscroll_tuning_helper.py  # --config PATH for a per-user config
#     ... hold the button, move, read the milestone + summary lines ...
#     # set DEADZONE_IN / FULL_IN (+ _H) in /etc/veloscroll/config.ini to your liking
#     sudo systemctl start veloscroll
#
# It reads config.ini hot-reloadable like the daemon (1 s poller): live edits switch the
# thresholds mid-session, a rejected edit keeps the old values. The helper never emits
# scroll and never starts/stops the daemon — stopping it first is your job; if the grab
# fails with `device busy`, whatever holds the mouse (usually the daemon) must be stopped.
#
# Run as root, or as a user in the input group with access to /dev/uinput — the same
# permissions as running veloscroll.py manually (see README "Permissions").

import argparse
import errno
import os
import select
import signal
import sys
import threading
import time
import evdev
from evdev import UInput, ecodes as e


class SetupError(Exception):
    """Failure surfaced as a one-line stderr message (exit 1)."""


_BTN_NAMES = {}             # button code -> BTN_* name; filled from evdev.ecodes after the veloscroll import
_hold = {"v": None, "h": None}   # axis -> per-hold measurement dict (press_ts / dz_crossed / max_reached / peak); None when no session on that axis
_at_line_start = True        # output bookkeeping: the last write ended at the start of a fresh line
_print_lock = threading.Lock()


def _num(x):
    """Clean display for float-parsed config values: DPI = 1600 -> '1600', 2.3 in * 1600 -> '3680' (not the raw float error)."""
    if isinstance(x, float):
        r = round(x)
        if abs(x - r) < 1e-9:
            return str(int(r))
        return f"{x:.4f}".rstrip("0").rstrip(".")
    return str(x)


def _btn_name(code):
    return _BTN_NAMES.get(code)


def _disp_off(vs, axis, off):
    """Display-signed distance: negative = below/left of the start point. Measured on hardware: raw REL_Y accumulates positive when the hand moves BELOW the start (opposite of REL_X's right-positive), so v-mode and VERTICAL_H negate; horizontal without VERTICAL_H already matches."""
    if axis == "h" and not vs.VERTICAL_H:
        return off
    return -off


def _dir_label(vs, axis, d):
    """Gauge suffix (leading space included; "" exactly at the start) for a display-signed distance d (see _disp_off): physical direction of the hand relative to this hold's start point. H-mode without VERTICAL_H is left/right; v-mode and VERTICAL_H are up/down — in every case that matches what scrolls (see veloscroll.py ticker, side/vertical_axis)."""
    if axis == "h" and not vs.VERTICAL_H:
        return " (rightwards)" if d > 0 else (" (leftwards)" if d < 0 else "")
    return " (upwards)" if d > 0 else (" (downwards)" if d < 0 else "")


def _line(msg=""):
    """Discrete stdout line; first replaces an in-place gauge with a newline. Safe from any thread."""
    global _at_line_start
    with _print_lock:
        if not _at_line_start:
            sys.stdout.write("\n")
        if msg:
            sys.stdout.write(msg + "\n")
        sys.stdout.flush()
        _at_line_start = True


def _gauge(text):
    """In-place gauge line (\\r, no newline). Caller holds vs.lock so two merged devices can't interleave."""
    global _at_line_start
    with _print_lock:
        sys.stdout.write("\r" + text)
        sys.stdout.flush()
        _at_line_start = False


def _target_rate(vs, axis, dist):
    """The daemon's exact ramp formula (veloscroll.py ticker() — source of truth), per-axis effective values."""
    if axis == "h":                       # each unset horizontal key falls back to the vertical one
        dz, full = vs.DEADZONE_H, vs.FULL_H
        min_r = vs.MIN_RATE_H if vs.MIN_RATE_H is not None else vs.MIN_RATE
        max_r = vs.MAX_RATE_H if vs.MAX_RATE_H is not None else vs.MAX_RATE
        curve = vs.CURVE_H if vs.CURVE_H is not None else vs.CURVE
    else:
        dz, full, min_r, max_r, curve = vs.DEADZONE, vs.FULL, vs.MIN_RATE, vs.MAX_RATE, vs.CURVE
    if dist <= dz:
        return 0.0
    frac = min(1.0, (dist - dz) / (full - dz))
    return min_r * (max_r / min_r) ** (frac ** curve)


def _begin_hold(axis):
    # fresh per-hold measurement state; accumulators were just zeroed by the caller under vs.lock
    _hold[axis] = {"press_ts": time.monotonic(), "in_dz": True, "dz_crossed": False, "at_max": False, "max_reached": False, "peak": 0}


def _on_move(vs, axis, off):
    """Milestones + gauge for one REL event while held. Caller holds vs.lock."""
    info = _hold[axis]
    if info is None:                      # session was reset externally (e.g. live button swap) — nothing to measure
        return
    dist = abs(off)
    d = _disp_off(vs, axis, off)                  # display-signed distance (negative below/left of the start); thresholds compare on dist (magnitude), only display follows d's sign
    if dist > abs(info["peak"]):                  # peak keeps the direction of the farthest excursion, so the release summary shows which way you went furthest
        info["peak"] = d
    dz, full = (vs.DEADZONE_H, vs.FULL_H) if axis == "h" else (vs.DEADZONE, vs.FULL)   # effective counts; a hot reload switches them mid-hold (daemon semantics: the next event uses the new globals)
    if info["in_dz"]:                              # one line per crossing, not just the first of the hold
        if dist > dz:                              # strictly greater — same crossing metric as the daemon
            info["in_dz"] = False
            info["dz_crossed"] = True
            _line(f"[{axis}] deadzone passed at {d / vs.DPI:.2f} in ({_num(d)} counts)")
    elif dist <= dz:                               # came back inside after leaving this hold
        info["in_dz"] = True
        _line(f"[{axis}] deadzone re-entered at {d / vs.DPI:.2f} in ({_num(d)} counts)")
    if not info["at_max"]:                        # one line per entry into the clamped region, like the deadzone crossings
        if dist >= full:                          # offset is clamped to +/-FULL, so this fires exactly when clamping kicks in (or re-kicks in after pulling back)
            info["at_max"] = True
            info["max_reached"] = True
            _line(f"[{axis}] max-rate reached at {d / vs.DPI:.2f} in ({_num(d)} counts) — further movement clamps here")
    elif dist < full:                             # pulled back below the clamp -> a later re-entry prints again
        info["at_max"] = False
        _line(f"[{axis}] max-rate exited at {d / vs.DPI:.2f} in ({_num(d)} counts) — clamping lifted")
    rate = int(round(_target_rate(vs, axis, dist)))   # 0 inside the deadzone
    _gauge(f"[{axis}] {d / vs.DPI:.2f} in from start ({_num(d)} counts) | target {rate} notches/s{_dir_label(vs, axis, d)}")


def _end_hold(vs, axis):
    """Per-hold summary — the key copy-pasteable result for picking config values. Caller holds vs.lock."""
    info = _hold[axis]
    if info is None:
        return
    _hold[axis] = None
    elapsed = time.monotonic() - info["press_ts"]
    peak = info["peak"]
    dz_part = "deadzone crossed" if info["dz_crossed"] else "deadzone not crossed"
    max_part = "max-rate reached" if info["max_reached"] else "max-rate not reached"
    _line(f"[{axis}] released after {elapsed:.1f} s — peak {peak / vs.DPI:.1f} in ({_num(peak)} counts), {dz_part}, {max_part}")


def _reader(vs, path, dev, ui, stop):
    """Per-device event loop mirroring veloscroll.run() (hold-mode state machine, same clamping, same swallowed-event set) — but held RELs/wheel are dropped instead of scrolled, everything else is forwarded via the temporary UInput device. Like run()'s read_loop it is select-driven so pass-through stays smooth (any event wakes it instantly); only difference: each wait is capped at 100 ms so Ctrl-C exits promptly even when the mouse is quiet."""
    while not stop.is_set():
        try:
            r, _, _ = select.select([dev.fd], [], [], 0.1)   # instant wake on any event (no poll delay for pass-through); bounded wait -> prompt Ctrl-C
            if r:
                try:
                    batch = list(dev.read())                 # all pending events in one go — exactly what evdev's read_loop does; BlockingIOError when drained between select and read
                except BlockingIOError:
                    continue
                for ev in batch:
                    with vs.lock:                                      # whole event under the daemon's lock — a hot reload can switch values between events (same as run())
                        if ev.type == e.EV_KEY and (ev.code == vs.SCROLL_BTN or ev.code == vs.SCROLL_BTN_H):
                            is_h = ev.code == vs.SCROLL_BTN_H
                            axis = "h" if is_h else "v"
                            name = _btn_name(ev.code)
                            label = f"{name} / {ev.code}" if name else str(ev.code)
                            if ev.value == 1:                                # press -> this button becomes the active axis (LIFO), fresh hold
                                if is_h: vs.held_h = True
                                else:    vs.held_v = True
                                vs.held = True
                                vs.mode = axis
                                vs.offset = vs.h_offset = 0
                                _begin_hold(axis)
                                _line(f"[{axis}] scroll button pressed ({label})")
                            elif ev.value == 0:                              # release (key auto-repeats, value 2, are no-ops — same as the daemon)
                                if is_h: vs.held_h = False
                                else:    vs.held_v = False
                                if not (vs.held_v or vs.held_h):
                                    vs.held = False
                                    _end_hold(vs, axis)
                                else:                                        # other button still down -> reactivate it fresh (D3, same as the daemon)
                                    axis = "v" if vs.held_v else "h"
                                    vs.mode = axis
                                    vs.offset = vs.h_offset = 0
                                    _begin_hold(axis)
                            continue

                        # [disabled-btn] swallows the disabled button (it never reaches the OS) — same as the daemon
                        if ev.type == e.EV_KEY and ev.code == vs.DISABLED_BTN:
                            continue

                        if vs.held and ev.type == e.EV_REL and ev.code in (e.REL_X, e.REL_Y):
                            if vs.mode == "v" and ev.code == e.REL_Y:
                                vs.offset = max(-vs.FULL, min(vs.FULL, vs.offset + ev.value))
                                _on_move(vs, "v", vs.offset)
                            elif vs.mode == "h" and ev.code == (e.REL_Y if vs.VERTICAL_H else e.REL_X):   # VERTICAL_H: H-mode accumulates up/down movement instead of left/right
                                vs.h_offset = max(-vs.FULL_H, min(vs.FULL_H, vs.h_offset + ev.value))
                                _on_move(vs, "h", vs.h_offset)
                            continue                                         # every held REL_X/REL_Y is swallowed — the cursor stays put

                        if vs.held and ev.type == e.EV_REL and ev.code in (e.REL_WHEEL, e.REL_WHEEL_HI_RES, e.REL_HWHEEL, e.REL_HWHEEL_HI_RES):
                            continue                                         # wheel while held is swallowed; no scroll of any kind is ever emitted

                        try:                                                 # everything else passes through to the OS via the temporary virtual mouse (the device's own SYN_REPORT events ride along, so reports stay atomic)
                            ui.write_event(ev)
                        except Exception:
                            pass
        except Exception as exc:                                       # select/read/processing I/O failure — e.g. unplugged mid-session; any remaining grabbed devices keep working
            if not stop.is_set():                                      # a read failing during shutdown is expected — no "lost device" line then
                _line(f"lost device {path}: {exc}")
            return


def _maybe_reload(vs):
    """One reload check mirroring veloscroll._maybe_reload_config (veloscroll.py:806) — but printed unconditionally, since this is a terminal tool."""
    try:
        st = os.stat(vs.CONFIG_PATH)
    except OSError:
        if vs._cfg_stat is not None:              # was present, now gone — say so once
            _line("config file missing — keeping current values")
            vs._cfg_stat = None
        return
    cur = (st.st_mtime_ns, st.st_size)
    if cur == vs._cfg_stat:
        return
    vs._cfg_stat = cur                            # update before parsing: a rejected parse is not retried until the file changes again
    try:
        values = vs.load_config()
    except vs.ConfigError as exc:
        _line(f"config reload rejected, keeping current values: {exc}")
        return
    errors = vs.check_config(values)
    if errors:
        _line("config reload rejected, keeping current values: " + "; ".join(errors))
        return
    changed = vs.apply_values(values)             # takes vs.lock internally; in-progress holds keep their accumulators while thresholds/counts switch to the new values immediately (daemon semantics)
    if changed:
        _line("config reloaded: " + ", ".join(f"{k} {o!r}->{n!r}" for k, o, n in changed))


def _reload_poller(vs, stop):
    """1 s hot-reload loop; exits on the shared stop event."""
    while not stop.is_set():
        if stop.wait(1.0):
            return
        _maybe_reload(vs)


def _wait_for_matches(vs, stop):
    """Rescan every 2 s like the supervisor until a match appears; None if stopped first (Ctrl-C -> exit 130)."""
    announced = False
    while not stop.is_set():
        try:
            matches = vs.find_matches()
        except Exception as exc:
            print(f"scan failed: {exc}")          # same wording as the daemon's supervisor; scan again next round
            matches = set()
        if matches:
            return sorted(matches)
        if not announced:                         # like the supervisor's first-scan line, said once per waiting episode
            print("no matching device yet — waiting")
            announced = True
        stop.wait(2.0)
    return None


def _make_ui(vs, dev):
    """One temporary pass-through virtual mouse for all grabbed devices, advertising the first grab's USB IDs (mirrors sync_virtual_device)."""
    try:
        return UInput(vs.cap, name=vs.VIRTUAL_NAME, vendor=dev.info.vendor, product=dev.info.product, version=dev.info.version)
    except OSError as exc:
        raise SetupError(f"could not create the pass-through virtual mouse at /dev/uinput: {exc}")


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="veloscroll_tuning_helper.py",
        description="Manual tuning aid for veloscroll: with the daemon stopped, grabs the configured mouse and measures your real hand movement "
                    "(deadzone/full-rate distances in inches + counts, would-be target rate) so you can set DEADZONE_IN/FULL_IN (+ _H), sanity-check DPI, "
                    "and judge MAX_RATE/MIN_RATE/CURVE. Never emits scroll; hot-reloads config.ini like the daemon.")
    parser.add_argument("--config", metavar="PATH",
                        help="path to config.ini (default: $VELOSCROLL_CONFIG or /etc/veloscroll/config.ini)")
    args = parser.parse_args(argv)

    if args.config:
        os.environ["VELOSCROLL_CONFIG"] = args.config   # veloscroll reads it at import time; the explicit flag wins over the env var
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        import veloscroll as vs      # also loads/validates config.ini on import — fail-fast like veloscroll_preset.py (module-level load is intended)
    except ImportError as exc:
        print(f"veloscroll-tuning-helper: cannot import veloscroll (is evdev installed? see README): {exc}", file=sys.stderr)
        return 1

    for name in dir(e):              # reverse map over the BTN_* ecodes for the banner / press lines
        if name.startswith("BTN_"):
            code = getattr(e, name)
            if isinstance(code, int):
                _BTN_NAMES.setdefault(code, name)

    try:
        vs.apply_values(vs.load_config())   # startup apply (the import already did it; re-applying keeps every effective value + derived count identical to the daemon's)
    except vs.ConfigError as exc:           # unreachable in practice — a bad config already exits during the import above
        print(f"veloscroll-tuning-helper: {exc}", file=sys.stderr)
        return 1

    stop = threading.Event()

    def _on_signal(signum, frame):
        stop.set()
    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    if vs._cfg_load_info is not None:
        path, n = vs._cfg_load_info
        print(f"config: {path} ({n} override(s))")
    else:
        print(f"config: built-in defaults — no config.ini at {vs.CONFIG_PATH}")
    print(f"note: inch readouts are only as good as the DPI key (DPI = {_num(vs.DPI)})")

    devs, ui, threads = [], None, []
    code = 0
    try:
        matches = _wait_for_matches(vs, stop)
        if matches is None:                      # Ctrl-C while waiting for a device
            return 130
        for path in matches:                     # grab every matching device (like the daemon); any failure aborts with exit 1
            try:
                dev = evdev.InputDevice(path)
            except OSError as exc:
                if exc.errno in (errno.EACCES, errno.EPERM):
                    raise SetupError(f"{path}: no permission: run as root or add user to input group")
                raise SetupError(f"could not open {path}: {exc}")
            try:
                dev.grab()
            except OSError as exc:
                if exc.errno == errno.EBUSY:     # daemon or any other grabbing tool holds it
                    raise SetupError(f"{path}: device busy — sudo systemctl stop veloscroll, then re-run this helper")
                raise SetupError(f"{path}: no permission: run as root or add user to input group")
            devs.append((path, dev))
        ui = _make_ui(vs, devs[0][1])

        for path, dev in devs:
            print(f"grabbed {path} {dev.name}")
        dz_h = f"= {_num(vs.DEADZONE_IN_H)} in ({_num(vs.DEADZONE_H)} counts)" if vs.DEADZONE_IN_H is not None else "falls back to vertical"
        full_h = f"= {_num(vs.FULL_IN_H)} in ({_num(vs.FULL_H)} counts)" if vs.FULL_IN_H is not None else "falls back to vertical"
        print(f"DEADZONE_IN = {_num(vs.DEADZONE_IN)} in ({_num(vs.DEADZONE)} counts) | FULL_IN = {_num(vs.FULL_IN)} in ({_num(vs.FULL)} counts)")
        print(f"DEADZONE_IN_H {dz_h} | FULL_IN_H {full_h}")
        btn = _btn_name(vs.SCROLL_BTN)
        print(f"SCROLL_BTN = {btn + ' / ' if btn else ''}{vs.SCROLL_BTN}")
        if vs.SCROLL_BTN_H is None:
            print("SCROLL_BTN_H = none (horizontal scrolling disabled)")
        else:
            bth = _btn_name(vs.SCROLL_BTN_H)
            print(f"SCROLL_BTN_H = {bth + ' / ' if bth else ''}{vs.SCROLL_BTN_H}")
        print("hold the button and move; Ctrl-C quits")

        threads = [threading.Thread(target=_reader, args=(vs, path, dev, ui, stop), daemon=True) for path, dev in devs]
        threads.append(threading.Thread(target=_reload_poller, args=(vs, stop), daemon=True))
        for t in threads:
            t.start()
        stop.wait()                              # block until Ctrl-C / SIGTERM
    except SetupError as exc:
        print(f"veloscroll-tuning-helper: {exc}", file=sys.stderr)
        code = 1
    finally:
        for path, dev in devs:                   # release every grab so the mouse is immediately usable again
            try: dev.ungrab()
            except OSError: pass
            try: dev.close()
            except OSError: pass
        if ui is not None:
            try: ui.close()
            except OSError: pass
        for t in threads:                        # let "lost device" lines land before the reminder; no thread writes during finalization
            t.join(2.0)
        print("veloscroll is not running — restart when done: sudo systemctl start veloscroll")
    return code


if __name__ == "__main__":
    sys.exit(main())
