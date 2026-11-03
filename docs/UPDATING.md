# Updating VeloScroll

There is no automatic update mechanism in the daemon itself — when a new version is released, you fetch it yourself and re-deploy. (The [VeloScroll GUI](https://github.com/LucasTippelt/VeloScroll-GUI) has a one-click **Update daemon…** button that does all of this behind a polkit prompt; see below.)

**The running daemon is always the deployed copy in `/usr/lib/veloscroll`, never the checkout.** After checking out *any* commit or tag — an update, a rollback, local dev iteration on the repo — run the deploy block (step 3) before restarting. Manual work on the repo reaches root only through that explicit step; a `git pull` can touch any file without breaking the privilege boundary, because the checkout is user-owned source and nothing root-executed lives in it.

Your `/etc/veloscroll/config.ini` lives outside the repo and is left untouched by an update. Unknown keys are ignored with a warning, and removed keys fall back to built-in defaults. This is also why all configuration belongs in `config.ini`: local edits to `veloscroll.py` are lost or conflict on every update (see [Customize and reload](CONFIGURATION.md#customize-and-reload)).

---

## Update steps

### 1. Verify what changed

The daemon runs as root from `/usr/lib/veloscroll`, so treat an update like installing any other software:

- Read the release notes, or `git log --oneline` for the incoming commits.
- Check whether `veloscroll.service` or one of the five deployed files (`veloscroll.py`, `veloscroll_preset.py`, `helpers/ListDeviceNames.py`, `helpers/ListButtonPresses.py`, `helpers/veloscroll_tuning_helper.py`) changed:

  ```bash
  git -C /opt/veloscroll fetch origin main
  git -C /opt/veloscroll diff --name-only HEAD..origin/main
  ```

- Review any diff before running the update.

### 2. Update the code (no sudo)

The checkout is user-owned, so this runs as your user:

```bash
git -C /opt/veloscroll pull origin main
```

To pin a specific version instead (or to roll back, see below), check out a tag or commit — then continue with step 3 either way.

### 3. Re-deploy the root-executed files

Run the deploy block from [Installation](INSTALL.md#installation) step 4:

```bash
sudo mkdir -p /usr/lib/veloscroll/helpers
sudo cp /opt/veloscroll/veloscroll.py /opt/veloscroll/veloscroll_preset.py /usr/lib/veloscroll/
sudo cp /opt/veloscroll/helpers/ListDeviceNames.py \
        /opt/veloscroll/helpers/ListButtonPresses.py \
        /opt/veloscroll/helpers/veloscroll_tuning_helper.py /usr/lib/veloscroll/helpers/
sudo chown -R root:root /usr/lib/veloscroll
sudo chmod 755 /usr/lib/veloscroll /usr/lib/veloscroll/*.py \
               /usr/lib/veloscroll/helpers /usr/lib/veloscroll/helpers/*.py
```

It is idempotent and cheap — run it on every update, or only when one of the five files changed (step 1's diff tells you). Skipping it means the old deployed code keeps running: safe by construction, but not what you just pulled.

### 4. Refresh the service file (only if it changed)

If the release changed `veloscroll.service`, copy it to `/etc/systemd/system/` again and reload systemd:

```bash
sudo cp /opt/veloscroll/veloscroll.service /etc/systemd/system/
sudo systemctl daemon-reload
```

### 5. Restart and verify

Code changes never hot-reload; only `config.ini` does. A restart is needed when `veloscroll.py` or the service file changed — preset/helper-only changes need no daemon restart (the GUI helper re-runs them as fresh processes).

```bash
sudo systemctl restart veloscroll
journalctl -u veloscroll -n 10
```

Expect to see:

- a fresh `config loaded from ...` line,
- a `grabbed ...` line for your mouse.

---

## Rolling back

Check out the previous tag or commit in `/opt/veloscroll`, re-run the deploy block (step 3), refresh the unit if it changed (step 4), then restart:

```bash
git -C /opt/veloscroll checkout <previous-tag-or-commit>
# step 3's deploy block here
sudo systemctl restart veloscroll
journalctl -u veloscroll -n 10
```

---

## One-click update via the GUI

If you use the [VeloScroll GUI](https://github.com/LucasTippelt/VeloScroll-GUI), its **Update daemon…** button performs steps 2–5 for you behind a polkit prompt: it pulls as the checkout owner, re-deploys any changed files to `/usr/lib/veloscroll` refreshes the unit when it changed, restarts only when `veloscroll.py` or the unit changed, and tails the journal — with a transcript of every step and a one-line rollback command.

---

Back to the [README](../README.md) · See also: [Advanced](ADVANCED.md)
