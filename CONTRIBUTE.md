# Contributing

Bug reports, feature requests, and pull requests are welcome — open an [issue](https://github.com/LucasTippelt/VeloScroll/issues) for anything that isn't a code change yet. Doc-only pull requests are especially appreciated: the more distros/desktop environments/mice with verified documentation, the better.

There are three kinds of contributions so far:

## 1. Bug reports & feature requests

- File an issue first — describe your setup (distro, desktop environment, X11 or Wayland), what you expected, and what happened (`journalctl -u veloscroll` output helps a lot).
- A pull request with the fix is welcome too; small, focused changes are easiest to review.

## 2. Desktop environment guides — `docs-desktop/`

If you want to validate/test VeloScroll on your distro and desktop environment, write up what worked as a guide in `docs-desktop/<de-name>.md`, following [kde-plasma.md](docs-desktop/kde-plasma.md) as the template: step-by-step from an empty system to a verified running daemon (install dependencies → install unit → find device & button → configure → seed pointer settings → verify), plus any DE-specific tuning notes and caveats. A pull request containing only your new documentation is greatly appreciated.

## 3. Hardware documentation — `docs-hardware/`

If you want to contribute the hardware details (device name, USB IDs, button mappings) of your specific mouse:

- Use the file structure convention `docs-hardware/<manufacturer>/<device_name>.md` — lowercase manufacturer directory, device filename matching the mouse's evdev-reported name.
- Fill it in using [logitech/Logitech_PRO_X.md](docs-hardware/logitech/Logitech_PRO_X.md) as a worked example: how to find the device name and USB ID pair (for `DEVICE_MATCH`), which button keycodes the device actually emits, recommended `SCROLL_BTN`/`DISABLED_BTN`, and any caveats (e.g. two identical mice sharing one USB ID pair).
- Verify everything against your own system — the README's "Finding your device name & activation button" section has the exact commands; don't copy another mouse's values.
