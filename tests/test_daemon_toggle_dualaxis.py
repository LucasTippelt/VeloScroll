"""Integration tier: toggle (latched) scroll mode, per-axis TOGGLE_SCROLL_H fallback/override, LIFO dual-button state machine.

Semantics pinned from veloscroll.py run():
- every press edge (hold or toggle engage) resets offset=h_offset=0, acc_notch=0, ticker_reset=True;
- in toggle mode release edges and key repeats are consumed as no-ops while latched;
- releasing a held button while the other axis is still engaged reactivates that axis fresh (D3);
- TICK is widened to 20ms where a test must observe ticker_reset before the ticker thread consumes it."""
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


def _settled_idle(s):
    wait_until(lambda: not _state(s.vs)["held"])
    time.sleep(0.15)


TOGGLE_INI = "[veloscroll]\nSCROLL_BTN_H = BTN_EXTRA\nTOGGLE_SCROLL = true\n"
SLOW_TICK_TOGGLE_INI = TOGGLE_INI + "TICK = 0.02\n"
HOLD_DUAL_INI = "[veloscroll]\nSCROLL_BTN_H = BTN_EXTRA\nTICK = 0.02\n"


def test_toggle_latch_release_edge_and_repeat_are_noop(sim):
    with sim(TOGGLE_INI) as s:
        push(s.dev, e.EV_KEY, e.BTN_SIDE, 1)                 # tap -> engage (latched)
        wait_until(lambda: _state(s.vs)["held_v"])

        push(s.dev, e.EV_KEY, e.BTN_SIDE, 0)                 # release edge while latched: no-op...
        time.sleep(0.12)                                     # ...several ticks later it must still be engaged
        st = _state(s.vs)
        assert st["held_v"] and st["held"]

        push(s.dev, e.EV_KEY, e.BTN_SIDE, 2)                 # key repeat while latched: no-op
        time.sleep(0.05)
        assert _state(s.vs)["held_v"]

        push(s.dev, e.EV_KEY, e.BTN_SIDE, 1)                 # tap again -> disengage
        _settled_idle(s)

    assert s.ui.writes == []                                 # no motion was ever pushed: nothing may have been emitted or passed through


def test_toggle_h_falls_back_to_vertical_toggle_value(sim):
    with sim(TOGGLE_INI) as s:                          # TOGGLE_SCROLL_H unset -> h-axis uses the vertical toggle value
        push(s.dev, e.EV_KEY, e.BTN_EXTRA, 1)                # tap -> engage h-axis latched
        wait_until(lambda: _state(s.vs)["held_h"])
        st = _state(s.vs)
        assert st["mode"] == "h" and not st["held_v"]

        push(s.dev, e.EV_KEY, e.BTN_EXTRA, 0)                # release edge ignored while latched
        time.sleep(0.12)
        assert _state(s.vs)["held_h"]

        push(s.dev, e.EV_KEY, e.BTN_EXTRA, 1)                # tap again -> disengage
        _settled_idle(s)

    assert s.ui.writes == []


def test_toggle_h_explicit_override_leaves_v_axis_in_hold_mode(sim):
    ini = "[veloscroll]\nSCROLL_BTN_H = BTN_EXTRA\nTOGGLE_SCROLL = false\nTOGGLE_SCROLL_H = true\n"
    with sim(ini) as s:
        # v-axis: plain hold mode — release ends the session
        push(s.dev, e.EV_KEY, e.BTN_SIDE, 1)
        wait_until(lambda: _state(s.vs)["held_v"])
        push(s.dev, e.EV_REL, e.REL_Y, 480)                            # motion while held in v-mode -> emits happen
        time.sleep(0.25)
        push(s.dev, e.EV_KEY, e.BTN_SIDE, 0)                 # release -> session over (hold mode honors release edges)
        _settled_idle(s)

        # h-axis: toggle mode — latches across a release edge
        push(s.dev, e.EV_KEY, e.BTN_EXTRA, 1)
        wait_until(lambda: _state(s.vs)["held_h"])
        assert _state(s.vs)["mode"] == "h"
        push(s.dev, e.EV_KEY, e.BTN_EXTRA, 0)                # release edge ignored while latched
        time.sleep(0.12)
        assert _state(s.vs)["held_h"]
        push(s.dev, e.EV_KEY, e.BTN_EXTRA, 1)                # tap again -> disengage
        _settled_idle(s)

    rel_writes = [w for w in s.ui.writes if len(w) == 3]     # v-mode emits happened...
    assert any(t == e.EV_REL and c == e.REL_WHEEL_HI_RES for t, c, _v in rel_writes)   # ...on vertical wheel codes
    assert not any(t == e.EV_REL and c in (e.REL_HWHEEL, e.REL_HWHEEL_HI_RES) for t, c, _v in rel_writes)  # nothing horizontal was ever emitted


