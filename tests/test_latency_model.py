"""Unit tier: latency model math (_latency_model), percentiles (_pct), per-second line builder
(_lat_build_line) and kernel-timestamp sampling (_lat_input_sample). Port of the scratch lat_unit_test."""
import re
import time

from evdev import ecodes as e  # noqa: F401  (kept for clarity if events are scripted later)


class _Ev:
    def __init__(self, sec, usec):
        self.sec = sec
        self.usec = usec


# ---------------- _latency_model ----------------

def test_model_at_defaults(vs):
    vs.TICK, vs.OUT_SMOOTH, vs.MIN_RATE = 0.004, 0.8, 4.0
    line = vs._latency_model()
    assert "tick=4.0ms" in line
    assert "tau=2.5ms" in line
    assert "63% response ~4.5ms" in line
    assert "95% ~9.5ms" in line
    assert "~2-6ms (1 tick)" in line, line


def test_model_out_smooth_one_no_math_error(vs):
    vs.TICK, vs.OUT_SMOOTH, vs.MIN_RATE = 0.004, 1.0, 4.0
    line = vs._latency_model()
    assert "tau=0.0ms" in line and "~2-6ms (1 tick)" in line, line


def test_model_first_emit_over_50_tick_cap(vs):
    vs.TICK, vs.OUT_SMOOTH, vs.MIN_RATE = 0.004, 0.2, 0.01   # tiny rate + low smooth: never reaches one notch in 50 ticks
    line = vs._latency_model()
    assert ">50 ticks" in line, line


def test_model_multi_tick_plural_format(vs):
    vs.TICK, vs.OUT_SMOOTH, vs.MIN_RATE = 0.010, 0.3, 1.0
    line = vs._latency_model()
    m = re.search(r"first emit after deadzone ~(\d+)-(\d+)ms \((\d+) ticks?\)", line)
    assert m, line
    n = int(m.group(3))
    assert n > 1 and "ticks)" in line      # plural


# ---------------- _pct (nearest-rank on pre-sorted input) ----------------

def test_pct_single_element(vs):
    assert vs._pct([5.0], 95) == 5.0


def test_pct_0_to_99(vs):
    s = [float(i) for i in range(100)]     # 0..99
    assert vs._pct(s, 50) == 50.0          # idx = round(99 * 0.5) = round(49.5) -> 50 (banker's rounding to even)
    assert vs._pct(s, 95) == 94.0          # idx = round(99 * 0.95) = round(94.05) = 94


# ---------------- _lat_build_line ----------------

def test_build_line_empty_window_is_none(vs):
    vs._lat_reset_windows()
    assert vs._lat_build_line() is None


def test_build_line_periods_alone_are_not_activity(vs):
    vs._lat_reset_windows()
    vs._lat["periods"] = [0.004] * 250     # the ticker loop runs 24/7; idle periods must not emit a line
    assert vs._lat_build_line() is None


def test_build_line_populated_window_segments_and_invariants(vs):
    vs._lat_reset_windows()
    vs._lat["input"] = [0.001 * i for i in range(1, 201)]
    vs._lat["periods"] = [0.004] * 250
    vs._lat["overrun_max"] = 0.006
    vs._lat["overruns"] = 3
    vs._lat["press_emit"] = [0.0078, 0.0091]
    vs._lat["crossing_emit"] = [0.0039]
    vs._lat["uinput_max"] = 0.0004
    line = vs._lat_build_line()
    assert line.startswith("latency: input p50="), line

    m = re.search(r"p50=([\d.]+)ms p95=([\d.]+)ms max=([\d.]+)ms n=(\d+)", line)
    assert m, line
    p50, p95, mx, n = float(m.group(1)), float(m.group(2)), float(m.group(3)), int(m.group(4))
    assert p95 >= p50 >= 0.0
    assert mx >= p95
    assert n == 200

    assert "tick period=4.0ms overrun_max=6.0ms overruns=3" in line, line
    assert "press->emit=" in line and "crossing->emit=3.9ms (n=2)" in line, line
    assert "uinput_write_max=0.4ms" in line, line


def test_build_line_uinput_segment_only_when_positive(vs):
    vs._lat_reset_windows()
    vs._lat["input"] = [0.001]             # activity without any uinput writes
    assert "uinput_write_max" not in (vs._lat_build_line() or "")


# ---------------- _lat_input_sample ----------------

def test_input_sample_zero_ts_skipped_and_offset_unset(vs):
    vs._lat_reset_windows()
    saved_off, saved_ok = vs._lat["ts_offset"], vs._lat["input_ok"]
    try:
        now = time.monotonic()
        vs._lat_input_sample(_Ev(0, 0), now)
        assert len(vs._lat["input"]) == 0
        assert vs._lat["ts_offset"] is None      # no valid event yet -> offset never set
    finally:
        vs._lat["ts_offset"], vs._lat["input_ok"] = saved_off, saved_ok


def test_input_sample_valid_event_appends_sane_delta(vs):
    vs._lat_reset_windows()
    now = time.monotonic()
    t = time.time()                             # kernel timestamps are wall-clock domain
    vs._lat_input_sample(_Ev(int(t), int((t % 1) * 1e6)), now)
    assert len(vs._lat["input"]) == 1
    assert 0.0 <= vs._lat["input"][0] < 5.0, vs._lat["input"]


def test_input_sample_stale_offset_recalibrates_once(vs):
    """A drift beyond the threshold (e.g. an NTP step) recalibrates ts_offset and the sample lands."""
    vs._lat_reset_windows()
    saved_off, saved_ok = vs._lat["ts_offset"], vs._lat["input_ok"]
    try:
        now = time.monotonic()
        t = time.time()
        vs._lat_input_sample(_Ev(int(t), int((t % 1) * 1e6)), now)   # calibrate offset correctly
        good_off = vs._lat["ts_offset"]
        assert good_off is not None

        vs._lat["ts_offset"] = good_off + 7200.0                     # simulate a stale (2 h off) calibration
        vs._lat_input_sample(_Ev(int(t), int((t % 1) * 1e6)), now)   # same wall-clock event, fresh monotonic read
        assert len(vs._lat["input"]) == 2                            # recalibrated once -> sample accepted
        assert abs(vs._lat["ts_offset"] - good_off) < 5.0            # offset re-anchored to the current clock
    finally:
        vs._lat["ts_offset"], vs._lat["input_ok"] = saved_off, saved_ok


def test_input_sample_unusable_timestamps_disable_metric_with_one_warning(vs, capsys):
    """Timestamps that are wrong even after recalibration (>1 h off) disable the input metric for good."""
    vs._lat_reset_windows()
    saved_off, saved_ok = vs._lat["ts_offset"], vs._lat["input_ok"]
    try:
        now = time.monotonic()
        t = time.time()
        vs._lat_input_sample(_Ev(int(t), int((t % 1) * 1e6)), now)   # calibrate

        bad_ts = t - 7200.0                                          # two hours stale: wrong before AND after recalibration
        vs._lat_input_sample(_Ev(int(bad_ts), int((bad_ts % 1) * 1e6)), time.monotonic())
        assert vs._lat["input_ok"] is False
        out = capsys.readouterr().out
        assert "latency input metric disabled: kernel event timestamps do not match the wall-clock domain" in out
        assert len(vs._lat["input"]) == 1                            # the bad sample was dropped

        vs._lat_input_sample(_Ev(int(t), int((t % 1) * 1e6)), time.monotonic())   # once disabled, nothing is sampled again
        assert len(vs._lat["input"]) == 1
    finally:
        vs._lat["ts_offset"], vs._lat["input_ok"] = saved_off, saved_ok
