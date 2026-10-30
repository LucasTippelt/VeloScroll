"""Unit tier: pure functions of veloscroll_preset.py (fmt/regexes, line rewriter, backup
pruning + listing + restore resolution, covering-command hints). No CLI subprocess here —
the e2e tier covers main()."""
import os
from types import SimpleNamespace

import pytest

import veloscroll_preset as vp


# ---------------- _fmt ----------------

def test_fmt():
    assert vp._fmt(None) == "none"
    assert vp._fmt((0x46d, 0xc084)) == "0x46d, 0xc084"     # hex like config.ini.example; the daemon parses it back to the same tuple
    assert vp._fmt(130.0) == "130.0"
    assert vp._fmt("Fallback") == "Fallback"


# ---------------- NAME_RE / BAK_RE ----------------

@pytest.mark.parametrize("name", ["fast", "my.preset_2-x", "A1"])
def test_name_re_accepts(name):
    assert vp.NAME_RE.fullmatch(name) is not None


@pytest.mark.parametrize("name", ["/etc/passwd", "", "a b", "pre/set"])
def test_name_re_rejects(name):
    assert vp.NAME_RE.fullmatch(name) is None     # separators blocked -> no path traversal; empty name rejected


def test_name_re_allows_dots_but_stays_in_presets_dir():
    # NAME_RE = [A-Za-z0-9._-]+ : dots are allowed (a preset named '..' becomes the literal file '...ini', still inside presets/)
    assert vp.NAME_RE.fullmatch("..") is not None


def bak(orig, ts):
    return f"{orig}.bak-{ts}"


@pytest.mark.parametrize("ts", ["20250101-103000000000", "20261231-235959999999"])   # \d{8}-\d{6}\d{6}
def test_bak_re_matches(ts):
    assert vp.BAK_RE.match(bak("config.ini", ts)) is not None


@pytest.mark.parametrize("name", [
    bak("config.ini", "2025010-103000000000"),     # 7-digit date: wrong width
    bak("config.ini", "20250101-1030000"),         # 6+? too few time digits
    bak("config.ini", "20250101-1030000000001"),   # one digit too many
    "config.ini.bak-latest",                       # not a timestamp at all
    "unrelated.txt",
])
def test_bak_re_rejects(name):
    assert vp.BAK_RE.match(name) is None


# ---------------- _rewrite_config_lines ----------------

SAMPLE = (
    "# top comment\n"
    "[veloscroll]\n"
    "# a comment inside the section\n"
    "CURVE = 0.5   # trailing note\n"
    "\n"
    "DPI = 1600\n"
    "\n"
    "[other]\n"
    "x = 1\n"
)


def test_rewrite_in_place_preserves_comments_and_ordering(vs):
    out = vp._rewrite_config_lines(SAMPLE, {"CURVE": "0.7"}, vs.DAEMON_KEYS)
    lines = out.split("\n")
    assert "# top comment" in lines[0]
    assert "# a comment inside the section" in lines
    assert "x = 1" in lines                       # other sections untouched
    idx_curve = next(i for i, l in enumerate(lines) if l.startswith("CURVE"))
    assert lines[idx_curve] == "CURVE = 0.7"      # line replaced, position kept (trailing note dropped by design)
    idx_dpi = next(i for i, l in enumerate(lines) if l.startswith("DPI"))
    assert idx_curve < idx_dpi                    # ordering of untouched lines preserved


def test_rewrite_absent_keys_appended_in_daemon_key_order(vs):
    out = vp._rewrite_config_lines(SAMPLE, {"INVERT": "true", "TICK": "0.01"}, vs.DAEMON_KEYS)
    lines = out.split("\n")
    idx_dpi = next(i for i, l in enumerate(lines) if l.startswith("DPI"))
    idx_invert = next(i for i, l in enumerate(lines) if l.startswith("INVERT"))
    idx_tick = next(i for i, l in enumerate(lines) if l.startswith("TICK"))
    assert idx_dpi < idx_invert < idx_tick        # appended at section end in DAEMON_KEYS order (INVERT precedes TICK there)
    assert lines[idx_invert] == "INVERT = true"
    assert lines[idx_tick] == "TICK = 0.01"


def test_rewrite_creates_section_when_missing(vs):
    out = vp._rewrite_config_lines("[other]\nx = 1\n", {"CURVE": "0.9"}, vs.DAEMON_KEYS)
    assert "[veloscroll]" in out.split("\n") and "CURVE = 0.9" in out


