"""Unit tier: config.ini parsing (_parse_ini_value) and load_config()."""
import pytest
from evdev import ecodes as e


# ---------------- _parse_ini_value, per key family ----------------

@pytest.mark.parametrize("raw", ["Fallback", "Logitech PRO X", "  spaced name  ", ""])
def test_name_match_passthrough(vs, raw):
    assert vs._parse_ini_value("NAME_MATCH", raw) == raw


@pytest.mark.parametrize("raw,want", [
    ("0x46d, 0xc084", (1133, 49284)),          # hex pair
    ("1133 16531", (1133, 16531)),             # decimal pair
    ("0x46D, 0xC084", (1133, 49284)),          # hex pair, mixed case + comma+space
    ("1133, 16531", (1133, 16531)),            # decimal pair with comma
    ("/dev/input/by-id/usb-test-event-mouse", "/dev/input/by-id/usb-test-event-mouse"),   # stable path string
    ("none", None),                            # fall back to NAME_MATCH
])
def test_device_match_valid(vs, raw, want):
    assert vs._parse_ini_value("DEVICE_MATCH", raw) == want


@pytest.mark.parametrize("raw", [
    "1234",            # bare number: one token is a valid int but the pair needs two
    "abc def",            # garbage tokens
    "0x46d c084",         # second token lacks the 0x prefix -> not a pair (and no '/' path)
    "0x46d 0xc084 extra", # three tokens
])
def test_device_match_invalid(vs, raw):
    with pytest.raises(vs.ConfigError):
        vs._parse_ini_value("DEVICE_MATCH", raw)


@pytest.mark.parametrize("key,raw,want", [
    ("SCROLL_BTN", "BTN_SIDE", e.BTN_SIDE),     # ecodes symbol
    ("SCROLL_BTN_H", "BTN_EXTRA", e.BTN_EXTRA),
    ("DISABLED_BTN", "279", 279),               # decimal code
    ("DISABLED_BTN", "none", None),             # disables the feature
    ("SCROLL_BTN_H", "none", None),
])
def test_button_keys_valid(vs, key, raw, want):
    assert vs._parse_ini_value(key, raw) == want


@pytest.mark.parametrize("key,raw", [
    ("SCROLL_BTN", "none"),                     # 'none' is not allowed for the main button
    ("SCROLL_BTN", "NOT_A_BUTTON"),             # unknown non-numeric name
    ("DISABLED_BTN", "12.5"),                   # not an int and no such ecodes symbol
])
def test_button_keys_invalid(vs, key, raw):
    with pytest.raises(vs.ConfigError):
        vs._parse_ini_value(key, raw)


@pytest.mark.parametrize("key,raw,want", [
    ("INVERT", "true", True), ("INVERT", "YES", True), ("INVERT", "on", True), ("INVERT", "1", True),
    ("LATENCY_LOG", "false", False), ("TOGGLE_SCROLL", "No", False), ("TOGGLE_SCROLL", "off", False),
    ("TOGGLE_SCROLL", "0", False), ("VERTICAL_H", "True", True),
])
def test_booleans_valid(vs, key, raw, want):
    assert vs._parse_ini_value(key, raw) is want


@pytest.mark.parametrize("key,raw", [
    ("INVERT", "banana"), ("LATENCY_LOG", ""), ("TOGGLE_SCROLL", "2"),
])
def test_booleans_invalid(vs, key, raw):
    with pytest.raises(vs.ConfigError):
        vs._parse_ini_value(key, raw)


@pytest.mark.parametrize("raw,want", [
    ("none", None),      # unset -> fall back to the vertical value at runtime
    ("true", True),
    ("false", False),
])
def test_toggle_scroll_h(vs, raw, want):
    assert vs._parse_ini_value("TOGGLE_SCROLL_H", raw) is want


@pytest.mark.parametrize("raw,want", [("0", 0), ("3", 3)])
def test_log_level_valid(vs, raw, want):
    assert vs._parse_ini_value("LOG_LEVEL", raw) == want


@pytest.mark.parametrize("raw", ["-1", "4", "2.5", "x"])
def test_log_level_invalid(vs, raw):
    with pytest.raises(vs.ConfigError):
        vs._parse_ini_value("LOG_LEVEL", raw)


