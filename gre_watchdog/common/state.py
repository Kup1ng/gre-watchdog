# gre_watchdog/common/state.py
import os, json, time
from dataclasses import dataclass, asdict, field
from typing import Dict, List, Any

@dataclass
class TunnelState:
    id: int
    iface_local: str
    iface_remote: str
    peer_public: str
    local_private: str
    peer_private: str

    status: str = "INIT"
    bad_rounds: int = 0
    last_seen: float = 0
    last_public_loss: float = 100.0
    last_gre_loss: float = 100.0
    last_action: str = "-"
    paused_until: float = 0
    resets_window: List[float] = field(default_factory=list)

    last_error: str = ""
    last_reset_started_at: float = 0
    last_reset_finished_at: float = 0

@dataclass
class AppState:
    tunnels: Dict[str, TunnelState] = field(default_factory=dict)   # key = str(id)
    events: List[Dict[str, Any]] = field(default_factory=list)      # rolling events

def load_state(path: str) -> AppState:
    try:
        with open(path, "r") as f:
            raw = json.load(f)
        st = AppState()
        for k, v in raw.get("tunnels", {}).items():
            st.tunnels[k] = TunnelState(**v)
        st.events = raw.get("events", [])[-2000:]
        return st
    except:
        return AppState()

def save_state(path: str, state: AppState):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    raw = {
        "tunnels": {k: asdict(v) for k, v in state.tunnels.items()},
        "events": state.events[-2000:],
    }
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(raw, f)
    os.replace(tmp, path)

def add_event(state: AppState, kind: str, msg: str, tid: int | None = None, extra: dict | None = None):
    e = {"ts": time.time(), "kind": kind, "msg": msg}
    if tid is not None:
        e["tunnel_id"] = tid
    if extra:
        e["extra"] = extra
    state.events.append(e)
    state.events = state.events[-2000:]
