# Testing — running and understanding the test suite

The pytest suite lives in `tests/` at the repo root. It covers all six Python programs — two at the repo root (`veloscroll.py`, `veloscroll_preset.py`) plus four helpers in `helpers/` (`veloscroll_seed.py`, `veloscroll_tuning_helper.py`, `ListDeviceNames.py`, `ListButtonPresses.py`) — across three tiers, needs **no mouse, no uinput device and no root**, and never modifies product code or `/etc/veloscroll/config.ini` — every test points the daemon at temp files or fakes.

## Running the tests

Prerequisites: Python 3 with `evdev` importable (the system package on Debian/Ubuntu, or `pip install evdev`) and pytest. Install both from the repo root:

```sh
pip install -r requirements-dev.txt        # standard route (also what CI does)
# — or on a distro without pip, e.g. plain Ubuntu:
sudo apt-get install -y python3-evdev python3-pytest
```

Then run the whole suite from the repo root:

```sh
python3 -m pytest tests/ --tb=short        # everything (~30 s; the hot-reload e2e test is ~18 s of that)
python3 -m pytest tests/test_daemon_scroll.py            # one file
python3 -m pytest "tests/test_check_config.py::test_invalid_values"   # one (parameterized) test
python3 -m pytest tests/ --collect-only -q               # list all 318 tests without running them
```

The CI workflow `.github/workflows/test.yml` runs exactly `python3 -m pytest tests/ --tb=short` on ubuntu-latest after `pip install -r requirements-dev.txt`.

## How it is organized

| Tier | What runs | Hardware | Purpose |
| --- | --- | --- | --- |
| **Unit** (`test_config_parse`, `test_check_config`, `test_latency_model`, `test_preset_ops`, `test_seed_backend`, `tuning_helper_units`, `list_scripts`) | Pure functions in isolation; fake `busctl`/subprocess for the seed backend | none | Pin parse rules, validation messages, ramp math and CLI helpers line-for-line |
| **Integration** (`test_daemon_scroll`, `test_daemon_toggle_dualaxis`, `test_hot_reload_state`, `test_supervisor`) | The real `veloscroll.py` module in-process: its actual `run()` event loop, ticker, `_maybe_reload_config()` and `supervisor()`, driven by fake evdev input devices with a recording UInput (`tests/fakes.py`) | faked | Pin daemon behavior — notch math, held-event swallowing, toggle/dual-axis rules, reload semantics |
| **E2E** (`test_startup_matrix`, `test_hot_reload_e2e`, `test_preset_cli`, `test_seed_cli`, `test_docs_links`) | The real programs as subprocesses (or `main()` in-process for the seed CLI), against temp config files and a live daemon process | none (the e2e daemon uses an unmatchable `NAME_MATCH`, so it never grabs a device) | Pin what a user actually sees: startup output, exit codes, stdout/stderr strings, files created on disk |

## Test files — what each test does

### Unit tier

**`tests/test_config_parse.py`** — the ini parser (`_parse_ini_value`) and `load_config()`:
- `test_name_match_passthrough` — NAME_MATCH is taken verbatim (spaces, empty string included)
- `test_device_match_valid` / `test_device_match_invalid` — DEVICE_MATCH accepts hex pairs, decimal pairs (comma or space separated), a `/…/…` path string and `none`; bare numbers, garbage and 3-token lines raise ConfigError
- `test_button_keys_valid` / `test_button_keys_invalid` — button keys accept ecodes symbol names (`BTN_SIDE`) and decimals; `none` is allowed for DISABLED_BTN/SCROLL_BTN_H but rejected for SCROLL_BTN; unknown symbols are errors
- `test_booleans_valid` / `test_booleans_invalid` — true/false/yes/no/on/off/1/0 case-insensitively; anything else (including empty and `2`) is an error
- `test_toggle_scroll_h` — booleans plus `none` → None (runtime fallback to the vertical value)
- `test_log_level_valid` / `test_log_level_invalid` — integer 0..3 only
- `test_h_float_keys` — each of the six `*_H` ramp keys accepts a number or `none`
- `test_plain_floats` / `test_plain_floats_invalid` — DPI/TICK/rate/curve/smooth keys parse as float; malformed numbers are errors
- `test_load_missing_file_pure_defaults` — no config file → all built-in defaults, no error
- `test_load_empty_value_keeps_default` — an empty value means "default applies" and is not counted as an override
- `test_load_unknown_section_and_key_warn_but_apply` — unknown sections/keys log a warning but known keys in the same file still apply
- `test_load_malformed_ini_structure` — broken INI structure surfaces as one ConfigError naming the file
- `test_load_two_bad_keys_single_error` — several bad values are collected into a single error joined with `"; "`