def test_rewrite_empty_file_creates_section(vs):
    out = vp._rewrite_config_lines("", {"DPI": "800"}, vs.DAEMON_KEYS)
    lines = out.split("\n")
    assert "[veloscroll]" in lines and "DPI = 800" in lines


def test_rewrite_lossless_round_trip_when_no_updates(vs):
    assert vp._rewrite_config_lines(SAMPLE, {}, vs.DAEMON_KEYS) == SAMPLE


# ---------------- _prune_backups ----------------

def make_baks(d, names):
    for n in names:
        with open(os.path.join(d, n), "w") as f:
            f.write("x\n")


TS = [f"202501{d:02d}-103000{i:06d}" for d, i in ((1, 0), (2, 0), (3, 0), (4, 0))]   # fixed-width, lexicographic == chronological


def test_prune_keeps_n_newest_and_returns_deleted(tmp_path):
    cfg = tmp_path / "kcminputrc"
    cfg.write_text("[s]\nk=v\n")
    make_baks(tmp_path, [bak("kcminputrc", t) for t in TS])
    pruned = vp._prune_backups(str(cfg), 2)
    assert pruned == [bak("kcminputrc", TS[0]), bak("kcminputrc", TS[1])]   # oldest first
    left = sorted(f for f in os.listdir(tmp_path) if f.startswith("kcminputrc.bak-"))
    assert left == [bak("kcminputrc", TS[2]), bak("kcminputrc", TS[3])]


def test_prune_unlimited_deletes_nothing(tmp_path):
    cfg = tmp_path / "kcminputrc"
    cfg.write_text("[s]\nk=v\n")
    make_baks(tmp_path, [bak("kcminputrc", t) for t in TS])
    assert vp._prune_backups(str(cfg), -1) == []
    left = [f for f in os.listdir(tmp_path) if f.startswith("kcminputrc.bak-")]
    assert len(left) == 4


def test_prune_disabled_zero_is_noop_deletes_nothing(tmp_path):
    cfg = tmp_path / "kcminputrc"
    cfg.write_text("[s]\nk=v\n")
    make_baks(tmp_path, [bak("kcminputrc", t) for t in TS])
    assert vp._prune_backups(str(cfg), 0) == []      # MAX_BACKUPS = 0: backups disabled — pruning is a no-op
    left = sorted(f for f in os.listdir(tmp_path) if f.startswith("kcminputrc.bak-"))
    assert len(left) == 4                             # existing backups stay untouched


def test_prune_invalid_value_raises_before_deleting(tmp_path):
    cfg = tmp_path / "kcminputrc"
    cfg.write_text("[s]\nk=v\n")
    make_baks(tmp_path, [bak("kcminputrc", t) for t in TS])
    before = sorted(os.listdir(tmp_path))
    for bad in (-2, "5"):                             # 0 is valid now (backups disabled); only < -1 / non-int raise
        with pytest.raises(vp.PresetError):
            vp._prune_backups(str(cfg), bad)
    assert sorted(os.listdir(tmp_path)) == before     # nothing deleted
    with pytest.raises(vp.PresetError) as exc:
        vp._prune_backups(str(cfg), -2)
    msg = str(exc.value)
    assert "-1 (unlimited)" in msg and "0" in msg and "positive number of backups to keep" in msg   # names all three valid forms


def test_prune_ignores_unrelated_files(tmp_path):
    cfg = tmp_path / "kcminputrc"
    cfg.write_text("[s]\nk=v\n")
    make_baks(tmp_path, [bak("other.ini", t) for t in TS] + ["notes.txt"])
    assert vp._prune_backups(str(cfg), 1) == []   # only kcminputrc.bak-* candidates (none exist)
    left = sorted(os.listdir(tmp_path))
    assert "notes.txt" in left and len([f for f in left if f.startswith("other.ini.bak-")]) == 4


# ---------------- _backup_files ----------------

def test_backup_files_scans_both_dirs_newest_first(tmp_path, vs):
    cfg = tmp_path / "config.ini"
    cfg.write_text("[veloscroll]\n")
    preset_dir = tmp_path / "presets"
    preset_dir.mkdir()
    (preset_dir / "fast.ini").write_text("[veloscroll]\nCURVE = 0.7\n")

    make_baks(tmp_path, [bak("config.ini", TS[0]), bak("config.ini", TS[3])])
    make_baks(preset_dir, [bak("fast.ini", TS[1])])
    (tmp_path / "not-a-backup.txt").write_text("x")

    found = vp._backup_files(str(cfg))
    assert found == [str(tmp_path / bak("config.ini", TS[3])),
                     str(preset_dir / bak("fast.ini", TS[1])),
                     str(tmp_path / bak("config.ini", TS[0]))]     # newest first, both dirs


