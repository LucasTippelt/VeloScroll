#!/usr/bin/env python3

# VeloScroll — print every key event a device emits, so you can read off button codes (for SCROLL_BTN & co.)
# Copyright (C) 2026 Lucas Tippelt
# SPDX-License-Identifier: GPL-3.0-or-later
# Full license: https://www.gnu.org/licenses/gpl-3.0.html
#
# Standalone replacement for the inline snippet in README "Finding your device name & activation button":
# opens /dev/input/event<N> and prints every key event as `code value` while you press buttons — movement/
# scroll events are filtered out, Ctrl-C stops:
#
#     sudo python3 /opt/veloscroll/helpers/ListButtonPresses.py 30     # -> /dev/input/event30
#     sudo python3 /opt/veloscroll/helpers/ListButtonPresses.py /dev/input/by-id/...   # a full path works too
#
# Run as root, or as a user in the input group.

import argparse
import errno
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="ListButtonPresses.py",
        description="Print every key event (code value) that an input device emits while you press its buttons "
                    "(for SCROLL_BTN / SCROLL_BTN_H / DISABLED_BTN in config.ini); movement and scroll events are filtered out.")
    parser.add_argument("device", metavar="EVENT_NUMBER_OR_PATH",
                        help="event number of the mouse node from ListDeviceNames.py (30 -> /dev/input/event30) or a full device path")
    args = parser.parse_args(argv)

    if args.device.startswith("/"):
        path = args.device
    else:
        try:
            n = int(args.device)
        except ValueError:
            print(f"list-button-presses: {args.device!r} is neither an event number nor a device path", file=sys.stderr)
            return 1
        path = f"/dev/input/event{n}"

    try:
        import evdev
        from evdev import ecodes as e
    except ImportError as exc:
        print(f"list-button-presses: cannot import evdev (is it installed? see README): {exc}", file=sys.stderr)
        return 1

    try:
        dev = evdev.InputDevice(path)
    except OSError as exc:
        if exc.errno in (errno.EACCES, errno.EPERM):
            print(f"list-button-presses: {path}: no permission: run as root or add user to input group", file=sys.stderr)
        else:
            print(f"list-button-presses: could not open {path}: {exc}", file=sys.stderr)
        return 1

    print("press the candidate side buttons; Ctrl-C to stop")
    try:
        for ev in dev.read_loop():
            if ev.type == e.EV_KEY:   # EV_KEY only — movement/scroll events are filtered out
                print(ev.code, ev.value)
    except KeyboardInterrupt:         # clean exit on Ctrl-C (no traceback)
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
