"""Shared fixtures for the VeloScroll test suite.

VELOSCROLL_CONFIG must point at a *nonexistent* path before veloscroll is first
imported: `import veloscroll` runs load_config()/check_config()/apply_values() and
calls sys.exit(1) on a broken config (veloscroll.py startup block). A missing file
yields pure code defaults, which every tier expects as the baseline state.

All fixtures restore every daemon global afterwards — the module is deliberately
global-heavy (26 config keys + derived counts + held-state), and tests must never
leak state into each other.
"""
import contextlib
import importlib
import io
import itertools
import os
import sys
import tempfile
import threading

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
HELPERS_DIR = os.path.join(REPO_ROOT, "helpers")   # veloscroll_seed / veloscroll_tuning_helper / ListDeviceNames / ListButtonPresses live here
for _p in (REPO_ROOT, TESTS_DIR, HELPERS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from fakes import Sim, install_fakes, stop_daemon_threads, wait_until  # noqa: E402

# unique per process so parallel test runs never share (or clobber) a config path
_DEFAULT_CONFIG_ENV = os.path.join(tempfile.gettempdir(), f"veloscroll-pytest-{os.getpid()}.ini")
assert not os.path.exists(_DEFAULT_CONFIG_ENV), "expected the default test config path to be absent"
os.environ.setdefault("VELOSCROLL_CONFIG", _DEFAULT_CONFIG_ENV)


# runtime globals that must be restored after every test (see veloscroll.py module state)
_STATE_KEYS = (
    "DEADZONE", "FULL", "DEADZONE_H", "FULL_H",
    "held", "held_v", "held_h", "mode", "offset", "h_offset", "acc_notch", "ticker_reset",
    "_cfg_stat", "_cfg_load_info",
)


@pytest.fixture(scope="session")
def veloscroll_module():
    """Import veloscroll once for the whole session (the env guard above makes this safe)."""
    return importlib.import_module("veloscroll")


@pytest.fixture
def vs(veloscroll_module):
    """The live veloscroll module, with every daemon global snapshotted and restored around the test."""
    v = veloscroll_module
    keys = tuple(v.DAEMON_KEYS) + _STATE_KEYS
    snapshot = {k: getattr(v, k) for k in keys}
    dict_snapshots = {n: dict(getattr(v, n)) for n in ("active", "devices", "last_fail_log")}
    yield v
    for key, val in snapshot.items():
        setattr(v, key, val)
    for name, saved in dict_snapshots.items():
        cur = getattr(v, name)
        cur.clear()
        cur.update(saved)
    v._lat_reset_windows()
    v._lat_reset_hold()


@pytest.fixture
def reload_vs(tmp_path, monkeypatch):
    """Factory: `with reload_vs(ini_text) as (v, startup_out):` — re-executes veloscroll.py
    against a scenario ini so the module comes up in exactly that config's state. Yields the
    fresh module plus captured startup-apply stdout; restores the default (nonexistent-config)
    state on exit even if the test body fails."""
    import veloscroll as v0

    counter = itertools.count(1)

    def make(ini_text=None, name="config.ini"):
        @contextlib.contextmanager
        def _cm():
            path = tmp_path / f"{name}.{next(counter)}"
            if ini_text is not None:
                path.write_text(ini_text, encoding="utf-8")
            monkeypatch.setenv("VELOSCROLL_CONFIG", str(path))
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                importlib.reload(v0)
            try:
                yield v0, buf.getvalue()
            finally:
                monkeypatch.setenv("VELOSCROLL_CONFIG", _DEFAULT_CONFIG_ENV)
                with contextlib.redirect_stdout(io.StringIO()):
                    importlib.reload(v0)

        return _cm()   # instantiate: contextlib.contextmanager rebinds the name to a class; callers use it directly in `with`

    return make


@pytest.fixture
def sim(tmp_path, reload_vs, monkeypatch):
    """Factory for the full in-process daemon harness (integration tier).

    `with sim.make(ini_text) as s:` gives a fresh module started from the scenario ini,
    fake device + UInput recorder installed, and ticker()/run("sim://mouse") running as
    daemon threads. On exit: run() is stopped cleanly via the fake device's close(),
    the infinite-loop threads are killed (stop_daemon_threads), and the module state is
    restored by reload_vs."""

    counter = itertools.count(1)

    def make(ini_text=None):
        reload_cm = reload_vs(ini_text, name=f"sim.{next(counter)}")

        @contextlib.contextmanager
        def _cm():
            with reload_cm as (v, startup_out):
                bus = install_fakes(monkeypatch, v)
                threads = [
                    threading.Thread(target=v.ticker, daemon=True),
                    threading.Thread(target=v.run, args=("sim://mouse",), daemon=True),
                ]
                for t in threads:
                    t.start()
                try:
                    wait_until(lambda: bus.holder.get("ui") is not None)   # run() grabbed + created the virtual mouse
                    assert len(bus.created) == 1, f"expected exactly one device open, got {[d.path for d in bus.created]}"
                    yield Sim(v, bus.created[0], bus.holder, startup_out)
                finally:
                    for dev in bus.created:
                        dev.close()    # every read_loop ends -> run thread exits cleanly
                    leftover = stop_daemon_threads(threads)
                    if leftover:
                        pytest.fail(f"daemon threads still alive after teardown: {leftover}")

        return _cm()   # instantiate: contextlib.contextmanager rebinds the name to a class; callers use it directly in `with`

    return make


@pytest.fixture(scope="session")
def vsd_module():
    """Import veloscroll_seed once (safe at import time: no evdev/veloscroll access outside main())."""
    return importlib.import_module("veloscroll_seed")


@pytest.fixture
def backend(vsd_module, monkeypatch):
    """A fresh KdePlasmaBackend with the D-Bus session bus env removed so _live_apply takes its skip path."""
    monkeypatch.delenv("DBUS_SESSION_BUS_ADDRESS", raising=False)
    return vsd_module.KdePlasmaBackend()
