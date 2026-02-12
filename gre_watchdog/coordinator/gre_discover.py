import asyncio, re, ipaddress

IFACE_LINE = re.compile(r"^\d+:\s+([^\s:]+)@")
PEER_LINE  = re.compile(r"link/gre\s+(\S+)\s+peer\s+(\S+)")
INET_LINE  = re.compile(r"\s+inet\s+(\d+\.\d+\.\d+\.\d+)/(\d+)")

async def sh(cmd: list[str]) -> str:
    p = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    out = (await p.stdout.read()).decode(errors="ignore")
    return out

def other_host_in_30(cidr_ip: str, mask: int) -> str:
    net = ipaddress.ip_network(f"{cidr_ip}/{mask}", strict=False)
    hosts = list(net.hosts())
    if len(hosts) == 2:
        return str(hosts[1]) if str(hosts[0]) == cidr_ip else str(hosts[0])
    # fallback
    for h in hosts:
        if str(h) != cidr_ip:
            return str(h)
    return cidr_ip

async def discover_gre(iface_regex: str) -> list[dict]:
    out = await sh(["ip", "-d", "addr", "show"])
    blocks = out.split("\n\n")
    r = re.compile(iface_regex)
    tunnels = []

    for b in blocks:
        m1 = IFACE_LINE.search(b)
        if not m1:
            continue
        iface = m1.group(1)
        m_id = r.match(iface)
        if not m_id:
            continue

        mpeer = PEER_LINE.search(b)
        minet = INET_LINE.search(b)
        if not (mpeer and minet):
            continue

        _, peer_pub = mpeer.group(1), mpeer.group(2)
        local_priv, mask = minet.group(1), int(minet.group(2))
        peer_priv = other_host_in_30(local_priv, mask)
        tid = int(m_id.group(1))

        tunnels.append({
            "id": tid,
            "iface_local": iface,
            "iface_remote": f"gre-kh-{tid}",
            "peer_public": peer_pub,
            "local_private": local_priv,
            "peer_private": peer_priv,
        })
    return tunnels
