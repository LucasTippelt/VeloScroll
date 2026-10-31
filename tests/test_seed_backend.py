"""Unit tier: veloscroll_seed backend functions (KdePlasmaBackend + discovery), no subprocesses.

D-Bus is faked at the subprocess.run / shutil.which level; kcminputrc lives in a tmp XDG_CONFIG_HOME.
The `backend` fixture removes DBUS_SESSION_BUS_ADDRESS so _live_apply takes its skip path unless a test
sets it up deliberately via the harness below."""
import configparser
import os
from types import SimpleNamespace

import pytest

import veloscroll_seed as vsd


def _fake_real_device():
    return vsd.RealDevice(name="Logitech PRO X", vendor=0x46d, product=0x4093, version=1, node="/dev/input/event7")


# ---------------- _usb_ids ----------------

@pytest.mark.parametrize("raw,want", [
    ("3/46d/4093/1", (0x46d, 0x4093, 1)),
    ("3/1234/5678/2", (0x1234, 0x5678, 2)),
])
def test_usb_ids_valid(vsd_module, raw, want):
    assert vsd._usb_ids(raw) == want


@pytest.mark.parametrize("raw", [
    "",                    # empty
    "3/46d/4093",          # three parts
    "3/46d/4093/1/x",      # five parts
    "1/46d/4093/1",        # not the USB bus (BUS_USB = 3)
    "3/0/4093/1",          # zero vendor
    "3/46d/0/1",           # zero product
    "3/z/4093/1",          # non-hex
])
def test_usb_ids_rejects(vsd_module, raw):
    assert vsd._usb_ids(raw) is None


# ---------------- discover_real_mouse ----------------

