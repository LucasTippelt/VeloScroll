# VeloScroll #
## TLDR ##

- VeloScroll is a small Linux daemon that turns one mouse button into completely-configurable variable-velocity hold-to-scroll.
- Both default **vertical scrolling** and optional **horizontal scrolling** (activated via a second mouse button) are supported.
- While you hold the button, moving the mouse scrolls at a speed proportional to your distance from the press point.
- When you release it, the mouse behaves exactly as normal. 
- It works under X11 and Wayland alike.
- **All configuration lives in `/etc/veloscroll/config.ini`** — hot-reloaded within ~2 s and survives updates. Do not edit `veloscroll.py` for your settings (see [Customize & reload](#customize--reload)).

## Compatibility ##

**Any Linux distro with a modern kernel (evdev + uinput support)**
There is no compositor dependency — the daemon operates below X11/Wayland via `/dev/input`, so behavior is identical under X11, Wayland, and any desktop environment (GNOME/KDE/XFCE/…).

## Permissions ## 
The primary install model runs as a root system unit → none needed. If you run it as a normal user instead, the user needs membership in the `input` group plus access to `/dev/uinput` (exact setup varies by distro). 

## Caveats ##

1) Only one process may exclusively grab a device at a time, so:
- **close other mouse utilities** (e.g. Logi Options+) before starting
- **or pass the virtual device of that mouse utility into VeloScroll** (if your specific mouse utility tool creates a virtual device). See [Finding your device name & activation button](#finding-your-device-name--activation-button).
2) If the daemon can't grab, it logs `device busy` and keeps retrying until the device frees up.
3) You might need to enable options like smooth scrolling/high res scrolling in Apps that support those (like browsers or certain terminals) 

## Dependencies ##

<details open>

<summary>Click here to open/hide.</summary>

#### Python 3 + evdev. ####

<details>

<summary>Click here to open/hide.</summary>

Distro packages:
  - Debian/Ubuntu: `sudo apt install python3-evdev`
  - Fedora: `sudo dnf install python3-evdev`
  - Arch: `sudo pacman -S python-evdev`
  - openSUSE: `sudo zypper in python3-evdev`
  - Fallback: pip inside a virtualenv (`python3 -m venv <dir>`, activate it, then `pip install evdev`).
    
</details>

#### systemd (soft dependency) ####

<details>

<summary>Click here to open/hide.</summary>

- The script can run standalone without it (python3 veloscroll.py), but the provided install path uses veloscroll.service, a root system unit for automatic restarts — so systemd is needed for that setup. 
- Per-user units (systemctl --user) also work but aren't covered here.
</details>
</details>

## Finding your device name & activation button ##

<details>

<summary>Click here to open/hide.</summary><br/>

List all input devices with their USB IDs (uses the evdev package you already installed):

```bash
sudo python3 -c "import evdev; [print(p, '->', d.name, hex(d.info.vendor), hex(d.info.product)) for p in evdev.list_devices() if (d := evdev.InputDevice(p))]"
```

- **HIGHLY Recommended: set `DEVICE_MATCH` in `/etc/veloscroll/config.ini` to your mouse's exact USB ID pair** — e.g. `DEVICE_MATCH = 0x46d, 0xc084`, read off from the last two columns above. It selects exactly one device (stable across reboots and USB ports), avoids grabbing other mice that share a name fragment, and maybe lets per-device pointer rules in your DE/WM apply to the virtual mouse automatically (see above, depends on how your DE/WM implemented per-device pointer rules).
- `NAME_MATCH` is a simpler fallback: any case-insensitive substring of your mouse's name from that list (e.g. `"Logitech Pro X"`); it is only used when `DEVICE_MATCH` is None, so make sure no other device shares the fragment or set `DEVICE_MATCH`.
- Alternative for names without Python: `/sys/class/input/event*/device/name`; stable symlinks with IDs: `ls -l /dev/input/by-id`.

**Rare edge case: Two of the same mouse** share one USB ID pair, so use a stable path string in `DEVICE_MATCH` instead — `/dev/input/by-id/usb-...-event-mouse` (only disambiguates if the device reports a serial number) or `/dev/input/by-path/pci-...-event-mouse`, which pins the mouse to its USB port (keep it plugged into the same port). Note that while several devices match, they are all grabbed and share one virtual mouse — holding the button on either drives scrolling from movement on either.

