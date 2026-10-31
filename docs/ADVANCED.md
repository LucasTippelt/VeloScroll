# VeloScroll Advanced Guide

Nothing here is needed for normal use.

## Contents

1. [Advanced notes (not needed for normal use)](#advanced-notes-not-needed-for-normal-use)
2. [`veloscroll_seed.py` options](#veloscroll_seedpy-options)
3. [Latency & debugging](#latency--debugging)

---

## Advanced notes (not needed for normal use)

`DE_WM` and `VIRTUAL_NAME` at the top of `veloscroll.py` belong to `veloscroll_seed.py`. Both are intentionally **not** in `config.ini`.

Only touch them if you maintain a fork or run an unusual setup. Like every edit to `veloscroll.py`, changes need a restart (`sudo systemctl restart veloscroll`) and will be lost (or conflict) on the next [update](UPDATING.md).

| Constant | Meaning |
|----------|---------|
| `DE_WM` | Which pointer-settings backend the seed script uses. Supported values live in its backend registry (`BACKENDS`, currently only `kde-plasma`; per-DE guides in [`docs-desktop/`](../docs-desktop/)). An unknown value makes the seed script exit with an error listing the supported ones. |
| `VIRTUAL_NAME` | Name of the virtual device (default `veloscroll-mouse`). It is advertised together with your real mouse's USB IDs, so per-device pointer rules might apply to it automatically. The seed script looks for exactly this name, so keep the default unless you run several daemon instances side by side. |

### Pointing the daemon at another config file

For tests or per-user setups you can point the daemon at another file:

```bash
VELOSCROLL_CONFIG=/path/to/config.ini python3 veloscroll.py
```

---

## `veloscroll_seed.py` options

Run as your **desktop user, not root** (as root it would target `/root/.config`). All modes operate on KDE Plasma's `kcminputrc`, currently the only implemented backend.

| Option | Effect |
|--------|--------|
| *(none)* | **Seed:** copy your real mouse's per-device pointer settings into a matching `[Libinput][<vendor>][<product>][veloscroll-mouse]` group, then apply them to the running session via KWin's D-Bus interface. |
| `--name <NAME>` | Select the real mouse by case-insensitive substring of its device name instead of `DEVICE_MATCH` (IDs are taken from that device's `uevent`). Combines with any mode below. |
| `--apply-only` | **Apply:** push the existing `veloscroll-mouse` group to the running session without re-seeding or modifying the file (e.g. after hand-editing it). |
| `--remove-stale-config` | **Clean up:** delete `[Libinput][…][veloscroll-mouse]` groups that don't match your current mouse's USB IDs (dead config from old mice / pre-ID-copy runs), writing a `.bak-*` backup first. |

`--apply-only` and `--remove-stale-config` are combinable in one run: apply happens first, then removal. All modes are idempotent, so re-running is always safe.

### Backups

A backup of the config file (`~/.config/kcminputrc.bak-<timestamp>`) is written only when seed or `--remove-stale-config` actually changes it, and only while backups are enabled. That means:

- on **KDE Plasma only**, the only backend with per-device settings (on other desktops VeloScroll never writes any config file, hence no backups),
- not for runs where nothing changed,
- not for `--apply-only`,
- not at all when `MAX_BACKUPS = 0` in `config.ini` — backups are disabled entirely and existing `.bak-*` files stay untouched.

Each backup keeps the previous state recoverable. How many are kept per file family is capped by that same hot-reloaded `MAX_BACKUPS` key (`-1` = unlimited, default `5`) (see [Configuration → Backups](CONFIGURATION.md#backups-helper-scripts)).
---

## Latency & debugging

Where does time go when you hold the button? This is the pipeline and what each segment is responsible for:

```
mouse → kernel evdev → veloscroll run() thread → ticker (TICK, default 250 Hz) → uinput veloscroll-mouse → compositor → app
└─────────── input delivery ───────────┘└──────────── daemon: ticker + emit ────────────┘└──────── out of scope ────────┘
```

- **Input delivery:** USB polling interval, kernel scheduling delays, and any CPU work before the daemon's read loop runs. Measured from the kernel event timestamp to arrival in the daemon (`input p50/p95/max`).
- **Daemon (ticker + emit):** rate smoothing, tick quantization, and the `/dev/uinput` write cost (`tick period`, `overrun_max`, `press->emit`, `crossing->emit`, `uinput_write_max`).
- **Compositor → app:** rendering, frame pacing, and in-app scroll handling. Not observable from the daemon. If scrolling still looks laggy with healthy lines below, look here (frame rate, smooth-scroll settings in the app).

### Theoretical latency (model)

A model computed purely from config (`TICK`, `OUT_SMOOTH`, `MIN_RATE`): the design-inherent floor, **not a measurement**. With `T = TICK` and `S = OUT_SMOOTH`:

- **Smoothing time constant:** `τ = T / (−ln(1 − S))`. This is how quickly the emitted rate follows your target speed. Default: ≈ 2.5 ms.
- **Response to sustained movement (step change in target):** ~`T/2 + τ` to reach 63% of the new rate, ~`T/2 + 3τ` for 95% (`T/2` = average tick quantization delay). Defaults: ~4.5 ms / ~9.5 ms.
- **First emit after deadzone crossing:** simulated from the real ticker recurrence at `MIN_RATE`. With defaults the first notch lands on the very next tick, ≈ `T/2 + (n−1)·T` ≈ 2–6 ms (one tick).

Excluded from the model: USB polling/kernel delivery (covered by the measured input metric), deadzone travel time (how long *you* take to move past the deadzone), and compositor/app rendering. Real movement changes the target continuously, so t₆₃/t₉₅ are estimates for a step change. Treat all of these numbers as model values, never as measurements.

### Enabling the measured lines

Set `LATENCY_LOG = True` in `/etc/veloscroll/config.ini`, then watch:

```bash
journalctl -u veloscroll -f
```

It hot-reloads like every other key (no restart). While there is activity, one summary line appears per second. A model line appears at startup and whenever `LATENCY_LOG` or any of `TICK`/`OUT_SMOOTH`/`MIN_RATE` changes. These lines are independent of `LOG_LEVEL`.

Sample output:

```
latency model: tick=4.0ms tau=2.5ms -> 63% response ~4.5ms, 95% ~9.5ms; first emit after deadzone ~2-6ms (1 tick) [TICK/OUT_SMOOTH/MIN_RATE]
latency: input p50=2.1ms p95=8.4ms max=21.7ms n=1204 | tick period=4.0ms overrun_max=0.3ms overruns=1 | press->emit=7.8ms crossing->emit=3.9ms (n=3) | uinput_write_max=0.4ms
```

| Field | Meaning / typical value |
|-------|-------------------------|
| `input p50/p95/max` | Kernel timestamp → daemon arrival over the last 1 s. p50 ≈ your USB polling interval (1–8 ms). A high p95 points at USB/power/scheduler issues, not the daemon. |
| `tick period` | Actual ticker loop period. Should sit at ≈ `TICK` (4.0 ms by default). |
| `overrun_max`, `overruns` | Worst/number of ticks that woke late in the window. An occasional single-digit-ms blip is normal GIL/scheduler noise; sustained overruns mean CPU starvation. |
| `press->emit` | Button-down → first scroll event emitted (p50 per hold). Includes your deadzone travel time, so expect it to be larger than `crossing->emit`. |
| `crossing->emit` | Moment the distance first passed the deadzone → first emit. Isolates daemon latency from how fast you move; healthy systems stay within ~2 ticks (≤ 8 ms at default `TICK`). |
| `uinput_write_max` | Slowest `/dev/uinput` write+syn in the window. Single-digit milliseconds or less is normal. |

### Troubleshooting

| Symptom | Likely cause |
|---------|--------------|
| High input p95 (p50 fine) | USB power management, flaky cable/port, kernel scheduler load. Try another port/cable, disable USB autosuspend for the mouse. |
| `tick period` > `TICK` or frequent overruns | CPU saturation or GIL stalls (e.g. config reloads, slow uinput writes). Check system load and `uinput_write_max`. |
| Large `press->emit`, small `crossing->emit` | Normal: you spent time moving past the deadzone. Not a bug; lower `DEADZONE_IN` if starting feels slow. |
| Healthy daemon lines but scrolling still looks laggy | Likely: Compositor/app side (frame pacing, app smooth-scroll settings). Out of scope for this daemon. You can try to lower `TICK` even further if system load/overruns look fine. **Be careful with this, I would advice AGAINST going above 1000hz (0.001).**|

---

Back to the [README](../README.md) · See also: [Install](INSTALL.md), [Updating](UPDATING.md)
