#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/gre-watchdog"
CFG_DIR="/etc/gre-watchdog"
LOG_DIR="/var/log/gre-watchdog"

sudo mkdir -p "$APP_DIR" "$CFG_DIR" "$LOG_DIR" "/var/lib/gre-watchdog"
sudo rsync -a --delete ./ "$APP_DIR/"

sudo apt-get update -y
sudo apt-get install -y python3 python3-venv python3-pip rsync

cd "$APP_DIR"
python3 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

if [ ! -f "$CFG_DIR/agent.yaml" ]; then
  sudo cp config/agent.yaml.example "$CFG_DIR/agent.yaml"
  echo "[!] Copied example config to $CFG_DIR/agent.yaml (edit it!)"
fi

sudo sed -i "s|config/agent.yaml|/etc/gre-watchdog/agent.yaml|g" gre_watchdog/agent/main.py

sudo cp systemd/gre-watchdog-agent.service /etc/systemd/system/gre-watchdog-agent.service
sudo systemctl daemon-reload
sudo systemctl enable --now gre-watchdog-agent.service

echo "[OK] Agent installed. Check: sudo systemctl status gre-watchdog-agent"
