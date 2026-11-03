# TUNING — feel presets (starting points)

Starting points for the four "feel" keys (`MAX_RATE`, `MIN_RATE`, `CURVE`, `OUT_SMOOTH`), organized by use case. To apply a preset, set those four keys in `/etc/veloscroll/config.ini`; changes hot-reload within ~2 s — verify with `journalctl -u veloscroll` (a `config reloaded:` line shows old→new per key). Or apply one of the six bundled feel presets (`presets.example/{balanced,fast,precise,cruising,firefox,snappy}.ini`, copy into `/etc/veloscroll/presets/`) in one command — e.g. `sudo python3 /usr/lib/veloscroll/veloscroll_preset.py loadfeel fast` (the deployed copy — see [Installation](INSTALL.md#installation) step 4; with a per-user `VELOSCROLL_CONFIG` the repo's script works too, since nothing elevated runs). There is also one bundled *use-case* preset that configures both axes at once — [Two vertical modes](#two-vertical-modes). The bundled presets carry the four feel keys only, so your distance keys (`DEADZONE_IN`/`FULL_IN` + `_H`) stay per-user — to apply them from a preset, save one yourself with `save` (it captures every daemon key) and run `loaddistances <name>`.

## Presets

| Case | MAX_RATE | MIN_RATE | CURVE | OUT_SMOOTH | DEADZONE_IN | FULL_IN |
| --- | --- | --- | --- | --- | --- | --- |
| Balanced | 130.0 | 4.0 | 0.5 | 0.8 | | |
| Fast | 220.0 | 6.0 | 0.35 | 0.9 | | |
| Precise | 45.0 | 2.0 | 1.6 | 0.5 | | |
| Cruising | 90.0 | 3.0 | 1.2 | 0.65 | | |
| Snappy | 160.0 | 8.0 | 1.0 | 1.0 | | |
| Firefox | 158.0 | 1.5 | 0.85 | 0.9 | 0.0075 | 1.1 |

**Balanced is the shipped default** (the built-in fallbacks in `veloscroll.py`, mirrored in `config.ini.example`) — your reference point for "what did I change". This row intentionally tracks those code defaults; if they ever change, update it here too. Apply every tweak via `/etc/veloscroll/config.ini` — do not edit `veloscroll.py`: local edits are lost (or conflict) on the next update.

## The cases

### Balanced
The out-of-the-box feel: a middle-ground combination where no single knob dominates. Use it as the anchor when judging any other preset or your own tweaks. If something feels off, start with `MAX_RATE` (overall speed) before touching the ramp shape.

### Fast
For long documents and big lists. The high ceiling (`MAX_RATE` 220) does most of the work; low `CURVE` (0.35 < 1) makes the ramp steep near the start so small movements reach speed quickly, and the higher floor (`MIN_RATE` 6) avoids a crawl at the start. If it's too fast: lower `MAX_RATE` before touching `CURVE`.

### Precise
For spreadsheets, code, and small UIs. The low ceiling (45) is the main effect; high `CURVE` (1.6 > 1) keeps the ramp gentle near the start (forgiving), and heavy smoothing (`OUT_SMOOTH` 0.5) damps jitter. If it still feels jittery: lower `OUT_SMOOTH` further or raise `CURVE`.

### Cruising
For long reading sessions: a moderate pace (90) with a forgiving ramp (1.2 > 1) and smooth output (0.65). No single knob dominates — it's the "comfortable middle" between Fast and Precise. If it feels sluggish mid-session, raise `MAX_RATE`; if you overshoot easily, lower `OUT_SMOOTH`.

### Snappy
For deliberate movements with minimal lag: instant rate tracking (`OUT_SMOOTH` 1.0 = no smoothing at all — the rate jumps straight to its target each tick), a linear reference curve (1.0), and a high floor (8) so small moves already scroll meaningfully. If it feels jumpy, lower `OUT_SMOOTH` to ~0.9 — that's the only knob controlling how quickly the rate follows.

### Firefox
An approximation of the Firefox Autoscroll behavior, not 1 to 1 identical. Tune `DEADZONE_IN` and `FULL_IN` according to your mouse/desk setup.

### Two vertical modes
Two velocity scrolls on one mouse, both vertical: `SCROLL_BTN` at a slow-to-medium pace (the Cruising values) for reading, and `SCROLL_BTN_H` with `VERTICAL_H = true` at a medium-to-fast pace (the Fast values) for quick page jumps — e.g. main button vs thumb button.

| Axis | MAX_RATE | MIN_RATE | CURVE | OUT_SMOOTH |
| --- | --- | --- | --- | --- |
| Vertical (`SCROLL_BTN`) | 90.0 | 3.0 | 1.2 | 0.65 |
| H axis (`SCROLL_BTN_H`, `VERTICAL_H = true`) | 220.0 | 90.0 | 0.35 | 0.9 |

Unlike the feel cases above, this is a dual-axis setup: it sets both ramps plus `VERTICAL_H` in one file ([`presets.example/two-vertical.ini`](../presets.example/two-vertical.ini)), so apply it with `loadall`, not `loadfeel`:

```bash
sudo python3 /usr/lib/veloscroll/veloscroll_preset.py loadall two-vertical
```

The distance keys (`DEADZONE_IN`/`FULL_IN`) are deliberately not part of the preset — set them once per machine. To change the pace split, edit the eight feel values in the preset file or build your own with `save`. See [PRESETS.md](PRESETS.md#two-vertical-modes-use-case).

## Knob refresher

- `MAX_RATE` — notches/second at FULL_IN and beyond: your top scrolling speed.
- `MIN_RATE` — notches/second just past the deadzone: the floor of the ramp, keep > 0.
- `CURVE` — shape of the speed ramp: <1 steep near the start, =1 linear reference, >1 gentle near the start.
- `OUT_SMOOTH` — 0..1 how quickly the rate follows the target: lower = smoother, higher = snappier (1.0 = instant tracking).

For the full key list with tuning hints, see [Customize and reload](CONFIGURATION.md#customize-and-reload) in the configuration guide.

## Horizontal scrolling (optional)

The presets above tune the vertical ramp. If you use `SCROLL_BTN_H`, horizontal scrolling reuses those same values unless overridden by the per-axis variants: `DEADZONE_IN_H`, `FULL_IN_H`, `MIN_RATE_H`, `MAX_RATE_H`, `CURVE_H`, `OUT_SMOOTH_H`. Each key falls back independently to its vertical counterpart when unset or set to `none` — e.g. setting only `DEADZONE_IN_H` changes just the horizontal deadzone while the rest of the ramp stays vertical. To give horizontal scrolling a different feel, pick one of the cases above and set that case's values as the corresponding `*_H` keys (all hot-reload like the vertical ones). With `VERTICAL_H = true`, these `_H` values instead drive a second *vertical* velocity scroll on SCROLL_BTN_H (up/down movement, REL_WHEEL output) rather than horizontal — the bundled [`two-vertical`](../presets.example/two-vertical.ini) preset is exactly that use case (slow-to-medium vertical + medium-to-fast vertical), see [PRESETS.md](PRESETS.md#two-vertical-modes-use-case).

## A note on DPI

These four keys need no per-DPI variants: `DEADZONE_IN`/`FULL_IN` are in inches and converted by your `DPI` setting (`veloscroll.py`: `DEADZONE = DEADZONE_IN * DPI`, `FULL = FULL_IN * DPI`), so the ramp against physical hand movement is identical at any DPI; `OUT_SMOOTH` acts per tick, not per distance. If you want a different *physical* ramp distance, adjust `DEADZONE_IN`/`FULL_IN` (not covered here). Make sure `DPI` itself is set to your mouse's current DPI setting, not its maximum.

## Starting points, not verified values

These are starting points to tune by feel — they have not been verified on any particular setup or hardware. All four keys hot-reload within ~2 s, so experimenting is cheap; a malformed edit is rejected and the previous values stay in effect (one `config reload rejected` line in `journalctl -u veloscroll`). For the physical distance keys (`DEADZONE_IN`/`FULL_IN` + `_H`) you can measure your real hand movement instead of guessing: run the tuning aid `veloscroll_tuning_helper.py` with the daemon stopped and read off the exact inches where you cross the deadzone and reach full rate (README, "Tuning aid").
