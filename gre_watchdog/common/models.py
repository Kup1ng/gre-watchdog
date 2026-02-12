# gre_watchdog/common/models.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Literal, Dict, Any

TunnelStatus = Literal[
    "INIT",
    "OK",
    "FILTERED_OR_DOWN",
    "PUBLIC_OK_GRE_BAD",
    "WEIRD_PUBLIC_BAD_GRE_OK",
    "RESETTING",
    "ERROR",
    "PAUSED",
    "PAUSED_MANUAL",
]

ActionKind = Literal[
    "reset",
    "down",
    "up",
    "restart",
    "pause",
    "resume",
    "reset_all",
]

@dataclass(frozen=True)
class TunnelInfo:
    """
    Discovered tunnel information (runtime snapshot).
    """
    id: int
    iface_local: str
    iface_remote: str
    peer_public: str
    local_private: str
    peer_private: str

@dataclass(frozen=True)
class AgentResult:
    ok: bool
    command_id: str
    iface: str
    out: Optional[str] = None
    error: Optional[str] = None

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "AgentResult":
        return AgentResult(
            ok=bool(d.get("ok", False)),
            command_id=str(d.get("command_id", "")),
            iface=str(d.get("iface", "")),
            out=d.get("out"),
            error=d.get("error"),
        )

@dataclass(frozen=True)
class PingResult:
    ip: str
    loss_percent: float
    ok: bool
