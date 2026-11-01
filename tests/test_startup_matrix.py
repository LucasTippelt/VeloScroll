"""E2E startup matrix: import veloscroll in a fresh subprocess (via probe_values.py)
with different VELOSCROLL_CONFIG files and assert the effective key values.

The probe prints `VALUES <json>` of every daemon key after the real startup block
(load/check/apply) has run, so these tests exercise the exact path a user hits on
service start — including fail-fast exit(1) on broken configs."""
import json
import os
import subprocess
import sys

import veloscroll as v   # conftest already imported it with VELOSCROLL_CONFIG pointed at a missing file

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROBE = os.path.join(ROOT, "tests", "probe_values.py")


def _defaults():
    return {k: (list(val) if isinstance(val, tuple) else val) for k, val in v._DEFAULTS.items()}


def run_probe(tmp_path, text=None):
    cfg = tmp_path / "config.ini"
    env = os.environ.copy()
    if text is None:
        assert not cfg.exists(), "caller must ensure the path does not exist"
        env["VELOSCROLL_CONFIG"] = str(cfg)
    else:
        cfg.write_text(text, encoding="utf-8")
        env["VELOSCROLL_CONFIG"] = str(cfg)
    r = subprocess.run([sys.executable, PROBE], capture_output=True, text=True, env=env)
    return r


def values_of(r):
    for line in r.stdout.splitlines():
        if line.startswith("VALUES "):
            return json.loads(line[len("VALUES "):])
    raise AssertionError(f"no VALUES line; rc={r.returncode}\nstdout:\n{r.stdout}\nstderr:\n{r.stderr}")


def test_missing_file_pure_defaults(tmp_path):
    r = run_probe(tmp_path, text=None)           # path never created
    assert r.returncode == 0, r.stdout + r.stderr
    got = values_of(r)
    assert got == _defaults()
    assert "config loaded from" not in r.stdout


def test_partial_overlay_and_override_count(tmp_path):
    cfg_text = "[veloscroll]\nNAME_MATCH = MyMouse\nCURVE = 0.75\nDPI = 800\n"
    r = run_probe(tmp_path, cfg_text)
    assert r.returncode == 0, r.stdout + r.stderr
    got = values_of(r)
    exp = _defaults()
    exp.update(NAME_MATCH="MyMouse", CURVE=0.75, DPI=800.0)
    assert got == exp
    assert f"config loaded from {tmp_path / 'config.ini'} (3 override(s))" in r.stdout


def test_malformed_value_exits_1(tmp_path):
    cfg = tmp_path / "config.ini"
    cfg.write_text("[veloscroll]\nCURVE = abc\n", encoding="utf-8")
    r = subprocess.run([sys.executable, PROBE], capture_output=True, text=True,
                       env={**os.environ, "VELOSCROLL_CONFIG": str(cfg)})
    assert r.returncode == 1
    assert f"config error: CURVE in {cfg}: expected a number (got 'abc')" in r.stdout
    assert "VALUES " not in r.stdout


def test_range_violation_from_check_config(tmp_path):
    cfg = tmp_path / "config.ini"
    cfg.write_text("[veloscroll]\nOUT_SMOOTH = 2\n", encoding="utf-8")
    r = subprocess.run([sys.executable, PROBE], capture_output=True, text=True,
                       env={**os.environ, "VELOSCROLL_CONFIG": str(cfg)})
    assert r.returncode == 1
    assert "config error: OUT_SMOOTH must be in the range (0, 1] (got 2.0)" in r.stdout


def test_unknown_key_and_section_warn_but_start(tmp_path):
    cfg_text = "[other]\nX = 1\n[veloscroll]\nFOO = 1\nCURVE = 0.7\n"
    r = run_probe(tmp_path, cfg_text)
    assert r.returncode == 0, r.stdout + r.stderr
    got = values_of(r)
    exp = _defaults()
    exp["CURVE"] = 0.7
    assert got == exp
    assert "config warning: unknown section [other]" in r.stdout
    assert "config warning: unknown key FOO" in r.stdout


def test_device_match_hex_pair(tmp_path):
    r = run_probe(tmp_path, "[veloscroll]\nDEVICE_MATCH = 0x46d, 0xc084\n")
    assert r.returncode == 0, r.stdout + r.stderr
    assert values_of(r)["DEVICE_MATCH"] == [1133, 49284]


def test_device_match_decimal_pair(tmp_path):
    r = run_probe(tmp_path, "[veloscroll]\nDEVICE_MATCH = 1133, 49284\n")
    assert r.returncode == 0, r.stdout + r.stderr
    assert values_of(r)["DEVICE_MATCH"] == [1133, 49284]


def test_device_match_path_string(tmp_path):
    path = "/dev/input/by-id/usb-Logitech_Mouse-event-mouse"
    r = run_probe(tmp_path, f"[veloscroll]\nDEVICE_MATCH = {path}\n")
    assert r.returncode == 0, r.stdout + r.stderr
    assert values_of(r)["DEVICE_MATCH"] == path


def test_device_match_none_falls_back_to_name_match(tmp_path):
    r = run_probe(tmp_path, "[veloscroll]\nDEVICE_MATCH = none\nNAME_MATCH = Fallback\n")
    assert r.returncode == 0, r.stdout + r.stderr
    assert values_of(r)["DEVICE_MATCH"] is None


def test_device_match_bare_number_rejected(tmp_path):
    cfg = tmp_path / "config.ini"
    cfg.write_text("[veloscroll]\nDEVICE_MATCH = 123\n", encoding="utf-8")
    r = subprocess.run([sys.executable, PROBE], capture_output=True, text=True,
                       env={**os.environ, "VELOSCROLL_CONFIG": str(cfg)})
    assert r.returncode == 1
    assert f"config error: DEVICE_MATCH in {cfg}: expected vendor product pair or path" in r.stdout


def test_button_symbol_decimal_and_none(tmp_path):
    cfg_text = "[veloscroll]\nSCROLL_BTN = BTN_EXTRA\nSCROLL_BTN_H = 275\nDISABLED_BTN = none\n"
    r = run_probe(tmp_path, cfg_text)
    assert r.returncode == 0, r.stdout + r.stderr
    got = values_of(r)
    assert got["SCROLL_BTN"] == 276            # e.BTN_EXTRA
    assert got["SCROLL_BTN_H"] == 275          # decimal code (e.BTN_SIDE)
    assert got["DISABLED_BTN"] is None


def test_scroll_btn_none_rejected(tmp_path):
    cfg = tmp_path / "config.ini"
    cfg.write_text("[veloscroll]\nSCROLL_BTN = none\n", encoding="utf-8")
    r = subprocess.run([sys.executable, PROBE], capture_output=True, text=True,
                       env={**os.environ, "VELOSCROLL_CONFIG": str(cfg)})
    assert r.returncode == 1
    assert f"config error: SCROLL_BTN in {cfg}: 'none' is not allowed" in r.stdout


def test_malformed_ini_structure_exits_1(tmp_path):
    cfg = tmp_path / "config.ini"
    cfg.write_text("CURVE = 0.5\n", encoding="utf-8")     # no section header
    r = subprocess.run([sys.executable, PROBE], capture_output=True, text=True,
                       env={**os.environ, "VELOSCROLL_CONFIG": str(cfg)})
    assert r.returncode == 1
    assert f"config error: malformed INI in {cfg}:" in r.stdout
