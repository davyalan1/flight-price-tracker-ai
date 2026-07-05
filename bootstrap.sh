#!/usr/bin/env bash
# Idempotent install/upgrade for Skytracer. Run as root from a checked-out
# copy of this repo:
#
#   sudo ./bootstrap.sh
#
# Safe to re-run: it syncs the current repo into /opt/skytracer, re-installs
# dependencies, and re-enables the systemd units without touching an
# existing /etc/skytracer/config.toml or /var/lib/skytracer database.
#
# Written for Debian 12 (the Proxmox LXC target in the build spec) but uses
# only plain apt/systemd, so it also works unchanged on Ubuntu 24.04 — this
# has been run for real on both.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="/opt/skytracer"
CONFIG_DIR="/etc/skytracer"
DATA_DIR="/var/lib/skytracer"
SYSTEMD_DIR="/etc/systemd/system"
SERVICE_USER="skytracer"

if [ "$(id -u)" -ne 0 ]; then
  echo "bootstrap.sh must run as root (try: sudo ./bootstrap.sh)" >&2
  exit 1
fi

echo "==> Installing OS packages"
apt-get update
apt-get install -y python3 python3-venv python3-pip git curl rsync

echo "==> Creating the service user and directories"
id -u "$SERVICE_USER" >/dev/null 2>&1 || \
  useradd --system --home "$INSTALL_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
mkdir -p "$INSTALL_DIR" "$DATA_DIR" "$CONFIG_DIR"

echo "==> Syncing application code to $INSTALL_DIR"
# --exclude 'venv': the source repo never has this directory, so without
# excluding it, --delete would wipe the *installed* venv on every re-run
# (it gets rebuilt a few lines below anyway, but there's no reason to pay
# that cost, or to have it briefly missing while a service might restart).
rsync -a --delete \
  --exclude '.git' --exclude '.venv' --exclude 'venv' --exclude 'dev' \
  --exclude '__pycache__' --exclude '*.egg-info' \
  "$REPO_DIR"/ "$INSTALL_DIR"/

echo "==> Creating/upgrading the virtualenv"
python3 -m venv "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/pip" install -U pip
"$INSTALL_DIR/venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt"
"$INSTALL_DIR/venv/bin/pip" install "$INSTALL_DIR" --no-deps

echo "==> Seeding config (first install only — never overwrites an existing one)"
if [ ! -f "$CONFIG_DIR/config.toml" ]; then
  cp "$INSTALL_DIR/config.example.toml" "$CONFIG_DIR/config.toml"
fi

echo "==> Fixing ownership"
# Must happen before the Playwright step below, which writes its browser
# cache into $INSTALL_DIR as the skytracer user — that user needs to already
# own the directory to write there.
chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR" "$DATA_DIR" "$CONFIG_DIR"

if grep -q '^use_browser_fallback = true' "$CONFIG_DIR/config.toml"; then
  echo "==> Google browser fallback is enabled — installing Playwright's Chromium"
  # playwright isn't in requirements.txt — it's only needed for this optional
  # fallback path, which fast_flights.browser already handles gracefully via
  # ImportError if it's missing (see skytracer/sources/google.py).
  "$INSTALL_DIR/venv/bin/pip" install playwright
  # OS-level shared libs need root; the browser binary itself must be cached
  # under the skytracer user's home (-H), since that's who runs the service —
  # caching it under /root would leave the service unable to find it.
  "$INSTALL_DIR/venv/bin/playwright" install-deps chromium
  sudo -u "$SERVICE_USER" -H "$INSTALL_DIR/venv/bin/playwright" install chromium
else
  echo "==> Google browser fallback is disabled — skipping Playwright/Chromium install"
  echo "    (toggling it on later needs, as root:"
  echo "     $INSTALL_DIR/venv/bin/pip install playwright"
  echo "     $INSTALL_DIR/venv/bin/playwright install-deps chromium"
  echo "     sudo -u $SERVICE_USER -H $INSTALL_DIR/venv/bin/playwright install chromium)"
fi

echo "==> Installing systemd units"
cp "$INSTALL_DIR/systemd/skytracer-poll.service" "$SYSTEMD_DIR/"
cp "$INSTALL_DIR/systemd/skytracer-poll.timer" "$SYSTEMD_DIR/"
cp "$INSTALL_DIR/systemd/skytracer-web.service" "$SYSTEMD_DIR/"
cp "$INSTALL_DIR/systemd/skytracer-bot-telegram.service" "$SYSTEMD_DIR/"
cp "$INSTALL_DIR/systemd/skytracer-bot-discord.service" "$SYSTEMD_DIR/"

echo "==> Enabling services"
systemctl daemon-reload
systemctl enable --now skytracer-poll.timer skytracer-web.service

# The conversational bots are optional — each only starts if its own token
# is actually configured. `skytracer run-telegram-bot`/`run-discord-bot`
# also refuse to start without a token, so this is a convenience
# (auto-start once configured), not the only safety net.
#
# Checked against the live settings *database*, not config.toml: that file
# only ever seeds the settings table once on first install (see
# skytracer/bootstrap.py) — on any box that's already been configured via
# the Settings page (i.e. every real install past its first boot), the
# token genuinely lives in the database and config.toml stays exactly as
# it was seeded. Checking config.toml here would (and, on this box, did)
# read a stale/absent value and enable a service with no real token,
# crash-looping it under Restart=on-failure.
for platform in telegram discord; do
  token="$("$INSTALL_DIR/venv/bin/python3" -c "
import sqlite3, json
try:
    conn = sqlite3.connect('$DATA_DIR/skytracer.db')
    row = conn.execute(\"SELECT value FROM settings WHERE key = 'ai.${platform}_bot_token'\").fetchone()
    print(json.loads(row[0]) if row else '')
except sqlite3.Error:
    print('')
")"
  if [ -n "$token" ]; then
    echo "==> ai.${platform}_bot_token is set — enabling the $platform bot"
    systemctl enable --now "skytracer-bot-$platform.service"
  else
    echo "==> ai.${platform}_bot_token is empty — skipping the $platform bot"
    systemctl disable --now "skytracer-bot-$platform.service" 2>/dev/null || true
  fi
done

echo
echo "==> Done."
echo "    Visit http://<this box's IP>:8087/setup to create the admin password,"
echo "    then use the Settings page for everything else — see README.md."
