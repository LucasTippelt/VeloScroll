# Updating VeloScroll

There is no automatic update mechanism. When a new version is released, you have to fetch it yourself and restart the daemon.

Your `/etc/veloscroll/config.ini` lives outside the repo and is left untouched by an update. Unknown keys are ignored with a warning, and removed keys fall back to built-in defaults. This is also why all configuration belongs in `config.ini`: local edits to `veloscroll.py` are lost or conflict on every update (see [Customize and reload](CONFIGURATION.md#customize-and-reload)).

---

## Update steps

### 1. Verify what changed

The daemon runs as root, so treat an update like installing any other software:

- Read the release notes, or `git log --oneline` for the incoming commits.
- Check whether `veloscroll.service`, dependencies (`python3-evdev`), or behavior changed.
- Review any diff before running the update.

### 2. Update the code

```bash
sudo git -C /opt/veloscroll pull origin main
```

To pin a specific version instead (or to roll back, see below), check out a tag or commit.

### 3. Refresh the service file (only if it changed)

If the release changed `veloscroll.service`, copy it to `/etc/systemd/system/` again and reload systemd:

```bash
sudo cp /opt/veloscroll/veloscroll.service /etc/systemd/system/
sudo systemctl daemon-reload
```

### 4. Restart and verify

Code changes never hot-reload; only `config.ini` does.

```bash
sudo systemctl restart veloscroll
journalctl -u veloscroll -n 10
```

Expect to see:

- the newest version (like `VeloScroll vX.Y`),
- a fresh `config loaded from ...` line,
- a `grabbed ...` line for your mouse.

---

## Rolling back

Check out the previous tag or commit in `/opt/veloscroll`, then repeat step 4:

```bash
sudo git -C /opt/veloscroll checkout <previous-tag-or-commit>
sudo systemctl restart veloscroll
journalctl -u veloscroll -n 10
```

---

Back to the [README](../README.md) · See also: [Advanced](ADVANCED.md)
