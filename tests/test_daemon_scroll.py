"""Integration tier: full daemon loops (run() + ticker) against a fake device and UInput recorder, hold-mode scrolling.

Behavior pinned here is the *actual* product behavior: while any scroll button is held, ALL REL_X/REL_Y
events are swallowed by run() regardless of active axis (veloscroll.py — the cursor stays put in both v- and h-mode),
and wheel events while held are dropped too — except while BTN_LEFT is also down (drag-select): then movement and
physical wheel pass through to move the virtual cursor, velocity output pauses, and a left release resumes the
session from a fresh origin."""
import time

from evdev import ecodes as e

from fakes import push, wait_until


def _state(v):
    with v.lock:
        return {
            "held": v.held, "held_v": v.held_v, "held_h": v.held_h, "mode": v.mode,
            "offset": v.offset, "h_offset": v.h_offset, "acc_notch": v.acc_notch,
            "ticker_reset": v.ticker_reset,
        }


def _released(s):
    wait_until(lambda: not _state(s.vs)["held"])
    time.sleep(0.15)      # a few ticker ticks: once not held the emitter is provably silent (rate/acc zeroed each tick)


def _wheel_totals(writes, hi_code, coarse_code):
    # write() records 3-tuples (EV_REL emits); write_event() passthroughs are 4-tuples — skip those
    rel = [w for w in writes if len(w) == 3 and w[0] == e.EV_REL]
    hi = sum(val for t, c, val in rel if c == hi_code)
    coarse = sum(val for t, c, val in rel if c == coarse_code)
    return hi, coarse


def _press(s, code):
    push(s.dev, e.EV_KEY, code, 1)
    wait_until(lambda: _state(s.vs)["held"])


def _release(s, code):
    push(s.dev, e.EV_KEY, code, 0)
    _released(s)


# ---------------- vertical hold-mode scrolling (defaults: DEADZONE=32 counts, FULL=4000 @ DPI 1600) ----------------

def test_down_motion_emits_negative_wheel_with_exact_notch_math(sim):
    with sim() as s:
        _press(s, e.BTN_SIDE)
        push(s.dev, e.EV_REL, e.REL_Y, 4000)         # full-scale down-movement (clamps to FULL=4000 -> max rate ~130 notches/s)
        time.sleep(0.35)                   # steady-state emitting at the ramped rate
        _release(s, e.BTN_SIDE)

        writes = list(s.ui.writes)         # read module state before teardown reloads it
        hi_total, coarse_total = _wheel_totals(writes, e.REL_WHEEL_HI_RES, e.REL_WHEEL)
        assert hi_total < 0                    # mouse down -> scroll down (negative), v-mode convention
        assert abs(hi_total) >= 120            # enough motion for at least one coarse notch...

        with s.vs.lock:
            acc = s.vs.acc_notch
        # emit_scroll() invariant, exact: every hi-res count either became a whole 120-count notch or remains in acc_notch
        assert coarse_total * 120 + acc == hi_total
        assert abs(acc) < 120


def test_motion_inside_deadzone_emits_nothing(sim):
    with sim() as s:
        _press(s, e.BTN_SIDE)
        push(s.dev, e.EV_REL, e.REL_Y, 16)           # total 24 counts — inside the 32-count deadzone
        push(s.dev, e.EV_REL, e.REL_Y, 8)
        time.sleep(0.25)                   # several ticks at target rate 0
        _release(s, e.BTN_SIDE)

    assert s.ui.writes == []               # every pushed event was swallowed; nothing ever emitted


def test_offset_clamps_to_full(sim):
    with sim() as s:
        _press(s, e.BTN_SIDE)
        push(s.dev, e.EV_REL, e.REL_Y, 9999)         # far beyond FULL=4000 counts in a single event
        time.sleep(0.2)
        _release(s, e.BTN_SIDE)

        with s.vs.lock:
            assert s.vs.offset == s.vs.FULL    # clamped on accumulation; the clamp value persists after release


def test_invert_flips_direction(sim):
    ini = "[veloscroll]\nINVERT = true\n"
    with sim(ini) as s:
        _press(s, e.BTN_SIDE)
        push(s.dev, e.EV_REL, e.REL_Y, 480)          # same down-movement...
        time.sleep(0.35)
        _release(s, e.BTN_SIDE)

    hi_total, _coarse = _wheel_totals(list(s.ui.writes), e.REL_WHEEL_HI_RES, e.REL_WHEEL)
    assert hi_total > 0                    # ...now scrolls up (positive)


def test_up_motion_emits_positive_wheel(sim):
    with sim() as s:
        _press(s, e.BTN_SIDE)
        push(s.dev, e.EV_REL, e.REL_Y, -480)         # hand above the start point
        time.sleep(0.35)
        _release(s, e.BTN_SIDE)

    hi_total, _coarse = _wheel_totals(list(s.ui.writes), e.REL_WHEEL_HI_RES, e.REL_WHEEL)
    assert hi_total > 0


# ---------------- horizontal axis ----------------

