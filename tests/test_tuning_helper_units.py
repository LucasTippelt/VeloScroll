"""Unit tier: veloscroll_tuning_helper measurement logic (_target_rate, milestones, gauge, release summary).

The helper's _on_move/_end_hold are pure functions of the vs module globals + per-hold state, so they can be
driven directly without any device. Note the display convention pinned here: raw REL_Y accumulates positive
when the hand moves BELOW the start point, so v-mode (and VERTICAL_H) negates it — milestone/gauge lines show
negative inches and negative counts for downward motion."""
import re

import pytest

import veloscroll_tuning_helper as th


@pytest.fixture(autouse=True)
def reset_helper_state(vs):
    th._hold = {"v": None, "h": None}
    th._at_line_start = True
    yield
    th._hold = {"v": None, "h": None}
    th._at_line_start = True


# ---------------- _num / display sign helpers ----------------

@pytest.mark.parametrize("x,want", [
    (1600.0, "1600"),          # whole-valued float renders without decimals
    (4000.0, "4000"),
    (32.5, "32.5"),
    (1000 / 3, "333.3333"),    # non-whole float: 4 decimal places
    (480, "480"),              # int passes through str()
    (-480, "-480"),            # display-signed distances are negative -> counts print signed too
])
def test_num(vs, x, want):
    assert th._num(x) == want


@pytest.mark.parametrize("axis,vh,off,want", [
    ("v", False, 480, -480),   # v-mode negates (below-start is negative)
    ("v", True, 480, -480),
    ("h", False, 480, 480),    # horizontal without VERTICAL_H: right-positive as-is
    ("h", True, 480, -480),    # VERTICAL_H measures up/down -> same sign convention as v-mode
])
def test_disp_off(vs, axis, vh, off, want):
    vs.VERTICAL_H = vh
    assert th._disp_off(vs, axis, off) == want


@pytest.mark.parametrize("axis,vh,d,want", [
    ("h", False, 5, " (rightwards)"), ("h", False, -5, " (leftwards)"), ("h", False, 0, ""),
    ("v", False, 5, " (upwards)"), ("v", False, -5, " (downwards)"), ("v", False, 0, ""),
    ("h", True, 5, " (upwards)"), ("h", True, -5, " (downwards)"),
])
def test_dir_label(vs, axis, vh, d, want):
    vs.VERTICAL_H = vh
    assert th._dir_label(vs, axis, d) == want


# ---------------- _target_rate (the daemon's exact ramp formula) ----------------

def test_target_rate_zero_inside_deadzone(vs):
    assert th._target_rate(vs, "v", 0) == 0.0
    assert th._target_rate(vs, "v", vs.DEADZONE) == 0.0     # dist <= dz is exactly at the boundary -> still zero


def test_target_rate_full_equals_max_rate_exactly(vs):
    assert th._target_rate(vs, "v", vs.FULL) == vs.MAX_RATE   # frac = 1 -> min_r * (max/min)**1 == max_r exactly
    assert th._target_rate(vs, "v", vs.FULL + 999) == vs.MAX_RATE   # clamped by min(1.0, ...)


def test_target_rate_monotonic_in_distance(vs):
    prev = -1.0
    for dist in (int(d) for d in range(int(vs.DEADZONE) + 1, int(vs.FULL) + 1, 97)):
        r = th._target_rate(vs, "v", dist)
        assert r >= prev
        prev = r


def test_target_rate_h_falls_back_to_vertical_when_unset(vs):
    for dist in (40, 500, 2000, int(vs.FULL)):
        assert th._target_rate(vs, "h", dist) == pytest.approx(th._target_rate(vs, "v", dist))


def test_target_rate_h_uses_explicit_h_values_and_derived_counts(vs):
    values = dict(vs._DEFAULTS)
    values.update(DEADZONE_IN_H=0.1, FULL_IN_H=2.5, MIN_RATE_H=10.0, MAX_RATE_H=50.0, CURVE_H=2.0)
    vs.apply_values(values)

    assert vs.DEADZONE_H == pytest.approx(0.1 * 1600)      # derived count = inches * DPI (fallback logic exercised by the daemon too)
    assert th._target_rate(vs, "h", vs.DEADZONE_H) == 0.0
    assert th._target_rate(vs, "h", int(vs.DEADZONE_H) + 1) > 0.0
    assert th._target_rate(vs, "h", vs.FULL_H) == pytest.approx(50.0)

    dist = int(vs.DEADZONE_H + (vs.FULL_H - vs.DEADZONE_H) / 2)   # frac_h = exactly 0.5
    r_h = th._target_rate(vs, "h", dist)
    assert r_h != pytest.approx(th._target_rate(vs, "v", dist))   # different rates/curve -> different ramp


