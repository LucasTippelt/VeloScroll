"""E2E seed CLI entry point: run veloscroll_seed.main() in-process.

The heavy backend logic is covered by tests/test_seed_backend.py; here we pin the
entry-point wiring — root refusal, discovery-failure surfacing, unsupported-DE_WM
rejection, and argparse behavior — without needing a real mouse or KWin session."""
import os
import sys

import veloscroll as v
import veloscroll_seed as seed


def _ensure_nonroot(monkeypatch):
    if os.geteuid() == 0:      # CI/containers may run as root; the refusal path is tested separately
        monkeypatch.setattr(os, "geteuid", lambda: 1000)


def test_root_refusal(monkeypatch, capsys):
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    rc = seed.main([])
    assert rc == 1
    err = capsys.readouterr().err
    assert err.startswith("veloscroll-seed: refusing to run as root")


def test_discovery_failure_is_surfaced(monkeypatch, capsys):
    _ensure_nonroot(monkeypatch)

    def boom(*a, **k):
        raise seed.SeedError("no mouse matched the current configuration (NAME_MATCH='Fallback')")

    monkeypatch.setattr(seed, "discover_real_mouse", boom)
    rc = seed.main([])
    assert rc == 1
    err = capsys.readouterr().err
    assert "veloscroll-seed: no mouse matched the current configuration" in err


def test_unsupported_de_wm_rejected(monkeypatch, capsys):
    _ensure_nonroot(monkeypatch)
    fake = seed.RealDevice(name="Test Mouse", vendor=0x12d, product=0x3456, version=0, node="/dev/input/event9")
    monkeypatch.setattr(seed, "discover_real_mouse", lambda *a, **k: fake)
    monkeypatch.setattr(v, "DE_WM", "gnome-shell")
    rc = seed.main([])
    assert rc == 1
    err = capsys.readouterr().err
    assert "veloscroll-seed: unsupported DE_WM 'gnome-shell' — supported values: 'kde-plasma'" in err


def test_argparse_rejects_unknown_flag(capsys):
    try:
        seed.main(["--bogus"])
        raise AssertionError("expected SystemExit from argparse")
    except SystemExit as exc:
        assert exc.code == 2
    assert "unrecognized arguments: --bogus" in capsys.readouterr().err
