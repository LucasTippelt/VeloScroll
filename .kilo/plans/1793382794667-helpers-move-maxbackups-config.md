# Plan: Move helpers into `helpers/` + configurable `MAX_BACKUPS`

Repo: `/opt/veloscroll`. Two tasks, one release (new `[Unreleased]` CHANGELOG section — v1.1 is already tagged at `v1.1-16`).

## Resolved decisions

1. **Move:** all root `.py` except `veloscroll.py` and `veloscroll_preset.py` go to a new flat (non-package) `helpers/` dir:
   `ListButtonPresses.py`, `ListDeviceNames.py`, `veloscroll_seed.py`, `veloscroll_tuning_helper.py`. No backward-compat shims at the old paths; all docs are updated in the same change.
2. **MAX_BACKUPS** (user wrote "MAXBACKUP" — this is the existing constant) becomes a full config.ini key: 26th entry of `DAEMON_KEYS` in `veloscroll.py`, hot-reloaded, single source of truth via `import veloscroll`. **Presets never touch it:** no load command (including `loadall`) may apply it, and `save` does not capture it — backup policy is per-machine operational state, like the excluded button/device groups. A preset file that contains it anyway (hand-edited) gets a warn-and-ignore line on every load.
3. **Value semantics:** integer ≥ −1. `-1` = unlimited, `N ≥ 1` = keep newest N per file family, **`0` = backups disabled altogether** — no `.bak-*` file is written by any helper run; existing backups are left untouched (non-destructive); pruning is a no-op for that run. Invalid: non-integers and anything < −1 (e.g. `-2`).

## Task 1 — move scripts into `helpers/`

1. `mkdir helpers`; `git mv` the four files above into it (preserves history/modes).
2. Fix `import veloscroll` in the two moved scripts that import it (currently they insert their *own* dir, which becomes `helpers/`):
   - `helpers/veloscroll_seed.py:504` → `sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))`
   - `helpers/veloscroll_tuning_helper.py:303` → same parent-dir expression.
   - `veloscroll_preset.py:526` stays unchanged (script remains at root).
3. Update usage comments inside the moved scripts to the new absolute paths: `ListDeviceNames.py:12`, `ListButtonPresses.py:12-13`, `veloscroll_seed.py:20`, `veloscroll_tuning_helper.py:19` (→ `/opt/veloscroll/helpers/<name>`).
4. Update stale cross-reference comment `veloscroll_preset.py:96` (`Duplicated from veloscroll_seed._prune_backups (veloscroll_seed.py:185)` → `helpers/veloscroll_seed.py`).
5. Tests — only path plumbing changes, module names stay the same:
   - `tests/conftest.py:23-27`: add `HELPERS_DIR = os.path.join(REPO_ROOT, "helpers")` to the sys.path loop so `import veloscroll_seed`, `import veloscroll_tuning_helper`, `import ListDeviceNames`, `import ListButtonPresses` (used by `test_seed_backend.py:12`, `test_seed_cli.py:10`, `test_tuning_helper_units.py:11`, `test_list_scripts.py:9-10`) keep working.
   - `tests/test_preset_cli.py:11` (`PRESET_CLI = ROOT/veloscroll_preset.py`) unchanged — preset helper stays at root.
6. `.gitignore`: add `helpers/__pycache__` (matches the existing per-dir style). Optionally delete the now-stale root `__pycache__/` contents from old modules.

## Task 2 — `MAX_BACKUPS` in config.ini (incl. new `0` = disabled)

### Code

1. `veloscroll.py`:
   - `DAEMON_KEYS` (line 70-74): append `"MAX_BACKUPS"` at the end of the tuple (after `"LATENCY_LOG"`) — keeps existing ordering assumptions in `_rewrite_config_lines` appends and tests stable. `_DEFAULTS` picks up the code default `5` automatically; `apply_values` assigns it under lock with no runtime effect on the daemon (helpers read the fresh value at their own import).
   - `_parse_ini_value`: new branch before the float fallback: `int(raw)`; raise `ConfigError` if result < −1, message naming `-1` (unlimited), `0` (disable backups) and positive integers.
   - `check_config`: defensive guard mirroring other keys — integer (not bool) and ≥ −1.
   - Update the constant comment at line 60 (no longer "intentionally not in config.ini") and the header block lines 19-26: only `DE_WM` / `VIRTUAL_NAME` remain fork-level constants outside config.ini; `MAX_BACKUPS` is a normal key, hot-reloaded.
