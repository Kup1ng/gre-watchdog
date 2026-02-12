import time
from fastapi import APIRouter, Request, HTTPException, Form
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse
from jinja2 import Template
from gre_watchdog.common.security import new_token, Session

TEMPLATE = Template("""
<html>
<head><meta charset="utf-8"><title>GRE Watchdog</title></head>
<body style="font-family:sans-serif;max-width:1100px;margin:20px auto">
  <h2>GRE Watchdog</h2>
  <p>Logged in as: {{user}}</p>
  <form method="post" action="/logout"><button>Logout</button></form>

  <h3>Tunnels</h3>
  <table border="1" cellpadding="6" cellspacing="0" style="width:100%">
    <tr>
      <th>ID</th><th>Status</th><th>Public loss%</th><th>GRE loss%</th><th>Bad rounds</th>
      <th>Paused until</th><th>Last action</th><th>Actions</th>
    </tr>
    {% for t in tunnels %}
    <tr>
      <td>{{t.id}}</td>
      <td>{{t.status}}</td>
      <td>{{"%.1f"|format(t.last_public_loss)}}</td>
      <td>{{"%.1f"|format(t.last_gre_loss)}}</td>
      <td>{{t.bad_rounds}}</td>
      <td>{{t.paused_until_h}}</td>
      <td>{{t.last_action}}</td>
      <td>
        <form method="post" action="/action/reset/{{t.id}}" style="display:inline"><button>Reset</button></form>
        <form method="post" action="/action/down/{{t.id}}"  style="display:inline"><button>Down</button></form>
        <form method="post" action="/action/up/{{t.id}}"    style="display:inline"><button>Up</button></form>
        <form method="post" action="/action/restart/{{t.id}}" style="display:inline"><button>Restart</button></form>
        <form method="post" action="/action/pause/{{t.id}}" style="display:inline"><button>Pause</button></form>
        <form method="post" action="/action/resume/{{t.id}}" style="display:inline"><button>Resume</button></form>
      </td>
    </tr>
    {% endfor %}
  </table>

  <h3>Global actions</h3>
  <form method="post" action="/action/reset_all"><button>Reset ALL</button></form>

  <h3>Recent events</h3>
  <pre style="background:#f4f4f4;padding:10px;height:260px;overflow:auto">{{events}}</pre>

  <h3>Logs</h3>
  <p><a href="/logs/coordinator">Open coordinator log</a></p>
</body>
</html>
""")

LOGIN_TEMPLATE = Template("""
<html><head><meta charset="utf-8"><title>Login</title></head>
<body style="font-family:sans-serif;max-width:400px;margin:50px auto">
<h2>Login</h2>
{% if err %}<p style="color:red">{{err}}</p>{% endif %}
<form method="post" action="/login">
  <label>Username</label><br>
  <input name="username" /><br><br>
  <label>Password</label><br>
  <input type="password" name="password" /><br><br>
  <button>Login</button>
</form>
</body></html>
""")

def build_router(state, cfg, logger, do_action, read_log):
    r = APIRouter()
    sessions: dict[str, Session] = {}

    def get_session(req: Request) -> Session | None:
        tok = req.cookies.get("gw_session", "")
        s = sessions.get(tok)
        if not s:
            return None
        if time.time() > s.expires_at:
            sessions.pop(tok, None)
            return None
        return s

    def require_login(req: Request) -> Session:
        s = get_session(req)
        if not s:
            raise HTTPException(401, "login required")
        return s

    @r.get("/login", response_class=HTMLResponse)
    async def login_page():
        return LOGIN_TEMPLATE.render(err="")

    @r.post("/login")
    async def login(username: str = Form(...), password: str = Form(...)):
        if username != cfg["panel_username"] or password != cfg["panel_password"]:
            return HTMLResponse(LOGIN_TEMPLATE.render(err="bad credentials"), status_code=401)
        tok = new_token()
        ttl = cfg["panel_session_ttl_min"] * 60
        sessions[tok] = Session(token=tok, username=username, expires_at=time.time() + ttl)
        resp = RedirectResponse("/", status_code=303)
        resp.set_cookie("gw_session", tok, httponly=True, secure=False, samesite="lax")
        return resp

    @r.post("/logout")
    async def logout(req: Request):
        tok = req.cookies.get("gw_session", "")
        sessions.pop(tok, None)
        resp = RedirectResponse("/login", status_code=303)
        resp.delete_cookie("gw_session")
        return resp

    @r.get("/", response_class=HTMLResponse)
    async def index(req: Request):
        s = get_session(req)
        if not s:
            return RedirectResponse("/login", status_code=303)

        tunnels = []
        for k, t in sorted(state.tunnels.items(), key=lambda x: int(x[0])):
            paused = "-" if t.paused_until <= time.time() else time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t.paused_until))
            tunnels.append(type("T", (), {
                "id": t.id,
                "status": t.status,
                "last_public_loss": t.last_public_loss,
                "last_gre_loss": t.last_gre_loss,
                "bad_rounds": t.bad_rounds,
                "paused_until_h": paused,
                "last_action": t.last_action
            })())

        # events
        lines = []
        for e in state.events[-200:]:
            ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(e["ts"]))
            tid = e.get("tunnel_id", "-")
            lines.append(f"{ts} [{e['kind']}] tid={tid} {e['msg']}")
        events_txt = "\n".join(lines)

        return TEMPLATE.render(user=s.username, tunnels=tunnels, events=events_txt)

    # Actions
    @r.post("/action/reset/{tid}")
    async def action_reset(req: Request, tid: int):
        require_login(req)
        await do_action("reset", tid)
        return RedirectResponse("/", status_code=303)

    @r.post("/action/down/{tid}")
    async def action_down(req: Request, tid: int):
        require_login(req)
        await do_action("down", tid)
        return RedirectResponse("/", status_code=303)

    @r.post("/action/up/{tid}")
    async def action_up(req: Request, tid: int):
        require_login(req)
        await do_action("up", tid)
        return RedirectResponse("/", status_code=303)

    @r.post("/action/restart/{tid}")
    async def action_restart(req: Request, tid: int):
        require_login(req)
        await do_action("restart", tid)
        return RedirectResponse("/", status_code=303)

    @r.post("/action/pause/{tid}")
    async def action_pause(req: Request, tid: int):
        require_login(req)
        await do_action("pause", tid)
        return RedirectResponse("/", status_code=303)

    @r.post("/action/resume/{tid}")
    async def action_resume(req: Request, tid: int):
        require_login(req)
        await do_action("resume", tid)
        return RedirectResponse("/", status_code=303)

    @r.post("/action/reset_all")
    async def action_reset_all(req: Request):
        require_login(req)
        await do_action("reset_all", None)
        return RedirectResponse("/", status_code=303)

    @r.get("/logs/coordinator", response_class=PlainTextResponse)
    async def logs(req: Request):
        require_login(req)
        return read_log()

    return r
