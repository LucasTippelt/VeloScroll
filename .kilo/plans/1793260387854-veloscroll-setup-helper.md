# Plan: Setup-Helper script (`veloscroll_setup.py`)

## Goal

A manual terminal helper for tuning the ramp keys. With the daemon stopped, it grabs the configured mouse and prints precise values measured from real hand movement so the user can set `DEADZONE_IN`/`FULL_IN` (+ `_H`), sanity-check `DPI`, and judge `MAX_RATE`/`MIN_RATE`/`CURVE`. It reads `/etc/veloscroll/config.ini` hot-reloadable — live edits change the thresholds mid-session, exactly like the daemon.

## Resolved decisions

| Decision | Choice |
| --- | --- |
| Name / placement | `veloscroll_setup.py`, repo root; conventions of `veloscroll_preset.py` (argparse, one-line stderr errors + exit 1, `--config PATH` that sets `VELOSCROLL_CONFIG` before importing `veloscroll`) |
| Mouse handling | **Full daemon parity**: exclusive grab of *all* matching devices + temporary UInput pass-through (same `cap` dict, same `VIRTUAL_NAME`, grabbed device's USB IDs). Forwards everything except: hold-button press/release, `REL_X`/`REL_Y` while held, wheel events while held, and `DISABLED_BTN`. **No scroll is ever emitted.** Cursor stays put while held; mouse fully usable between holds. |
| Live readout | In-place `\r` gauge while held + discrete milestone lines (see spec). Gauge includes the computed "would-be" target rate. |
| Config source of truth | Import `veloscroll` (safe: import runs config load/apply only, no threads/devices — same pattern as `veloscroll_preset.py`). Reuse `load_config`, `check_config`, `_parse_ini_value`, `DAEMON_KEYS`, and call `vs.apply_values()` on startup and each successful reload so all effective values + derived counts (`DEADZONE = DEADZONE_IN * DPI`, …) stay identical to the daemon's. |
| Hot reload | Background poller, 1 s period, mirroring `_maybe_reload_config` (veloscroll.py:747): stat `(mtime_ns, size)` of `vs.CONFIG_PATH`; changed → `load_config()` + `check_config()`; rejection prints `config reload rejected, keeping current values: …` and keeps old thresholds; success prints `config reloaded: K old->new` per changed key. |
| Daemon stop/start | **Not the script's job** (user stops it manually). No systemd coupling in code. Grab failure with `EBUSY` → one-line error with exact guidance (`sudo systemctl stop veloscroll, then re-run this helper`); on any exit print a reminder that the daemon is not running and how to start it again. |

## Behavior spec

**Startup banner** (before waiting for input):
- config path + override count (from `vs._cfg_load_info`, else "built-in defaults — no config.ini"), warning that inch values are only as good as the `DPI` key;
- each grabbed device: `<path> <name>`; grab failure → error line, exit 1 (`EBUSY` wording per daemon veloscroll.py:621-630);
- effective thresholds in use: `DEADZONE_IN`/`FULL_IN` with counts (`DPI` × inches), `_H` variants when set (else "falls back to vertical"), `SCROLL_BTN` code + name, note if `SCROLL_BTN_H = none`;
- prompt: hold the button and move; Ctrl-C quits.

**No matching device**: rescan every 2 s like the supervisor (`"no matching device yet — waiting"`), until a match appears or Ctrl-C (exit 130).

**Per-hold state machine — mirrors `run()` exactly (veloscroll.py:646-695):**
- press of `SCROLL_BTN` → line `[v] scroll button pressed (BTN_SIDE / 275)`; reset accumulators, fresh hold. Press of `SCROLL_BTN_H` → same for `[h]`; last press wins (LIFO); releasing one while the other stays down reactivates it fresh — identical to the daemon.
- while held: mode `v` accumulates `REL_Y` into `offset`, clamped ±`FULL` counts; mode `h` accumulates `REL_X` into `h_offset`, clamped ±`FULL_H`.

**Milestone lines (first occurrence per hold):**
- deadzone passed when `|off| > dz` counts (strictly greater, same as the daemon's crossing metric): `[v] deadzone passed at 0.05 in (81 counts)`
- max-rate reached when `|off| >= full` counts: `[v] max-rate reached at 2.50 in (4000 counts) — further movement clamps here`

**Gauge** (updated on each REL event while held, printed via `\r`, replaced by a newline before the next discrete line):
`[v] 1.32 in from start (2112 counts) | target 87 notches/s`
Target rate uses the daemon's exact ramp formula with per-axis effective values (`None → vertical fallback`, veloscroll.py:564-577); inside the deadzone it shows `0`.

**Release line (per-hold summary):**
`[v] released after 1.3 s — peak 2.7 in (4320 counts), deadzone crossed, max-rate reached`
(booleans reflect whether each milestone fired; this is the key copy-pasteable result for picking config values).

**Exit**: Ctrl-C or error → close all grabbed devices (release grabs), close UInput, print reminder: `veloscroll is not running — restart when done: sudo systemctl start veloscroll`.

## Failure modes

| Case | Behavior |
| --- | --- |
| No config file | pure built-in defaults + one warning line (same as daemon) |
| Bad key edit while running | `config reload rejected, keeping current values: …`; old thresholds stay in effect; never crashes on a config edit |
| Grab `EBUSY` | error with stop-daemon guidance, exit 1 (covers daemon *or* any other grabbing tool) |
| No permission | same wording as daemon (`run as root or add user to input group`), exit 1 |
| `/dev/uinput` unavailable | one-line error, exit 1 (required for parity pass-through) |
| Multiple matching devices | all grabbed and merged, like the daemon; first grab's USB IDs advertised by the UInput device |

## Tasks (ordered)

1. **Skeleton** — `veloscroll_setup.py`: header comment block in sibling-helper style (purpose, usage lines, permissions note: run as root or user with `input` group + `/dev/uinput`, same as daemon manual mode); argparse with `--config PATH`; set env then `sys.path.insert(0, dirname(__file__))` + `import veloscroll as vs` (fail-fast message like the preset helper).
2. **Config layer** — startup: `vs.apply_values(vs.load_config())` (module import already validated; re-validate on each reload), build banner from module globals (`vs.DPI`, `vs.DEADZONE_IN`, …, `vs.SCROLL_BTN`, …); button-code → name via a small reverse map over `evdev.ecodes.BTN_*`.
3. **Device grab + UInput pass-through** — reuse `vs.find_matches()` / `vs.device_selected` (globals kept current by `apply_values`); per-device reader thread mirroring `run()`: same state machine, same clamping, same swallowed-event set (`DISABLED_BTN`, wheel-while-held), but instead of `emit_scroll` it does nothing for held RELs and forwards everything else via the UInput device. Create UInput once with the first grabbed device's IDs (mirror `sync_virtual_device`). Guard gauge printing under `vs.lock` so two merged devices can't interleave `\r` lines.
4. **Milestones + gauge** — per-hold flags (`dz_crossed`, `max_reached`, peak, press timestamp); format helpers producing the exact line shapes above; ramp-rate formula copied from veloscroll.py:576-584 with a comment naming it as source of truth.
5. **Hot-reload poller** — 1 s thread mirroring `_maybe_reload_config` (reuse `vs._cfg_stat`, `vs.load_config`, `vs.check_config`, `vs.apply_values`); on adoption, in-progress holds keep their accumulators but thresholds/counts switch to the new values immediately (matches daemon semantics: next event uses new globals).
6. **Lifecycle** — signal handler for Ctrl-C → clean shutdown of threads/devices/UInput + restart reminder; exit codes 0 (clean quit), 1 (errors), 130 (Ctrl-C during "no device yet" is also fine as 130).
7. **Docs** — README: new short section after *Presets* ("Tuning aid: veloscroll_setup.py") with the workflow (stop daemon → run helper → read milestone/summary values → edit config.ini → restart daemon) and a sample output block; TUNING.md: one-line pointer in "Starting points, not verified values" to measure real distances with it.

## Validation

No test infra exists in this repo — validation is manual on a live system (project convention):

1. `python3 -m py_compile veloscroll_setup.py`.
2. `sudo systemctl stop veloscroll`, then `sudo python3 /opt/veloscroll/veloscroll_setup.py` → banner shows grabbed device + effective thresholds.
3. Hold the vertical button, move slowly: gauge updates in place; deadzone line fires at ≈ `DEADZONE_IN` inches; max-rate line at ≈ `FULL_IN`; release summary consistent (peak ≥ both). Keep moving past FULL — distance stays clamped at the FULL value.
4. Live-edit config.ini while running (`DEADZONE_IN 0.05 → 0.2`) → `config reloaded:` line within ~1–2 s; next hold's deadzone fires at the new distance. Then break a key → `reload rejected` line, old thresholds still in effect.
5. With `SCROLL_BTN_H` configured: repeat step 3 for horizontal (mouse X movement).
6. EBUSY path: start the daemon, run the helper → clear busy message with stop guidance, exit 1.
7. Pass-through sanity: between holds the pointer moves and other buttons click normally; while held, cursor stays put and the hold button triggers no OS action.
8. Ctrl-C → clean exit, mouse immediately usable (grab released), restart reminder printed.

## Out of scope

- No changes to `veloscroll.py` — the helper is self-contained plus imports only.
- No auto stop/start of the daemon; no systemd dependency in code.
- No scroll output of any kind; no new config.ini keys; no GUI beyond terminal lines.
