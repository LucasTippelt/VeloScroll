"""Integration tier: in-process config hot-reload (_maybe_reload_config) and apply_values state-transition semantics.

No threads involved — the supervisor's once-per-iteration reload is exercised by calling it directly against a tmp file,
so every log line lands on the main thread where capsys can see it."""
import os

from evdev import ecodes as e


def _point_at(v, p):
    v.CONFIG_PATH = str(p)


# ---------------- basic reload cycle ----------------

def test_first_call_applies_and_unchanged_file_is_noop(vs, tmp_path, capsys):
    p = tmp_path / "config.ini"
    p.write_text("[veloscroll]\nCURVE = 0.6\nINVERT = true\n")
    _point_at(vs, p)

    vs._maybe_reload_config()
    out = capsys.readouterr().out
    assert "config reloaded:" in out
    assert "CURVE 0.5->0.6" in out and "INVERT False->True" in out
    assert vs.CURVE == 0.6 and vs.INVERT is True

    vs._maybe_reload_config()              # mtime/size unchanged -> early return before parsing
    assert capsys.readouterr().out == ""


def test_valid_live_change_applies_new_values(vs, tmp_path, capsys):
    p = tmp_path / "config.ini"
    p.write_text("[veloscroll]\nCURVE = 0.6\n")
    _point_at(vs, p)
    vs._maybe_reload_config()
    capsys.readouterr()

    p.write_text("[veloscroll]\nCURVE = 0.9\nMIN_RATE = 8\n")     # size differs -> stat changed
    vs._maybe_reload_config()
    out = capsys.readouterr().out
    assert "config reloaded:" in out and "CURVE 0.6->0.9" in out and "MIN_RATE 4.0->8.0" in out   # floats repr as 4.0/8.0
    assert vs.CURVE == 0.9 and vs.MIN_RATE == 8.0


def test_unchanged_content_with_new_mtime_logs_nothing(vs, tmp_path, capsys):
    p = tmp_path / "config.ini"
    content = "[veloscroll]\nCURVE = 0.6\n"
    p.write_text(content)
    _point_at(vs, p)
    vs._maybe_reload_config()
    capsys.readouterr()

    p.write_text(content)                  # same bytes: stat may differ (new mtime_ns), values cannot
    vs._maybe_reload_config()
    assert capsys.readouterr().out == ""   # no "config reloaded:" line when nothing actually changed
    assert vs.CURVE == 0.6


# ---------------- rejection paths ----------------

def test_malformed_file_rejected_once_not_retried_until_it_changes(vs, tmp_path, capsys):
    p = tmp_path / "config.ini"
    p.write_text("[veloscroll]\nCURVE = 0.6\n")
    _point_at(vs, p)
    vs._maybe_reload_config()
    capsys.readouterr()

    p.write_text("[veloscroll]\nCURVE = abc\n")     # unparseable number
    vs._maybe_reload_config()
    out = capsys.readouterr().out
    assert "config reload rejected, keeping current values:" in out and "CURVE" in out
    assert vs.CURVE == 0.6                           # old value kept

    vs._maybe_reload_config()                        # stat already advanced -> a rejected parse is NOT retried...
    assert capsys.readouterr().out == ""             # ...until the file changes again

    p.write_text("[veloscroll]\nCURVE = 0.8\n")      # fix it: reload succeeds on the next change
    vs._maybe_reload_config()
    out = capsys.readouterr().out
    assert "config reloaded:" in out and "CURVE 0.6->0.8" in out
    assert vs.CURVE == 0.8


def test_check_config_failure_is_rejected_with_all_errors(vs, tmp_path, capsys):
    p = tmp_path / "config.ini"
    p.write_text("[veloscroll]\nCURVE = 0.6\n")
    _point_at(vs, p)
    vs._maybe_reload_config()
    capsys.readouterr()

    # parseable (plain floats) but semantically invalid: both errors reported together, joined with "; "
    p.write_text("[veloscroll]\nOUT_SMOOTH = 2\nCURVE_H = -1\n")
    vs._maybe_reload_config()
    out = capsys.readouterr().out
    assert "config reload rejected, keeping current values:" in out
    assert "OUT_SMOOTH must be in the range (0, 1]" in out and "CURVE_H must be > 0" in out
    assert vs.OUT_SMOOTH == 0.8 and vs.CURVE_H is None   # old values kept


