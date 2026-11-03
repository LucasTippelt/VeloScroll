"""Integration tier: STATE_FILE — the /run/veloscroll/state JSON contract (status snapshot for GUIs) —
and DISTANCE_FILE, its high-rate companion: a small per-axis distance/rate document at
VELOSCROLL_DISTANCE_FILE rewritten on every tick while a session is held (one final idle doc on release).

Uses the sim harness (fake device + recorder); VELOSCROLL_STATE_FILE / VELOSCROLL_DISTANCE_FILE point at tmp paths so the writers never touch /run.
Covers: flag off -> no file ever; startup apply with flag on -> full document whose values match the effective config;
hot-reload toggling the flag mid-run; grab/release populating devices_grabbed; held transitions driving `active`;
DISTANCE_FILE publishing both axes' distances + rate at tick frequency while held (vertical and horizontal), dropping to an idle doc on release, plus its default-off behavior;
a rejected reload flipping reload_ok (values unchanged); plus unit checks of key parsing/validation and serialization."""
import json
import os
import time

from evdev import ecodes as e

from fakes import push, wait_until


def _read(state):
    with open(state, "r", encoding="utf-8") as f:
        return json.load(f)


def _held(v):
    with v.lock:
        return v.held


def _state_env(tmp_path, monkeypatch):
    state = tmp_path / "state"
    # must be set before the sim's module reload re-executes veloscroll.py (module-level STATE_PATH reads it)
    monkeypatch.setenv("VELOSCROLL_STATE_FILE", str(state))
    return str(state)


def _distance_env(tmp_path, monkeypatch):
    dist = tmp_path / "distance"
    # must be set before the sim's module reload re-executes veloscroll.py (module-level DISTANCE_PATH reads it)
    monkeypatch.setenv("VELOSCROLL_DISTANCE_FILE", str(dist))
    return str(dist)


STATE_ON = "[veloscroll]\nCURVE = 0.75\nSTATE_FILE = true\n"
DISTANCE_ON = STATE_ON + "DISTANCE_FILE = true\n"
DUAL_AXIS_INI = DISTANCE_ON + "SCROLL_BTN_H = BTN_EXTRA\n"


# ---------------- flag off: zero overhead, no file ever ----------------

def test_flag_off_writes_no_state_file(sim, tmp_path, monkeypatch):
    state = _state_env(tmp_path, monkeypatch)
    with sim() as s:                                  # STATE_FILE defaults to False; exercise every write call site anyway
        push(s.dev, e.EV_KEY, e.BTN_SIDE, 1)          # grab success + held transition (True)...
        wait_until(lambda: _held(s.vs))
        push(s.dev, e.EV_KEY, e.BTN_SIDE, 0)          # ...and back to False; teardown closes the device (release call site)
        wait_until(lambda: not _held(s.vs))
    assert not os.path.exists(state)


# ---------------- startup apply with flag on: full document ----------------

def test_startup_apply_writes_full_document(sim, tmp_path, monkeypatch):
    state = _state_env(tmp_path, monkeypatch)
    with sim(STATE_ON) as s:
        wait_until(lambda: os.path.exists(state))     # first document arrives on grab success (sim has no main(); it publishes the same full contract)
        data = _read(state)
        assert data["version"] == "2.0.0"
        assert data["pid"] == os.getpid()             # in-process daemon
        assert data["config_path"] == s.vs.CONFIG_PATH
        assert data["config_mtime_ns"] == os.stat(s.vs.CONFIG_PATH).st_mtime_ns
        assert data["reload_ok"] is True and data["reload_error"] is None
        assert set(data["values"]) == set(s.vs.DAEMON_KEYS)      # all 30 keys, parsed Python values (None -> null, pair -> list)
        for key in s.vs.DAEMON_KEYS:                              # exactly the effective config (ini overlay on defaults)
            expected = getattr(s.vs, key)
            if isinstance(expected, tuple):
                expected = list(expected)
            assert data["values"][key] == expected, key
        assert data["values"]["STATE_FILE"] is True and data["values"]["CURVE"] == 0.75
        wait_until(lambda: len(_read(state)["devices_grabbed"]) == 1)   # grab success publishes the device
        [entry] = _read(state)["devices_grabbed"]
        assert entry == {"path": "sim://mouse", "name": s.dev.name,
                         "vendor": f"0x{s.dev.info.vendor:x}", "product": f"0x{s.dev.info.product:x}"}
        assert data["active"] is False                 # nothing held at startup...
        assert data["virtual_device_name"] == s.vs.VIRTUAL_NAME
        assert "live" not in data                      # live metrics moved to the separate distance file (DISTANCE_FILE) — never part of this document