To find the activation button code, open your device and print every event — press the candidate side buttons and read off their codes (Ctrl-C to stop):

```bash
sudo python3 - <<'EOF'
import evdev
path = "/dev/input/eventX"  # replace with your mouse's node from the list above
dev = evdev.InputDevice(path)
print("press the candidate side buttons; Ctrl-C to stop")
for ev in dev.read_loop():
    print(ev.type, ev.code, ev.value)
EOF
```

Common button keycodes (`ev.type` 1 = EV_KEY):

| Button | Code | evdev constant |
| --- | --- | --- |
| BTN_LEFT | 272 | `e.BTN_LEFT` |
| BTN_RIGHT | 273 | `e.BTN_RIGHT` |
| BTN_MIDDLE | 274 | `e.BTN_MIDDLE` |
| BTN_SIDE | 275 | `e.BTN_SIDE` |
| BTN_EXTRA | 276 | `e.BTN_EXTRA` |
| BTN_FORWARD | 277 | `e.BTN_FORWARD` |
| BTN_BACK | 278 | `e.BTN_BACK` |
| BTN_TASK | 279 | `e.BTN_TASK` |

The constants are available as `evdev.ecodes.BTN_*`; in `/etc/veloscroll/config.ini` use the bare name or decimal code (e.g. `SCROLL_BTN = BTN_SIDE` or `SCROLL_BTN = 275`). Set these in config.ini, not in veloscroll.py.

### Mice with more buttons than these Buttons ###

<details open>

<summary>Click here to open/hide.</summary><br/>

VeloScroll gives each button at most one role; every other event is forwarded to the virtual mouse unchanged:

- **`SCROLL_BTN`** — one code you hold to scroll. Its press and release are consumed by the daemon and never reach the OS, so while veloscroll runs that button no longer performs its normal click action.
- **`SCROLL_BTN_H`** — optional second code held for horizontal velocity scrolling (mouse X movement drives `REL_HWHEEL`/`REL_HWHEEL_HI_RES` through the vertical ramp, unless overridden by the per-axis keys below); set `none` to disable this feature.
- **`DISABLED_BTN`** — optionally a second code that is swallowed entirely (does nothing); set `none` to disable this feature.
- **All remaining buttons pass through as-is**, whatever their codes.

Note the virtual device only advertises seven button capabilities — `BTN_LEFT`, `BTN_RIGHT`, `BTN_MIDDLE`, `BTN_SIDE`, `BTN_EXTRA`, `BTN_FORWARD`, `BTN_BACK` (the `cap` dict at the top of veloscroll.py). The kernel still delivers events for other codes to your compositor, but standard desktops only map a handful of button codes, so extra buttons on many-button mice — top/DPI buttons or media keys, often reported as `BTN_TASK`, `BTN_5`–`BTN_9` or keyboard/media keycodes — may do nothing. To make such a button work under veloscroll you must add its code to the `EV_KEY` list in `cap` at the top of `veloscroll.py`, then restart (`sudo systemctl restart veloscroll`) — a deliberate exception to the config.ini-only rule below, since it cannot be expressed as a config key; expect to re-apply this edit after updates.

- **Set `DEVICE_MATCH` to your mouse's USB ID pair from the list above (or fall back to a unique name fragment in `NAME_MATCH`) and your preferred scroll button to `SCROLL_BTN` — in `/etc/veloscroll/config.ini`, not in veloscroll.py.**

</details>

### Feeding another tool's virtual device into VeloScroll instead ###

<details open>

<summary>Click here to open/hide.</summary><br/>

VeloScroll doesn't care where events come from — any evdev input node that advertises `REL_X` and matches your selector is a valid source, including uinput devices created by other tools (e.g. the virtual mouse of [input-remapper](https://github.com/sezanzeb/input-remapper)). The pipeline becomes: physical mouse → remapper (exclusively grabs it) → its virtual device → veloscroll → `veloscroll-mouse`.

