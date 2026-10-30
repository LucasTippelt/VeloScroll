"""E2E preset CLI: run veloscroll_preset.py as a real subprocess against a temp config.ini
and assert on its output, the presets/ dir, and the backups it creates."""
import os
import re
import subprocess
import sys

import veloscroll as v   # for DAEMON_KEYS / _DEFAULTS shape only (conftest already imported it)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRESET_CLI = os.path.join(ROOT, "veloscroll_preset.py")
BAK_RE = re.compile(r"^(?P<orig>.+)\.bak-(?P<ts>\d{8}-\d{6}\d{6})$")

BASE_CFG = "[veloscroll]\nNAME_MATCH = TestMouse\nCURVE = 0.7\n"


def run(cfg, *ops):
    return subprocess.run([sys.executable, PRESET_CLI, "--config", str(cfg), *ops],
                          capture_output=True, text=True)


def write_cfg(tmp_path, text=BASE_CFG):
    cfg = tmp_path / "config.ini"
    cfg.write_text(text, encoding="utf-8")
    return cfg


def preset_dir(cfg):
    return os.path.join(os.path.dirname(str(cfg)), "presets")


def saved_key_count(cfg_text):
    """save captures every daemon key except *_H keys that are unset in config.ini and the never-applied keys (MAX_BACKUPS)."""
    present = re.findall(r"^(\w+)\s*=", cfg_text, re.M)
    return len([k for k in v.DAEMON_KEYS if not (k.endswith("_H") and k not in present) and k != "MAX_BACKUPS"])


def test_save_creates_preset(tmp_path):
    cfg = write_cfg(tmp_path)
    r = run(cfg, "save", "fast")
    assert r.returncode == 0, r.stdout + r.stderr
    p = os.path.join(preset_dir(cfg), "fast.ini")
    assert f"saved {p} ({saved_key_count(BASE_CFG)} keys)" in r.stdout
    body = open(p, encoding="utf-8").read()
    assert "# VeloScroll preset 'fast'" in body
    assert "NAME_MATCH = TestMouse" in body
    assert "CURVE = 0.7" in body


def test_save_unchanged_is_noop(tmp_path):
    cfg = write_cfg(tmp_path)
    assert run(cfg, "save", "fast").returncode == 0
    r = run(cfg, "save", "fast")
    assert r.returncode == 0
    p = os.path.join(preset_dir(cfg), "fast.ini")
    assert f"no change — {p} already matches the current config" in r.stdout
    baks = [f for f in os.listdir(preset_dir(cfg)) if BAK_RE.match(f)]
    assert baks == []


def test_save_changed_creates_backup(tmp_path):
    cfg = write_cfg(tmp_path)
    assert run(cfg, "save", "fast").returncode == 0
    cfg.write_text(BASE_CFG.replace("CURVE = 0.7", "CURVE = 0.9"), encoding="utf-8")
    r = run(cfg, "save", "fast")
    assert r.returncode == 0, r.stdout + r.stderr
    assert f"saved {os.path.join(preset_dir(cfg), 'fast.ini')} (" in r.stdout
    assert "backup     : " in r.stdout
    baks = [f for f in os.listdir(preset_dir(cfg)) if BAK_RE.match(f)]
    assert len(baks) == 1


def test_loadfeel_applies_only_its_group(tmp_path):
    cfg = write_cfg(tmp_path, "[veloscroll]\nNAME_MATCH = TestMouse\nMIN_RATE = 8.0\n"
                              "MAX_RATE = 200.0\nCURVE = 0.9\nOUT_SMOOTH = 0.5\n")
    assert run(cfg, "save", "fast").returncode == 0
    cfg.write_text("[veloscroll]\nNAME_MATCH = TestMouse\nMIN_RATE = 8.0\n"
                   "MAX_RATE = 200.0\nCURVE = 0.3\nOUT_SMOOTH = 0.5\n", encoding="utf-8")
    r = run(cfg, "loadfeel", "fast")
    assert r.returncode == 0, r.stdout + r.stderr
    assert f"applied preset 'fast' (loadfeel) to {cfg}" in r.stdout
    assert "CURVE: 0.3 -> 0.9" in r.stdout
    assert "MIN_RATE:" not in r.stdout            # unchanged feel keys produce no change lines
    assert f"that loadfeel does not apply:" in r.stdout   # note about the other groups' keys
    assert "backup     : " in r.stdout
    assert r.stdout.rstrip().endswith("the daemon applies the change within ~2 s — verify with: journalctl -u veloscroll")
    new_text = cfg.read_text(encoding="utf-8")
    assert "CURVE = 0.9" in new_text              # line rewritten in place
    assert "NAME_MATCH = TestMouse" in new_text   # group boundary respected
    baks = [f for f in os.listdir(os.path.dirname(str(cfg))) if BAK_RE.match(f) and f.startswith("config.ini.bak-")]
    assert len(baks) == 1


