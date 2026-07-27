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
# in your browser via the setup wizard, deliberately not here, since
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

checkout_latest_release() {
  # Prefer the latest tagged release over main. This means an existing
  # install only picks up a new version when you explicitly cut a release,
  # not on every commit that happens to land on main.
  git fetch --tags --quiet
  LATEST_TAG="$(git tag --list --sort=-v:refname | head -n1)"
  if [ -n "$LATEST_TAG" ]; then
    git checkout "$LATEST_TAG" --quiet
    echo "Using release ${LATEST_TAG}"
  else
    echo "No tagged releases found yet, using main (expect this to change once releases exist)."
    git checkout main --quiet
    git pull --quiet
  fi
}

if [ -d "$INSTALL_DIR" ]; then
  echo "Found existing install at $INSTALL_DIR, checking for updates."
  cd "$INSTALL_DIR"
  checkout_latest_release
else
  echo "Cloning into $INSTALL_DIR ..."
  git clone --quiet "$REPO_URL" "$INSTALL_DIR"
  cd "$INSTALL_DIR"
  checkout_latest_release
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
chmod 600 .env

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

echo "Setting up passwordless restart permission for the in-app updater ..."
# Scoped to exactly one command, restarting this one service, as this one
# user. This is what lets the "Update now" button on the Settings page
# restart the app itself after pulling a new release, without you having
# to SSH in every time. It grants nothing beyond that single command.
SUDOERS_FILE="/etc/sudoers.d/${SERVICE_NAME}-restart"
SUDOERS_RULE="${USER} ALL=(root) NOPASSWD: /bin/systemctl restart ${SERVICE_NAME}, /usr/bin/systemctl restart ${SERVICE_NAME}"
echo "$SUDOERS_RULE" | sudo tee "$SUDOERS_FILE" > /dev/null
sudo chmod 0440 "$SUDOERS_FILE"
if ! sudo visudo -c -f "$SUDOERS_FILE" &>/dev/null; then
  echo "Sudoers rule failed validation, removing it. The in-app updater will"
  echo "still pull new code, but you'll need to run 'sudo systemctl restart"
  echo "${SERVICE_NAME}' yourself after using it."
  sudo rm -f "$SUDOERS_FILE"
fi

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
echo "(Discord, ntfy, Pushover, SMS). Skip anything you don't want, you"
echo "can always add it later from the Settings page."
echo ""
echo "Future updates: run this same install command again, or use the"
echo "'Check for updates' button on the Settings page inside the app."