# ---------------- hot-reload toggling the flag mid-run ----------------

def test_hot_reload_flag_on_mid_run_creates_file(sim, tmp_path, monkeypatch):
    state = _state_env(tmp_path, monkeypatch)
    with sim("[veloscroll]\nCURVE = 0.7\n") as s:      # flag off initially (code default)
        assert not os.path.exists(state)
        with open(s.vs.CONFIG_PATH, "a", encoding="utf-8") as f:   # file changed -> the supervisor's once-per-iteration call picks it up
            f.write("STATE_FILE = true\n")
        s.vs._maybe_reload_config()                    # sim harness has no supervisor thread; drive the same reload directly
        wait_until(lambda: os.path.exists(state))      # apply_values publishes on an accepted reload (flag just enabled)
        data = _read(state)
        assert data["values"]["STATE_FILE"] is True and data["values"]["CURVE"] == 0.7
        assert data["reload_ok"] is True and data["reload_error"] is None


# ---------------- grab/release populate devices_grabbed ----------------

def test_grab_and_release_populate_devices(sim, tmp_path, monkeypatch):
    state = _state_env(tmp_path, monkeypatch)
    with sim(STATE_ON) as s:
        wait_until(lambda: os.path.exists(state))   # grab success publishes the first document (may land just after Sim is yielded)
        wait_until(lambda: len(_read(state)["devices_grabbed"]) == 1)
        [entry] = _read(state)["devices_grabbed"]
        assert entry["path"] == "sim://mouse" and entry["name"] == s.dev.name
        s.dev.close()                                  # device lost -> read_loop ends -> run()'s finally block publishes the release
        wait_until(lambda: _read(state)["devices_grabbed"] == [])


# ---------------- held transitions drive `active` ----------------

def test_held_transitions_drive_active(sim, tmp_path, monkeypatch):
    state = _state_env(tmp_path, monkeypatch)
    with sim(STATE_ON) as s:
        wait_until(lambda: os.path.exists(state))
        assert not _read(state)["active"]              # idle at startup
        push(s.dev, e.EV_KEY, e.BTN_SIDE, 1)           # press -> session engaged
        wait_until(lambda: _read(state)["active"])
        push(s.dev, e.EV_KEY, e.BTN_SIDE, 0)           # release -> session ended
        wait_until(lambda: not _read(state)["active"])


# ---------------- DISTANCE_FILE: high-rate per-axis distance feed (config key, off by default) ----------------

def test_distance_file_off_by_default_writes_nothing(sim, tmp_path, monkeypatch):
    state = _state_env(tmp_path, monkeypatch)         # DISTANCE_FILE unset -> code default False (zero overhead without a consumer)
    dist = _distance_env(tmp_path, monkeypatch)
    with sim(STATE_ON) as s:
        wait_until(lambda: os.path.exists(state))
        push(s.dev, e.EV_KEY, e.BTN_SIDE, 1)           # hold + motion...
        wait_until(lambda: _held(s.vs))
        push(s.dev, e.EV_REL, e.REL_Y, 480)
        time.sleep(0.2)                                # many ticks pass while held...
        assert not os.path.exists(dist)                # ...yet no distance file is ever written
        assert "live" not in _read(state)              # and the state document carries no live metrics either


