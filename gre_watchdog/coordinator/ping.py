import asyncio, re

async def ping_loss_percent(ip: str, count: int, timeout_sec: int) -> float:
    proc = await asyncio.create_subprocess_exec(
        "ping", "-c", str(count), "-W", str(timeout_sec), ip,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
    )
    out = (await proc.stdout.read()).decode(errors="ignore")
    m = re.search(r"(\d+(?:\.\d+)?)%\s*packet loss", out)
    if not m:
        return 100.0
    return float(m.group(1))
