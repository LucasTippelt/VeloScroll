"""Unit tier: check_config() validation over full value dicts (base = _DEFAULTS)."""
import pytest


def _patch(vs, **overrides):
    v = dict(vs._DEFAULTS)
    v.update(overrides)
    return v


def test_defaults_are_valid(vs):
    assert vs.check_config(dict(vs._DEFAULTS)) == []


@pytest.mark.parametrize("name,patch,needle", [
    ("dpi zero", {"DPI": 0}, "DPI must be > 0"),
    ("min_rate zero", {"MIN_RATE": 0}, "MIN_RATE must be > 0"),
    ("max below min", {"MAX_RATE": 3.0, "MIN_RATE": 4.0}, "MAX_RATE must be >= MIN_RATE"),
    ("deadzone zero", {"DEADZONE_IN": 0}, "DEADZONE_IN must be > 0"),
    ("full equals deadzone", {"FULL_IN": 0.5, "DEADZONE_IN": 0.5}, "FULL_IN must be greater than DEADZONE_IN"),
    ("curve zero", {"CURVE": 0}, "CURVE must be > 0"),
    ("out_smooth zero", {"OUT_SMOOTH": 0}, "OUT_SMOOTH must be in the range (0, 1]"),
    ("out_smooth above one", {"OUT_SMOOTH": 1.5}, "OUT_SMOOTH must be in the range (0, 1]"),
])
def test_invalid_values(vs, name, patch, needle):
    errors = vs.check_config(_patch(vs, **patch))
    assert any(needle in e for e in errors), errors


@pytest.mark.parametrize("name,patch", [
    ("max equals min ok", {"MAX_RATE": 4.0}),
    ("out_smooth one ok", {"OUT_SMOOTH": 1.0}),
    ("max_backups unlimited ok", {"MAX_BACKUPS": -1}),
    ("max_backups disabled ok", {"MAX_BACKUPS": 0}),
    ("max_backups default ok", {"MAX_BACKUPS": 5}),
])
def test_boundary_values_valid(vs, name, patch):
    assert vs.check_config(_patch(vs, **patch)) == []


@pytest.mark.parametrize("name,patch,needle", [
    ("max_backups below -1", {"MAX_BACKUPS": -2}, "MAX_BACKUPS must be an integer"),
    ("max_backups float rejected", {"MAX_BACKUPS": 5.0}, "MAX_BACKUPS must be an integer"),
    ("max_backups bool-as-int rejected", {"MAX_BACKUPS": True}, "MAX_BACKUPS must be an integer"),
])
def test_max_backups_type(vs, name, patch, needle):
    errors = vs.check_config(_patch(vs, **patch))
    assert any(needle in e for e in errors), errors


# ---- horizontal fallback cross-checks (effective values) ----

@pytest.mark.parametrize("name,patch,needle", [
    ("only full_h below vertical dz", {"FULL_IN_H": 0.01}, "FULL_IN_H must be greater than DEADZONE_IN"),
    ("only deadzone_h zero", {"DEADZONE_IN_H": 0}, "DEADZONE_IN_H must be > 0"),
    ("both h: full below dz", {"DEADZONE_IN_H": 0.4, "FULL_IN_H": 0.2}, "FULL_IN_H must be greater than DEADZONE_IN_H"),
    ("min_rate_h zero", {"MIN_RATE_H": 0}, "MIN_RATE_H must be > 0"),
    ("max_rate_h below vertical min", {"MAX_RATE_H": 2.0, "MIN_RATE": 4.0}, "MAX_RATE_H must be >= MIN_RATE"),
    ("curve_h zero", {"CURVE_H": 0}, "CURVE_H must be > 0"),
    ("out_smooth_h zero", {"OUT_SMOOTH_H": 0}, "OUT_SMOOTH_H must be in the range (0, 1]"),
    ("out_smooth_h above one", {"OUT_SMOOTH_H": 2.0}, "OUT_SMOOTH_H must be in the range (0, 1]"),
])
def test_h_fallback_invalid(vs, name, patch, needle):
    errors = vs.check_config(_patch(vs, **patch))
    assert any(needle in e for e in errors), errors