H_INI = "[veloscroll]\nSCROLL_BTN_H = BTN_EXTRA\n"


def test_h_mode_rel_x_emits_positive_hwheel(sim):
    with sim(H_INI) as s:
        _press(s, e.BTN_EXTRA)             # SCROLL_BTN_H press -> mode "h"
        push(s.dev, e.EV_REL, e.REL_X, 480)          # right-movement while held in h-mode (REL_X is the active axis)
        time.sleep(0.35)
        _release(s, e.BTN_EXTRA)

        st = _state(s.vs)                  # read module state before teardown reloads it
        assert st["mode"] == "h" and not st["held_v"]      # state persists after release until the next press
        hi_total, coarse_total = _wheel_totals(list(s.ui.writes), e.REL_HWHEEL_HI_RES, e.REL_HWHEEL)
        assert hi_total > 0                    # hand right -> positive REL_HWHEEL (D4 convention)
        with s.vs.lock:
            acc = s.vs.acc_notch
        assert coarse_total * 120 + acc == hi_total and abs(acc) < 120


def test_vertical_h_mode_accumulates_rel_y_and_emits_vertical_wheel(sim):
    ini = "[veloscroll]\nSCROLL_BTN_H = BTN_EXTRA\nVERTICAL_H = true\n"
    with sim(ini) as s:
        _press(s, e.BTN_EXTRA)
        push(s.dev, e.EV_REL, e.REL_Y, 480)          # VERTICAL_H: h-mode measures up/down movement...
        time.sleep(0.35)
        _release(s, e.BTN_EXTRA)

        st = _state(s.vs)                  # read module state before teardown reloads it
        assert st["mode"] == "h" and st["h_offset"] == 480     # REL_Y accumulated into h_offset (clamped range intact)
        writes = list(s.ui.writes)
        hi_total, coarse_total = _wheel_totals(writes, e.REL_WHEEL_HI_RES, e.REL_WHEEL)
        assert hi_total < 0                    # ...and output follows the vertical convention (down-movement scrolls down)...
        assert not any(len(w) == 3 and w[0] == e.EV_REL and w[1] in (e.REL_HWHEEL, e.REL_HWHEEL_HI_RES) for w in writes)   # ...on vertical wheel codes


# ---------------- event handling rules ----------------

def test_free_events_pass_through_held_rels_and_wheel_are_swallowed(sim):
    with sim() as s:
        push(s.dev, e.EV_KEY, e.BTN_LEFT, 1)       # not held -> passes through to the virtual mouse...
        time.sleep(0.05)
        push(s.dev, e.EV_KEY, e.BTN_LEFT, 0)       # ...and release it: a left still down would arm drag mode for the session below
        time.sleep(0.05)
        _press(s, e.BTN_SIDE)
        push(s.dev, e.EV_REL, e.REL_X, 5)                    # held v-mode: REL_X swallowed (cursor frozen)...
        push(s.dev, e.EV_REL, e.REL_WHEEL_HI_RES, 3)         # ...and wheel while held is dropped entirely
        time.sleep(0.1)
        _release(s, e.BTN_SIDE)

        # released: every event type passes through again — all four wheel codes included
        push(s.dev, e.EV_REL, e.REL_WHEEL, 1)
        push(s.dev, e.EV_REL, e.REL_WHEEL_HI_RES, -2)
        push(s.dev, e.EV_REL, e.REL_HWHEEL, 3)
        push(s.dev, e.EV_REL, e.REL_HWHEEL_HI_RES, -4)
        time.sleep(0.1)

    assert s.ui.writes == [
        ("ev", e.EV_KEY, e.BTN_LEFT, 1),
        ("ev", e.EV_KEY, e.BTN_LEFT, 0),
        ("ev", e.EV_REL, e.REL_WHEEL, 1),
        ("ev", e.EV_REL, e.REL_WHEEL_HI_RES, -2),
        ("ev", e.EV_REL, e.REL_HWHEEL, 3),
        ("ev", e.EV_REL, e.REL_HWHEEL_HI_RES, -4),
    ]


def test_disabled_button_never_reaches_the_os(sim):
    ini = "[veloscroll]\nDISABLED_BTN = BTN_TASK\n"
    with sim(ini) as s:
        push(s.dev, e.EV_KEY, e.BTN_TASK, 1)       # disabled button swallowed when free...
        time.sleep(0.05)
        _press(s, e.BTN_SIDE)                      # ...and while held (it is not a scroll button here)
        push(s.dev, e.EV_KEY, e.BTN_TASK, 2)       # key repeat: still swallowed
        time.sleep(0.05)
        _release(s, e.BTN_SIDE)
        push(s.dev, e.EV_KEY, e.BTN_LEFT, 1)       # ...while other buttons pass through untouched

    assert s.ui.writes == [("ev", e.EV_KEY, e.BTN_LEFT, 1)]


def test_release_stops_emitting_permanently(sim):
    with sim() as s:
        _press(s, e.BTN_SIDE)
        push(s.dev, e.EV_REL, e.REL_Y, 480)
        time.sleep(0.3)
        _release(s, e.BTN_SIDE)

        n = len(list(s.ui.writes))
        time.sleep(0.2)                            # ~50 more ticks with nothing held: no new writes may appear
        assert len(list(s.ui.writes)) == n