def test_distance_docs_track_both_axes_while_held(sim, tmp_path, monkeypatch):
    state = _state_env(tmp_path, monkeypatch)
    dist = _distance_env(tmp_path, monkeypatch)
    with sim(DUAL_AXIS_INI) as s:
        wait_until(lambda: os.path.exists(dist))       # startup apply publishes an idle document the moment the flag is on
        data = _read(dist)
        assert set(data) == {"version", "pid", "active", "mode",
                             "distance_in_v", "distance_in_h", "rate_nps", "ts"}   # the GUI's live curve markers read exactly these
        assert data["version"] == "2.0.0" and data["pid"] == os.getpid()
        assert data["active"] is False and data["mode"] is None                     # idle at startup...
        assert data["distance_in_v"] == 0.0 and data["distance_in_h"] == 0.0

        push(s.dev, e.EV_KEY, e.BTN_SIDE, 1)           # press -> session engaged (active flips without waiting for a tick)
        wait_until(lambda: _read(dist)["active"] is True and _read(dist)["mode"] == "v")
        push(s.dev, e.EV_REL, e.REL_Y, 480)            # vertical motion while held...
        def v_with_motion():                           # ...until a per-tick write carries the accumulated distance (inches = counts / DPI)
            d = _read(dist)
            return d["distance_in_v"] == 480 / s.vs.DPI and d["distance_in_h"] == 0.0   # both axes published; H untouched while v is active
        wait_until(v_with_motion)
        data = _read(dist)
        assert isinstance(data["rate_nps"], float)     # smoothed rate of the active session...
        assert os.stat(dist).st_mode & 0o777 == 0o644  # ...world-readable for the GUI user (root-owned under systemd)

        push(s.dev, e.EV_KEY, e.BTN_EXTRA, 1)          # second button -> LIFO axis switch to horizontal (fresh origin on both axes)
        wait_until(lambda: _read(dist)["mode"] == "h")
        push(s.dev, e.EV_REL, e.REL_X, 240)            # horizontal motion...
        def h_with_motion():
            d = _read(dist)
            return d["distance_in_h"] == 240 / s.vs.DPI and d["distance_in_v"] == 0.0
        wait_until(h_with_motion)

        push(s.dev, e.EV_KEY, e.BTN_EXTRA, 0)          # release both -> session ended: one final idle document
        push(s.dev, e.EV_KEY, e.BTN_SIDE, 0)
        def idle_doc():
            d = _read(dist)
            return d["active"] is False and d["mode"] is None and d["rate_nps"] == 0.0
        wait_until(idle_doc)


def test_distance_docs_update_continuously_while_held(sim, tmp_path, monkeypatch):
    """The feed must keep moving while held (per-tick writes), not publish once per hold."""
    dist = _distance_env(tmp_path, monkeypatch)
    with sim(DISTANCE_ON + "TICK = 0.01\n") as s:      # 100 Hz ticker — comfortably above the old ~20 Hz live throttle
        wait_until(lambda: os.path.exists(dist))
        push(s.dev, e.EV_KEY, e.BTN_SIDE, 1)           # hold + motion so every tick has fresh values to publish
        wait_until(lambda: _held(s.vs))
        for i in range(0, 480, 60):
            push(s.dev, e.EV_REL, e.REL_Y, 60)
        first = _read(dist)["ts"]
        mtimes = {os.stat(dist).st_mtime_ns}           # distinct file rewrites over the window...
        deadline = time.monotonic() + 0.4              # ...at ~100 Hz that is dozens of writes; a one-shot publish would show exactly one
        while time.monotonic() < deadline:
            mtimes.add(os.stat(dist).st_mtime_ns)
            time.sleep(0.02)
        assert len(mtimes) >= 6                        # continuous rewriting (the old 20 Hz throttle managed ~8 in this window at best — and only while held)
        assert _read(dist)["ts"] > first               # the wall-clock write ts advances with every document


# ---------------- rejected reload flips reload_ok ----------------

def test_rejected_reload_reports_error_in_state(sim, tmp_path, monkeypatch):
    state = _state_env(tmp_path, monkeypatch)
    with sim(STATE_ON) as s:
        wait_until(lambda: os.path.exists(state))
        assert _read(state)["reload_ok"] is True and _read(state)["values"]["CURVE"] == 0.75
        with open(s.vs.CONFIG_PATH, "w", encoding="utf-8") as f:   # invalid value -> rejected reload keeps the old values
            f.write("[veloscroll]\nCURVE = abc\nSTATE_FILE = true\n")
        s.vs._maybe_reload_config()
        wait_until(lambda: _read(state)["reload_ok"] is False)
        data = _read(state)
        assert "CURVE" in (data["reload_error"] or "")   # the error string names the bad key...
        assert data["values"]["CURVE"] == 0.75           # ...while every effective value stays unchanged


# ---------------- unit: key parsing / validation / registry ----------------

def test_daemon_keys_include_gui_flags(vs):
    assert "STATE_FILE" in vs.DAEMON_KEYS and "DISTANCE_FILE" in vs.DAEMON_KEYS
    assert len(vs.DAEMON_KEYS) == 30         # was 28 before LEFT_CLICK_RESET/INVERT_H landed; the probe prints exactly this many


