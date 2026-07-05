# Skytracer

A self-hosted flight-price tracker. Polls fare sources on a schedule, stores
history in SQLite, and alerts on price drops. No Docker, no LLM in the poll/
alert path — see `FLIGHT_TRACKER_CLAUDE_CODE_PROMPT.md` for the full spec.

Status: **all 9 phases complete.** Google Flights works standalone with no
key; Kiwi, Travelpayouts, Duffel, and a user-run MCP server are optional
sources, each toggled on the Settings page. Flexible-window trips sample
every `scan_step_days` across the window, not just the first date. The route
detail page has a price-history chart. `bootstrap.sh` does a real system
install (system user, systemd timer + service).

---

## Using Skytracer (no technical background needed)

Someone else has already set this up for you and given you a web address
like `http://<box-ip>:8087`. Everything you'd want to change happens on the
**Settings page** — you never need to edit a file or use a terminal.

1. **First visit**: open `http://<box-ip>:8087/setup` and create a password.
   This only happens once.
2. **Dashboard** (`http://<box-ip>:8087/`): shows your tracked trip's current
   price, all-time low, and trend — no login needed, safe to bookmark.
   Click a route for its full price history and a chart.
3. **Settings** (`http://<box-ip>:8087/settings`, requires the password from
   step 1):
   - **Trip** — your airports, dates (exact, or "any date in this window"),
     passengers, cabin, currency.
   - **Alerts** — get notified when the price drops below a number you pick,
     drops by some %, or hits a new all-time low. **Cooldown** stops repeat
     notifications for the same drop.
   - **Schedule** — how often to check prices (e.g. every 6 hours). Changing
     this takes effect automatically within about 15 minutes — no need to
     ask anyone to restart anything.
   - **Sources** — Google is on by default and needs nothing from you. Each
     other source (Kiwi, Travelpayouts, Duffel, MCP) has a field for a key,
     a link to where you get one, and a **Test** button that tells you ✅ or
     ❌ right away. Paste the key, flip it on, click Test, then Save.
   - **Notifications** — pick WhatsApp, ntfy, Discord, or email, fill in
     that channel's fields, and use **Send test notification** to confirm
     it actually reaches you before relying on it.
   - **Conversational AI (optional)** — chat with the tracker on Telegram or
     Discord: ask "what's the status" or "any price drops" and get a real
     answer. Pick a provider (a locally-hosted model via Ollama, or
     Anthropic's cloud API), then paste a bot token (from @BotFather for
     Telegram, or the Discord Developer Portal for Discord) and your own
     numeric user ID — the bot ignores everyone else. Each bot only starts
     once its token is set; see "Installing" below for enabling the
     service.
   - **Security** — change your password here.
   - **Actions** — **"Run a check now"** if you don't want to wait for the
     next scheduled check.

### Troubleshooting

- **Dashboard shows nothing yet** — the first scheduled check hasn't run.
  Use Settings → Actions → "Run a check now".
- **A search keeps coming back empty** — on the Settings page, under
  Sources → Google, turn on "browser fallback" and Test again.
- **Want cheaper fares than Google alone finds** — add a Kiwi (or
  Travelpayouts/Duffel) key under Sources; Skytracer checks every source
  you enable and keeps the cheapest.
- **Not getting alerted even though the price is low** — check Alerts:
  is the threshold actually below the current price? Is a cooldown from a
  recent alert still active? Use "Send test notification" to confirm the
  channel itself works, independent of alert logic.
