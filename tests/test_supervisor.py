"""Integration tier: supervisor() — periodic scan, run-thread start/release/reap, and failed-scan safety.

Only the supervisor thread runs (no ticker); evdev.list_devices is driven from a mutable dict so each test
scripts which devices exist per iteration. time.sleep is capped at 50ms where fast iterations matter;
stop_daemon_threads() unwinds the infinite loop cleanly via LoopStop."""
import threading
import time

import evdev
import pytest

from fakes import _REAL_SLEEP, install_fakes, stop_daemon_threads, wait_until


@pytest.fixture
def sup(vs, monkeypatch):
    """Fake bus + controllable list_devices; start() launches one supervisor thread. Teardown kills it."""
    v = vs
    bus = install_fakes(monkeypatch, v)
    state = {"matches": []}
    monkeypatch.setattr(evdev, "list_devices", lambda: list(state["matches"]))

    threads = []

    def start():
        t = threading.Thread(target=v.supervisor, daemon=True)
        t.start()
        threads.append(t)
        return t

    yield {"start": start, "bus": bus, "state": state}
    assert not stop_daemon_threads(threads), "supervisor thread failed to unwind"


def _fast_iters(monkeypatch):
    # supervisor's 2s iteration sleep -> 50ms; wait_until's 10ms poll is unaffected (min() only shrinks)
    monkeypatch.setattr(time, "sleep", lambda d: _REAL_SLEEP(min(d, 0.05)))


def test_failed_scan_is_logged_and_changes_nothing(vs, sup, monkeypatch, capsys):
    v = vs
    _fast_iters(monkeypatch)

    sup["state"]["matches"] = ["/dev/input/fakeA"]
    sup["start"]()
    wait_until(lambda: "/dev/input/fakeA" in v.active and v.active["/dev/input/fakeA"].is_alive())
    run_dev = sup["bus"].created[1]              # created[0] was find_matches' probe (opened+closed); [1] is what run() holds

    def boom():
        raise RuntimeError("boom")

    monkeypatch.setattr(evdev, "list_devices", boom)   # scan now fails every iteration...
    wait_until(lambda: "scan failed: boom" in capsys.readouterr().out)  # ...and the failure is reported (always-print tier)

    time.sleep(0.15)                                  # several more failed iterations pass by
    assert v.active.get("/dev/input/fakeA") is not None and v.active["/dev/input/fakeA"].is_alive()
    assert run_dev.close_count == 0                   # a failed scan must never release or restart threads


def test_device_started_then_released_when_deselected(vs, sup, monkeypatch, capsys):
    v = vs
    _fast_iters(monkeypatch)

    sup["state"]["matches"] = ["/dev/input/fakeA"]
    sup["start"]()
    wait_until(lambda: "/dev/input/fakeA" in v.active and v.active["/dev/input/fakeA"].is_alive())
    t = v.active["/dev/input/fakeA"]
    assert "grabbed /dev/input/fakeA Fallback Sim Mouse" in capsys.readouterr().out   # run() really started for it

    sup["state"]["matches"] = []                      # config no longer selects this mouse -> release it next iteration
    wait_until(lambda: "/dev/input/fakeA" not in v.active, timeout=5.0)  # close -> read_loop ends -> thread exits -> reaped from active
    assert not t.is_alive()


def test_dead_thread_is_restarted_while_still_selected(vs, sup, monkeypatch):
    v = vs
    _fast_iters(monkeypatch)

    sup["state"]["matches"] = ["/dev/input/fakeA"]
    sup["start"]()
    wait_until(lambda: "/dev/input/fakeA" in v.active and v.active["/dev/input/fakeA"].is_alive())
    t = v.active["/dev/input/fakeA"]

    sup["bus"].created[1].close()                     # simulate the device node vanishing mid-session
    wait_until(lambda: v.active.get("/dev/input/fakeA") is not None
               and v.active["/dev/input/fakeA"] is not t
               and v.active["/dev/input/fakeA"].is_alive())   # reaped, then a fresh run() thread started for the same path


def test_empty_first_scan_reports_waiting(vs, sup, capsys):
    sup["state"]["matches"] = []                      # no matching device at all (default NAME_MATCH="Fallback" matches nothing real here)
    sup["start"]()

    seen = []

    def found():                                      # first iteration runs immediately — no sleep cap needed
        out = capsys.readouterr().out
        if "no matching device yet — waiting" in out:
            seen.append(True)
        return bool(seen)

    wait_until(found, timeout=3.0)