@pytest.fixture(autouse=True)
def _xdg(tmp_path, monkeypatch):
    """Point kcminputrc at a tmp dir for every seed test (the module fallback would hit the real home), and remove
    the D-Bus session bus env so live-apply never touches a real running session."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("DBUS_SESSION_BUS_ADDRESS", raising=False)


def _cand(name, node="/dev/input/event7", usb=(0x46d, 0xc084, 1), rel=True):
    return vsd._Candidate(name=name, node=node, usb=usb, rel=rel)


def test_discover_no_match(vsd_module, monkeypatch):
    monkeypatch.setattr(vsd, "_scan_devices", lambda: [_cand("Some Other Mouse", usb=(0x1234, 0x5678, 1))])
    with pytest.raises(vsd.SeedError) as exc:
        vsd.discover_real_mouse((0x46d, 0xc084), "Fallback")
    assert "no matching real mouse found" in str(exc.value)


def test_discover_multiple_without_group_lists_names(vsd_module, monkeypatch):
    devs = [_cand("Mouse A", node="/dev/input/event1"), _cand("Mouse B", node="/dev/input/event2")]
    monkeypatch.setattr(vsd, "_scan_devices", lambda: devs)
    with pytest.raises(vsd.SeedError) as exc:
        vsd.discover_real_mouse((0x46d, 0xc084), "Fallback")
    msg = str(exc.value)
    assert "multiple candidate devices found" in msg
    assert "Mouse A" in msg and "Mouse B" in msg


def test_discover_tiebreak_prefers_existing_kcminput_group(vsd_module, monkeypatch, tmp_path):
    a = _cand("Logitech PRO X", node="/dev/input/event1")
    b = _cand("Logitech PRO X Clone", node="/dev/input/event2")   # same USB IDs as A
    monkeypatch.setattr(vsd, "_scan_devices", lambda: [a, b])
    (tmp_path / "kcminputrc").write_text(   # group keyed by the candidates' own IDs (default usb = 0x46d:0xc084)
        "[Libinput][1133][49284][Logitech PRO X]\nPointerAcceleration=-0.4\n", encoding="utf-8")
    real = vsd.discover_real_mouse((0x46d, 0xc084), "Fallback")
    assert real.name == "Logitech PRO X" and real.node == "/dev/input/event1"


def test_discover_single_without_usb_ids(vsd_module, monkeypatch):
    # e.g. a Bluetooth mouse: name matches but no USB vendor/product to key kcminputrc by
    monkeypatch.setattr(vsd, "_scan_devices", lambda: [_cand("Fallback", usb=None)])
    with pytest.raises(vsd.SeedError) as exc:
        vsd.discover_real_mouse(None, "Fallback")
    assert "reports no USB vendor/product" in str(exc.value)


def test_discover_happy_path_fields(vsd_module, monkeypatch):
    monkeypatch.setattr(vsd, "_scan_devices", lambda: [_cand("Logitech PRO X")])
    real = vsd.discover_real_mouse(None, "PRO X")
    assert (real.name, real.vendor, real.product, real.version, real.node) == \
        ("Logitech PRO X", 0x46d, 0xc084, 1, "/dev/input/event7")   # _cand's default USB ID set
    assert real.ids_hex == "0x46d:0xc084"


def test_discover_name_override_skips_id_matching(vsd_module, monkeypatch):
    dev = _cand("My Fancy Mouse", usb=(0x1234, 0x5678, 2), node="/dev/input/event9")
    monkeypatch.setattr(vsd, "_scan_devices", lambda: [dev])
    real = vsd.discover_real_mouse((0x46d, 0xc084), "Fallback", name_override="fancy")
    assert (real.vendor, real.product) == (0x1234, 0x5678)


def test_discover_excludes_veloscroll_named_devices(vsd_module, monkeypatch):
    # the virtual device itself must never be a candidate
    monkeypatch.setattr(vsd, "_scan_devices", lambda: [_cand("veloscroll-mouse")])
    with pytest.raises(vsd.SeedError):
        vsd.discover_real_mouse(None, "Fallback")


# ---------------- KdePlasmaBackend.seed ----------------

SRC = "[Libinput][1133][16531][Logitech PRO X]\n" \
      "Enabled=true\nPointerAcceleration=-0.4\nScrollFactor=1.5\n"
TARGET_SEC = "Libinput][1133][16531][veloscroll-mouse"     # as cp.sections() reports it (no trailing bracket)


def test_seed_no_file_system_defaults(backend, tmp_path):
    rep = backend.seed(_fake_real_device(), "veloscroll-mouse", 5)
    assert "will use system defaults" in rep.message
    assert rep.target_section is None and rep.changes == [] and rep.backup_path is None
    assert rep.live_notes == []     # early return — live apply never attempted


def test_seed_source_group_missing_system_defaults(backend, tmp_path):
    (tmp_path / "kcminputrc").write_text("[KDE]\nSomeKey=1\n", encoding="utf-8")
    before = (tmp_path / "kcminputrc").read_bytes()
    rep = backend.seed(_fake_real_device(), "veloscroll-mouse", 5)
    assert "will use system defaults" in rep.message
    assert (tmp_path / "kcminputrc").read_bytes() == before      # untouched


def test_seed_copies_group_excluding_enabled_with_backup(backend, tmp_path):
    path = tmp_path / "kcminputrc"
    path.write_text(SRC, encoding="utf-8")
    rep = backend.seed(_fake_real_device(), "veloscroll-mouse", 5)

    assert rep.message == f"seeded {TARGET_SEC} from Libinput][1133][16531][Logitech PRO X"   # _libinput_section has no trailing bracket
    keys = [k for k, _o, _n in rep.changes]
    assert "PointerAcceleration" in keys and "ScrollFactor" in keys
    assert "Enabled" not in keys                                  # a disabled real mouse must not disable the virtual one
    assert rep.backup_path is not None and os.path.exists(rep.backup_path)
    assert os.path.basename(rep.backup_path).startswith("kcminputrc.bak-")

    cp = configparser.ConfigParser(interpolation=None); cp.optionxform = str
    with open(path, encoding="utf-8") as f:
        cp.read_file(f)
    tgt = cp[TARGET_SEC]
    assert tgt["PointerAcceleration"] == "-0.4" and tgt["ScrollFactor"] == "1.5"
    assert "Enabled" not in tgt


def test_seed_idempotent_second_run_no_changes_no_backup(backend, tmp_path):
    path = tmp_path / "kcminputrc"
    path.write_text(SRC, encoding="utf-8")
    backend.seed(_fake_real_device(), "veloscroll-mouse", 5)
    baks_after_first = [f for f in os.listdir(tmp_path) if f.startswith("kcminputrc.bak-")]

    rep2 = backend.seed(_fake_real_device(), "veloscroll-mouse", 5)
    assert "already matches" in rep2.message
    assert rep2.changes == [] and rep2.backup_path is None
    assert [f for f in os.listdir(tmp_path) if f.startswith("kcminputrc.bak-")] == baks_after_first


def test_seed_overwrite_removes_stale_target_keys(backend, tmp_path):
    path = tmp_path / "kcminputrc"
    path.write_text(SRC + "\n[Libinput][1133][16531][veloscroll-mouse]\n"
                          "PointerAcceleration=-0.2\nTapToClick=true\n", encoding="utf-8")
    rep = backend.seed(_fake_real_device(), "veloscroll-mouse", 5)

    changes = {k: (o, n) for k, o, n in rep.changes}
    assert changes["PointerAcceleration"] == ("-0.2", "-0.4")
    assert changes["ScrollFactor"] == (None, "1.5")
    assert changes["TapToClick"] == ("true", None)               # stale key removed

    cp = configparser.ConfigParser(interpolation=None); cp.optionxform = str
    with open(path, encoding="utf-8") as f:
        cp.read_file(f)
    assert "TapToClick" not in cp[TARGET_SEC]


def test_seed_prunes_old_backups(backend, tmp_path):
    path = tmp_path / "kcminputrc"
    path.write_text(SRC, encoding="utf-8")
    for i in range(3):   # three old backups (fixed-width ts sort lexicographically == chronologically)
        with open(str(path) + f".bak-2025010{i+1}-103000", "w") as f:
            f.write("old\n")
    rep = backend.seed(_fake_real_device(), "veloscroll-mouse", 2)   # keep only the newest two

    left = sorted(f for f in os.listdir(tmp_path) if f.startswith("kcminputrc.bak-"))
    assert len(left) == 2                       # the new one + the newest old one survive
    assert len(rep.pruned) == 2 and all(n.startswith("kcminputrc.bak-") for n in rep.pruned)


def test_seed_prune_zero_is_noop(vsd_module, tmp_path):
    """MAX_BACKUPS = 0: pruning is a no-op (existing .bak-* files stay untouched); only < -1 / non-int raise."""
    path = tmp_path / "kcminputrc"
    path.write_text("[s]\nk=v\n")
    with open(str(path) + ".bak-20250101-103000", "w") as f:
        f.write("old\n")
    assert vsd._prune_backups(str(path), 0) == []
    assert sorted(f for f in os.listdir(tmp_path) if f.startswith("kcminputrc.bak-")) == ["kcminputrc.bak-20250101-103000"]
    with pytest.raises(vsd.SeedError):
        vsd._prune_backups(str(path), -2)


def test_seed_disabled_backups_writes_nothing(backend, tmp_path):
    """MAX_BACKUPS = 0: the seed still happens, but no .bak-* file is written and pre-existing ones stay untouched."""
    path = tmp_path / "kcminputrc"
    path.write_text(SRC, encoding="utf-8")
    with open(str(path) + ".bak-20250101-103000", "w") as f:      # pre-existing backup must survive
        f.write("old\n")
    rep = backend.seed(_fake_real_device(), "veloscroll-mouse", 0)

    assert rep.backup_path is None and rep.pruned == []           # nothing written or deleted
    left = sorted(f for f in os.listdir(tmp_path) if f.startswith("kcminputrc.bak-"))
    assert left == ["kcminputrc.bak-20250101-103000"]             # pre-existing backup untouched (non-destructive)

    cp = configparser.ConfigParser(interpolation=None); cp.optionxform = str
    with open(path, encoding="utf-8") as f:
        cp.read_file(f)
    assert TARGET_SEC in cp.sections()                            # the seed itself still happened


def test_remove_stale_disabled_backups_writes_nothing(backend, tmp_path):
    """MAX_BACKUPS = 0: stale groups are still removed, but no .bak-* file is written and pre-existing ones stay untouched."""
    path = tmp_path / "kcminputrc"
    path.write_text(SRC + "\n[Libinput][9][9][veloscroll-mouse]\nPointerAcceleration=0.1\n"
                      f"\n[{TARGET_SEC}]\nPointerAcceleration=-0.4\n", encoding="utf-8")
    with open(str(path) + ".bak-20250101-103000", "w") as f:      # pre-existing backup must survive
        f.write("old\n")
    rep = backend.remove_stale(_fake_real_device(), "veloscroll-mouse", 0)

    assert "removed 1 stale veloscroll-mouse group(s)" in rep.message   # the cleanup itself still happened
    assert rep.backup_path is None and rep.pruned == []
    left = sorted(f for f in os.listdir(tmp_path) if f.startswith("kcminputrc.bak-"))
    assert left == ["kcminputrc.bak-20250101-103000"]


def test_seed_live_apply_skip_note_without_dbus(backend, tmp_path):
    (tmp_path / "kcminputrc").write_text(SRC, encoding="utf-8")
    rep = backend.seed(_fake_real_device(), "veloscroll-mouse", 5)   # `backend` fixture removed the env var
    assert len(rep.live_notes) == 1
    assert rep.live_notes[0].startswith("no D-Bus session bus — live apply skipped")


# ---------------- KdePlasmaBackend.apply_only ----------------

def test_apply_only_no_file(backend, tmp_path):
    with pytest.raises(vsd.SeedError) as exc:
        backend.apply_only(_fake_real_device(), "veloscroll-mouse")
    assert "nothing to apply" in str(exc.value) and "run without --apply-only first" in str(exc.value)


def test_apply_only_missing_target_group(backend, tmp_path):
    (tmp_path / "kcminputrc").write_text(SRC, encoding="utf-8")     # only the real mouse's group exists
    with pytest.raises(vsd.SeedError) as exc:
        backend.apply_only(_fake_real_device(), "veloscroll-mouse")
    assert "run without --apply-only first to create it" in str(exc.value)


def test_apply_only_success_leaves_file_untouched(backend, tmp_path):
    path = tmp_path / "kcminputrc"
    content = SRC + "\n[Libinput][1133][16531][veloscroll-mouse]\nPointerAcceleration=-0.9\n"
    path.write_text(content, encoding="utf-8")
    rep = backend.apply_only(_fake_real_device(), "veloscroll-mouse")
    assert "(no file changes)" in rep.message
    assert path.read_bytes() == content.encode("utf-8")
    assert len(rep.live_notes) == 1 and rep.live_notes[0].startswith("no D-Bus session bus")


# ---------------- KdePlasmaBackend.remove_stale ----------------

def test_remove_stale_no_file(backend, tmp_path):
    rep = backend.remove_stale(_fake_real_device(), "veloscroll-mouse", 5)
    assert "nothing to remove" in rep.message


def test_remove_stale_none_found_touches_nothing(backend, tmp_path):
    path = tmp_path / "kcminputrc"
    content = SRC + "\n[Libinput][1133][49284][Some Other Mouse]\nPointerAcceleration=0.5\n" \
                  + f"\n[{TARGET_SEC}]\nPointerAcceleration=-0.4\n"
    path.write_text(content, encoding="utf-8")
    before = path.read_bytes()
    rep = backend.remove_stale(_fake_real_device(), "veloscroll-mouse", 5)
    assert "no stale veloscroll-mouse groups found" in rep.message
    assert rep.backup_path is None and path.read_bytes() == before


def test_remove_stale_deletes_only_old_id_groups(backend, tmp_path):
    path = tmp_path / "kcminputrc"
    path.write_text(SRC + "\n[Libinput][9][9][veloscroll-mouse]\nPointerAcceleration=0.1\n"
                          f"\n[{TARGET_SEC}]\nPointerAcceleration=-0.4\n", encoding="utf-8")
    rep = backend.remove_stale(_fake_real_device(), "veloscroll-mouse", 5)

    assert "removed 1 stale veloscroll-mouse group(s)" in rep.message
    assert "[Libinput][9][9][veloscroll-mouse]" in rep.message     # sorted listing, bracketed
    assert rep.backup_path is not None and os.path.exists(rep.backup_path)

    cp = configparser.ConfigParser(interpolation=None); cp.optionxform = str
    with open(path, encoding="utf-8") as f:
        cp.read_file(f)
    assert "Libinput][9][9][veloscroll-mouse" not in cp.sections()
    assert TARGET_SEC in cp.sections()                            # the live group survives
    assert "Libinput][1133][16531][Logitech PRO X" in cp.sections()


# ---------------- _live_apply (D-Bus faked at subprocess level) ----------------

def _dbus_harness(monkeypatch, tmp_path, virtual_name="veloscroll-mouse", dbus_name=None, fail_prop=None):
    """Fake sysfs node + busctl. The sysfs device always advertises `virtual_name` (so the node is found);
    `dbus_name` lets a test make KWin report a different name for that object path; `fail_prop` makes one
    property Set fail with 'Access denied'."""
    evdir = tmp_path / "sys" / "event9"
    (evdir / "device").mkdir(parents=True)
    (evdir / "device" / "name").write_text(virtual_name + "\n", encoding="utf-8")

    monkeypatch.setattr(vsd.glob, "glob", lambda pattern: [str(evdir)] if "/sys/class/input/event*" in pattern else [])
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:path=/fake/bus")
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/busctl" if name == "busctl" else None)

    sets = []

    def fake_run(argv, **kw):
        argv = list(argv)
        if argv[2] == "get-property":      # [busctl, --user, get-property, service, path, iface, prop]
            prop = argv[-1]
            out = {
                "name": f's "{dbus_name or virtual_name}"',
                "supportsScrollEdge": "b true",
                "supportsScrollTwoFinger": "b true",
                "supportsScrollOnButtonDown": "b true",
            }.get(prop, 's ""')
            return SimpleNamespace(returncode=0, stdout=out + "\n", stderr="")
        # [busctl, --user, call, service, path, dbus-iface, Set, ssv, kwin-iface, prop, typ, --, value]
        sets.append((argv[9], argv[10], argv[12]))
        if fail_prop is not None and argv[9] == fail_prop:
            return SimpleNamespace(returncode=1, stdout="", stderr="Access denied")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)
    return sets


FULL_OPTIONS = [
    ("PointerAcceleration", "-0.4"),
    ("PointerAccelerationProfile", "2"),
    ("ScrollFactor", "1.5"),
    ("MiddleButtonEmulation", "true"),
    ("NaturalScroll", "false"),
    ("LeftHanded", "true"),
    ("ScrollMethod", "3"),
    ("ScrollButton", "276"),
]


def test_live_apply_full_property_sequence(backend, monkeypatch, tmp_path):
    sets = _dbus_harness(monkeypatch, tmp_path)
    notes = backend._live_apply("veloscroll-mouse", FULL_OPTIONS)

    assert sets == [
        ("pointerAcceleration", "d", "-0.4"),
        ("pointerAccelerationProfileAdaptive", "b", "true"),     # profile 2: adaptive first, then flat false
        ("pointerAccelerationProfileFlat", "b", "false"),
        ("scrollFactor", "d", "1.5"),
        ("middleEmulation", "b", "true"),
        ("naturalScroll", "b", "false"),
        ("leftHanded", "b", "true"),
        ("scrollEdge", "b", "false"),                            # ScrollMethod=3: all supported methods reconciled...
        ("scrollTwoFinger", "b", "false"),
        ("scrollOnButtonDown", "b", "true"),                     # ...and the button for method 3
        ("scrollButton", "u", "276"),
    ]
    assert len(notes) == 1 and notes[0].startswith("applied live via KWin: ")
    assert "pointerAcceleration=-0.4" in notes[0] and "scrollOnButtonDown=true" in notes[0]


def test_live_apply_profile_one_sets_flat(backend, monkeypatch, tmp_path):
    sets = _dbus_harness(monkeypatch, tmp_path)
    backend._live_apply("veloscroll-mouse", [("PointerAccelerationProfile", "1")])
    assert sets == [
        ("pointerAccelerationProfileFlat", "b", "true"),         # profile 1: flat first, then adaptive false
        ("pointerAccelerationProfileAdaptive", "b", "false"),
    ]


def test_live_apply_unknown_scroll_method_is_file_only(backend, monkeypatch, tmp_path):
    sets = _dbus_harness(monkeypatch, tmp_path)
    notes = backend._live_apply("veloscroll-mouse", [("ScrollMethod", "7")])
    assert sets == [] and notes == []


def test_live_apply_failed_set_reported_but_value_saved(backend, monkeypatch, tmp_path):
    sets = _dbus_harness(monkeypatch, tmp_path, fail_prop="pointerAcceleration")
    notes = backend._live_apply("veloscroll-mouse", FULL_OPTIONS)

    assert ("pointerAcceleration", "d", "-0.4") in sets          # the call was still made...
    failed = [n for n in notes if n.startswith("LIVE APPLY FAILED")]
    assert len(failed) == 1
    assert failed[0] == "LIVE APPLY FAILED — pointerAcceleration: Access denied (the value is still saved to kcminputrc)"
    applied = [n for n in notes if n.startswith("applied live via KWin")]
    assert len(applied) == 1 and "pointerAcceleration=" not in applied[0]


def test_live_apply_no_dbus_env(backend):
    # `backend` fixture already removed the env var; which() result is irrelevant (checked after)
    notes = backend._live_apply("veloscroll-mouse", FULL_OPTIONS)
    assert notes == ["no D-Bus session bus — live apply skipped; the settings take effect when the device next registers (or after re-login)"]


def test_live_apply_busctl_missing(backend, monkeypatch):
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:path=/fake/bus")
    monkeypatch.setattr("shutil.which", lambda name: None)
    notes = backend._live_apply("veloscroll-mouse", FULL_OPTIONS)
    assert notes == ["busctl not found — live apply skipped; the settings are in kcminputrc only"]


def test_live_apply_device_not_registered(backend, monkeypatch):
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:path=/fake/bus")
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/busctl" if name == "busctl" else None)
    monkeypatch.setattr(vsd.glob, "glob", lambda pattern: [])     # no sysfs event dir at all
    notes = backend._live_apply("veloscroll-mouse", FULL_OPTIONS)
    assert notes == ["veloscroll-mouse not registered with KWin (is veloscroll running?) — live apply skipped; re-run after starting it"]


def test_live_apply_name_mismatch(backend, monkeypatch, tmp_path):
    _dbus_harness(monkeypatch, tmp_path, dbus_name="some-other-device")   # sysfs says one name, KWin reports another
    notes = backend._live_apply("veloscroll-mouse", FULL_OPTIONS)
    assert notes == ["veloscroll-mouse not found among KWin's input devices — live apply skipped; the settings are in kcminputrc only"]


# ---------------- main() (in-process CLI) ----------------

def test_main_refuses_root(monkeypatch, capsys):
    monkeypatch.setattr("os.geteuid", lambda: 0)
    rc = vsd.main([])
    assert rc == 1
    assert "refusing to run as root" in capsys.readouterr().err


def test_main_unsupported_de_wm(vsd_module, veloscroll_module, monkeypatch, capsys):
    monkeypatch.setattr(vsd, "discover_real_mouse", lambda *a, **k: _fake_real_device())
    monkeypatch.setattr(veloscroll_module, "DE_WM", "gnome")
    rc = vsd.main([])
    err = capsys.readouterr().err
    assert rc == 1 and "unsupported DE_WM 'gnome'" in err and "'kde-plasma'" in err


def test_main_seed_run_prints_report(vsd_module, veloscroll_module, monkeypatch, tmp_path, capsys):
    (tmp_path / "kcminputrc").write_text(SRC, encoding="utf-8")
    monkeypatch.setattr(vsd, "discover_real_mouse", lambda *a, **k: _fake_real_device())

    rc = vsd.main([])
    out = capsys.readouterr().out
    assert rc == 0
    assert "real mouse : Logitech PRO X (0x46d:0x4093) at /dev/input/event7" in out   # _fake_real_device's IDs, matching the [1133][16531] source group
    assert f"{TARGET_SEC}:" in out                       # section header as cp.sections() renders it
    assert "PointerAcceleration: (none) -> -0.4" in out
    assert "backup     : " in out
    assert "live       : no D-Bus session bus — live apply skipped" in out


def test_main_name_override_no_kcminputrc(vsd_module, monkeypatch, tmp_path, capsys):
    dev = vsd._Candidate(name="My Fancy Mouse", node="/dev/input/event7", usb=(0x1234, 0x5678, 2), rel=True)
    monkeypatch.setattr(vsd, "_scan_devices", lambda: [dev])   # no kcminputrc in the tmp XDG dir

    rc = vsd.main(["--name", "fancy"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "real mouse : My Fancy Mouse (0x1234:0x5678) at /dev/input/event7" in out
    assert "no per-device settings for My Fancy Mouse in kcminputrc — veloscroll-mouse will use system defaults" in out


def test_main_discovery_failure_exits_one(vsd_module, monkeypatch, capsys):
    monkeypatch.setattr(vsd, "_scan_devices", lambda: [])
    rc = vsd.main([])
    err = capsys.readouterr().err
    assert rc == 1 and "no matching real mouse found" in err
