# Logitech PRO X (G Pro X Superlight, wireless)

Hardware notes for [VeloScroll](../../README.md): how to identify this mouse and which button keycodes it emits. All values below were read from a live system on 2026-10-28 — device IDs from the evdev capability masks, side-button mapping confirmed by capturing actual evdev events (see "Verify"). Re-verify for your own setup before trusting them (firmware/receiver differences can change codes).

## Device identification

| Property | Value |
| --- | --- |
| evdev name (`/sys/class/input/event*/device/name`) | `Logitech PRO X` |
| USB vendor/product pair for `DEVICE_MATCH` | `0x46d, 0x4093` |
| Connection | Lightspeed USB receiver — the input device re-reports the *mouse's* IDs above; the receiver itself is a separate USB device with its own PID (observed: `0xc547`, `0xc53a`) and must not be matched on |

- **Recommended:** `DEVICE_MATCH = 0x46d, 0x4093` in `/etc/veloscroll/config.ini` — stable across reboots and USB ports.
- `NAME_MATCH` fallback fragment: `Logitech PRO X` (only unique if no other Logitech mouse is connected).

## Buttons

Physical mapping confirmed by capturing live evdev events (press each side button once, read the code):

| Button | Code | Decimal |
| --- | --- | --- |
| Left click | `BTN_LEFT` | 272 |
| Right click | `BTN_RIGHT` | 273 |
| Scroll wheel / middle click | `BTN_MIDDLE` | 274 |
| Side button closest to the user (lower) | `BTN_SIDE` | 275 |
| Side button further from the user (upper, front-facing) | `BTN_EXTRA` | 276 |

Both units also advertise `BTN_FORWARD` (277), `BTN_BACK` (278) and `BTN_TASK` (279) in their capability masks (`/sys/class/input/event*/device/capabilities/key`), but no physical button on this mouse emits them — the receiver advertises a broad block. So:

- The code defaults in veloscroll.py work out of the box for this mouse: `SCROLL_BTN = BTN_SIDE` (lower side button) + `DISABLED_BTN = BTN_EXTRA` swallows the upper side button so it does nothing while you use the lower one to scroll.
- If you'd rather keep both side buttons functional, set `DISABLED_BTN = none`.
- **Horizontal velocity scrolling:** with `DISABLED_BTN = none`, setting `SCROLL_BTN_H = BTN_EXTRA` makes the upper side button horizontal velocity scroll — mouse X movement drives `REL_HWHEEL`/`REL_HWHEEL_HI_RES` through the same ramp, and both side buttons stay active. Intended direction: hand right scrolls right. *Not yet verified on this mouse* (no hardware access where this was written) — hold it and pan in a browser to confirm; if inverted, note that `INVERT` cannot fix it (it flips both axes): the direction comes from a one-line sign in veloscroll.py's ticker, so correcting it means editing code — an exception to the config.ini-only rule, and your edit will need re-applying after updates. Better: report what you observe as an issue so the upstream default can be fixed.


Wheel/axes: relative only (`REL_X`, `REL_Y`, vertical + horizontal wheel incl. hi-res variants; no absolute axes) — so the daemon's inch math depends entirely on `DPI`: set it to your *current* DPI (e.g. 1600, whatever Logi Options+ shows), not the maximum.

## Recommended config

```ini
DEVICE_MATCH = 0x46d, 0x4093
SCROLL_BTN = BTN_SIDE        # or whichever side button you confirm in Verify below
DISABLED_BTN = BTN_EXTRA     # swallow the upper side button; set none to keep it working
DPI = 1600                   # your current DPI setting
```

## Caveats — two identical mice

Identical units share the `0x46d, 0x4093` pair, so a pair match grabs **both** and they drive one shared virtual mouse (see README → [Finding your device name & activation button](../../README.md#finding-your-device-name--activation-button)). To pin exactly one:

- Use a port-pinned path string in `DEVICE_MATCH`, e.g. `/dev/input/by-path/pci-0000:12:00.0-usb-0:1.3:1.2-event-mouse` (observed on this system — keep that receiver in the same port).
- Don't rely on `/dev/input/by-id/` here: both receivers report the generic USB name "Logitech USB Receiver", so their `by-id` symlinks collide and only one node gets a link.

## Verify

List devices with IDs (find your mouse's event node):

```bash
sudo python3 -c "import evdev; [print(p, '->', d.name, hex(d.info.vendor), hex(d.info.product)) for p in evdev.list_devices() if (d := evdev.InputDevice(p))]"
```

(look for the line with your mouse's name and note its event node)

**Stop the daemon first** — `sudo systemctl stop veloscroll`. It exclusively grabs every device it matches, so while it runs no other reader receives events from those nodes (the capture below would just block forever). Start it again afterwards with `sudo systemctl start veloscroll`.

Press each side button once and read off its code (Ctrl-C to stop):

```bash
sudo python3 - <<'EOF'
import evdev
path = "/dev/input/eventX"  # replace with your mouse's node from the list above
dev = evdev.InputDevice(path)
print("press each side button once; Ctrl-C to stop")
for ev in dev.read_loop():
    if ev.type == 1:   # EV_KEY only
        print(ev.code, ev.value)
EOF
```