2. `veloscroll_preset.py`:
   - `_check_max_backups` (line 86-90): accept `-1`, `0`, ≥ 1; new error message mentioning all three.
   - `_prune_backups` (line 93-111): contract becomes the config key's contract — `max_backups == 0` returns `[]` early (deletes nothing); only < −1 / non-int raise. Update the docstring and error message; update the "Duplicated from" comment path (Task 1 step 4).
   - Backup call sites skip writing when disabled:
     - `cmd_save` line 264: `_backup(preset_path) if existing is not None else None` → also require `vs.MAX_BACKUPS != 0`.
     - `_cmd_load` line 351 and `cmd_restore` line 459: same condition on their existence checks. The existing `if backup_path` guards make pruning a no-op automatically. No new output lines when disabled (consistent with "no-op writes nothing").
    - Header comments: lines 28-30 — note `MAX_BACKUPS` now comes from config.ini and that `0` disables backups; line 12 usage block ("snapshot every daemon key") → "every daemon key except MAX_BACKUPS".
   - **Preset exclusion (user requirement: MAX_BACKUPS must never be loaded by any preset load group):**
     - Introduce a module constant, e.g. `PRESET_NEVER_APPLIED = ("MAX_BACKUPS",)` with a comment (per-machine backup policy — not part of a shareable preset profile), and add `"MAX_BACKUPS"` to `LOADALL_EXCLUDED` (line 61) so the `loadall` key tuple built at line 545 excludes it automatically. Named groups already don't contain it; this makes *no* command able to apply it.
     - `cmd_save` (lines 234-277): skip PRESET_NEVER_APPLIED keys in the capture loop so preset files never contain the key; fix the header comment (line 51-52 wording and line 251-253 "(all N daemon keys…)") to say "every daemon key except MAX_BACKUPS".
      - `_cmd_load` (lines 313-333): in the preset-key loop, route PRESET_NEVER_APPLIED keys to their own warn-and-ignore list after the empty-value check but *before* parsing and before they can reach `skipped` — otherwise a hand-edited preset containing the key would hit `_covering_cmds()` (line 280-289), which returns no covering command for it and print a broken "— use  to apply them" hint. Consequence: an invalid value for this key in a preset file never fails a load (it is not applied, so it is not validated). Warning wording along the lines of: `warning: MAX_BACKUPS in <preset> is ignored — backup policy is not part of presets; set it directly in config.ini`.
     - `cmd_list` (line 390): build columns from DAEMON_KEYS minus PRESET_NEVER_APPLIED so there is no permanently empty column.
     - `cmd_restore`: **no change** — restoring a `config.ini.bak-*` backup legitimately puts the file's MAX_BACKUPS value back (it validates via the same daemon-key merge as any other key); only preset *loads* are restricted.
3. `helpers/veloscroll_seed.py`:
   - `_prune_backups` (line 185-201): same contract change as the preset helper's copy (`0` → no-op `[]`, message updated).
   - Backup writes in `KdePlasmaBackend.seed()` (lines 260-264) and `remove_stale()` (lines 322-324): wrap the `backup_path = …; shutil.copy2(…); pruned = _prune_backups(…)` block in `if max_backups != 0:` so with `0` nothing is written or deleted.

### config.ini.example

Add under a new `; --- backups (helper scripts) ---` section after `TICK`:

```
MAX_BACKUPS = 5
; How many .bak-<timestamp> backups the preset helper and seed script keep per file family:
; -1 = unlimited, N >= 1 = keep only the newest N, 0 = disable backups entirely (no backup files are written).
; Hot-reloaded like every other key; each helper run reads the current value.
```

## Documentation updates

Task 1 (new paths) — update every reference:
- `README.md:56-59` — note helpers live in `helpers/` (`veloscroll_tuning_helper.py`, `ListDeviceNames.py`, `ListButtonPresses.py`).
- `docs/INSTALL.md:49,70` — `sudo python3 /opt/veloscroll/helpers/List{DeviceNames,ButtonPresses}.py …`.
- `docs-desktop/gnome.md:35,55`, `docs-desktop/cinnamon.md:35,55`, `docs-desktop/kde-plasma.md:38,58` — same List* paths; `kde-plasma.md:91,113,143,154,162` — `python3 /opt/veloscroll/helpers/veloscroll_seed.py …`.
- `docs/CONFIGURATION.md:113` — tuning helper path (keep the heading text identical so the TOC anchor on line 8 stays valid).
- `docs/TESTING.md:3` — "all five Python programs" → two at repo root + four helpers in `helpers/`.

