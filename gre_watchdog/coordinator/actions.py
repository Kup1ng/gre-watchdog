import asyncio, time
from gre_watchdog.common.state import add_event

async def ip_link_set(iface: str, up: bool):
    proc = await asyncio.create_subprocess_exec(
        "ip", "link", "set", "dev", iface, "up" if up else "down",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
    )
    out = (await proc.stdout.read()).decode(errors="ignore").strip()
    if proc.returncode != 0:
        raise RuntimeError(out or "ip link failed")
    return out

def prune_window(times: list[float], window_sec: int = 1800) -> list[float]:
    cut = time.time() - window_sec
    return [t for t in times if t >= cut]

async def coordinated_reset(tunnel, st, cfg, agent, logger, app_state, lock):
    tid = tunnel["id"]

    async with lock:  # هر تونل فقط یک reset همزمان
        if time.time() < st.paused_until:
            add_event(app_state, "info", "reset skipped (paused)", tid)
            return

        st.status = "RESETTING"
        st.last_action = "reset_start"
        st.last_reset_started_at = time.time()
        add_event(app_state, "action", "reset started", tid)

        # Rate limit window
        st.resets_window = prune_window(st.resets_window)
        if len(st.resets_window) >= cfg["max_resets_per_30min"]:
            st.paused_until = time.time() + cfg["pause_after_limit_min"] * 60
            st.status = "PAUSED"
            st.last_action = "paused_due_to_rate_limit"
            add_event(app_state, "warn", "paused due to reset rate limit", tid)
            return

        # 1) اول remote DOWN (اگر remote down fail شد، ادامه نده)
        try:
            await agent.call("/v1/iface/down", {"iface": tunnel["iface_remote"]}, must_ok=True)
        except Exception as e:
            st.status = "ERROR"
            st.last_action = "remote_down_failed"
            st.last_error = str(e)
            add_event(app_state, "error", f"remote down failed: {e}", tid)
            return

        # 2) سپس local DOWN (اگر local down fail شد، سعی کن remote up کنی)
        try:
            await ip_link_set(tunnel["iface_local"], up=False)
        except Exception as e:
            st.status = "ERROR"
            st.last_action = "local_down_failed"
            st.last_error = str(e)
            add_event(app_state, "error", f"local down failed: {e}", tid)
            # rollback remote up
            try:
                await agent.call("/v1/iface/up", {"iface": tunnel["iface_remote"]}, must_ok=False)
            except:
                pass
            return

        # 3) hold 5min
        await asyncio.sleep(cfg["down_hold_sec"])

        # 4) local UP
        try:
            await ip_link_set(tunnel["iface_local"], up=True)
        except Exception as e:
            st.status = "ERROR"
            st.last_action = "local_up_failed"
            st.last_error = str(e)
            add_event(app_state, "error", f"local up failed: {e}", tid)
            return

        # 5) gap then remote UP (اگر remote up fail شد، status خطا بزن و دیگه چیزی رو ok حساب نکن)
        await asyncio.sleep(cfg["up_gap_sec"])
        try:
            await agent.call("/v1/iface/up", {"iface": tunnel["iface_remote"]}, must_ok=True)
        except Exception as e:
            st.status = "ERROR"
            st.last_action = "remote_up_failed"
            st.last_error = str(e)
            add_event(app_state, "error", f"remote up failed: {e}", tid)
            return

        st.resets_window.append(time.time())
        st.bad_rounds = 0
        st.status = "OK"
        st.last_action = "reset_done"
        st.last_error = ""
        st.last_reset_finished_at = time.time()
        add_event(app_state, "action", "reset done", tid)
