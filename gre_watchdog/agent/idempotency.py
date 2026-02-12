import time
from typing import Dict

class IdempotencyStore:
    def __init__(self, ttl_sec: int):
        self.ttl = ttl_sec
        self.db: Dict[str, dict] = {}

    def get(self, key: str):
        self._gc()
        return self.db.get(key)

    def set(self, key: str, value: dict):
        self._gc()
        self.db[key] = {"ts": time.time(), "value": value}

    def _gc(self):
        now = time.time()
        dead = [k for k, v in self.db.items() if now - v["ts"] > self.ttl]
        for k in dead:
            self.db.pop(k, None)