def test_load_missing_preset_fails_and_leaves_config_untouched(tmp_path):
    cfg = write_cfg(tmp_path)
    before = cfg.read_text(encoding="utf-8")
    r = run(cfg, "loadfeel", "nosuch")
    assert r.returncode == 1
    p = os.path.join(preset_dir(cfg), "nosuch.ini")
    assert f"veloscroll-preset: no preset named 'nosuch' at {p} (see `veloscroll_preset.py list`)" in r.stderr
    assert cfg.read_text(encoding="utf-8") == before


def test_list_empty_then_table(tmp_path):
    cfg = write_cfg(tmp_path)
    d = preset_dir(cfg)
    r = run(cfg, "list")
    assert r.returncode == 0
    assert f"no presets found in {d} (create one with `veloscroll_preset.py save <name>`)" in r.stdout

    assert run(cfg, "save", "alpha").returncode == 0
    cfg.write_text(BASE_CFG.replace("CURVE = 0.7", "CURVE = 0.8"), encoding="utf-8")
    assert run(cfg, "save", "beta").returncode == 0

    r = run(cfg, "list")
    assert r.returncode == 0, r.stdout + r.stderr
    lines = r.stdout.splitlines()
    ia = next(i for i, l in enumerate(lines) if re.match(r"^alpha\b", l))
    ib = next(i for i, l in enumerate(lines) if re.match(r"^beta\b", l))
    assert ia < ib                                # sorted by name
    assert "(absent = not captured" in r.stdout


def test_backups_empty_then_newest_first(tmp_path):
    cfg = write_cfg(tmp_path)
    r = run(cfg, "backups")
    assert r.returncode == 0
    assert "no backups found (created automatically before every overwrite by the save / load commands)" in r.stdout

    # two config backups via two real applies
    assert run(cfg, "save", "fast").returncode == 0
    cfg.write_text(BASE_CFG.replace("CURVE = 0.7", "CURVE = 0.6"), encoding="utf-8")
    r1 = run(cfg, "loadfeel", "fast")
    b1 = [l.split("backup     : ", 1)[1].strip() for l in r1.stdout.splitlines() if l.startswith("backup     : ")][0]
    cfg.write_text(BASE_CFG.replace("CURVE = 0.7", "CURVE = 0.5"), encoding="utf-8")
    r2 = run(cfg, "loadfeel", "fast")
    b2 = [l.split("backup     : ", 1)[1].strip() for l in r2.stdout.splitlines() if l.startswith("backup     : ")][0]
    assert os.path.isfile(b1) and os.path.isfile(b2) and b1 != b2

    r = run(cfg, "backups")
    assert r.returncode == 0, r.stdout + r.stderr
    lines = r.stdout.splitlines()
    ib1 = next(i for i, l in enumerate(lines) if os.path.basename(b1) in l)
    ib2 = next(i for i, l in enumerate(lines) if os.path.basename(b2) in l)
    assert ib2 < ib1                              # newest first


def test_restore_default_newest_and_bad_ref(tmp_path):
    cfg = write_cfg(tmp_path)
    assert run(cfg, "save", "fast").returncode == 0
    cfg.write_text(BASE_CFG.replace("CURVE = 0.7", "CURVE = 0.6"), encoding="utf-8")
    r1 = run(cfg, "loadfeel", "fast")             # applies CURVE 0.6->0.7; backup B1 is the PRE-apply state (CURVE = 0.6)
    b1 = [l.split("backup     : ", 1)[1].strip() for l in r1.stdout.splitlines() if l.startswith("backup     : ")][0]
    assert "CURVE: 0.6 -> 0.7" in r1.stdout
    cfg.write_text(BASE_CFG.replace("CURVE = 0.7", "CURVE = 0.5"), encoding="utf-8")

    r = run(cfg, "restore")                       # default: newest config backup (B1) — rolls back to the pre-apply state
    assert r.returncode == 0, r.stdout + r.stderr
    assert f"restored {cfg} from {b1}" in r.stdout
    assert "backup of previous state:" in r.stdout
    assert "CURVE = 0.6" in cfg.read_text(encoding="utf-8")

    r = run(cfg, "restore", "nope.bak-20260101-000000000000")
    assert r.returncode == 1
    assert "veloscroll-preset: no backup named 'nope.bak-20260101-000000000000' (see `veloscroll_preset.py backups`)" in r.stderr


# ---------------- MAX_BACKUPS: never part of presets; 0 disables backups ----------------