- Point your selector at the *virtual* node, not the physical one — a `NAME_MATCH` fragment of the remapper's device name is the stable option (uinput devices get no USB `by-id`/`by-path` links on most systems, and bare `/dev/input/eventN` numbers change across reboots).
- If your selector also matches the physical mouse (the remapper's forwarding clone keeps the source's name and often its USB IDs), veloscroll grabs the virtual node and logs periodic `device busy` lines for the physical one the remapper holds — harmless but noisy.
- Start order: enable the remapper before starting veloscroll, so it wins the grab on the physical mouse; a remapper started later is picked up automatically on the next ~2 s scan (no restart).
- `SCROLL_BTN`/`DISABLED_BTN` accept any code the remapper emits; pass-through buttons are still subject to [the seven advertised button capabilities](#mice-with-more-buttons-than-that); relative motion passes through unscaled, so the same `DPI` value applies.

**Tested: no.** This combination is supported by design but has not been verified end-to-end with input-remapper or any other remapper — report what you find back in an issue/PR.

</details>

</details>

## Installation (General Guide) ##

<details open>

<summary>Click here to open/hide.</summary><br/>

1. Install Python 3 + evdev for your distro (see Dependencies above for Distro specific command).
2. Git Clone the project to a stable location (`/opt/veloscroll`) 
3. Create the config file from the bundled example:

   ```bash
   sudo mkdir -p /etc/veloscroll && sudo cp /opt/veloscroll/config.ini.example /etc/veloscroll/config.ini
   ```
 Then point it at your mouse (set `DEVICE_MATCH` to its USB ID pair and `DPI` to its current DPI; see [Finding your device name & activation button](#finding-your-device-name--activation-button))

4. **IF YOU ARE UNSURE ABOUT THIS, SKIP THIS STEP. It's not required**.
   
If your Desktop Environment has per Device Pointer settings:
Seed the per-device pointer settings via your desktop environment's guide (if present) so that `veloscroll-mouse` starts out feeling exactly like your real mouse (**run as your user, not root**). If your desktop environment is not yet supported with `veloroll_seed.py` instructions, don't worry (we will come back to this in Step 7).

5. Install `veloscroll.service` as a root system unit by copying it into `/etc/systemd/system/`
6. Run `sudo systemctl daemon-reload` and enable  with `sudo systemctl enable --now veloscroll`
7. Verify — `journalctl -u veloscroll` should show a line like `grabbed <path> <device name>`. 
*If step 4 applied to you (you have per device pointer settings and no `veloroll_seed.py` support)*, go into your system settings and change `veloscroll-mouse` settings to your liking (once, should get saved by your DE). 
8. Tweak `/etc/veloscroll/config.ini` to your preference. See [config.ini keys (hot-reloaded)](#configini-keys-hot-reloaded)

Follow your desktop environment's guide end-to-end for the full commands and explanations:

| Desktop environment | Guide |
| --- | --- |
| KDE Plasma (5/6, X11 or Wayland) | [docs-desktop/kde-plasma.md](docs-desktop/kde-plasma.md) |
| Fedora Workstation 44 (GNOME) | [docs-desktop/gnome.md](docs-desktop/gnome.md) |
| Cinnamon | [docs-desktop/cinnamon.md](docs-desktop/cinnamon.md) |

- Seeding is currently supported on KDE Plasma (Wayland) only. *(X11 has Global Pointer Settings)*
- **On desktop environments with Global Pointer Settings running veloscroll_seed.py is not neccessary** — your pointer settigns should just stay consistent out of the box.
- If your Desktop Environment has **Per Device Pointer Settings** and **seeding is not supported**, adjust the pointer settings for the Virtual Device (default name is veloscroll-mouse) in your system settings once after install so they match how your actual mouse feels (one-time setup). 

### veloscroll_seed.py options ###

<details>

<summary>Click here to open/hide.</summary><br/>

Run as your desktop user (**not** root — as root it would target `/root/.config`). All modes operate on KDE Plasma's `kcminputrc` (currently the only implemented backend):

| Option | Effect |
| --- | --- |
| *(none)* | **Seed** — copy your real mouse's per-device pointer settings into a matching `[Libinput][<vendor>][<product>][veloscroll-mouse]` group, then apply them to the running session via KWin's D-Bus interface |
| `--name <NAME>` | Select the real mouse by case-insensitive substring of its device name instead of `DEVICE_MATCH` (IDs are taken from that device's uevent); combines with any mode below |
| `--apply-only` | **Apply** — push the existing `veloscroll-mouse` group to the running session without re-seeding or modifying the file (e.g. after hand-editing it) |
| `--remove-stale-config` | **Clean up** — delete `[Libinput][…][veloscroll-mouse]` groups that don't match your current mouse's USB IDs (dead config from old mice / pre-ID-copy runs), writing a `.bak-*` backup first |

`--apply-only` and `--remove-stale-config` are combinable in one run — apply happens first, then removal. All modes are idempotent; re-running is always safe.

**Backups:** a backup of the config file (`~/.config/kcminputrc.bak-<timestamp>`) is written only when seed or `--remove-stale-config` actually changes it — so **on KDE Plasma only** (the only backend with per-device settings; on other desktops veloscroll never writes any config file, hence no backups), and not by runs where nothing changed nor by `--apply-only`. Each backup keeps the previous state recoverable; cap how many are kept with `MAX_BACKUPS`, a seed-script constant at the top of veloscroll.py that is intentionally not hot-reloadable (default -1 = keep all — see the Advanced notes under [Customize & reload](#customize--reload)).

</details>

</details>

## Latency & debugging ##

<details>

<summary>Click here to open/hide.</summary><br/>

Where does time go when you hold the button? The pipeline, and what each segment is responsible for:

```
mouse → kernel evdev → veloscroll run() thread → ticker (TICK, default 250 Hz) → uinput veloscroll-mouse → compositor → app
└─────────── input delivery ───────────┘└──────────── daemon: ticker + emit ────────────┘└──────── out of scope ────────┘
```

- **Input delivery** — USB polling interval, kernel scheduling delays, and any CPU work before the daemon's read loop runs. Measured from the kernel event timestamp to arrival in the daemon (`input p50/p95/max`).
- **Daemon (ticker + emit)** — rate smoothing, tick quantization, and the `/dev/uinput` write cost (`tick period`, `overrun_max`, `press->emit`, `crossing->emit`, `uinput_write_max`).
- **Compositor → app** — rendering, frame pacing, and in-app scroll handling. Not observable from the daemon; if scrolling still looks laggy with healthy lines below, look here (frame rate, smooth-scroll settings in the app).

### Theoretical latency (model) ###

<details open>

<summary>Click here to open/hide.</summary><br/>

A model computed purely from config (`TICK`, `OUT_SMOOTH`, `MIN_RATE`) — the design-inherent floor, not a measurement. With T = TICK and S = OUT_SMOOTH:

- **Smoothing time constant** τ = T / (−ln(1 − S)) — how quickly the emitted rate follows your target speed. Default: ≈ 2.5 ms.
- **Response to sustained movement** (step change in target): ~T/2 + τ to reach 63% of the new rate, ~T/2 + 3τ for 95% (T/2 = average tick quantization delay). Defaults: ~4.5 ms / ~9.5 ms.
- **First emit after deadzone crossing**: simulated from the real ticker recurrence at MIN_RATE — with defaults the first notch lands on the very next tick, ≈ T/2 + (n−1)·T ≈ 2–6 ms (one tick).

Excluded from the model: USB polling/kernel delivery (covered by the measured `input` metric), deadzone travel time (how long *you* take to move past the deadzone — user-t), and compositor/app rendering. Real movement changes the target continuously, so t₆₃/t₉₅ are estimates for a step change; treat all of these numbers as model values, never as measurements.

</details>

### Enabling the measured lines ###

<details open>

<summary>Click here to open/hide.</summary><br/>

Set `LATENCY_LOG = True` in `/etc/veloscroll/config.ini`, then watch:

```bash
journalctl -u veloscroll -f
```

Hot-reloads like every other key (no restart). While there is activity, one summary line appears per second; a model line appears at startup and whenever `LATENCY_LOG` or any of `TICK`/`OUT_SMOOTH`/`MIN_RATE` changes. The lines are int of `LOG_LEVEL`.

Sample output:

```
latency model: tick=4.0ms tau=2.5ms -> 63% response ~4.5ms, 95% ~9.5ms; first emit after deadzone ~2-6ms (1 tick) [TICK/OUT_SMOOTH/MIN_RATE]
latency: input p50=2.1ms p95=8.4ms max=21.7ms n=1204 | tick period=4.0ms overrun_max=0.3ms overruns=1 | press->emit=7.8ms crossing->emit=3.9ms (n=3) | uinput_write_max=0.4ms
```

| Field | Meaning / typical value |
| --- | --- |
| `input p50/p95/max` | kernel timestamp → daemon arrival over the last 1 s; p50 ≈ your USB polling interval (1–8 ms); a high p95 points at USB/power/scheduler issues, not the daemon |
| `tick period` | actual ticker loop period — should sit at ≈ TICK (4.0 ms by default) |
| `overrun_max`, `overruns` | worst/number of ticks that woke late in the window; an occasional single-digit-ms blip is normal GIL/scheduler noise, sustained overruns mean CPU starvation |
| `press->emit` | button-down → first scroll event emitted (p50 per hold); includes your deadzone travel time — expect it to be larger than crossing→emit |
| `crossing->emit` | moment the distance first passed DEADZONE → first emit; isolates daemon latency from how fast you move — healthy systems stay within ~2 ticks (≤ 8 ms at default TICK) |
| `uinput_write_max` | slowest `/dev/uinput` write+syn in the window; single-digit milliseconds or less is normal |

</details>



### Troubleshooting ###

<details open>

<summary>Click here to open/hide.</summary><br/>

| Symptom | Likely cause |
| --- | --- |
| High `input p95` (p50 fine) | USB power management, flaky cable/port, kernel scheduler load — try another port/cable, disable USB autosuspend for the mouse |
| `tick period` > TICK or frequent overruns | CPU saturation or GIL stalls (e.g. config reloads, slow uinput writes); check system load and `uinput_write_max` |
| Large `press->emit`, small `crossing->emit` | Normal: you spent time moving past the deadzone — not a bug; lower DEADZONE_IN if starting feels slow |
| Healthy daemon lines but scrolling still looks laggy | Compositor/app side (frame pacing, app smooth-scroll settings) — out of scope for this daemon |

</details>
</details>

## Switching mice ##

1. Find the new mouse's USB ID pair (procedure in [Finding your device name & activation button](#finding-your-device-name--activation-button)).
2. In `/etc/veloscroll/config.ini`: set `DEVICE_MATCH` to the new pair; update `DPI` if it changed; re-check `SCROLL_BTN` only if the side-button behavior looks different on the new mouse.
3. No restart needed — the daemon applies the change within ~2 s and releases the old mouse automatically (`journalctl -u veloscroll` shows a `config reloaded:` line, then a new `grabbed ...`).
4. Re-run the pointer-settings seed for your desktop environment (see its guide) — note that this resets any tweaks made to `veloscroll-mouse` back to the new real mouse's values.
5. Verify: `journalctl -u veloscroll` shows `grabbed <path> <new device name>`.

## Customize & reload ##

**Do not edit `veloscroll.py` to change your settings.** Every daemon tunable can be set in `/etc/veloscroll/config.ini`, which is hot-reloaded within ~2 s and lives outside the repo — so your configuration survives updates. Local edits to `veloscroll.py` are lost (or conflict) on the next update, and require a manual restart anyway.

- Two config sources; per key, a non-empty value in `/etc/veloscroll/config.ini` overrides the built-in default at the top of `/opt/veloscroll/veloscroll.py`.
- **Editing `/etc/veloscroll/config.ini` is the only supported way to configure the daemon.**
- A missing or empty key falls back to the built-in default — every config.ini key exists in veloscroll.py as its fallback.

### config.ini keys (hot-reloaded) ###

<details>

<summary>Click here to open/hide.</summary><br/>

| Key | Meaning / units | Tuning hint |
| --- | --- | --- |
| `NAME_MATCH` | Case-insensitive substring of your mouse's name that selects it — used only when DEVICE_MATCH is None (fallback) | Use a short unique fragment from the device list above; if any other device shares it, prefer DEVICE_MATCH; **If you want to pipe another virtual device into VeloScroll this is the recommended option** |
| `DEVICE_MATCH` | **Recommended for physical device** precise selector that overrides NAME_MATCH: an exact USB ID pair (`0x46d, 0xc084`) or a stable path string (e.g. `/dev/input/by-id/...`) for two identical mice | Set it to your mouse's USB IDs — stable across reboots/ports and lets per-device pointer rules apply automatically; see[Finding your device name & activation button](#finding-your-device-name--activation-button) |
| `SCROLL_BTN` | Key code of the button to hold for scrolling (evdev name like `BTN_SIDE`, or decimal code, e.g. 275) | Find with the interactive snippet above; names are `evdev.ecodes.BTN_*` |
| `SCROLL_BTN_H` | Optional second button to hold for horizontal velocity scrolling — driven by mouse X movement (emits REL_HWHEEL/REL_HWHEEL_HI_RES), using the vertical ramp unless overridden by the horizontal keys; evdev name or decimal code, or `none` to disable (default) | Must differ from SCROLL_BTN and DISABLED_BTN; INVERT flips both axes — see hardware docs for direction notes |
| `DISABLED_BTN` | Key code that is swallowed and does nothing, or `none` to disable this feature | Set `none` if you don't want to disable a button |
| `DPI` | Your mouse's current DPI (counts/inch) — converts inches to raw counts | Set it to your mouse's *current* DPI setting, not its maximum |
| `DEADZONE_IN` | Distance from the press point (inches) below which nothing scrolls | Raise if scrolling starts before you've moved the mouse at all |
| `FULL_IN` | Distance (inches) from the press point where MAX_RATE is reached; must be > DEADZONE_IN | The span over which speed ramps up |
| `MAX_RATE` | Scroll rate in notches/second at FULL_IN and beyond | Your top scrolling speed |
| `MIN_RATE` | Scroll rate in notches/second just past the deadzone | The floor of the ramp; keep above 0 |
| `CURVE` | Shape of the speed ramp: >1 gentle near the start, =1 linear, <1 steep near the start | Tune feel: <1 reacts fast to small movements, >1 is more forgiving |
| `DEADZONE_IN_H` | Horizontal variant of DEADZONE_IN (inches), used only while SCROLL_BTN_H is held; unset or `none` falls back to the vertical value | Only if horizontal scrolling should start at a different distance than vertical |
| `FULL_IN_H` | Horizontal variant of FULL_IN; must be greater than the effective horizontal deadzone (per-key fallback) | The span over which horizontal speed ramps up |
| `MAX_RATE_H` | Horizontal variant of MAX_RATE; must be >= the effective horizontal MIN_RATE | Your top horizontal scrolling speed |
| `MIN_RATE_H` | Horizontal variant of MIN_RATE (notches/second); unset or `none` falls back to the vertical value | The floor of the horizontal ramp; keep > 0 |
| `CURVE_H` | Horizontal variant of CURVE (ramp shape); unset or `none` falls back to the vertical value | Tune horizontal feel: same semantics as CURVE |
| `OUT_SMOOTH` | 0..1 — how quickly the rate follows the target; lower = smoother, higher = snappier | Lower it if scrolling feels steppy or jumpy |
| `INVERT` | True/False — flip scroll direction | Set true if your DE has "natural scrolling" enabled |
| `TICK` | Ticker loop period in seconds; 0.004 s ≈ 250 Hz — how often the scroll rate is recomputed and hi-res events are emitted | Not a feel setting (that's OUT_SMOOTH/MAX_RATE); only lower it if scrolling still looks steppy, at the cost of more CPU |
| `LOG_LEVEL` | What the daemon writes to its log (`journalctl -u veloscroll`): integer 0..3, higher = more verbose — 0 errors only / 1 +events (grabbed …) / 2 +config detail (default: unknown keys ignored, reload rejected, config reloaded old→new) / 3 +debug | Set 0 on a healthy system for silence; raise to 3 temporarily when debugging device selection. Note: lowering below 2 also hides the `config reloaded:` confirmation line itself |
| `LATENCY_LOG` | True/False — per-second measured latency summary lines plus a computed model line at startup/config change; independent of LOG_LEVEL (see "Latency & debugging" above) | Debugging only: set true, watch `journalctl -u veloscroll`, then leave it false |

**Starting points:** for `MAX_RATE` / `MIN_RATE` / `CURVE` / `OUT_SMOOTH`, [TUNING.md](TUNING.md) has five ready-to-paste value sets by use case (balanced, fast, precise, cruising, snappy). They hot-reload like every other key — edit `/etc/veloscroll/config.ini`; applies live within ~2 s; verify with `journalctl -u veloscroll` as below.

</details>

### Advanced notes (not needed for normal use) ###

<details>

<summary>Click here to open/hide.</summary><br/>

Three constants at the top of `veloscroll.py` belong to `veloscroll_seed.py` and are intentionally not in config.ini. Only touch them if you maintain a fork or run an unusual setup — like every edit to veloscroll.py, changes need a restart (`sudo systemctl restart veloscroll`) and will be lost (or conflict) on the next update:

- `DE_WM` — which pointer-settings backend the seed script uses; supported values live in its backend registry (`BACKENDS`, currently only `kde-plasma`; per-DE guides: [docs-desktop/](docs-desktop/)). An unknown value makes the seed exit with an error listing the supported ones.
- `VIRTUAL_NAME` — name of the virtual device (default `veloscroll-mouse`), advertised together with your real mouse's USB IDs so per-device pointer rules apply to it automatically; the seed script looks for exactly this name, so keep the default unless you run several daemon instances side by side.
- `MAX_BACKUPS` — max number of `kcminputrc.bak-*` backups the seed keeps (only relevant on DEs with per-device settings); -1 = unlimited (default), N ≥ 1 = keep only the newest N after each run that writes a backup.

Also:

- Thanks to the supervisor loop, a matching device plugged in *after* startup is picked up automatically — no restart needed for hotplug.
- For tests or per-user setups you can point the daemon at another file: `VELOSCROLL_CONFIG=/path/to/config.ini python3 veloscroll.py`.

</details>

## Updating ##

There is no automatic update mechanism — when a new version is released, you have to fetch it yourself and restart the daemon:

1. **Verify what changed first.** The daemon runs as root, so treat an update like installing any other software: read the release notes / `git log --oneline` for the incoming commits, check whether `veloscroll.service`, dependencies (`python3-evdev`), or behavior changed, and review any diff you don't recognize before running it.
2. Update the code in `/opt/veloscroll`:

   ```bash
   sudo git -C /opt/veloscroll pull origin main    
   ```

   or check out a specific tag/commit if you want to Rollback.

3. If the release changed `veloscroll.service`, copy it to `/etc/systemd/system/` again and run `sudo systemctl daemon-reload`.
4. Restart (code changes never hot-reload — only config.ini does) and verify:

   ```bash
   sudo systemctl restart veloscroll
   journalctl -u veloscroll -n 10   
   ```
   
Expect systemd printing the newest Version (like `Veloscroll vX.Y`), a fresh "config loaded from ..." and "grabbed <path> <device name>"
Your `/etc/veloscroll/config.ini` lives outside the repo and survives step 2 untouched — unknown keys are ignored with a warning, removed keys fall back to built-in defaults. That is also why all configuration belongs in config.ini: local edits to `veloscroll.py` are lost or conflict on every update (see [Customize & reload](#customize--reload) above). To roll back, check out the previous commit in `/opt/veloscroll` and repeat step 4.

## Tested ##

VeloScroll was tested on the following live ISOs (all x86_64), chosen to cover the major compositors, desktop environments, and package ecosystems:

| Distro | What it covers | Verified | 
| --- | --- | --- |
| Ubuntu Desktop 26.04.1 LTS | GNOME/Mutter Wayland + Xorg session (apt) |
| Kubuntu 26.10 | KDE on the Ubuntu/apt base — KWin Wayland | ✅ 
| Kubuntu 26.10 | KDE on the Ubuntu/apt base — X11 session  | ✅
| Fedora Workstation 44 | GNOME/Mutter Wayland + Xorg, newest dnf stack | ✅
| Fedora KDE Plasma Desktop 44 | KWin Wayland + X11 session, per-device input rules (dnf) |
| Fedora Sway Spin 44 | wlroots/Sway Wayland (dnf) — no install needed |
| Fedora XFCE Spin 44 | X11 XFCE on the dnf stack |
| Fedora i3 Spin 44 | Raw Xorg + tiling WM, minimal overhead (dnf) |
| openSUSE Tumbleweed KDE Live (snapshot 20261022) | KWin on a rolling stack, zypper ecosystem |
| openSUSE Tumbleweed XFCE Live (snapshot 20261022) | XFCE on a rolling stack, zypper ecosystem |
| Linux Mint 22.3 "Zena" Cinnamon | Classic X11 desktop (apt, Debian-based) | ✅
| MX Linux 25.3 Xfce | X11 XFCE, Debian-stable kernel 6.12 — old-kernel compatibility (apt) |
| Arch Linux 2026.10.01 | Minimal base for Hyprland/Sway/Xorg + newest kernel (pacman) |
| Pop!_OS 24.04 LTS (COSMIC Epoch 1) | COSMIC — Wayland/EGL compositor, apt base |