def test_startup_output_reports_config_overrides(sim):
    ini = "[veloscroll]\nCURVE = 0.6\nINVERT = true\n"
    with sim(ini) as s:
        assert "config loaded from" in s.startup_out and "(2 override(s))" in s.startup_out


def test_grab_line_and_virtual_device_identity(sim, capsys):
    with sim() as s:
        ui = s.ui
        assert ui is not None                      # run() created the virtual mouse before yielding
        assert ui.name == "veloscroll-mouse"       # VIRTUAL_NAME advertised...

    out = capsys.readouterr().out                  # ...while run()'s thread prints its grab line (LOG_LEVEL 2 >= 1)
    assert "grabbed sim://mouse Fallback Sim Mouse" in out
    assert "virtual mouse now advertises 0x1234:0x5678" in out   # the fake device's USB IDs cloned onto the virtual mouse


# ---------------- left-button drag-select (BTN_LEFT held during a session) ----------------

def test_drag_forwards_motion_and_pauses_velocity(sim):
    with sim() as s:
        _press(s, e.BTN_SIDE)
        push(s.dev, e.EV_REL, e.REL_Y, 9999)         # clamps to FULL=4000 -> steady max-rate emission
        time.sleep(0.35)

        push(s.dev, e.EV_KEY, e.BTN_LEFT, 1)         # left down mid-session: velocity output pauses...
        time.sleep(0.1)                              # ...residual rate decays away (~5 ticks at default TICK/OUT_SMOOTH)
        n = len(list(s.ui.writes))

        push(s.dev, e.EV_REL, e.REL_X, 7)            # cursor follows the hand: REL events pass through...
        push(s.dev, e.EV_REL, e.REL_Y, -9)           # ...in both axes (not accumulated into offset)...
        push(s.dev, e.EV_REL, e.REL_WHEEL_HI_RES, 2) # ...and physical wheel passes through too
        time.sleep(0.3)                              # ~75 more ticks: velocity output stays paused

        _release(s, e.BTN_SIDE)                      # session ends (the scroll-button release edge is consumed, as always); frozen accumulators persist for inspection
        with s.vs.lock:
            assert s.vs.offset == s.vs.FULL          # REL movement during drag never accumulated (frozen at the clamp value)

    writes = list(s.ui.writes)
    assert writes[n:] == [                           # after the pause settles, only the drag passthroughs appear...
        ("ev", e.EV_REL, e.REL_X, 7),
        ("ev", e.EV_REL, e.REL_Y, -9),
        ("ev", e.EV_REL, e.REL_WHEEL_HI_RES, 2),     # ...no new wheel emissions (3-tuples) while left is down
    ]


def test_left_release_resumes_from_fresh_origin(sim):
    with sim() as s:
        _press(s, e.BTN_SIDE)
        push(s.dev, e.EV_REL, e.REL_Y, 9999)         # clamps to FULL=4000 -> steady max-rate emission...
        time.sleep(0.35)

        push(s.dev, e.EV_KEY, e.BTN_LEFT, 1)         # drag: cursor moves (passthrough), offset frozen at FULL...
        push(s.dev, e.EV_REL, e.REL_Y, -24)          # ...velocity output paused
        time.sleep(0.1)

        push(s.dev, e.EV_KEY, e.BTN_LEFT, 0)         # left release -> fresh origin (offset = h_offset = 0)...
        time.sleep(0.05)                             # ...release passthrough lands; the rate is already zeroed by then
        n = len(list(s.ui.writes))

        push(s.dev, e.EV_REL, e.REL_Y, 16)           # normal hold mode again: swallowed for velocity math...
        push(s.dev, e.EV_REL, e.REL_Y, 8)            # ...total 24 counts < 32-count deadzone -> stays silent; without the reset, offset would sit at FULL and emit at max rate
        time.sleep(0.35)

    assert s.ui.writes[n:] == []                     # nothing new after the release: no passthroughs (swallowed again), no wheel emissions


def test_left_down_before_side_press_arms_drag_mode(sim):
    with sim() as s:
        push(s.dev, e.EV_KEY, e.BTN_LEFT, 1)         # free left press passes through (no session yet)...
        time.sleep(0.05)

        _press(s, e.BTN_SIDE)                        # session starts already in drag mode...
        push(s.dev, e.EV_REL, e.REL_X, 12)           # ...movement is forwarded to the virtual cursor...
        push(s.dev, e.EV_REL, e.REL_Y, -6)           # ...in both axes (never accumulated)...
        time.sleep(0.35)                             # ...and no velocity output ever happens

    assert s.ui.writes == [                          # every write is a passthrough — zero wheel emissions
        ("ev", e.EV_KEY, e.BTN_LEFT, 1),
        ("ev", e.EV_REL, e.REL_X, 12),
        ("ev", e.EV_REL, e.REL_Y, -6),
    ]