**`tests/test_check_config.py`** — semantic validation (`check_config`) with exact error strings:
- `test_defaults_are_valid` — the shipped defaults pass
- `test_invalid_values` (8 cases) — one case per scalar range rule (DPI, MIN_RATE, MAX_RATE≥MIN_RATE, DEADZONE_IN>0, FULL_IN>DEADZONE_IN, CURVE>0, OUT_SMOOTH∈(0,1]) asserting the exact message
- `test_boundary_values_valid` — boundaries are inclusive where intended (MAX_RATE==MIN_RATE, OUT_SMOOTH=1.0)
- `test_h_fallback_invalid` / `test_h_fallback_valid` — cross-axis checks use *effective* values after `_H` → vertical fallback
- `test_button_identity` — SCROLL_BTN_H and DISABLED_BTN must differ from each other and from SCROLL_BTN
- `test_type_checks` — strict types: real ints (bools rejected) for buttons, real bools for TOGGLE_SCROLL/TOGGLE_SCROLL_H/VERTICAL_H/LATENCY_LOG
- `test_device_match_valid_forms` / `test_device_match_invalid_forms` — pair/path/None rules; NAME_MATCH must be non-empty when DEVICE_MATCH is None
- `test_log_level_type` — LOG_LEVEL range/type errors