@pytest.mark.parametrize("key", [
    "DEADZONE_IN_H", "FULL_IN_H", "MIN_RATE_H", "MAX_RATE_H", "CURVE_H", "OUT_SMOOTH_H",
])
def test_h_float_keys(vs, key):
    assert vs._parse_ini_value(key, "none") is None
    assert vs._parse_ini_value(key, "1.5") == 1.5
    with pytest.raises(vs.ConfigError):
        vs._parse_ini_value(key, "abc")


@pytest.mark.parametrize("key,raw,want", [
    ("DPI", "800", 800.0),          # int-like string parses to float
    ("DEADZONE_IN", "0.35", 0.35),
    ("FULL_IN", "2.5", 2.5),
    ("MAX_RATE", "130", 130.0),
    ("MIN_RATE", "4.0", 4.0),
    ("CURVE", "0.7", 0.7),
    ("OUT_SMOOTH", "0.8", 0.8),
    ("TICK", "0.004", 0.004),
])
def test_plain_floats(vs, key, raw, want):
    assert vs._parse_ini_value(key, raw) == want


@pytest.mark.parametrize("key,raw", [
    ("DPI", "abc"), ("TICK", ""), ("MAX_RATE", "1.2.3"),
])
def test_plain_floats_invalid(vs, key, raw):
    with pytest.raises(vs.ConfigError):
        vs._parse_ini_value(key, raw)


@pytest.mark.parametrize("raw,want", [
    ("5", 5),      # int-like string parses to int (not float)
    ("-1", -1),    # unlimited
    ("0", 0),      # backups disabled entirely
])
def test_max_backups_valid(vs, raw, want):
    assert vs._parse_ini_value("MAX_BACKUPS", raw) == want


@pytest.mark.parametrize("raw", ["-2", "abc", "1.5"])   # non-integers and anything < -1 are invalid
def test_max_backups_invalid_names_all_forms(vs, raw):
    with pytest.raises(vs.ConfigError) as exc:
        vs._parse_ini_value("MAX_BACKUPS", raw)
    msg = str(exc.value)
    assert "-1" in msg and "0" in msg                  # the error names -1 (unlimited), 0 (disable backups) and positive integers


# ---------------- load_config() (patched CONFIG_PATH + tmp files) ----------------

def test_load_missing_file_pure_defaults(vs, tmp_path, monkeypatch):
    monkeypatch.setattr(vs, "CONFIG_PATH", str(tmp_path / "absent.ini"))
    assert vs.load_config() == dict(vs._DEFAULTS)
    assert vs._cfg_load_info is None


def test_load_empty_value_keeps_default(vs, tmp_path, monkeypatch):
    cfg = tmp_path / "config.ini"
    cfg.write_text("[veloscroll]\nCURVE =\n", encoding="utf-8")
    monkeypatch.setattr(vs, "CONFIG_PATH", str(cfg))
    values = vs.load_config()
    assert values["CURVE"] == vs._DEFAULTS["CURVE"]     # empty value -> code default applies
    assert vs._cfg_load_info == (str(cfg), 0)


def test_load_unknown_section_and_key_warn_but_apply(vs, tmp_path, monkeypatch, capsys):
    cfg = tmp_path / "config.ini"
    cfg.write_text("[veloscroll]\nCURVE = 0.6\nBOGUS_KEY = 1\n[other]\nx = 1\n", encoding="utf-8")
    monkeypatch.setattr(vs, "CONFIG_PATH", str(cfg))
    values = vs.load_config()
    assert values["CURVE"] == 0.6
    out = capsys.readouterr().out
    assert f"unknown key BOGUS_KEY in {cfg}" in out
    assert "unknown section [other]" in out


def test_load_malformed_ini_structure(vs, tmp_path, monkeypatch):
    cfg = tmp_path / "config.ini"
    cfg.write_text("CURVE = 0.7\nno section header here\n", encoding="utf-8")
    monkeypatch.setattr(vs, "CONFIG_PATH", str(cfg))
    with pytest.raises(vs.ConfigError) as exc:
        vs.load_config()
    assert "malformed INI" in str(exc.value)


def test_load_two_bad_keys_single_error(vs, tmp_path, monkeypatch):
    cfg = tmp_path / "config.ini"
    cfg.write_text("[veloscroll]\nCURVE = abc\nDPI = xyz\n", encoding="utf-8")
    monkeypatch.setattr(vs, "CONFIG_PATH", str(cfg))
    with pytest.raises(vs.ConfigError) as exc:
        vs.load_config()
    msg = str(exc.value)
    assert "CURVE" in msg and "DPI" in msg      # both messages joined into one error
