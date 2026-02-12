#!/usr/bin/env python3
import argparse
import ipaddress
import json
import os
import re
import subprocess
import time
from dataclasses import dataclass
from typing import Optional, Dict, Any, List, Tuple

try:
    from zoneinfo import ZoneInfo
    TEHRAN_TZ = ZoneInfo("Asia/Tehran")
except Exception:
    TEHRAN_TZ = None

STATE_PATH = "/run/gre-watchdog.json"

@dataclass
class PingResult:
    ok: bool
    loss: Optional[float]  # percent 0..100
    rc: int

def ts_tehran() -> str:
    if TEHRAN_TZ is None:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    import datetime as _dt
    return _dt.datetime.now(TEHRAN_TZ).strftime("%Y-%m-%d %H:%M:%S")

def log_err(msg: str) -> None:
    # Error-only logging, with Tehran timestamp
    print(f"{ts_tehran()} {msg}", flush=True)

def sh(cmd: List[str], timeout: int = 10) -> Tuple[int, str, str]:
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout)
    return p.returncode, p.stdout.strip(), p.stderr.strip()

def now() -> int:
    return int(time.time())

def load_state() -> Dict[str, Any]:
    try:
        with open(STATE_PATH, "r") as f:
            return json.load(f)
    except Exception:
        return {"ifs": {}}

def save_state(state: Dict[str, Any]) -> None:
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f)
    os.replace(tmp, STATE_PATH)

def list_gre_ifaces() -> List[str]:
    rc, out, _ = sh(["/sbin/ip", "-o", "-d", "link", "show", "type", "gre"])
    if rc != 0:
        return []
    ifaces = []
    for line in out.splitlines():
        m = re.match(r"^\d+:\s+([^:@]+)", line)
        if m:
            ifaces.append(m.group(1))
    return ifaces

def choose_role(args_role: str, ifaces: List[str]) -> str:
    if args_role in ("ir", "kh"):
        return args_role
    has_ir = any(x.startswith("gre-ir-") for x in ifaces)
    has_kh = any(x.startswith("gre-kh-") for x in ifaces)
    if has_ir and not has_kh:
        return "ir"
    if has_kh and not has_ir:
        return "kh"
    return "auto"

def monitored_ifaces(role: str, ifaces: List[str]) -> List[str]:
    if role == "ir":
        return [x for x in ifaces if x.startswith("gre-ir-")]
    if role == "kh":
        return [x for x in ifaces if x.startswith("gre-kh-")]
    return [x for x in ifaces if x.startswith("gre-") and x != "gre0"]

def iface_is_up(dev: str) -> bool:
    rc, out, _ = sh(["/sbin/ip", "link", "show", "dev", dev])
    if rc != 0:
        return False
    return "state UP" in out or ("<" in out and "UP" in out.split("<", 1)[1].split(">", 1)[0].split(","))

def set_link(dev: str, up: bool) -> bool:
    rc, _, _ = sh(["/sbin/ip", "link", "set", "dev", dev, "up" if up else "down"])
    return rc == 0

def get_outer_remote(dev: str) -> Optional[str]:
    rc, out, _ = sh(["/sbin/ip", "-d", "link", "show", "dev", dev])
    if rc != 0:
        return None
    m = re.search(r"\bremote\s+(\S+)\s+local\s+(\S+)", out)
    if m:
        return m.group(1)
    m = re.search(r"\blink/gre\s+\S+\s+peer\s+(\S+)", out)
    if m:
        return m.group(1)
    return None

def get_inner_peer(dev: str) -> Optional[str]:
    rc, out, _ = sh(["/sbin/ip", "-o", "-4", "addr", "show", "dev", dev, "scope", "global"])
    if rc != 0 or not out:
        return None
    line = out.splitlines()[0]

    m_peer = re.search(r"\binet\s+(\d+\.\d+\.\d+\.\d+)(?:/\d+)?\s+peer\s+(\d+\.\d+\.\d+\.\d+)", line)
    if m_peer:
        return m_peer.group(2)

    m = re.search(r"\binet\s+(\d+\.\d+\.\d+\.\d+)/(\d+)", line)
    if not m:
        return None

    local_ip = m.group(1)
    prefix = int(m.group(2))
    try:
        iface = ipaddress.ip_interface(f"{local_ip}/{prefix}")
        hosts = list(iface.network.hosts())
        if len(hosts) == 2:
            return str(hosts[0] if hosts[1] == iface.ip else hosts[1])
    except Exception:
        return None
    return None

def ping_with_loss(ip: str, dev: Optional[str], count: int, timeout_s: int) -> PingResult:
    cmd = ["/bin/ping", "-c", str(count), "-W", str(timeout_s)]
    if dev:
        cmd += ["-I", dev]
    cmd.append(ip)

    total_timeout = max(3, (count * timeout_s) + 3)
    rc, out, _ = sh(cmd, timeout=total_timeout)

    # Parse packet loss: "... X% packet loss ..."
    loss = None
    m = re.search(r"(\d+(?:\.\d+)?)%\s+packet\s+loss", out)
    if m:
        try:
            loss = float(m.group(1))
        except Exception:
            loss = None

    ok = (rc == 0)
    return PingResult(ok=ok, loss=loss, rc=rc)

