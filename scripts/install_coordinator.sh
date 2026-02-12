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

if [ ! -f "$CFG_DIR/coordinator.yaml" ]; then
  sudo cp config/coordinator.yaml.example "$CFG_DIR/coordinator.yaml"
  echo "[!] Copied example config to $CFG_DIR/coordinator.yaml (edit it!)"
fi

sudo sed -i "s|config/coordinator.yaml|/etc/gre-watchdog/coordinator.yaml|g" gre_watchdog/coordinator/main.py

sudo cp systemd/gre-watchdog-coordinator.service /etc/systemd/system/gre-watchdog-coordinator.service
sudo systemctl daemon-reload
sudo systemctl enable --now gre-watchdog-coordinator.service

echo "[OK] Coordinator installed. Web: http://SERVER_IP:8000"