def test_d3_releasing_h_while_v_still_held_reactivates_v_fresh(sim):
    with sim(HOLD_DUAL_INI) as s:                       # both axes hold-mode; TICK=20ms widens the observation window
        push(s.dev, e.EV_KEY, e.BTN_SIDE, 1)                 # v active (LIFO bottom of stack)
        wait_until(lambda: _state(s.vs)["held_v"])
        push(s.dev, e.EV_REL, e.REL_Y, 100)                            # v accumulates and emits...
        time.sleep(0.08)

        push(s.dev, e.EV_KEY, e.BTN_EXTRA, 1)                # h active on top; press zeroes both accumulators (fresh session)
        wait_until(lambda: _state(s.vs)["mode"] == "h")
        push(s.dev, e.EV_REL, e.REL_X, 50)                             # h emits its own notches -> acc_notch becomes non-trivial
        time.sleep(0.08)

        def d3_reactivated():                                # D3 reactivates the v-axis fresh before the ticker consumes ticker_reset (20ms window)
            st = _state(s.vs)
            return (st["mode"] == "v" and not st["held_h"] and st["held_v"]
                    and st["offset"] == 0 and st["h_offset"] == 0
                    and st["acc_notch"] == 0 and st["ticker_reset"] is True)

        push(s.dev, e.EV_KEY, e.BTN_EXTRA, 0)                # release h while v is still held down...
        wait_until(d3_reactivated)                           # ...v comes back with fresh accumulators

        push(s.dev, e.EV_KEY, e.BTN_SIDE, 0)                 # release v -> fully idle
        _settled_idle(s)


def test_d5_toggle_engage_resets_accumulators(sim):
    with sim(SLOW_TICK_TOGGLE_INI) as s:
        push(s.dev, e.EV_KEY, e.BTN_SIDE, 1)                 # engage v with zero motion (deterministic: nothing else can dirty the state)
        wait_until(lambda: _state(s.vs)["held_v"])
        st = _state(s.vs)
        assert st["offset"] == 0 and st["h_offset"] == 0 and st["acc_notch"] == 0

        push(s.dev, e.EV_REL, e.REL_Y, 480)                            # dirty the accumulators with real emitting...
        time.sleep(0.3)                                      # ...many ticks at TICK=20ms
        assert any(len(w) == 3 for w in s.ui.writes)         # sanity: emits actually happened

        push(s.dev, e.EV_KEY, e.BTN_SIDE, 1)                 # tap -> disengage (release edges are no-ops while latched)
        _settled_idle(s)

        push(s.dev, e.EV_KEY, e.BTN_SIDE, 1)                 # tap again -> re-engage: partial notches from the previous session must be gone
        wait_until(lambda: _state(s.vs)["held_v"])
        st = _state(s.vs)
        assert st["acc_notch"] == 0 and st["offset"] == 0    # D5: never carry partial notches across sessions


def test_axis_switch_rate_ramps_from_zero(sim):
    with sim("[veloscroll]\nSCROLL_BTN_H = BTN_EXTRA\n") as s:   # default TICK=4ms so the ramp is visible per-tick
        push(s.dev, e.EV_KEY, e.BTN_SIDE, 1)                 # v-axis to full scale -> steady state ~130 notches/s
        wait_until(lambda: _state(s.vs)["held_v"])
        push(s.dev, e.EV_REL, e.REL_Y, 4000)
        time.sleep(0.3)

        h_writes_before = sum(len(w) == 3 and w[1] == e.REL_HWHEEL_HI_RES for w in s.ui.writes)
        assert h_writes_before == 0                          # v-mode never emits horizontal codes

        push(s.dev, e.EV_KEY, e.BTN_EXTRA, 1)                # press h: D5 resets the smoothed rate to zero...
        wait_until(lambda: _state(s.vs)["mode"] == "h")
        push(s.dev, e.EV_REL, e.REL_X, 4000)                           # ...full-scale right-movement; output must ramp back up from nothing

        def h_emits():
            return [w[2] for w in s.ui.writes if len(w) == 3 and w[1] == e.REL_HWHEEL_HI_RES]

        wait_until(lambda: len(h_emits()) >= 6, timeout=1.0)
        emits = h_emits()

        # first emit after the reset is one smoothing step away from zero: |rate| <= MAX_RATE*OUT_SMOOTH -> hi <= int(130*0.8*120*TICK)+1
        assert abs(emits[0]) <= 50
        # a few ticks later the ramp reaches steady state (~62/tick at full scale)
        assert max(abs(v) for v in emits[1:]) >= 55