# ---------------- _resolve_backup ----------------

def test_resolve_no_ref_newest_config_backup(tmp_path):
    cfg = tmp_path / "config.ini"
    cfg.write_text("[veloscroll]\n")
    (tmp_path / "presets").mkdir()
    make_baks(tmp_path, [bak("config.ini", TS[0]), bak("config.ini", TS[2])])
    fake_vs = SimpleNamespace(CONFIG_PATH=str(cfg))
    assert vp._resolve_backup(fake_vs, None) == str(tmp_path / bak("config.ini", TS[2]))


def test_resolve_unique_basename_match(tmp_path):
    cfg = tmp_path / "config.ini"
    cfg.write_text("[veloscroll]\n")
    (tmp_path / "presets").mkdir()
    make_baks(tmp_path, [bak("config.ini", TS[0])])
    make_baks(tmp_path / "presets", [bak("fast.ini", TS[1])])
    fake_vs = SimpleNamespace(CONFIG_PATH=str(cfg))
    assert vp._resolve_backup(fake_vs, bak("fast.ini", TS[1])) == str(tmp_path / "presets" / bak("fast.ini", TS[1]))


def test_resolve_ambiguous_basename_across_dirs_errors(tmp_path):
    cfg = tmp_path / "config.ini"
    cfg.write_text("[veloscroll]\n")
    (tmp_path / "presets").mkdir()
    name = bak("config.ini", TS[0])
    make_baks(tmp_path, [name])
    make_baks(tmp_path / "presets", [name])            # same basename in both dirs
    fake_vs = SimpleNamespace(CONFIG_PATH=str(cfg))
    with pytest.raises(vp.PresetError) as exc:
        vp._resolve_backup(fake_vs, name)
    assert "ambiguous" in str(exc.value)


def test_resolve_explicit_path_constrained_to_allowed_dirs(tmp_path):
    cfg = tmp_path / "config.ini"
    cfg.write_text("[veloscroll]\n")
    (tmp_path / "presets").mkdir()
    make_baks(tmp_path / "presets", [bak("fast.ini", TS[0])])
    fake_vs = SimpleNamespace(CONFIG_PATH=str(cfg))

    ok_ref = os.path.join("presets", bak("fast.ini", TS[0]))     # relative path inside the presets dir is allowed
    assert vp._resolve_backup(fake_vs, ok_ref) == str(tmp_path / "presets" / bak("fast.ini", TS[0]))

    with pytest.raises(vp.PresetError):                          # traversal outside config dir + presets/ rejected
        vp._resolve_backup(fake_vs, os.path.join("..", "evil", bak("config.ini", TS[0])))


def test_resolve_missing_name_errors(tmp_path):
    cfg = tmp_path / "config.ini"
    cfg.write_text("[veloscroll]\n")
    fake_vs = SimpleNamespace(CONFIG_PATH=str(cfg))
    with pytest.raises(vp.PresetError) as exc:
        vp._resolve_backup(fake_vs, bak("fast.ini", TS[0]))
    assert "no backup named" in str(exc.value)


# ---------------- _covering_cmds ----------------

def test_covering_cmds_group_keys_and_loadall(vs):
    assert vp._covering_cmds(["MAX_RATE"]) == ["loadfeel"]
    assert vp._covering_cmds(["DEADZONE_IN", "FULL_IN_H"]) == ["loaddistances"]
    assert vp._covering_cmds(["SCROLL_BTN", "DISABLED_BTN"]) == ["loadkeys"]
    assert vp._covering_cmds(["NAME_MATCH", "DEVICE_MATCH", "DPI"]) == ["loaddevice"]
    assert vp._covering_cmds(["TOGGLE_SCROLL", "VERTICAL_H"]) == ["loadscroll"]
    for key in ("INVERT", "TICK", "LOG_LEVEL", "LATENCY_LOG"):   # outside every named group -> loadall
        assert vp._covering_cmds([key]) == ["loadall"]
    assert vp._covering_cmds(["MAX_RATE", "INVERT"]) == ["loadfeel", "loadall"]
