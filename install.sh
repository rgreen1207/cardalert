#!/usr/bin/env bash
#
# Card Alert installer.
#
# Usage:
#   curl -sSL https://raw.githubusercontent.com/rgreen1207/cardalert/main/install.sh | bash
#
# What this does: clones the repo, creates a Python venv, installs
# dependencies, sets up a systemd service, and starts it. All configuration
# (Discord webhook, ntfy, Pushover, Twilio, license key) happens afterward
# in your browser via the setup wizard — deliberately not here, since
# interactive prompts don't work reliably when a script is piped through
# `curl | bash` (stdin is consumed by the pipe, not your keyboard).

set -euo pipefail

REPO_URL="https://github.com/rgreen1207/cardalert.git"
INSTALL_DIR="${CARDALERT_DIR:-$HOME/cardalert}"
SERVICE_NAME="cardalert"
PORT="${CARDALERT_PORT:-8420}"

echo "== Card Alert installer =="

if ! command -v python3 &>/dev/null; then
  echo "python3 is required but not found. Install it first (e.g. 'sudo apt install python3 python3-venv python3-pip') and re-run."
  exit 1
fi
if ! command -v git &>/dev/null; then
  echo "git is required but not found. Install it first (e.g. 'sudo apt install git') and re-run."
  exit 1
fi

if [ -d "$INSTALL_DIR" ]; then
  echo "Found existing install at $INSTALL_DIR — updating instead of re-cloning."
  cd "$INSTALL_DIR"
  git fetch --tags --quiet
  git checkout main --quiet
  git pull --quiet
else
  echo "Cloning into $INSTALL_DIR ..."
  git clone --quiet "$REPO_URL" "$INSTALL_DIR"
  cd "$INSTALL_DIR"
fi

echo "Creating virtual environment ..."
python3 -m venv venv
# shellcheck disable=SC1091
source venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

if [ ! -f .env ]; then
  cp .env.example .env
fi

echo "Setting up systemd service ..."
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
sudo bash -c "cat > '$SERVICE_FILE'" << EOF
[Unit]
Description=Card Alert
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${USER}
WorkingDirectory=${INSTALL_DIR}
EnvironmentFile=${INSTALL_DIR}/.env
ExecStart=${INSTALL_DIR}/venv/bin/uvicorn app:app --host 0.0.0.0 --port ${PORT}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now "${SERVICE_NAME}"

# Figure out an IP to show the user, best-effort.
IP_ADDR="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"
[ -z "$IP_ADDR" ] && IP_ADDR="<this-device's-ip>"

echo ""
echo "== Done =="
echo "Card Alert is running. Open this in a browser on the same network:"
echo ""
echo "  http://${IP_ADDR}:${PORT}"
echo ""
echo "First visit walks you through an optional setup wizard for alerts"
echo "(Discord, ntfy, Pushover, SMS) — skip anything you don't want, you"
echo "can always add it later from the Settings page."
