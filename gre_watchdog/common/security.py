# gre_watchdog/common/security.py
import hmac, hashlib, time, secrets
from dataclasses import dataclass

def hmac_sign(secret: str, body: bytes, ts: str) -> str:
    msg = ts.encode() + b"." + body
    return hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()

def hmac_verify(secret: str, body: bytes, ts: str, sig: str, max_skew_sec: int) -> bool:
    try:
        t = int(ts)
    except:
        return False
    if abs(int(time.time()) - t) > max_skew_sec:
        return False
    good = hmac_sign(secret, body, ts)
    return hmac.compare_digest(good, sig)

def new_token() -> str:
    return secrets.token_urlsafe(32)

@dataclass
class Session:
    token: str
    username: str
    expires_at: float
