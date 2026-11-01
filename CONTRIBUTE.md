# Contributing

Bug reports, feature requests, and pull requests are welcome — open an [issue](https://github.com/LucasTippelt/VeloScroll/issues) for anything that isn't a just adding documentation first. Doc-only pull requests are especially appreciated: the more distros/desktop environments/mice with verified documentation, the better.

## 1. Bug reports

- File an issue first — describe your setup (distro, desktop environment, X11 or Wayland), what you expected, and what happened (`journalctl -u veloscroll` output helps a lot).
- A pull request with the fix is welcome too; small, focused changes are easiest to review.

## 2. Feature requests

- File an issue first — describe your idea, the why (and the how if you can)
- If you can implement and test it yourself, that's even better, keep it to one feature per Issue/Pull-Request

## 3. Adding a Preset to the example folder

- Explain the usecase and recommended loadgroup for the new preset in [docs/TUNING.me](docs/TUNING.me)
- Add it to the table in [docs/TUNING.me](docs/TUNING.me) 
- Add the new Preset in [presets.example](presets.example)
- Open a pull request directly, I see no need to discuss this in an Issue first

## 4. Desktop environment guides — `docs-desktop/`

- If you want to validate/test VeloScroll on your distro and desktop environment, write up what worked as a guide in `docs-desktop/<de-name>.md`
- Follow the existing documentation as the template: step-by-step from an empty system to a verified running daemon (install dependencies → install unit → find device & button → configure → (if needed) seed pointer settings → verify)
- Any DE-specific tuning notes and caveats
- Open a pull request directly, I see no need to discuss this in an Issue first

## 5. Hardware documentation — `docs-hardware/`

If you want to contribute the hardware details (device name, USB IDs, button mappings) of your specific mouse:

- Use the file structure convention `docs-hardware/<manufacturer>/<device_name>.md` — lowercase manufacturer directory, device filename matching the mouse's evdev-reported name.
- Fill it in using [logitech/Logitech_PRO_X.md](docs-hardware/logitech/Logitech_PRO_X.md) as a worked example: reported device name and USB ID pair (for `DEVICE_MATCH`), which button keycodes the device actually emits, recommended `SCROLL_BTN`/`SCROLL_BTN_H`.
- Verify everything against your own system — the Installation Guide's "Finding your device name & activation button" section has the exact commands.
- Open a pull request directly, I see no need to discuss this in an Issue first
