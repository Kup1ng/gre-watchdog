# gre_watchdog/coordinator/main.py
import yaml, asyncio, time
from fastapi import FastAPI
from gre_watchdog.common.log import setup_logger
from gre_watchdog.common.state import load_state, save_state, add_event
from gre_watchdog.coordinator.gre_discover import discover_gre
from gre_watchdog.coordinator.agent_client import AgentClient
from gre_watchdog.coordinator.actions import coordinated_reset, ip_link_set
from gre_watchdog.coordinator.scheduler import monitor_loop
from gre_watchdog.coordinator.web import build_router

def load_cfg(path="config/coordinator.yaml"):
    with open(path, "r") as f:
        return yaml.safe_load(f)

CFG = load_cfg()
logger = setup_logger("gre-watchdog-coordinator", CFG["log_dir"])

state = load_state(CFG["state_path"])
app_state = state  # same object

app = FastAPI()

# per-tunnel locks
locks: dict[int, asyncio.Lock] = {}

async def discover_fn():
    tunnels = await discover_gre(CFG["iface_regex"])
    for t in tunnels:
        locks.setdefault(t["id"], asyncio.Lock())
    return tunnels

agent = AgentClient(
    base_url=CFG["agent_base_url"],
    secret=CFG["shared_secret"],
    timeout_sec=CFG["rpc_timeout_sec"],
    max_attempts=CFG["rpc_max_attempts"],
    base_backoff_ms=CFG["rpc_base_backoff_ms"],
    max_backoff_ms=CFG["rpc_max_backoff_ms"],
    logger=logger,
)

def save_fn():
    save_state(CFG["state_path"], state)

async def do_action(kind: str, tid: int | None):
    # manual actions from panel
    if kind in ("pause", "resume") and tid is not None:
        st = state.tunnels.get(str(tid))
        if not st:
            return
        if kind == "pause":
            st.paused_until = time.time() + 365*24*3600
            st.status = "PAUSED_MANUAL"
            add_event(state, "info", "paused manually", tid)
        else:
            st.paused_until = 0
            add_event(state, "info", "resumed manually", tid)
        save_fn()
        return

    tunnels = await discover_fn()
    tmap = {t["id"]: t for t in tunnels}

    if kind == "reset_all":
        for t in tunnels:
            st = state.tunnels[str(t["id"])]
            asyncio.create_task(coordinated_reset(t, st, CFG, agent, logger, state, locks[t["id"]]))
        add_event(state, "action", "reset all triggered")
        save_fn()
        return

    if tid is None:
        return
    t = tmap.get(tid)
    st = state.tunnels.get(str(tid))
    if not t or not st:
        return

    if kind == "reset":
        asyncio.create_task(coordinated_reset(t, st, CFG, agent, logger, state, locks[tid]))
        add_event(state, "action", "manual reset triggered", tid)
        save_fn()
        return

    # For down/up/restart: coordinator does local + remote with ack rules
    try:
        if kind == "down":
            await agent.call("/v1/iface/down", {"iface": t["iface_remote"]}, must_ok=True)
            await ip_link_set(t["iface_local"], up=False)
            add_event(state, "action", "manual down ok", tid)
        elif kind == "up":
            await ip_link_set(t["iface_local"], up=True)
            await agent.call("/v1/iface/up", {"iface": t["iface_remote"]}, must_ok=True)
            add_event(state, "action", "manual up ok", tid)
        elif kind == "restart":
            await agent.call("/v1/iface/restart", {"iface": t["iface_remote"]}, must_ok=True)
            await ip_link_set(t["iface_local"], up=False)
            await ip_link_set(t["iface_local"], up=True)
            add_event(state, "action", "manual restart ok", tid)
        save_fn()
    except Exception as e:
        add_event(state, "error", f"manual action failed: {e}", tid)
        save_fn()

def read_log():
    # ساده: آخرین 400 خط
    import os
    p = os.path.join(CFG["log_dir"], "gre-watchdog-coordinator.log")
    try:
        with open(p, "r") as f:
            lines = f.readlines()[-400:]
        return "".join(lines)
    except Exception as e:
        return f"cannot read log: {e}"

router = build_router(state, CFG, logger, do_action, read_log)
app.include_router(router)

from fastapi import Request, HTTPException

@app.post("/cli/action")
async def cli_action(req: Request):
    tok = req.headers.get("x-cli-token", "")
    if not tok or tok != CFG.get("cli_token", ""):
        raise HTTPException(401, "unauthorized")

    data = await req.json()
    action = data.get("action")
    tid = data.get("tunnel_id")

    # reuse same do_action
    await do_action(action, tid)
    return {"ok": True, "action": action, "tunnel_id": tid}

@app.on_event("startup")
async def startup():
    add_event(state, "info", "coordinator started")
    save_fn()
    async def reset_fn(tunnel, st, lock):
        await coordinated_reset(tunnel, st, CFG, agent, logger, state, lock)
        save_fn()
    asyncio.create_task(monitor_loop(discover_fn, state, CFG, locks, reset_fn, save_fn, state, logger))