def test_distance_file_key_parse_and_check(vs, tmp_path):
    p = tmp_path / "config.ini"
    p.write_text("[veloscroll]\nDISTANCE_FILE = true\n")
    vs.CONFIG_PATH = str(p)                  # restored by the fixture afterwards
    values = vs.load_config()
    assert values["DISTANCE_FILE"] is True
    assert vs.check_config(values) == []

    p.write_text("[veloscroll]\nDISTANCE_FILE = none\n")   # 'none' is not a boolean (unlike TOGGLE_SCROLL_H, which allows it)
    import pytest
    with pytest.raises(vs.ConfigError) as exc:
        vs.load_config()
    assert "DISTANCE_FILE" in str(exc.value)

    bad = dict(vs._DEFAULTS)
    bad["DISTANCE_FILE"] = "true"            # an unparsed string must be rejected by check_config (defense-in-depth gate for writers)
    assert any("DISTANCE_FILE" in err for err in vs.check_config(bad))


def test_state_file_key_parse_and_check(vs, tmp_path):
    p = tmp_path / "config.ini"
    p.write_text("[veloscroll]\nSTATE_FILE = true\n")
    vs.CONFIG_PATH = str(p)                  # restored by the fixture afterwards
    values = vs.load_config()
    assert values["STATE_FILE"] is True
    assert vs.check_config(values) == []

    p.write_text("[veloscroll]\nSTATE_FILE = none\n")   # 'none' is not a boolean (unlike TOGGLE_SCROLL_H, which allows it)
    import pytest
    with pytest.raises(vs.ConfigError) as exc:
        vs.load_config()
    assert "STATE_FILE" in str(exc.value)

    bad = dict(vs._DEFAULTS)
    bad["STATE_FILE"] = "true"               # an unparsed string must be rejected by check_config (defense-in-depth gate for writers)
    assert any("STATE_FILE" in err for err in vs.check_config(bad))


# ---------------- unit: writer guard + serialization contract ----------------

def test_writer_is_noop_when_flag_off(vs, tmp_path):
    state = tmp_path / "state"
    vs.STATE_PATH = str(state)
    vs._state_writing = True                 # daemon loop running...
    vs.STATE_FILE = False                    # ...but the flag off: the guard lives inside the writer — no call-site noise
    vs._write_state()
    assert not state.exists()


def test_writer_is_noop_when_daemon_loop_not_running(vs, tmp_path):
    # helper scripts (veloscroll_preset.py, ...) import veloscroll with a real config: while STATE_FILE is on in that
    # config, their import-time apply must NOT publish — otherwise they clobber the live daemon's status file (wrong pid, no devices)
    state = tmp_path / "state"
    vs.STATE_PATH = str(state)
    vs.STATE_FILE = True
    assert vs._state_writing is False        # main() has not run in this process
    vs._write_state()
    assert not state.exists()


def test_distance_writer_is_noop_when_flag_off_or_loop_not_running(vs, tmp_path):
    dist = tmp_path / "distance"
    vs.DISTANCE_PATH = str(dist)
    vs._state_writing = True                 # daemon loop running...
    vs.DISTANCE_FILE = False                 # ...but the flag off: the guard lives inside the writer — no call-site noise
    vs._write_distance()
    assert not dist.exists()
    vs.DISTANCE_FILE = True
    vs._state_writing = False                # helper scripts import veloscroll without main(): their apply must never publish (wrong pid, stale offsets)
    vs._write_distance()
    assert not dist.exists()


def test_write_state_serializes_contract_fields(vs, tmp_path):
    state = tmp_path / "state"
    vs.STATE_PATH = str(state)
    vs.STATE_FILE = True
    vs._state_writing = True                 # simulate a process running the daemon loop (main())
    vs.DEVICE_MATCH = (0x46d, 0xc084)        # tuple -> [vendor, product] in JSON; the daemon parses it back to the same pair
    with vs.lock:
        vs._write_state_nolock()              # call-site variant used while holding `lock`...
    vs._write_state()                         # ...and the locking wrapper for unlocked callers (e.g. reload rejects)
    data = json.loads(state.read_text(encoding="utf-8"))
    assert data["version"] == "2.0.0" and data["pid"] == os.getpid()
    assert data["config_path"] == vs.CONFIG_PATH
    assert data["config_mtime_ns"] == 0       # the default test config path does not exist
    assert data["reload_ok"] is True and data["reload_error"] is None
    assert set(data["values"]) == set(vs.DAEMON_KEYS)      # all 30 keys
    assert data["values"]["DEVICE_MATCH"] == [0x46d, 0xc084]
    assert data["values"]["DISABLED_BTN"] is None          # None -> null
    assert data["active"] is False and data["devices_grabbed"] == []
    assert data["virtual_device_name"] == vs.VIRTUAL_NAME
    assert "live" not in data                                  # live metrics live in the distance file now, never here
    assert os.stat(state).st_mode & 0o777 == 0o644         # world-readable for the GUI user (root-owned under systemd)