def test_save_never_captures_max_backups(tmp_path):
    cfg = write_cfg(tmp_path, "[veloscroll]\nNAME_MATCH = TestMouse\nCURVE = 0.7\nMAX_BACKUPS = -1\n")
    r = run(cfg, "save", "fast")
    assert r.returncode == 0, r.stdout + r.stderr
    body = open(os.path.join(preset_dir(cfg), "fast.ini"), encoding="utf-8").read()
    assert not re.search(r"^MAX_BACKUPS\s*=", body, re.M)   # no MAX_BACKUPS assignment line — backup policy is per-machine (the header comment may name it)


def test_load_warns_and_ignores_max_backups_in_preset(tmp_path):
    cfg = write_cfg(tmp_path)             # no MAX_BACKUPS line -> the code default (5) applies
    d = preset_dir(cfg)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "fast.ini"), "w", encoding="utf-8") as f:      # hand-edited preset containing the key (even an invalid value must not fail the load — it is never applied or validated)
        f.write("[veloscroll]\nCURVE = 0.9\nMAX_BACKUPS = -2\n")

    r = run(cfg, "loadfeel", "fast")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "warning: MAX_BACKUPS" in r.stderr and "ignored" in r.stderr      # warn-and-ignore line on every load command
    assert "use  to apply them" not in r.stdout                              # no broken empty covering-command hint
    new_text = cfg.read_text(encoding="utf-8")
    assert "CURVE: 0.7 -> 0.9" in r.stdout and "CURVE = 0.9" in new_text     # the group itself applies normally
    assert "MAX_BACKUPS" not in new_text                                     # never rewritten into config.ini

    r_all = run(cfg, "loadall", "fast")                                       # loadall warns too (and is a no-op here: CURVE already matches)
    assert r_all.returncode == 0, r_all.stdout + r_all.stderr
    assert "warning: MAX_BACKUPS" in r_all.stderr


def test_list_has_no_max_backups_column(tmp_path):
    cfg = write_cfg(tmp_path)
    assert run(cfg, "save", "fast").returncode == 0
    r = run(cfg, "list")
    assert r.returncode == 0, r.stdout + r.stderr
    header = next(l for l in r.stdout.splitlines() if l.startswith("preset"))
    assert "MAX_BACKUPS" not in header


def test_max_backups_zero_writes_no_backups(tmp_path):
    cfg = write_cfg(tmp_path, "[veloscroll]\nNAME_MATCH = TestMouse\nCURVE = 0.7\nMAX_BACKUPS = 0\n")
    assert run(cfg, "save", "fast").returncode == 0

    # save-overwrite: the preset file is rewritten, but no .bak-* file and no backup line
    cfg.write_text("[veloscroll]\nNAME_MATCH = TestMouse\nCURVE = 0.9\nMAX_BACKUPS = 0\n", encoding="utf-8")
    r = run(cfg, "save", "fast")
    assert r.returncode == 0, r.stdout + r.stderr
    assert f"saved {os.path.join(preset_dir(cfg), 'fast.ini')} (" in r.stdout
    assert "backup     : " not in r.stdout
    assert [f for f in os.listdir(preset_dir(cfg)) if BAK_RE.match(f)] == []

    # change-producing load: the config change is applied, but no backup file or line either
    cfg.write_text("[veloscroll]\nNAME_MATCH = TestMouse\nCURVE = 0.3\nMAX_BACKUPS = 0\n", encoding="utf-8")
    r2 = run(cfg, "loadfeel", "fast")
    assert r2.returncode == 0, r2.stdout + r2.stderr
    assert "CURVE: 0.3 -> 0.9" in r2.stdout
    assert "backup     : " not in r2.stdout
    new_text = cfg.read_text(encoding="utf-8")
    assert "CURVE = 0.9" in new_text and "MAX_BACKUPS = 0" in new_text   # the MAX_BACKUPS line is never touched by a load
    assert [f for f in os.listdir(os.path.dirname(str(cfg))) if BAK_RE.match(f) and f.startswith("config.ini.bak-")] == []


def test_usage_errors(tmp_path):
    cfg = write_cfg(tmp_path)
    r = run(cfg, "list", "extra")
    assert r.returncode == 1 and "`list` takes no arguments — run it alone" in r.stderr

    r = run(cfg, "frobnicate", "x")
    assert r.returncode == 1 and "unknown command 'frobnicate'" in r.stderr

    r = run(cfg, "save")                          # odd number of ops
    assert r.returncode == 1 and "expected pairs of `COMMAND NAME`" in r.stderr


def test_failure_stops_remaining_ops(tmp_path):
    cfg = write_cfg(tmp_path)
    r = run(cfg, "loadfeel", "nosuch", "save", "okname")
    assert r.returncode == 1
    assert "no preset named 'nosuch'" in r.stderr
    assert not os.path.exists(os.path.join(preset_dir(cfg), "okname.ini"))
