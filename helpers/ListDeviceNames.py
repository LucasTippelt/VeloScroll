#!/usr/bin/env python3

# VeloScroll — list all input devices with their names and USB IDs (for setting DEVICE_MATCH / NAME_MATCH)
# Copyright (C) 2026 Lucas Tippelt
# SPDX-License-Identifier: GPL-3.0-or-later
# Full license: https://www.gnu.org/licenses/gpl-3.0.html
#
# Standalone replacement for the inline snippet in README "Finding your device name & activation button":
# prints every /dev/input/event* node with its name and USB vendor/product ID pair, so you can read off
# DEVICE_MATCH (the exact `0x46d, 0xc084` pair) or a NAME_MATCH fragment:
#
#     sudo python3 /opt/veloscroll/helpers/ListDeviceNames.py
#
# Run as root, or as a user in the input group — devices you can't open are skipped with a note on stderr.

import argparse
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="ListDeviceNames.py",
        description="List all /dev/input/event* devices with their name and USB vendor/product ID pair "
                    "(for DEVICE_MATCH / NAME_MATCH in config.ini).")
    args = parser.parse_args(argv)

    try:
        import evdev
    except ImportError as exc:
        print(f"list-device-names: cannot import evdev (is it installed? see README): {exc}", file=sys.stderr)
        return 1

    found = False
    for path in evdev.list_devices():
        try:
            d = evdev.InputDevice(path)
        except OSError as exc:
            print(f"list-device-names: skipping {path}: {exc}", file=sys.stderr)
            continue
        print(f"{path} -> {d.name} {hex(d.info.vendor)} {hex(d.info.product)}")
        found = True
    if not found:
        print("list-device-names: no readable input devices", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