Task 2 (MAX_BACKUPS is now a config key; 0 disables):
- `docs/CONFIGURATION.md`: new subsection after "Logging and debugging", e.g. "### Backups (helper scripts)" with one row: meaning, `-1` / `N ≥ 1` / `0` semantics, hot-reloaded, applies to preset helper (`config.ini.bak-*`, `<name>.ini.bak-*`) and seed (`kcminputrc.bak-*`).
- `docs/ADVANCED.md`: line 15 — only `DE_WM`/`VIRTUAL_NAME` remain intentionally out of config.ini; drop the `MAX_BACKUPS` table row (line 23); Backups section lines 48-56 — it's a config.ini key now, no restart needed.
- `docs/PRESETS.md:92` — pruning per `MAX_BACKUPS` from config.ini (default 5), plus one sentence: with `0`, save/load/restore write no backup files at all and existing ones are left in place (so `restore`'s "backs up first" property only holds while backups are enabled).
- `docs/PRESETS.md` "What `save` captures" (lines 80-86): one sentence — `MAX_BACKUPS` is deliberately not part of presets (backup policy stays per-machine in config.ini); if a preset file contains it, every load command warns and ignores it.
- `README.md:78` — mention `MAX_BACKUPS` is set in config.ini, `0` disables.
- `CHANGELOG.md`: new `## [Unreleased]` section at top with entries for (a) the helpers/ move + updated paths, (b) `MAX_BACKUPS` becoming a hot-reloaded config key and the new `0 = backups disabled` semantics; note existing configs without the key keep default 5, and that presets deliberately never capture or apply it. Do not rewrite the shipped `[1.1]` entry (line 14).

## Tests to update / add

- `tests/test_config_parse.py`: MAX_BACKUPS parsing — `"5"`→5, `"-1"`→−1, `"0"`→0; rejects `"-2"`, `"abc"`, `"1.5"` with ConfigError naming the valid forms.
- `tests/test_check_config.py`: valid −1/0/5; invalid −2 / float / bool.
- `tests/test_preset_ops.py`: `test_prune_invalid_values_raises` — drop `0` from the bad-value list (now a no-op returning [] with nothing deleted); add explicit 0-case; message-text assertions updated to the new wording.
- `tests/test_seed_backend.py`: seed/remove_stale with `max_backups=0` → `rep.backup_path is None`, pre-existing `.bak-*` files untouched; keep existing N≥1 / −1 cases green.
- `tests/test_preset_cli.py`: e2e scenario with `MAX_BACKUPS = 0` in the ini — save-overwrite and change-producing load write config changes but emit no `backup     :` line and create no `.bak-*`; `saved_key_count()` (line 32-35) must now subtract MAX_BACKUPS as well (it derives from `DAEMON_KEYS`, which will contain it).
- Preset-exclusion cases: `save` output/preset file contains no MAX_BACKUPS line; a preset file hand-edited to include `MAX_BACKUPS = …` → every load command applies its group normally, prints the warn-and-ignore line for MAX_BACKUPS, and never rewrites that key in config.ini (no broken empty "use  to apply them" hint); `list` table has no MAX_BACKUPS column.
- Verify nothing hardcodes "25 keys" (conftest.py:9 comment, probe_values.py prints dynamically — update the conftest comment to 26).

## Risks / edge cases

- Existing user configs have no MAX_BACKUPS → default 5, zero behavior change. Users who hand-edited the constant in `veloscroll.py` per update now set it in config.ini (that pain point was the motivation; mention it in the changelog entry).
- With `0`, `restore` loses its "undo is itself reversible" property — must be stated in PRESETS.md.
- Seed with `0` never deletes pre-existing `kcminputrc.bak-*` files either (no destructive cleanup) — deliberate.
- Old preset files (saved before this change) contain no MAX_BACKUPS line at all, so loads of them are unaffected; the warn-and-ignore path only fires for hand-edited preset files.

## Validation

1. `pip install -r requirements-dev.txt` if needed (evdev, pytest), then full suite: `python3 -m pytest tests/ --tb=short` (same command CI runs, `.github/workflows/test.yml`).
2. Import smoke for the moved scripts' new sys.path logic (exercises each script's real import path): with a temp config (`VELOSCROLL_CONFIG=/tmp/vs-smoke.ini`, content `[veloscroll]\nMAX_BACKUPS = 0\n`), run `python3 /opt/veloscroll/helpers/veloscroll_seed.py` — expect the seed's own device-discovery error (rc 1, "veloscroll-seed:" message), **not** an ImportError of veloscroll.
3. Behavior smoke: same temp config + a preset dir; `python3 /opt/veloscroll/veloscroll_preset.py --config /tmp/vs-smoke.ini save x` then re-save after editing the config → no `.bak-*` files created, no `backup     :` output line.
4. `tests/test_docs_links.py` (in-suite) catches any broken relative link or same-page anchor introduced by the doc edits — keep heading texts whose anchors are referenced in TOCs unchanged.