# ---------------- milestone lines + gauge (v-mode, defaults: DEADZONE=32 counts, FULL=4000 @ DPI 1600) ----------------

def _ordered(out, *needles):
    """Assert each needle appears in `out`, strictly after the previous one."""
    idx = -1
    for n in needles:
        if isinstance(n, re.Pattern):
            m = n.search(out, idx + 1)
            assert m, f"pattern {n.pattern!r} not found after position {idx} in:\n{out!r}"
            idx = m.end() - 1
        else:
            pos = out.find(n, idx + 1)
            assert pos != -1, f"needle {n!r} not found after position {idx} in:\n{out!r}"
            idx = pos


def test_v_mode_milestones_gauge_and_release(vs, capsys):
    th._begin_hold("v")
    for off in (480, 16, 4000, 3200):      # down, back inside the deadzone, clamp at full, pull back below it
        th._on_move(vs, "v", off)
    th._end_hold(vs, "v")
    out = capsys.readouterr().out

    _ordered(
        out,
        "[v] deadzone passed at -0.30 in (-480 counts)",
        re.compile(r"\[v\] -0\.30 in from start \(-480 counts\) \| target \d+ notches/s \(downwards\)"),
        "\n[v] deadzone re-entered at -0.01 in (-16 counts)",      # _line prefixes a newline to replace the gauge
        re.compile(r"\[v\] -0\.01 in from start \(-16 counts\) \| target 0 notches/s \(downwards\)"),
        "[v] deadzone passed at -2.50 in (-4000 counts)",          # leaving the deadzone again before hitting full...
        "[v] max-rate reached at -2.50 in (-4000 counts) — further movement clamps here",
        re.compile(r"\[v\] -2\.50 in from start \(-4000 counts\) \| target 130 notches/s \(downwards\)"),   # rate(FULL) == MAX_RATE exactly
        "[v] max-rate exited at -2.00 in (-3200 counts) — clamping lifted",
        re.compile(r"\[v\] released after \d+\.\d s — peak -2\.5 in \(-4000 counts\), deadzone crossed, max-rate reached"),
    )


def test_h_mode_rightwards_without_vertical_h(vs, capsys):
    th._begin_hold("h")
    th._on_move(vs, "h", 480)              # right-positive REL_X: display sign stays positive
    out = capsys.readouterr().out
    _ordered(
        out,
        "[h] deadzone passed at 0.30 in (480 counts)",
        re.compile(r"\[h\] 0\.30 in from start \(480 counts\) \| target \d+ notches/s \(rightwards\)"),
    )


def test_h_mode_downwards_with_vertical_h(vs, capsys):
    vs.VERTICAL_H = True
    th._begin_hold("h")
    th._on_move(vs, "h", 480)              # REL_Y down-movement while held in H-mode: same convention as v-mode
    out = capsys.readouterr().out
    _ordered(
        out,
        "[h] deadzone passed at -0.30 in (-480 counts)",
        re.compile(r"\[h\] -0\.30 in from start \(-480 counts\) \| target \d+ notches/s \(downwards\)"),
    )


def test_release_summary_small_motion_no_crossings(vs, capsys):
    th._begin_hold("v")
    th._on_move(vs, "v", 10)               # stays inside the deadzone
    th._end_hold(vs, "v")
    out = capsys.readouterr().out
    _ordered(out, re.compile(r"\[v\] released after \d+\.\d s — peak -?0\.0 in \(-10 counts\), deadzone not crossed, max-rate not reached"))


def test_release_summary_no_motion(vs, capsys):
    th._begin_hold("v")
    th._end_hold(vs, "v")
    out = capsys.readouterr().out
    _ordered(out, re.compile(r"\[v\] released after \d+\.\d s — peak 0\.0 in \(0 counts\), deadzone not crossed, max-rate not reached"))


def test_end_hold_clears_state_and_makes_on_move_a_noop(vs, capsys):
    th._begin_hold("v")
    th._end_hold(vs, "v")
    assert th._hold["v"] is None
    before = capsys.readouterr().out
    th._on_move(vs, "v", 480)              # session reset externally -> nothing measured, nothing printed
    assert capsys.readouterr().out == "" and len(before.splitlines()) >= 1


# ---------------- _line / _gauge raw mechanics ----------------

def test_line_gauge_raw_mechanics(vs, capsys):
    th._at_line_start = True
    th._line("a")
    assert capsys.readouterr().out == "a\n"      # fresh line start: no leading newline

    th._gauge("g1")
    th._line("b")
    th._gauge("g2")
    out = capsys.readouterr().out
    assert out == "\rg1\nb\n\rg2"                # gauge is \r-in-place; _line replaces it with a newline first
