# gre_watchdog/coordinator/cli.py
from __future__ import annotations
import argparse, json, sys, time
import httpx, yaml
from rich.console import Console
from rich.table import Table
from gre_watchdog.common.state import load_state
from gre_watchdog.common.util import human_ts, tail_file

console = Console()

def load_cfg(path: str) -> dict:
    with open(path, "r") as f:
        return yaml.safe_load(f)

def api_headers(cfg: dict) -> dict:
    # CLI auth header
    return {"x-cli-token": cfg.get("cli_token", "")}

def must_have_token(cfg: dict):
    if not cfg.get("cli_token"):
        console.print("[red]cli_token is missing in coordinator config[/red]")
        sys.exit(1)

def show_status(st_path: str):
    state = load_state(st_path)
    t = Table(title="GRE Watchdog Status")
    t.add_column("ID", justify="right")
    t.add_column("Status")
    t.add_column("Pub loss%")
    t.add_column("GRE loss%")
    t.add_column("Bad rounds", justify="right")
    t.add_column("Paused until")
    t.add_column("Last action")
    t.add_column("Last seen")

    for k, v in sorted(state.tunnels.items(), key=lambda x: int(x[0])):
        paused = "-" if v.paused_until <= time.time() else human_ts(v.paused_until)
        t.add_row(
            str(v.id),
            v.status,
            f"{v.last_public_loss:.1f}",
            f"{v.last_gre_loss:.1f}",
            str(v.bad_rounds),
            paused,
            v.last_action,
            human_ts(v.last_seen),
        )
    console.print(t)

def show_events(st_path: str, n: int):
    state = load_state(st_path)
    evs = state.events[-n:]
    for e in evs:
        ts = human_ts(e.get("ts", 0))
        tid = e.get("tunnel_id", "-")
        console.print(f"{ts} [{e.get('kind','-')}] tid={tid} {e.get('msg','')}")

async def call_action(cfg: dict, action: str, tid: int | None):
    must_have_token(cfg)
    base = f"http://127.0.0.1:{cfg['listen_port']}"
    payload = {"action": action, "tunnel_id": tid}
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.post(base + "/cli/action", json=payload, headers=api_headers(cfg))
        r.raise_for_status()
        return r.json()

async def do_actions(cfg: dict, action: str, tid: int | None):
    try:
        res = await call_action(cfg, action, tid)
        if res.get("ok"):
            console.print(f"[green]OK[/green] {res}")
        else:
            console.print(f"[red]FAIL[/red] {res}")
    except Exception as e:
        console.print(f"[red]error:[/red] {e}")

def tail_coordinator_log(cfg: dict, lines: int):
    # direct file read
    p = cfg["log_dir"].rstrip("/") + "/gre-watchdog-coordinator.log"
    console.print(tail_file(p, lines))

def main():
    ap = argparse.ArgumentParser(prog="gre-watchdog-cli")
    ap.add_argument("--config", default="/etc/gre-watchdog/coordinator.yaml", help="path to coordinator.yaml")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status")
    ev = sub.add_parser("events")
    ev.add_argument("-n", type=int, default=50)

    for name in ("reset", "down", "up", "restart", "pause", "resume"):
        p = sub.add_parser(name)
        p.add_argument("id", type=int)

    sub.add_parser("reset-all")

    tl = sub.add_parser("tail-log")
    tl.add_argument("-n", type=int, default=200)

    args = ap.parse_args()
    cfg = load_cfg(args.config)
    st_path = cfg["state_path"]

    if args.cmd == "status":
        show_status(st_path)
        return

    if args.cmd == "events":
        show_events(st_path, args.n)
        return

    if args.cmd == "tail-log":
        tail_coordinator_log(cfg, args.n)
        return

    # actions (need local api)
    import asyncio
    if args.cmd == "reset-all":
        asyncio.run(do_actions(cfg, "reset_all", None))
        return

    # single-id action
    asyncio.run(do_actions(cfg, args.cmd.replace("-", "_"), args.id))

if __name__ == "__main__":
    main()
