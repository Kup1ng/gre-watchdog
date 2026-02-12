import asyncio, time
from gre_watchdog.coordinator.ping import ping_loss_percent
from gre_watchdog.common.state import add_event

def ok_loss(loss: float, cfg: dict) -> bool:
    return loss < cfg["loss_ok_percent"]

async def check_tunnel(tunnel: dict, st, cfg, locks, reset_fn, app_state, logger):
    tid = tunnel["id"]

    st.last_seen = time.time()

    pub_loss, gre_loss = await asyncio.gather(
        ping_loss_percent(tunnel["peer_public"], cfg["ping_count"], cfg["ping_timeout_sec"]),
        ping_loss_percent(tunnel["peer_private"], cfg["ping_count"], cfg["ping_timeout_sec"]),
    )
    st.last_public_loss = pub_loss
    st.last_gre_loss = gre_loss

    pub_ok = ok_loss(pub_loss, cfg)
    gre_ok = ok_loss(gre_loss, cfg)

    if pub_ok and gre_ok:
        st.status = "OK"
        st.bad_rounds = 0
        st.last_action = "none"
        return

    if (not pub_ok) and (not gre_ok):
        st.status = "FILTERED_OR_DOWN"
        st.bad_rounds = 0
        st.last_action = "none"
        return

    if pub_ok and (not gre_ok):
        st.status = "PUBLIC_OK_GRE_BAD"
        st.bad_rounds += 1
        st.last_action = f"bad_round_{st.bad_rounds}"
        if st.bad_rounds >= cfg["confirm_bad_rounds"]:
            # reset در background ولی lock دارد که همزمان دوبار انجام نشود
            add_event(app_state, "warn", "reset triggered (confirmed)", tid)
            asyncio.create_task(reset_fn(tunnel, st, locks[tid]))
        return

    st.status = "WEIRD_PUBLIC_BAD_GRE_OK"
    st.bad_rounds = 0
    st.last_action = "none"

async def monitor_loop(discover_fn, state, cfg, locks, reset_fn, save_fn, app_state, logger):
    while True:
        tunnels = await discover_fn()
        # sync state list
        for t in tunnels:
            tid = str(t["id"])
            if tid not in state.tunnels:
                from gre_watchdog.common.state import TunnelState
                state.tunnels[tid] = TunnelState(
                    id=t["id"],
                    iface_local=t["iface_local"],
                    iface_remote=t["iface_remote"],
                    peer_public=t["peer_public"],
                    local_private=t["local_private"],
                    peer_private=t["peer_private"],
                )
                add_event(app_state, "info", "tunnel discovered", t["id"])

        # run checks concurrently for all tunnels
        tasks = []
        for t in tunnels:
            st = state.tunnels[str(t["id"])]
            tasks.append(check_tunnel(t, st, cfg, locks, reset_fn, app_state, logger))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        # persist state
        save_fn()

        await asyncio.sleep(cfg["check_interval_sec"])
