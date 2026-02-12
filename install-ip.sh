#!/usr/bin/env bash
set -euo pipefail

REPO_URL_DEFAULT="https://github.com/Kup1ng/gre-watchdog.git"
BRANCH_DEFAULT="main"
APP_DIR_DEFAULT="/opt/gre-watchdog"

CFG_DIR="/etc/gre-watchdog"
LOG_DIR="/var/log/gre-watchdog"
STATE_DIR="/var/lib/gre-watchdog"

COORD_PORT_DEFAULT="8000"
AGENT_PORT_DEFAULT="7801"

need_root() {
  if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
    echo "[!] Run as root: sudo bash install-ip.sh"
    exit 1
  fi
}

install_pkgs() {
  apt-get update -y
  apt-get install -y git rsync python3 python3-venv python3-pip ca-certificates
}

gen_rand() {
  python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(48))
PY
}

prompt() {
  local var="$1" default="$2" text="$3"
  local val=""
  read -r -p "$text [$default]: " val || true
  val="${val:-$default}"
  printf -v "$var" "%s" "$val"
}

prompt_secret_optional() {
  local var="$1" text="$2"
  local val=""
  read -r -p "$text (leave empty to auto-generate): " val || true
  if [[ -z "$val" ]]; then
    val="$(gen_rand)"
    echo "    -> generated (hidden)"
  fi
  printf -v "$var" "%s" "$val"
}

clone_or_update_repo() {
  local repo_url="$1" branch="$2" app_dir="$3"
  if [[ -d "$app_dir/.git" ]]; then
    echo "[*] Updating repo in $app_dir ..."
    git -C "$app_dir" fetch --all --prune
    git -C "$app_dir" checkout "$branch"
    git -C "$app_dir" pull --ff-only
  else
    echo "[*] Cloning repo into $app_dir ..."
    rm -rf "$app_dir"
    git clone --branch "$branch" "$repo_url" "$app_dir"
  fi
}

setup_venv_and_deps() {
  local app_dir="$1"
  echo "[*] Creating venv & installing Python deps..."
  cd "$app_dir"
  python3 -m venv .venv
  # shellcheck disable=SC1091
  source .venv/bin/activate
  pip install --upgrade pip >/dev/null
  pip install -r requirements.txt
}

ensure_dirs() {
  mkdir -p "$CFG_DIR" "$LOG_DIR" "$STATE_DIR"
  chmod 755 "$CFG_DIR" "$LOG_DIR" "$STATE_DIR"
}

patch_config_paths_in_code() {
  local app_dir="$1"
  sed -i 's|config/agent.yaml|/etc/gre-watchdog/agent.yaml|g' "$app_dir/gre_watchdog/agent/main.py" || true
  sed -i 's|config/coordinator.yaml|/etc/gre-watchdog/coordinator.yaml|g' "$app_dir/gre_watchdog/coordinator/main.py" || true
}

write_agent_config() {
  local cfg_path="$1" shared_secret="$2" agent_port="$3" allow_cidrs="$4"
  cat > "$cfg_path" <<EOF
role: "kh"
listen_host: "0.0.0.0"
listen_port: ${agent_port}

shared_secret: "${shared_secret}"
iface_regex: "^gre-kh-(\\\\d+)$"

allow_cidrs:
  - "${allow_cidrs}"   # RECOMMENDED: IranPublicIP/32
max_clock_skew_sec: 45

idempotency_ttl_sec: 3600
log_dir: "${LOG_DIR}"
EOF
}

write_coordinator_config() {
  local cfg_path="$1" shared_secret="$2" outside_ip="$3" agent_port="$4" panel_user="$5" panel_pass="$6" cli_token="$7"
  cat > "$cfg_path" <<EOF
role: "ir"
listen_host: "0.0.0.0"
listen_port: ${COORD_PORT_DEFAULT}

shared_secret: "${shared_secret}"
iface_regex: "^gre-ir-(\\\\d+)$"

agent_base_url: "http://${outside_ip}:${agent_port}"

check_interval_sec: 15
confirm_bad_rounds: 3

ping_count: 7
ping_timeout_sec: 2
loss_ok_percent: 20

down_hold_sec: 300
up_gap_sec: 45

rpc_max_attempts: 6
rpc_base_backoff_ms: 250
rpc_max_backoff_ms: 4000
rpc_timeout_sec: 6

max_resets_per_30min: 3
pause_after_limit_min: 30

panel_username: "${panel_user}"
panel_password: "${panel_pass}"
panel_session_ttl_min: 120

cli_token: "${cli_token}"

state_path: "${STATE_DIR}/state.json"
log_dir: "${LOG_DIR}"
EOF
}

