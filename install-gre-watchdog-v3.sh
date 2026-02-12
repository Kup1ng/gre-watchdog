#!/usr/bin/env bash
set -euo pipefail

PY_URL_DEFAULT="https://raw.githubusercontent.com/Kup1ng/gre-watchdog/main/gre-watchdog.py"
GREWD_URL_DEFAULT="https://raw.githubusercontent.com/Kup1ng/gre-watchdog/main/grewd"

PY_DST="/usr/local/sbin/gre-watchdog.py"
CLI="/usr/local/sbin/grewd"

SVC="/etc/systemd/system/gre-watchdog.service"
TMR="/etc/systemd/system/gre-watchdog.timer"
STATE="/run/gre-watchdog.json"

need_root() {
  if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
    echo "ERROR: Please run as root (e.g. sudo bash ...)" >&2
    exit 1
  fi
}

validate_role() { [[ "$1" == "ir" || "$1" == "kh" ]]; }

detect_role_from_ifaces() {
  local gre_list=""
  gre_list="$(ip -o -d link show type gre 2>/dev/null || true)"
  if echo "$gre_list" | grep -qE ':\s+gre-ir-'; then echo "ir"; return; fi
  if echo "$gre_list" | grep -qE ':\s+gre-kh-'; then echo "kh"; return; fi
  echo ""
}

choose_role() {
  if [[ -n "${ROLE:-}" ]]; then
    validate_role "$ROLE" || { echo "ERROR: ROLE must be 'ir' or 'kh'." >&2; exit 1; }
    echo "$ROLE"; return
  fi

  local auto=""
  auto="$(detect_role_from_ifaces)"
  if validate_role "$auto"; then echo "$auto"; return; fi

  echo "Could not auto-detect role (no gre-ir-* / gre-kh-* interfaces found)."
  while true; do
    read -r -p "Select server role (ir/kh): " ans
    if validate_role "$ans"; then echo "$ans"; return; fi
    echo "Please enter exactly: ir or kh"
  done
}

install_deps() {
  echo "[*] Installing dependencies..."
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -y >/dev/null
  apt-get install -y python3 iproute2 iputils-ping curl >/dev/null
}

download_python() {
  local url="${PY_URL:-$PY_URL_DEFAULT}"
  echo "[*] Downloading Python watchdog from: $url"
  curl -fsSL "$url" -o "$PY_DST"
  chmod +x "$PY_DST"
}

download_grewd() {
  local url="${GREWD_URL:-$GREWD_URL_DEFAULT}"
  echo "[*] Downloading grewd CLI from: $url"
  curl -fsSL "$url" -o "$CLI"
  chmod +x "$CLI"
}

write_service() {
  local role="$1"
  echo "[*] Writing systemd service (role=$role)"
  cat > "$SVC" <<EOF
[Unit]
Description=GRE watchdog ($role)
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/bin/python3 $PY_DST --role $role
EOF
}

write_timer() {
  echo "[*] Writing systemd timer (runs at second 50 of every minute)"
  cat > "$TMR" <<'TIMER_EOF'
[Unit]
Description=Run GRE watchdog every minute at second 50

[Timer]
OnCalendar=*-*-* *:*:50
AccuracySec=1s
Persistent=true

[Install]
WantedBy=timers.target
TIMER_EOF
}

reload_and_start() {
  echo "[*] Reloading systemd and enabling timer..."
  systemctl daemon-reload
  systemctl reset-failed gre-watchdog.service >/dev/null 2>&1 || true
}

bring_managed_ifaces_up() {
  echo "[*] Bringing managed interfaces UP (from state if exists)..."
  if [[ -f "$STATE" ]]; then
    python3 - <<'PY'
import json, subprocess
p="/run/gre-watchdog.json"
try:
    d=json.load(open(p))
    for dev in (d.get("ifs", {}) or {}).keys():
        if not isinstance(dev, str) or not dev:
            continue
        r=subprocess.run(["/sbin/ip","link","show","dev",dev], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if r.returncode==0:
            subprocess.run(["/sbin/ip","link","set","dev",dev,"up"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
except Exception:
    pass
PY
  fi
}

do_install() {
  local role
  role="$(choose_role)"
  install_deps
  download_python
  download_grewd
  write_service "$role"
  write_timer
  reload_and_start
  echo
  echo "[+] Installed."
  echo "Role: $role"
  echo "Try: grewd start"
}

do_update() {
  need_root
  install_deps
  download_python
  # Optionally also refresh grewd:
  download_grewd
  systemctl restart gre-watchdog.timer >/dev/null 2>&1 || true
  systemctl reset-failed gre-watchdog.service >/dev/null 2>&1 || true
  echo "[+] Updated (Python + grewd)."
}

do_uninstall() {
  need_root
  echo "[*] Stopping..."
  systemctl stop gre-watchdog.timer 2>/dev/null || true
  systemctl stop gre-watchdog.service 2>/dev/null || true

  bring_managed_ifaces_up

  echo "[*] Disabling..."
  systemctl disable gre-watchdog.timer 2>/dev/null || true

  echo "[*] Removing files..."
  rm -f "$PY_DST" "$CLI" "$SVC" "$TMR" "$STATE"

  systemctl daemon-reload
  systemctl reset-failed
  echo "[+] Uninstalled."
}

usage() {
  cat <<EOF
Usage:
  bash install-gre-watchdog-v3.sh [install|update|uninstall]

Modes:
  install   Install everything (default)
  update    Update Python watchdog (and grewd), restart timer
  uninstall Stop + bring interfaces UP + remove everything
EOF
}

main() {
  need_root
  local mode="${1:-install}"
  case "$mode" in
    install)   do_install ;;
    update)    do_update ;;
    uninstall) do_uninstall ;;
    -h|--help|help) usage ;;
    *) echo "ERROR: Unknown mode: $mode" >&2; usage; exit 1 ;;
  esac
}

main "$@"
