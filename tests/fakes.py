"""Fake evdev device + UInput recorder for in-process daemon tests.

The fake kernel timestamps use the wall-clock domain (`time.time()`) exactly like real
kernel event timestamps — do not "fix" them to monotonic: the daemon's latency sampler
maps its monotonic clock into that domain (veloscroll.py _lat_input_sample).

Every `evdev.InputDevice(path)` call hands out a *fresh* FakeDev, mirroring real evdev
(open = new fd; close releases it; re-open works). find_matches() opens and closes each
candidate per scan, so sharing one instance across opens would poison later run() threads.
"""
import queue
import threading
import time
from dataclasses import dataclass, field

import evdev
from evdev import ecodes as e, InputEvent


class LoopStop(Exception):
    """Sentinel raised from a patched time.sleep to unwind infinite-loop daemon threads."""


_REAL_SLEEP = time.sleep   # the true original; nested patches (e.g. the supervisor fast-sleep cap) must not corrupt restoration


def stop_daemon_threads(threads, timeout=2.0):
    """Kill infinite-loop daemon threads by making time.sleep raise LoopStop until each exits.

    ticker()/supervisor() only call sleep outside of `lock`, so raising there can never
    wedge the daemon's state lock. Returns the list of threads still alive afterwards
    (should be empty). Restores the true original sleep and excepthook on exit."""
    real_hook = threading.excepthook

    def _swallow(info):
        if isinstance(getattr(info, "exc_value", None), LoopStop):
            return
        real_hook(info)

    def _boom(*_args, **_kwargs):
        raise LoopStop()

    time.sleep = _boom
    threading.excepthook = _swallow
    try:
        for t in threads:
            t.join(timeout)
    finally:
        time.sleep = _REAL_SLEEP
        threading.excepthook = real_hook
    return [t for t in threads if t.is_alive()]


def wait_until(cond, timeout=5.0, interval=0.01):
    """Poll cond() until truthy; raise TimeoutError after `timeout` seconds."""
    deadline = time.monotonic() + timeout
    while True:
        if cond():
            return
        if time.monotonic() >= deadline:
            raise TimeoutError(f"condition not met within {timeout:.2f} s")
        time.sleep(interval)


@dataclass
class Sim:
    """Handle yielded by conftest.sim.make(): the live module, fake device and UI recorder."""
    vs: object
    dev: "FakeDev"
    holder: dict = field(default_factory=dict)   # {"ui": FakeUI} once run() has grabbed the device
    startup_out: str = ""

    @property
    def ui(self):
        return self.holder.get("ui")


class FakeDev:
    """Queue-backed stand-in for evdev.InputDevice; read_loop ends cleanly once close()d."""

    def __init__(self, path="sim://mouse", name="Fallback Sim Mouse"):
        self.path = path
        self.name = name
        self.info = type("Info", (), {"vendor": 0x1234, "product": 0x5678, "version": 1})()
        self.q = queue.Queue()
        self.closed = False
        self.close_count = 0

    def grab(self):
        pass

    def close(self):
        self.closed = True
        self.close_count += 1

    def capabilities(self):
        return {e.EV_REL: [e.REL_X, e.REL_Y], e.EV_KEY: [e.BTN_SIDE, e.BTN_EXTRA]}

    def read_loop(self):
        while not self.closed:
            try:
                yield self.q.get(timeout=0.05)
            except queue.Empty:
                continue


class FakeUI:
    """Records every write/write_event/syn/close instead of touching /dev/uinput."""

    def __init__(self, cap=None, name=None, vendor=0, product=0, version=0):
        self.writes = []
        self.syn_count = 0
        self.close_count = 0
        self.name = name

    def write(self, etype, code, value):
        self.writes.append((etype, code, value))

    def syn(self):
        self.syn_count += 1

    def write_event(self, ev):
        self.writes.append(("ev", ev.type, ev.code, ev.value))

    def close(self):
        self.close_count += 1


class FakeBus:
    """What install_fakes returns: every FakeDev handed out (in order) + the UInput holder."""

    def __init__(self):
        self.created = []
        self.holder = {}

    def open_device(self, path):
        dev = FakeDev(path=path)
        self.created.append(dev)
        return dev


def push(dev, etype, code, value):
    """Enqueue one scripted event with a wall-clock kernel timestamp."""
    t = time.time()
    dev.q.put(InputEvent(int(t), int((t % 1) * 1e6), etype, code, value))


def install_fakes(monkeypatch, vs_module):
    """Patch evdev.InputDevice (module attribute — veloscroll opens via `evdev.InputDevice`)
    and <vs_module>.UInput (sync_virtual_device resolves the bare name). Returns a FakeBus;
    bus.holder["ui"] is set once run() creates the virtual mouse."""
    bus = FakeBus()

    class _FakeUI(FakeUI):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            bus.holder["ui"] = self

    monkeypatch.setattr(evdev, "InputDevice", bus.open_device)
    monkeypatch.setattr(vs_module, "UInput", _FakeUI)
    return bus
