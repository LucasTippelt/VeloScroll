"""E2E hot-reload: run the real daemon as a subprocess with NAME_MATCH set to a name
that matches no device (so it never grabs anything or creates a virtual mouse), and
drive config.ini through every reload outcome while watching its log.

Covers: startup report, live change, rejected parse (logged once, not retried until
the file changes again), fix after rejection, missing-file notice (once), and
recreate-after-delete."""
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DAEMON = os.path.join(ROOT, "veloscroll.py")

RELOAD_MARKERS = ("config reloaded:", "config reload rejected", "config file missing")


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return ""


def wait_for(log_path, needle, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        text = _read(log_path)
        if needle in text:
            return text
        time.sleep(0.1)
    raise AssertionError(f"{needle!r} not found within {timeout}s; log tail:\n{_read(log_path)[-2000:]}")


def reload_lines(text):
    return [l for l in text.splitlines() if any(m in l for m in RELOAD_MARKERS)]


class Daemon:
    def __init__(self, cfg_path, log_path):
        self.cfg = cfg_path
        self.log = log_path
        env = os.environ.copy()
        env["VELOSCROLL_CONFIG"] = str(cfg_path)
        out = open(log_path, "w", encoding="utf-8")
        self.proc = subprocess.Popen([sys.executable, DAEMON], stdout=out, stderr=subprocess.STDOUT, env=env)

    def write_cfg(self, text):
        with open(self.cfg, "w", encoding="utf-8") as f:
            f.write(text)

    def remove_cfg(self):
        os.remove(self.cfg)

    def assert_no_reload_activity(self, seconds=4.5):
        """Two full scan cycles pass without any new reload/reject/missing line."""
        before = len(reload_lines(_read(self.log)))
        time.sleep(seconds)
        after = reload_lines(_read(self.log))
        assert len(after) == before, f"unexpected reload activity:\n" + "\n".join(after[before:])

    def stop(self):
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=5)


def test_hot_reload_lifecycle(tmp_path):
    cfg = tmp_path / "config.ini"
    log = tmp_path / "daemon.log"
    d = Daemon(cfg, log)
    try:
        # Phase 1 — startup with one override.
        d.write_cfg("[veloscroll]\nNAME_MATCH = ZzNoSuchMouse\n")
        wait_for(log, f"config loaded from {cfg} (1 override(s))")

        # Phase 2 — live change applies within a couple of scan cycles.
        d.write_cfg("[veloscroll]\nNAME_MATCH = ZzNoSuchMouse\nCURVE = 0.6\n")
        wait_for(log, "config reloaded: CURVE 0.5->0.6")

        # Phase 3 — malformed parse is rejected and NOT retried while the file stays put.
        d.write_cfg("[veloscroll]\nNAME_MATCH = ZzNoSuchMouse\nCURVE = abc\n")
        wait_for(log, "config reload rejected, keeping current values:")
        assert f"CURVE in {cfg}: expected a number (got 'abc')" in _read(log)
        d.assert_no_reload_activity()

        # Phase 4 — fixing the file re-triggers the check; the old value is still in effect.
        d.write_cfg("[veloscroll]\nNAME_MATCH = ZzNoSuchMouse\nCURVE = 0.7\n")
        wait_for(log, "config reloaded: CURVE 0.6->0.7")

        # Phase 5 — deleting the file is noticed once; values are kept, no repeat notices.
        d.remove_cfg()
        wait_for(log, "config file missing — keeping current values")
        d.assert_no_reload_activity()

        # Phase 6 — recreating the file resumes normal reloads from the kept value.
        d.write_cfg("[veloscroll]\nNAME_MATCH = ZzNoSuchMouse\nCURVE = 0.8\n")
        wait_for(log, "config reloaded: CURVE 0.7->0.8")

        text = _read(log)
        assert reload_lines(text).count("config file missing — keeping current values") == 1
    finally:
        d.stop()
    assert d.proc.returncode is not None