- **A source's "Test" button fails** — Kiwi and Travelpayouts don't offer a
  free no-signup tier (unlike Google and Duffel's free test tokens); you
  need a real key registered with them. Their free/developer tiers are
  fine for tracking one person's trip — production/commercial use would
  need their partner approval, which doesn't apply here.

---

## Installing (for whoever sets this up)

### 1. Create the LXC on Proxmox

```bash
pveam update
pveam available | grep debian-12
pveam download local debian-12-standard_<ver>_amd64.tar.zst
pct create 210 local:vztmpl/debian-12-standard_<ver>_amd64.tar.zst \
  --hostname skytracer --cores 1 --memory 1024 --swap 512 \
  --rootfs local-lvm:8 --net0 name=eth0,bridge=vmbr0,ip=dhcp \
  --unprivileged 1 --features nesting=1 --onboot 1 --start 1
pct enter 210
```

`nesting=1` only matters if you plan to enable Google's browser fallback
(it installs a headless Chromium via Playwright). This repo has also been
run for real on Ubuntu 24.04 — `bootstrap.sh` only uses plain `apt`/
`systemd`, so it works unchanged there too; if your box isn't Debian 12,
that's the one thing worth knowing before you file a bug about it.

### 2. Clone this repo onto the box, then run bootstrap.sh

```bash
git clone <this-repo-url> skytracer && cd skytracer
sudo ./bootstrap.sh
```

`bootstrap.sh` is idempotent — re-running it after a `git pull` upgrades the
code and dependencies in place without touching your existing
`/etc/skytracer/config.toml` or `/var/lib/skytracer/skytracer.db`. It:

- installs `python3`/`venv`/`pip`/`git`/`curl`/`rsync` via `apt`
- creates a dedicated, unprivileged `skytracer` system user
- copies this repo into `/opt/skytracer` and builds a venv there
- seeds `/etc/skytracer/config.toml` from `config.example.toml` (first
  install only — never overwrites an existing config)
- installs Playwright's Chromium only if the seed config has Google's
  browser fallback turned on
- installs the systemd units from `systemd/` and enables/starts
  `skytracer-poll.timer` + `skytracer-web.service`
- enables `skytracer-bot-telegram.service`/`skytracer-bot-discord.service`
  too, but only if `ai.telegram_bot_token`/`ai.discord_bot_token` are
  already set in the seed config — leave them blank (the default) to skip
  the conversational-AI feature entirely. If you configure a bot token
  later via the Settings page (which lives in the database, not
  `config.toml`), start its service yourself once:
  `sudo systemctl enable --now skytracer-bot-telegram.service` (or
  `-discord`).

After it finishes, visit `http://<box-ip>:8087/setup` and hand the box off
per the walkthrough above.

### How the schedule actually works

`skytracer-poll.timer` fires every 15 minutes, but each tick is a no-op
unless `schedule.every_hours` (set on the Settings page) has actually
elapsed since the last attempt — see `skytracer.poller.is_poll_due`. This
means changing the schedule in Settings takes effect on the very next tick,
with nobody needing to touch systemd.

### Useful commands once installed

```bash
sudo systemctl status skytracer-web.service skytracer-poll.timer
sudo journalctl -u skytracer-poll -f      # watch poll attempts live
sudo journalctl -u skytracer-web -f       # watch the web server
sudo -u skytracer /opt/skytracer/venv/bin/skytracer poll --force  # poll right now
sudo -u skytracer /opt/skytracer/venv/bin/skytracer show          # print current stats
```

---

## Development

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt -e .

# Point the CLI at a repo-local dev DB/config instead of /etc/skytracer + /var/lib/skytracer:
export SKYTRACER_CONFIG="$(pwd)/dev/config.toml"
export SKYTRACER_DB="$(pwd)/dev/skytracer.db"
cp config.example.toml dev/config.toml

.venv/bin/skytracer poll --once   # seeds settings from config.toml on first run
.venv/bin/skytracer run-web       # http://127.0.0.1:8087 (or whatever config.toml's web.port is)
.venv/bin/ruff check .
.venv/bin/pytest
```

## Configuration

`config.example.toml` only seeds the SQLite `settings` table once, on first
boot when that table is empty. After that, all configuration changes happen
through the web Settings page — the TOML file is ignored on subsequent runs.