install_systemd_agent() {
  local app_dir="$1"
  cp "$app_dir/systemd/gre-watchdog-agent.service" /etc/systemd/system/gre-watchdog-agent.service
  systemctl daemon-reload
  systemctl enable --now gre-watchdog-agent.service
}

install_systemd_coordinator() {
  local app_dir="$1"
  cp "$app_dir/systemd/gre-watchdog-coordinator.service" /etc/systemd/system/gre-watchdog-coordinator.service
  systemctl daemon-reload
  systemctl enable --now gre-watchdog-coordinator.service
}

print_agent_done() {
  local port="$1"
  echo
  echo "[OK] Agent installed & running."
  echo "    API:    http://<OUTSIDE_IP>:${port}/health"
  echo "    Note:   limit allow_cidrs to Iran IP/32 in ${CFG_DIR}/agent.yaml"
  echo
  systemctl --no-pager --full status gre-watchdog-agent.service || true
}

print_coord_done() {
  local ip_hint="$1"
  echo
  echo "[OK] Coordinator installed & running."
  echo "    Panel:  http://${ip_hint}:${COORD_PORT_DEFAULT}/"
  echo "    Login:  use panel_username/panel_password in ${CFG_DIR}/coordinator.yaml"
  echo
  systemctl --no-pager --full status gre-watchdog-coordinator.service || true
}

main() {
  need_root

  echo "=== GRE Watchdog IP Installer ==="
  echo "App Dir:  ${APP_DIR_DEFAULT}"
  echo "Config:   ${CFG_DIR}"
  echo "Logs:     ${LOG_DIR}"
  echo "State:    ${STATE_DIR}"
  echo

  local repo_url branch app_dir role
  prompt repo_url "$REPO_URL_DEFAULT" "GitHub repo URL"
  prompt branch "$BRANCH_DEFAULT" "Git branch"
  prompt app_dir "$APP_DIR_DEFAULT" "Install directory"

  echo
  echo "Select role:"
  echo "  1) Coordinator (Iran)  - panel on port ${COORD_PORT_DEFAULT}"
  echo "  2) Agent (Outside)     - api on port ${AGENT_PORT_DEFAULT}"
  read -r -p "Enter 1 or 2 [1]: " role || true
  role="${role:-1}"

  echo "[*] Installing dependencies..."
  install_pkgs

  clone_or_update_repo "$repo_url" "$branch" "$app_dir"
  patch_config_paths_in_code "$app_dir"
  ensure_dirs
  chown -R root:root "$app_dir"

  setup_venv_and_deps "$app_dir"

  if [[ "$role" == "2" ]]; then
    echo
    echo "--- Agent setup (Outside) ---"
    local shared_secret agent_port allow_cidrs
    prompt agent_port "$AGENT_PORT_DEFAULT" "Agent listen port"
    prompt_secret_optional shared_secret "Shared secret (must match coordinator)"
    prompt allow_cidrs "0.0.0.0/0" "Allowed CIDR to call agent (RECOMMENDED: IranPublicIP/32)"

    write_agent_config "${CFG_DIR}/agent.yaml" "$shared_secret" "$agent_port" "$allow_cidrs"
    install_systemd_agent "$app_dir"
    print_agent_done "$agent_port"
    exit 0
  fi

  echo
  echo "--- Coordinator setup (Iran) ---"
  local outside_ip agent_port shared_secret panel_user panel_pass cli_token ip_hint
  prompt outside_ip "OUTSIDE_SERVER_IP" "Outside server public IP (agent host)"
  prompt agent_port "$AGENT_PORT_DEFAULT" "Agent port on outside server"
  prompt_secret_optional shared_secret "Shared secret (must match agent)"

  prompt panel_user "admin" "Panel username"
  prompt_secret_optional panel_pass "Panel password"
  prompt_secret_optional cli_token "CLI token (used by local CLI)"

  prompt ip_hint "<YOUR_IRAN_PUBLIC_IP>" "Iran server public IP (just for final display)"

  write_coordinator_config "${CFG_DIR}/coordinator.yaml" "$shared_secret" "$outside_ip" "$agent_port" "$panel_user" "$panel_pass" "$cli_token"
  install_systemd_coordinator "$app_dir"
  print_coord_done "$ip_hint"
}

main "$@"
