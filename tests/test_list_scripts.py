"""Unit tier: ListDeviceNames.py and ListButtonPresses.py (evdev patched at module level; both scripts
import evdev inside main(), so patching the shared real module is what they resolve)."""
from types import SimpleNamespace

import pytest
from evdev import ecodes as e

import evdev  # noqa: F401  (patched target)
import ListDeviceNames as ldn
import ListButtonPresses as lbp


class _Dev:
    """Just enough of evdev.InputDevice for these scripts."""

    def __init__(self, path, name="Test Mouse", vendor=0x46d, product=0xc084, events=None):
        self.path = path
        self.name = name
        self.info = SimpleNamespace(vendor=vendor, product=product)
        self._events = list(events or [])

    def read_loop(self):
        for ev in self._events:      # the real loop is infinite; a finite stand-in lets main() return
            yield ev


# ---------------- ListDeviceNames ----------------

def test_list_device_names_prints_path_name_and_ids(monkeypatch, capsys):
    devs = {
        "/dev/input/event1": _Dev("/dev/input/event1", name="Logitech PRO X"),
        "/dev/input/event2": _Dev("/dev/input/event2", name="Keyboard", vendor=0x46d, product=0xc07d),
    }
    monkeypatch.setattr(evdev, "list_devices", lambda: list(devs))
    monkeypatch.setattr(evdev, "InputDevice", lambda path: devs[path])

    rc = ldn.main([])
    out = capsys.readouterr().out
    assert rc == 0
    assert "/dev/input/event1 -> Logitech PRO X 0x46d 0xc084" in out
    assert "/dev/input/event2 -> Keyboard 0x46d 0xc07d" in out


def test_list_device_names_skips_unopenable_with_stderr_note(monkeypatch, capsys):
    def fake(path):
        if path == "/dev/input/event1":
            return _Dev(path)
        raise OSError("device busy")

    monkeypatch.setattr(evdev, "list_devices", lambda: ["/dev/input/event1", "/dev/input/event2"])
    monkeypatch.setattr(evdev, "InputDevice", fake)

    rc = ldn.main([])
    captured = capsys.readouterr()
    out, err = captured.out, captured.err
    assert rc == 0
    assert "/dev/input/event1 -> Test Mouse 0x46d 0xc084" in out
    assert "event2" not in out
    assert "skipping /dev/input/event2: device busy" in err


def test_list_device_names_none_readable_exits_one(monkeypatch, capsys):
    monkeypatch.setattr(evdev, "list_devices", lambda: [])
    rc = ldn.main([])
    assert rc == 1
    assert "no readable input devices" in capsys.readouterr().err


# ---------------- ListButtonPresses ----------------

def _events():
    return [
        SimpleNamespace(type=e.EV_KEY, code=275, value=1),      # BTN_SIDE press -> printed
        SimpleNamespace(type=e.EV_REL, code=e.REL_Y, value=4),  # movement -> filtered out (not EV_KEY)
        SimpleNamespace(type=e.EV_KEY, code=276, value=0),      # BTN_EXTRA release -> printed
    ]


def test_button_presses_number_arg_maps_to_event_path(monkeypatch, capsys):
    opened = []

    def fake(path):
        opened.append(path)
        return _Dev(path, events=_events())

    monkeypatch.setattr(evdev, "InputDevice", fake)
    rc = lbp.main(["30"])
    out = capsys.readouterr().out
    assert rc == 0
    assert opened == ["/dev/input/event30"]
    assert "press the candidate side buttons; Ctrl-C to stop" in out
    lines = [l for l in out.splitlines() if l.strip()]
    assert lines[-2:] == ["275 1", "276 0"]     # only EV_KEY events, as `code value`


def test_button_presses_full_path_passthrough(monkeypatch, capsys):
    opened = []

    def fake(path):
        opened.append(path)
        return _Dev(path, events=[])

    monkeypatch.setattr(evdev, "InputDevice", fake)
    rc = lbp.main(["/dev/input/by-id/usb-test-mouse-event-mouse"])
    assert rc == 0 and opened == ["/dev/input/by-id/usb-test-mouse-event-mouse"]


def test_button_presses_invalid_arg_exits_one(monkeypatch, capsys):
    monkeypatch.setattr(evdev, "InputDevice", lambda path: pytest.fail("must not open a device"))
    rc = lbp.main(["abc"])
    err = capsys.readouterr().err
    assert rc == 1 and "'abc' is neither an event number nor a device path" in err


def test_button_presses_permission_error_message(monkeypatch, capsys):
    def fake(path):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(evdev, "InputDevice", fake)
    rc = lbp.main(["42"])
    err = capsys.readouterr().err
    assert rc == 1 and "/dev/input/event42: no permission: run as root or add user to input group" in err


def test_button_presses_keyboard_interrupt_is_clean_exit(monkeypatch, capsys):
    def fake(path):
        dev = _Dev(path)

        def loop():
            yield SimpleNamespace(type=e.EV_KEY, code=275, value=1)
            raise KeyboardInterrupt

        dev.read_loop = loop
        return dev

    monkeypatch.setattr(evdev, "InputDevice", fake)
    rc = lbp.main(["30"])
    out = capsys.readouterr().out
    assert rc == 0 and "275 1" in out      # event before the interrupt still printed; no traceback