def is_fail(pr: PingResult, loss_threshold: float) -> bool:
    # Treat as FAIL if:
    # - ping rc != 0, OR
    # - we could parse loss and it is >= threshold
    if pr.rc != 0:
        return True
    if pr.loss is not None and pr.loss >= loss_threshold:
        return True
    return False

def align_to_next_minute() -> Tuple[int, int]:
    """
    Returns:
      (next_minute_epoch, seconds_until_next_minute)
    """
    t = time.time()
    next_min = int(t // 60 + 1) * 60
    return next_min, max(0, int(round(next_min - t)))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--role", choices=["auto", "ir", "kh"], default="auto")
    ap.add_argument("--cooldown", type=int, default=900)
    ap.add_argument("--fail-count", type=int, default=3)
    ap.add_argument("--outer-pings", type=int, default=3)
    ap.add_argument("--inner-pings", type=int, default=7)
    ap.add_argument("--ping-timeout", type=int, default=1)
    ap.add_argument("--loss-threshold", type=float, default=70.0, help="packet loss %% to treat as FAIL (>= threshold)")
    ap.add_argument("--align-minute", action="store_true", default=True, help="discover at :50 then ping at :00 (best with systemd timer at second 50)")
    ap.add_argument("--no-align-minute", dest="align_minute", action="store_false")
    ap.add_argument("--post-up-ignore", type=int, default=-1, help="seconds to skip checks after interface is brought UP; -1=auto by role")
    args = ap.parse_args()

    ifaces_all = list_gre_ifaces()
    role = choose_role(args.role, ifaces_all)
    ifaces = monitored_ifaces(role, ifaces_all)

    # Your original: Iran up after 5 min, foreign after 6 min
    up_delay = 300 if role != "kh" else 360

    # Post-up ignore default
    if args.post_up_ignore < 0:
        # Iran: 60s (as requested)
        # Foreign: keep slightly larger (90s) to avoid false positives if you want
        args.post_up_ignore = 60 if role != "kh" else 90

    state = load_state()
    st_ifs: Dict[str, Any] = state.setdefault("ifs", {})

    # Align logic:
    # This script should be started at :50 by systemd timer.
    # It discovers interfaces now, then performs scheduled UP at :59, then pings at :00.
    if args.align_minute:
        next_min_epoch, _ = align_to_next_minute()
        up_epoch = next_min_epoch - 1  # bring due interfaces up 1s before minute boundary
    else:
        next_min_epoch = 0
        up_epoch = 0

    # 1) Discovery now (fast)
    discoveries = []
    for dev in ifaces:
        if not iface_is_up(dev):
            continue
        outer = get_outer_remote(dev)
        inner = get_inner_peer(dev)
        if outer and inner:
            discoveries.append((dev, outer, inner))

    # 2) Scheduled UP handling (aligned)
    t = now()
    if args.align_minute:
        # wait until up_epoch if it's in the future
        if up_epoch > time.time():
            time.sleep(max(0, up_epoch - time.time()))
        t = now()

    for dev, info in list(st_ifs.items()):
        next_up = int(info.get("next_up", 0) or 0)
        if next_up and t >= next_up:
            if set_link(dev, True):
                info["last_up_ts"] = t
                # error-only log: only log when we actually do scheduled UP
                log_err(f"[{dev}] scheduled UP")
            info["next_up"] = 0

    # 3) Wait until minute boundary then start pings (aligned)
    if args.align_minute:
        # sleep to exactly next minute boundary
        while time.time() < next_min_epoch:
            time.sleep(0.01)

    t = now()

    # 4) Evaluate each discovered GRE
    for (dev, outer_ip, inner_ip) in discoveries:
        info = st_ifs.setdefault(dev, {})
        if not iface_is_up(dev):
            continue

        # Skip checks for some time after we brought it UP
        last_up = int(info.get("last_up_ts", 0) or 0)
        if last_up and (t - last_up) < args.post_up_ignore:
            continue

        # Ping outer and inner
        outer_pr = ping_with_loss(outer_ip, dev=None, count=args.outer_pings, timeout_s=args.ping_timeout)
        inner_pr = ping_with_loss(inner_ip, dev=dev, count=args.inner_pings, timeout_s=args.ping_timeout)

        outer_fail = is_fail(outer_pr, args.loss_threshold)
        inner_fail = is_fail(inner_pr, args.loss_threshold)

        # Only treat as "GRE stuck" when outer is OK but inner is FAIL
        # (outer OK means: not fail by our loss logic)
        if (not outer_fail) and inner_fail:
            consec = int(info.get("consecutive", 0) or 0) + 1
            info["consecutive"] = consec

            if consec >= args.fail_count:
                next_allowed = int(info.get("next_allowed_reset", 0) or 0)
                if t < next_allowed:
                    # do not log spam
                    info["consecutive"] = 0
                    continue

                ok_down = set_link(dev, False)
                # schedule next up (exact minute anchoring)
                # Since we are aligned at minute boundary, t is ~:00
                info["next_up"] = t + up_delay
                info["next_allowed_reset"] = t + args.cooldown
                info["consecutive"] = 0

                log_err(f"[{dev}] RESET (outer_loss={outer_pr.loss} inner_loss={inner_pr.loss}) down={ok_down} up_in={up_delay}s role={role}")

        else:
            info["consecutive"] = 0

    save_state(state)

if __name__ == "__main__":
    main()
