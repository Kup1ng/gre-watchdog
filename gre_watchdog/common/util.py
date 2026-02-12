# gre_watchdog/common/util.py
from __future__ import annotations
import os, time
from typing import Iterable, Any, List

def human_ts(ts: float) -> str:
    if not ts:
        return "-"
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))

def clamp(n: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, n))

def tail_file(path: str, lines: int = 400) -> str:
    """
    Return last N lines of a file. Safe for small/medium logs.
    """
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            data = f.readlines()
        return "".join(data[-lines:])
    except Exception as e:
        return f"cannot read log {path}: {e}"

def ensure_dir(p: str):
    os.makedirs(p, exist_ok=True)

def chunks(xs: List[Any], size: int) -> Iterable[List[Any]]:
    for i in range(0, len(xs), size):
        yield xs[i:i+size]