@pytest.mark.parametrize("name,patch", [
    ("only full_h above vertical dz ok", {"FULL_IN_H": 3.0}),
    ("min_rate_h only ok", {"MIN_RATE_H": 5.0}),
    ("h rates consistent", {"MIN_RATE_H": 4.0, "MAX_RATE_H": 100.0}),
])
def test_h_fallback_valid(vs, name, patch):
    assert vs.check_config(_patch(vs, **patch)) == []


# ---- button identity + type checks ----

@pytest.mark.parametrize("name,patch,needle", [
    ("h equals main", {"SCROLL_BTN_H": 275}, "SCROLL_BTN_H and SCROLL_BTN must be different"),
    ("disabled equals main", {"DISABLED_BTN": 275}, "SCROLL_BTN and DISABLED_BTN must be different"),
    ("h equals disabled", {"SCROLL_BTN_H": 276, "DISABLED_BTN": 276}, "SCROLL_BTN_H and DISABLED_BTN must be different"),
])
def test_button_identity(vs, name, patch, needle):
    errors = vs.check_config(_patch(vs, **patch))
    assert any(needle in e for e in errors), errors


@pytest.mark.parametrize("name,patch,needle", [
    ("scroll_btn not int", {"SCROLL_BTN": "BTN_SIDE"}, "SCROLL_BTN must be an integer button code"),
    ("disabled_btn not int", {"DISABLED_BTN": 1.5}, "DISABLED_BTN must be an integer button code or none"),
    ("h_btn not int", {"SCROLL_BTN_H": "x"}, "SCROLL_BTN_H must be an integer button code or none"),
    ("toggle bool-as-int rejected", {"TOGGLE_SCROLL": 1}, "TOGGLE_SCROLL must be a boolean"),
    ("vertical_h bool-as-int rejected", {"VERTICAL_H": 0}, "VERTICAL_H must be a boolean"),
    ("toggle_h not bool", {"TOGGLE_SCROLL_H": 2}, "TOGGLE_SCROLL_H must be a boolean true/false or none"),
    ("latency_log int rejected", {"LATENCY_LOG": 1}, "LATENCY_LOG must be a boolean"),
])
def test_type_checks(vs, name, patch, needle):
    errors = vs.check_config(_patch(vs, **patch))
    assert any(needle in e for e in errors), errors


# ---- DEVICE_MATCH forms + NAME_MATCH coupling ----

@pytest.mark.parametrize("name,patch", [
    ("dm pair ok", {"DEVICE_MATCH": (1133, 49284)}),
    ("dm path ok", {"DEVICE_MATCH": "/dev/input/by-id/usb-x"}),
    ("empty name ok when dm set", {"NAME_MATCH": "", "DEVICE_MATCH": (1, 2)}),
])
def test_device_match_valid_forms(vs, name, patch):
    assert vs.check_config(_patch(vs, **patch)) == []


@pytest.mark.parametrize("name,patch,needle", [
    ("dm single-element tuple", {"DEVICE_MATCH": (1133,)}, "DEVICE_MATCH must be a"),
    ("dm string without slash", {"DEVICE_MATCH": "usb-foo"}, "DEVICE_MATCH must be a"),
    ("empty name with dm None", {"NAME_MATCH": "   "}, "NAME_MATCH must be non-empty when DEVICE_MATCH is None"),
])
def test_device_match_invalid_forms(vs, name, patch, needle):
    errors = vs.check_config(_patch(vs, **patch))
    assert any(needle in e for e in errors), errors


@pytest.mark.parametrize("name,patch,needle", [
    ("log_level out of range", {"LOG_LEVEL": 4}, "LOG_LEVEL must be an integer"),
    ("log_level not int", {"LOG_LEVEL": "2"}, "LOG_LEVEL must be an integer"),
])
def test_log_level_type(vs, name, patch, needle):
    errors = vs.check_config(_patch(vs, **patch))
    assert any(needle in e for e in errors), errors