def test_missing_file_logged_once_then_silent_until_recreated(vs, tmp_path, capsys):
    p = tmp_path / "config.ini"
    p.write_text("[veloscroll]\nCURVE = 0.6\n")
    _point_at(vs, p)
    vs._maybe_reload_config()
    capsys.readouterr()

    os.remove(p)
    vs._maybe_reload_config()
    out = capsys.readouterr().out
    assert "config file missing — keeping current values" in out
    assert vs.CURVE == 0.6                            # current values kept

    vs._maybe_reload_config()                         # still absent: the "gone" notice is not repeated
    assert capsys.readouterr().out == ""

    p.write_text("[veloscroll]\nCURVE = 0.9\n")       # recreated -> reloads normally again
    vs._maybe_reload_config()
    out = capsys.readouterr().out
    assert "config reloaded:" in out and "CURVE 0.6->0.9" in out


# ---------------- LATENCY_LOG transitions ----------------

def test_latency_log_enable_resets_epoch_and_prints_model(vs, tmp_path, capsys):
    p = tmp_path / "config.ini"
    p.write_text("[veloscroll]\nLATENCY_LOG = true\n")
    _point_at(vs, p)

    vs._lat["press_ts"] = 123.0                       # stale epoch state from a previous life...
    vs._maybe_reload_config()                         # ...must be wiped when LATENCY_LOG flips False->True
    out = capsys.readouterr().out

    assert vs.LATENCY_LOG is True
    assert vs._lat["press_ts"] is None                # _lat_reset_hold ran on the enable transition
    expected = "latency model: " + vs._latency_model()
    assert expected in out                            # default values: tick=4.0ms tau=2.5ms ...


def test_model_key_change_reprints_model_at_new_values(vs, tmp_path, capsys):
    p = tmp_path / "config.ini"
    p.write_text("[veloscroll]\nLATENCY_LOG = true\n")
    _point_at(vs, p)
    vs._maybe_reload_config()
    capsys.readouterr()

    p.write_text("[veloscroll]\nLATENCY_LOG = true\nTICK = 0.008\nOUT_SMOOTH = 0.5\n")
    vs._maybe_reload_config()
    out = capsys.readouterr().out

    assert "config reloaded:" in out and "TICK 0.004->0.008" in out and "OUT_SMOOTH 0.8->0.5" in out
    expected = "latency model: " + vs._latency_model()      # recomputed from the now-applied globals
    assert expected in out
    assert "tick=8.0ms" in expected                        # sanity: the line really reflects the new TICK


# ---------------- apply_values D7 (live button/mode swap) ----------------

def test_d7_button_swap_clears_stuck_held_state(vs):
    with vs.lock:
        vs.held = True
        vs.held_v = True
        vs.offset = 123.0
        vs.acc_notch = 55

    values = dict(vs._DEFAULTS)
    values["SCROLL_BTN"] = e.BTN_TASK                   # differs from the current BTN_SIDE -> D7 path
    vs.apply_values(values)

    with vs.lock:
        assert not (vs.held or vs.held_v or vs.held_h)  # a stuck-held/latched state never carries over...
        assert vs.offset == 0 and vs.h_offset == 0      # ...nor do partial accumulators
        assert vs.acc_notch == 0 and vs.ticker_reset is True
    assert vs.SCROLL_BTN == e.BTN_TASK


def test_d7_toggle_mode_flip_also_clears_held_state(vs):
    with vs.lock:
        vs.held = True
        vs.held_h = True
        vs.mode = "h"
        vs.h_offset = -80.0

    values = dict(vs._DEFAULTS)
    values["TOGGLE_SCROLL"] = True                      # scroll-mode switch -> D7 path
    vs.apply_values(values)

    with vs.lock:
        assert not (vs.held or vs.held_v or vs.held_h)
        assert vs.offset == 0 and vs.h_offset == 0 and vs.acc_notch == 0
    assert vs.TOGGLE_SCROLL is True


def test_d7_vertical_h_flip_also_clears_held_state(vs):
    with vs.lock:
        vs.held = True
        vs.held_v = True

    values = dict(vs._DEFAULTS)
    values["VERTICAL_H"] = True                         # vertical-H mode flip -> D7 path
    vs.apply_values(values)

    with vs.lock:
        assert not (vs.held or vs.held_v or vs.held_h)
        assert vs.ticker_reset is True
    assert vs.VERTICAL_H is True


def test_d7_button_swap_also_clears_stale_btn_left_down(vs):
    with vs.lock:
        vs.held = True
        vs.btn_left_down = True                    # stale flag from a forced session reset while left was physically down...

    values = dict(vs._DEFAULTS)
    values["SCROLL_BTN"] = e.BTN_TASK               # differs from the current BTN_SIDE -> D7 path
    vs.apply_values(values)

    with vs.lock:
        assert not (vs.held or vs.held_v or vs.held_h)
        assert vs.btn_left_down is False            # ...a stale flag can never arm drag mode on the next session
