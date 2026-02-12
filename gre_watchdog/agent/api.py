# gre_watchdog/agent/api.py
import json, ipaddress
from fastapi import FastAPI, Request, HTTPException
from gre_watchdog.common.security import hmac_verify
from gre_watchdog.agent.gre_ops import iface_down, iface_up, iface_restart
from gre_watchdog.agent.idempotency import IdempotencyStore

def cidr_allowed(client_ip: str, cidrs: list[str]) -> bool:
    ip = ipaddress.ip_address(client_ip)
    for c in cidrs:
        if ip in ipaddress.ip_network(c, strict=False):
            return True
    return False

def build_agent_app(cfg: dict, logger):
    app = FastAPI()
    store = IdempotencyStore(cfg["idempotency_ttl_sec"])

    def auth(req: Request, body: bytes):
        client_ip = req.client.host if req.client else "0.0.0.0"
        if not cidr_allowed(client_ip, cfg.get("allow_cidrs", ["0.0.0.0/0"])):
            raise HTTPException(403, "forbidden")

        ts = req.headers.get("x-ts", "")
        sig = req.headers.get("x-sig", "")
        ok = hmac_verify(cfg["shared_secret"], body, ts, sig, cfg["max_clock_skew_sec"])
        if not ok:
            raise HTTPException(401, "unauthorized")

    async def handle(req: Request, op):
        body = await req.body()
        auth(req, body)
        data = json.loads(body.decode())
        cmd_id = data.get("command_id")
        iface = data.get("iface")

        if not cmd_id or not iface:
            raise HTTPException(400, "command_id and iface required")

        cached = store.get(cmd_id)
        if cached:
            return cached["value"]  # همان پاسخ قبلی: idempotent

        try:
            out = op(iface)
            res = {"ok": True, "command_id": cmd_id, "iface": iface, "out": out}
            store.set(cmd_id, res)
            logger.info(f"cmd {cmd_id} ok iface={iface}")
            return res
        except Exception as e:
            res = {"ok": False, "command_id": cmd_id, "iface": iface, "error": str(e)}
            store.set(cmd_id, res)
            logger.error(f"cmd {cmd_id} fail iface={iface} err={e}")
            return res

    @app.post("/v1/iface/down")
    async def down(req: Request):
        return await handle(req, iface_down)

    @app.post("/v1/iface/up")
    async def up(req: Request):
        return await handle(req, iface_up)

    @app.post("/v1/iface/restart")
    async def restart(req: Request):
        return await handle(req, iface_restart)

    @app.get("/health")
    async def health():
        return {"ok": True}

    return app