**`tests/test_latency_model.py`** — the latency model line (`_latency_model`) and LATENCY_LOG windowing:
- `test_model_at_defaults` — the printed model matches hand-computed tick/tau/63%/95% values at defaults
- `test_model_out_smooth_one_no_math_error` — OUT_SMOOTH=1 (tau→TICK) doesn't divide by zero
- `test_model_first_emit_over_50_tick_cap` — huge deadzones report the ">50 ticks" cap instead of a giant number
- `test_model_multi_tick_plural_format` — "tick" vs "ticks" pluralization
- `test_pct_single_element` / `test_pct_0_to_99` — percentage rounding (banker's) over all 0..100 window sizes
- `test_build_line_empty_window_is_none` / `test_build_line_periods_alone_are_not_activity` — no input → no line; timer ticks alone don't count as activity
- `test_build_line_populated_window_segments_and_invariants` — a full window produces the segment layout with its monotonicity invariants
- `test_build_line_uinput_segment_only_when_positive` — the uinput segment prints only when > 0
- `test_input_sample_zero_ts_skipped…` / `…valid_event_appends_sane_delta` / `…stale_offset_recalibrates_once` / `…unusable_timestamps_disable_metric_with_one_warning` — timestamp edge cases in sample intake (zero ts, stale offset recalibration exactly once, one-shot disable warning)

**`tests/test_preset_ops.py`** — the preset CLI's internal machinery (`veloscroll_preset.py`):
- `test_fmt` — value formatting: None→`none`, tuple→hex pair, everything else via str()
- `test_name_re_accepts` / `test_name_re_rejects` / `test_name_re_allows_dots_but_stays_in_presets_dir` — preset names allow letters/digits/`.`/`_`/`-`; paths and spaces are blocked (no traversal out of `presets/`)
- `test_bak_re_matches` / `test_bak_re_rejects` — the exact `.bak-<YYYYMMDD-HHMMSSffffff>` backup filename format
- `test_rewrite_in_place_preserves_comments_and_ordering`, `test_rewrite_absent_keys_appended_in_daemon_key_order`, `test_rewrite_creates_section_when_missing`, `test_rewrite_empty_file_creates_section`, `test_rewrite_lossless_round_trip_when_no_updates` — the line-based config rewriter: in-place updates, deterministic append order, section creation, and byte-identical round-trip when nothing changes
- `test_prune_keeps_n_newest_and_returns_deleted`, `test_prune_unlimited_deletes_nothing`, `test_prune_disabled_zero_is_noop_deletes_nothing`, `test_prune_invalid_value_raises_before_deleting`, `test_prune_ignores_unrelated_files` — MAX_BACKUPS pruning (incl. -1 = unlimited, 0 = disabled no-op that leaves existing backups untouched, and fail-before-delete on bad values)
- `test_backup_files_scans_both_dirs_newest_first` — backups are found in both the config dir and `presets/`, newest first
- `test_resolve_no_ref_newest_config_backup`, `test_resolve_unique_basename_match`, `test_resolve_ambiguous_basename_across_dirs_errors`, `test_resolve_explicit_path_constrained_to_allowed_dirs`, `test_resolve_missing_name_errors` — restore reference resolution (default = newest, ambiguity and path-escape errors)
- `test_covering_cmds_group_keys_and_loadall` — the "use loadX to apply these keys" hint groups

**`tests/test_seed_backend.py`** — `veloscroll_seed.py`'s discovery + KdePlasmaBackend with a fake `busctl`:
- `test_usb_ids_valid` / `test_usb_ids_rejects` — parsing `ID_BUS/vendor/product/version` from sysfs uevent data (hex or decimal, malformed lines rejected)
- `test_discover_no_match`, `test_discover_multiple_without_group_lists_names`, `test_discover_tiebreak_prefers_existing_kcminput_group`, `test_discover_single_without_usb_ids`, `test_discover_happy_path_fields`, `test_discover_name_override_skips_id_matching`, `test_discover_excludes_veloscroll_named_devices` — mouse discovery: no match, ambiguous lists, tie-break on an existing kcminputrc group, missing IDs, the `--name` override, and self-exclusion of veloscroll's own virtual device
- `test_seed_no_file_system_defaults`, `test_seed_source_group_missing_system_defaults`, `test_seed_copies_group_excluding_enabled_with_backup`, `test_seed_idempotent_second_run_no_changes_no_backup`, `test_seed_overwrite_removes_stale_target_keys`, `test_seed_prunes_old_backups`, `test_seed_prune_zero_is_noop`, `test_seed_disabled_backups_writes_nothing`, `test_seed_live_apply_skip_note_without_dbus` — the seed operation: fresh file, missing source group, copy excluding `Enabled=` with a `.bak-*` backup, idempotency, stale-key removal, pruning (incl. 0 = disabled no-op), and the no-D-Bus note
- `test_apply_only_no_file`, `test_apply_only_missing_target_group`, `test_apply_only_success_leaves_file_untouched` — `--apply-only` never rewrites kcminputrc
- `test_remove_stale_no_file`, `test_remove_stale_none_found_touches_nothing`, `test_remove_stale_deletes_only_old_id_groups`, `test_remove_stale_disabled_backups_writes_nothing` — `--remove-stale-config` only deletes groups with foreign USB IDs (with MAX_BACKUPS=0 it still cleans up, just without writing a backup)
- `test_live_apply_full_property_sequence`, `test_live_apply_profile_one_sets_flat`, `test_live_apply_unknown_scroll_method_is_file_only`, `test_live_apply_failed_set_reported_but_value_saved`, `test_live_apply_no_dbus_env`, `test_live_apply_busctl_missing`, `test_live_apply_device_not_registered`, `test_live_apply_name_mismatch` — the exact `busctl --user … Set value` / `get-property` argv sequence (including property indices) and every failure mode
- `test_main_refuses_root`, `test_main_unsupported_de_wm`, `test_main_seed_run_prints_report`, `test_main_name_override_no_kcminputrc`, `test_main_discovery_failure_exits_one` — `main()` wiring: root refusal, DE_WM registry check, report output format

**`tests/test_tuning_helper_units.py`** — the pure helpers of `veloscroll_tuning_helper.py`:
- `test_num` — number formatting in helper lines (ints stay ints, floats capped at 4 decimals)
- `test_disp_off`, `test_dir_label` — displayed offset and direction labels per axis/mode/INVERT (`(rightwards)`, `(upwards)`…)
- `test_target_rate_zero_inside_deadzone`, `test_target_rate_full_equals_max_rate_exactly`, `test_target_rate_monotonic_in_distance`, `test_target_rate_h_falls_back_to_vertical_when_unset`, `test_target_rate_h_uses_explicit_h_values_and_derived_counts` — the ramp math mirrors the daemon's: zero in the deadzone, exactly MAX_RATE at full scale, monotonic, `_H` fallback and derived counts
- `test_v_mode_milestones_gauge_and_release`, `test_h_mode_rightwards_without_vertical_h`, `test_h_mode_downwards_with_vertical_h` — live milestone lines for both axes (incl. VERTICAL_H flipping the label)
- `test_release_summary_small_motion_no_crossings`, `test_release_summary_no_motion` — end-of-hold summary edge cases
- `test_end_hold_clears_state_and_makes_on_move_a_noop` — state machine reset after release
- `test_line_gauge_raw_mechanics` — the `[####----]` gauge rendering

**`tests/test_list_scripts.py`** — `ListDeviceNames.py` and `ListButtonPresses.py`:
- `test_list_device_names_prints_path_name_and_ids`, `…_skips_unopenable_with_stderr_note`, `…_none_readable_exits_one` — output format, graceful skip of unreadable nodes (PermissionError → stderr note), exit 1 when nothing is readable
- `test_button_presses_number_arg_maps_to_event_path`, `…_full_path_passthrough`, `…_invalid_arg_exits_one`, `…_permission_error_message`, `…_keyboard_interrupt_is_clean_exit` — argument handling (`3` → `/dev/input/event3`), the "no permission" hint, and a clean Ctrl-C exit

### Integration tier (real daemon code, faked hardware)

**`tests/test_daemon_scroll.py`** — the real `run()` loop + ticker with fake input:
- `test_down_motion_emits_negative_wheel_with_exact_notch_math` — full-scale motion; asserts the exact telescoping invariant `coarse*120 + acc == hi-res total` for every prefix of writes
- `test_motion_inside_deadzone_emits_nothing` — sub-deadzone movement produces zero OS events
- `test_offset_clamps_to_full` — accumulated offset never exceeds FULL counts (state read while the loop is live)
- `test_invert_flips_direction`, `test_up_motion_emits_positive_wheel` — INVERT and sign of emitted wheel codes
- `test_h_mode_rel_x_emits_positive_hwheel` — held horizontal button: REL_X drives REL_HWHEEL with the same notch invariant
- `test_vertical_h_mode_accumulates_rel_y_and_emits_vertical_wheel` — VERTICAL_H: up/down movement in H mode emits vertical wheel codes only, using the `_H` ramp values
- `test_free_events_pass_through_held_rels_and_wheel_are_swallowed` — free state passes every REL and wheel event through verbatim; held state swallows REL_X/REL_Y (frozen cursor) while the model's own wheel events still go out; after release everything passes again — exact write-list equality
- `test_disabled_button_never_reaches_the_os` — DISABLED_BTN is consumed even while another button is held
- `test_release_stops_emitting_permanently` — no further emission after the hold ends, even with more motion
- `test_startup_output_reports_config_overrides` — real startup path prints `config loaded from <path> (N override(s))`
- `test_grab_line_and_virtual_device_identity` — grab log line and the virtual device advertising the grabbed mouse's USB IDs
- `test_drag_forwards_motion_and_pauses_velocity` — left held mid-session: REL movement and physical wheel pass through to the virtual cursor while velocity output stays paused; offset accumulation freezes at its clamped value (exact write-list equality)
- `test_left_release_resumes_from_fresh_origin` — releasing left mid-session resets the origin: sub-deadzone movement afterwards emits nothing (without the reset, a FULL-scale offset would emit at max rate); also pins the quick-click edge case
- `test_left_down_before_side_press_arms_drag_mode` — left pressed before the session starts arms drag mode immediately; every write is a passthrough with zero wheel emissions

**`tests/test_daemon_toggle_dualaxis.py`** — toggle latches and dual-axis rules:
- `test_toggle_latch_release_edge_and_repeat_are_noop` — a toggled button latches on press; release edges and key-repeat don't retrigger
- `test_toggle_h_falls_back_to_vertical_toggle_value`, `test_toggle_h_explicit_override_leaves_v_axis_in_hold_mode` — TOGGLE_SCROLL_H fallback vs explicit override per axis
- `test_d3_releasing_h_while_v_still_held_reactivates_v_fresh` — releasing one axis while the other stays held reactivates the remaining axis with *fresh* accumulators (D3 rule), observed on a full state snapshot
- `test_d5_toggle_engage_resets_accumulators` — engaging via toggle clears offset/accumulator/ticker-reset (D5 rule)
- `test_axis_switch_rate_ramps_from_zero` — after an axis switch the rate restarts from zero: first emission small, next ones at steady-state size

**`tests/test_hot_reload_state.py`** — in-process `_maybe_reload_config()` + `apply_values()`:
- `test_first_call_applies_and_unchanged_file_is_noop` — first reload applies; an unchanged file logs nothing
- `test_valid_live_change_applies_new_values` — exact `config reloaded: K old->new, …` lines with Python reprs (floats stay floats)
- `test_unchanged_content_with_new_mtime_logs_nothing` — mtime-only changes are ignored
- `test_malformed_file_rejected_once_not_retried_until_it_changes` — a rejected parse is logged once and *not* retried while the file stays put (stat advances before parsing)
- `test_check_config_failure_is_rejected_with_all_errors` — semantic failures reject with every error joined by `"; "`
- `test_missing_file_logged_once_then_silent_until_recreated` — deletion logs one em-dash notice, then silence until the file returns
- `test_latency_log_enable_resets_epoch_and_prints_model` — turning LATENCY_LOG on resets the timing epoch and prints the model line
- `test_model_key_change_reprints_model_at_new_values` — changing TICK/OUT_SMOOTH/MIN_RATE reprints the model with the new numbers (`tick=8.0ms`)
- `test_d7_button_swap_clears_stuck_held_state`, `…_toggle_mode_flip_also_clears_held_state`, `…_vertical_h_flip_also_clears_held_state`, `test_d7_button_swap_also_clears_stale_btn_left_down` — D7 rule: swapping any engagement key clears a stuck held state, all accumulators and the stale `btn_left_down` drag flag

**`tests/test_supervisor.py`** — the device watcher thread:
- `test_failed_scan_is_logged_and_changes_nothing` — an exception inside the scan logs level-0 `scan failed:` and neither starts nor stops anything
- `test_device_started_then_released_when_deselected` — a matching device gets its run() thread; dropping out of the match set closes it
- `test_dead_thread_is_restarted_while_still_selected` — a crashed daemon thread is reaped and restarted on the next iteration
- `test_empty_first_scan_reports_waiting` — first scan with no matches logs `no matching device yet — waiting`

### E2E tier (real programs as subprocesses)

**`tests/test_startup_matrix.py`** — imports `veloscroll.py` in a fresh subprocess via `tests/probe_values.py`, which prints the effective values of all 26 daemon keys after the real startup block ran:
- `test_missing_file_pure_defaults` — no file → exactly the built-in defaults, no "config loaded" line
- `test_partial_overlay_and_override_count` — a partial ini overlays only its keys and reports `(3 override(s))`
- `test_malformed_value_exits_1`, `test_range_violation_from_check_config`, `test_malformed_ini_structure_exits_1` — parse errors, check_config errors and broken INI structure each exit 1 with the exact `config error: …` message before any device access
- `test_unknown_key_and_section_warn_but_start` — warnings only; startup succeeds with known keys applied
- `test_device_match_hex_pair`, `…_decimal_pair`, `…_path_string`, `…_none_falls_back_to_name_match`, `…_bare_number_rejected` — every DEVICE_MATCH syntax end-to-end
- `test_button_symbol_decimal_and_none`, `test_scroll_btn_none_rejected` — button parsing end-to-end (symbol → 276, decimal pass-through, `none` rules)

**`tests/test_hot_reload_e2e.py`** — the real daemon as a subprocess with an unmatchable NAME_MATCH (it never grabs anything):
- `test_hot_reload_lifecycle` — six phases against its live log: startup report → live change applies within ~2 s (`config reloaded: CURVE 0.5->0.6`) → malformed parse rejected once and *not retried* across two full scan cycles (4.5 s idle) → fix reloads from the kept value → deleting the file logs `config file missing — keeping current values` exactly once → recreating resumes normal reloads; SIGTERM cleanup is asserted

**`tests/test_preset_cli.py`** — `veloscroll_preset.py` as a subprocess against temp config files:
- `test_save_creates_preset`, `test_save_unchanged_is_noop`, `test_save_changed_creates_backup` — save writes `presets/<name>.ini` with the key count, is a no-op (no backup) when unchanged, and creates a `.bak-*` on overwrite
- `test_loadfeel_applies_only_its_group` — load applies only its group's keys, rewrites lines in place (comments preserved), backs up config.ini, prints per-key `old -> new`, the skipped-keys note and the journalctl hint; other groups' keys are untouched
- `test_load_missing_preset_fails_and_leaves_config_untouched` — rc 1 with the exact error; config byte-identical afterwards
- `test_list_empty_then_table` — empty-dir message, then a sorted table with the "(absent = not captured)" footer
- `test_backups_empty_then_newest_first` — empty message, then every backup listed newest first (verified against two real backups)
- `test_restore_default_newest_and_bad_ref` — default restore puts back the *pre-apply* snapshot of the newest config backup; a bad reference errors with rc 1 and writes nothing
- `test_save_never_captures_max_backups`, `test_load_warns_and_ignores_max_backups_in_preset`, `test_list_has_no_max_backups_column` — MAX_BACKUPS is never part of presets: save omits it, a hand-edited preset containing it (even an invalid value) gets a warn-and-ignore line on every load while its group still applies and config.ini's key is untouched, and list has no column for it
- `test_max_backups_zero_writes_no_backups` — with MAX_BACKUPS=0 in config.ini, save-overwrite and change-producing loads apply their changes but write no `.bak-*` files and print no backup line (existing backups stay untouched)
- `test_usage_errors`, `test_failure_stops_remaining_ops` — argparse-level usage errors (`list extra`, unknown command, odd op count) and that one failed op stops the rest while earlier ops stay applied

**`tests/test_seed_cli.py`** — `veloscroll_seed.main()` in-process (the backend itself is covered by `test_seed_backend.py`):
- `test_root_refusal` — euid 0 → rc 1 with the "refusing to run as root" message
- `test_discovery_failure_is_surfaced` — a SeedError from discovery becomes rc 1 + `veloscroll-seed: …` on stderr
- `test_unsupported_de_wm_rejected` — an unknown DE_WM exits before any backend work, listing the supported ones
- `test_argparse_rejects_unknown_flag` — argparse SystemExit(2) with "unrecognized arguments"

**`tests/test_docs_links.py`** — documentation integrity:
- `test_all_markdown_files_exist` — README + every file in `docs/` and `docs-desktop/` is present
- `test_relative_links_resolve` — every relative markdown link resolves to an existing file/directory, and every anchor (same-page or cross-file) matches a heading's GitHub-style slug; code blocks are ignored so example snippets can't false-positive

## Test helpers (not tests)

- `tests/conftest.py` — sets `VELOSCROLL_CONFIG` to a nonexistent path **before** importing veloscroll (the import runs the real config load/check/apply block and would otherwise read `/etc/veloscroll/config.ini`); provides the snapshot/restore fixture for daemon globals, the fresh-module reload helper, and the fake-hardware context manager
- `tests/fakes.py` — FakeDev/FakeUI/FakeBus: a fake evdev input device with a recording UInput, plus `install_fakes()` (patches evdev/UInput in the module namespace) and thread-stop/wait helpers
- `tests/probe_values.py` — subprocess probe for the startup matrix; prints `VALUES <json>` of all daemon keys after real import
- `pytest.ini`, `requirements-dev.txt` — test configuration and dev dependencies

---

Back to the [README](../README.md) · See also: [Advanced](ADVANCED.md), [Configuration](CONFIGURATION.md)
