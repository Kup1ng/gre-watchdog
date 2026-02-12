# gre_watchdog/agent/gre_ops.py
import subprocess

def run(cmd: list[str]) -> str:
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if p.returncode != 0:
        raise RuntimeError(p.stdout.strip())
    return p.stdout.strip()

def iface_down(iface: str) -> str:
    return run(["ip", "link", "set", "dev", iface, "down"])

def iface_up(iface: str) -> str:
    return run(["ip", "link", "set", "dev", iface, "up"])

def iface_restart(iface: str) -> str:
    iface_down(iface)
    return iface_up(iface)
