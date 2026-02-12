import json, time, random, uuid
import httpx
from gre_watchdog.common.security import hmac_sign

class AgentClient:
    def __init__(self, base_url: str, secret: str, timeout_sec: int, max_attempts: int,
                 base_backoff_ms: int, max_backoff_ms: int, logger):
        self.base = base_url.rstrip("/")
        self.secret = secret
        self.timeout = timeout_sec
        self.max_attempts = max_attempts
        self.base_backoff = base_backoff_ms
        self.max_backoff = max_backoff_ms
        self.logger = logger

    def _headers(self, body: bytes) -> dict:
        ts = str(int(time.time()))
        sig = hmac_sign(self.secret, body, ts)
        return {"x-ts": ts, "x-sig": sig}

    async def call(self, path: str, payload: dict, must_ok: bool = True) -> dict:
        # command_id برای idempotency
        payload = dict(payload)
        payload.setdefault("command_id", str(uuid.uuid4()))
        body = json.dumps(payload).encode()

        backoff = self.base_backoff / 1000.0
        last_err = None

        for attempt in range(1, self.max_attempts + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as c:
                    r = await c.post(self.base + path, content=body, headers=self._headers(body))
                    r.raise_for_status()
                    data = r.json()
                    if must_ok and not data.get("ok", False):
                        raise RuntimeError(data.get("error", "agent error"))
                    return data
            except Exception as e:
                last_err = e
                self.logger.warning(f"agent call fail attempt={attempt}/{self.max_attempts} path={path} err={e}")
                if attempt == self.max_attempts:
                    break
                # exponential backoff + jitter
                await self._sleep(backoff)
                backoff = min(backoff * 2, self.max_backoff / 1000.0)

        raise RuntimeError(f"agent call failed after retries: {last_err}")

    async def _sleep(self, seconds: float):
        # jitter
        await __import__("asyncio").sleep(seconds * (0.7 + random.random() * 0.6))
