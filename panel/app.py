"""HTTP + websocket API."""
from __future__ import annotations

import asyncio
import gzip
import json
import secrets
import shutil
import time
from contextlib import asynccontextmanager
from pathlib import Path

import psutil
from fastapi import Body, Depends, FastAPI, File, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import auth, backups, config, configs, files, hub, mods, pro_loader, properties, scheduler, update_check
from . import server as servers
from .server import Server

STATIC = config.BASE_DIR / "static"
VERSION = config.VERSION


async def _housekeeping():
    while True:
        try:
            for srv in list(servers.registry.values()):
                files.trash_empty(srv, older_than_days=14)
        except Exception as e:
            print("housekeeping", e)
        await asyncio.sleep(6 * 3600)


@asynccontextmanager
async def lifespan(app):
    config.load()
    pro_loader.load(app)          # may raise servers.max_servers
    servers.load_all()
    tasks = [asyncio.create_task(scheduler.loop()), asyncio.create_task(_housekeeping()),
             asyncio.create_task(update_check.loop())]
    pro_loader.started()
    yield
    for srv in servers.registry.values():
        srv.save_db()
    for t in tasks:
        t.cancel()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=STATIC), name="static")

viewer = Depends(auth.require("viewer"))
mod = Depends(auth.require("moderator"))
admin = Depends(auth.require("admin"))


def current_server(request: Request) -> Server:
    """Which server a request is about: X-Server header (from the UI) or ?server= (for links)."""
    sid = request.headers.get("x-server") or request.query_params.get("server")
    srv = servers.get(sid)
    if not srv:
        raise HTTPException(503, "No server is set up yet")
    return srv


SRV = Depends(current_server)


def ok(**kw):
    return {"ok": True, **kw}


def result(msg: str, **kw):
    """Turn a control-function message into an API response."""
    if msg == "ok" or msg.startswith("ok"):
        return ok(message=msg[4:] if len(msg) > 3 else "", **kw)
    raise HTTPException(409, msg)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "same-origin"
    if request.url.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


@app.get("/", response_class=HTMLResponse)
async def index():
    html = (STATIC / "index.html").read_text()
    extra = "".join(pro_loader.frontend_tags())
    return (html.replace("{{TITLE}}", config.get()["panel"]["title"]).replace("{{V}}", VERSION)
            .replace("<!--PRO-->", extra))


# ------------------------------------------------------------------- auth
@app.post("/api/login")
async def login(request: Request, body: dict = Body(...)):
    # Behind a Cloudflare Tunnel every request arrives from cloudflared, so use the visitor's real IP
    ip = request.headers.get("cf-connecting-ip") or (request.client.host if request.client else "?")
    if auth.rate_limited(ip):
        raise HTTPException(429, "Too many failed logins - wait 10 minutes")
    user = auth.find_user(str(body.get("username", "")))
    if not user or not auth.verify_password(str(body.get("password", "")), user["password_hash"]):
        auth.record_failure(ip)
        await asyncio.sleep(0.8)
        raise HTTPException(401, "Wrong username or password")
    resp = JSONResponse(ok(user={"username": user["username"], "role": user["role"]}))
    resp.set_cookie(auth.COOKIE, auth.make_session(user), httponly=True, samesite="strict",
                    secure=bool(config.get()["panel"].get("secure_cookies")),
                    max_age=int(config.get()["panel"]["session_hours"]) * 3600)
    hub.activity(user["username"], "logged in", ip)
    return resp


@app.post("/api/logout")
async def logout():
    resp = JSONResponse(ok())
    resp.delete_cookie(auth.COOKIE)
    return resp


@app.get("/api/me")
async def me(user=viewer):
    return {"username": user["username"], "role": user["role"], "title": config.get()["panel"]["title"],
            "version": VERSION, "roles": auth.ROLE_HELP, "pro": pro_loader.status(),
            "update": update_check.info() if auth.has_role(user, "admin") else None}


@app.post("/api/me/password")
async def change_password(body: dict = Body(...), user=viewer):
    if not auth.verify_password(body.get("current", ""), user["password_hash"]):
        raise HTTPException(400, "Current password is wrong")
    new = body.get("new", "")
    if len(new) < 8:
        raise HTTPException(400, "Use at least 8 characters")
    user["password_hash"] = auth.hash_password(new)
    user["session_version"] = user.get("session_version", 0) + 1
    config.save()
    hub.activity(user["username"], "changed password")
    resp = JSONResponse(ok())
    resp.set_cookie(auth.COOKIE, auth.make_session(user), httponly=True, samesite="strict",
                    secure=bool(config.get()["panel"].get("secure_cookies")))
    return resp


# ---------------------------------------------------------------- servers
@app.get("/api/servers")
async def server_list(user=viewer):
    return [{"id": s.id, "name": s.name, "status": s.status, "players": len(s.players),
             "address": s.cfg.get("address")} for s in servers.registry.values()]


# ----------------------------------------------------------------- status
@app.get("/api/status")
async def status(user=viewer, srv=SRV):
    return srv.snapshot()


@app.get("/api/history")
async def history(user=viewer, srv=SRV):
    return list(srv.history)


@app.post("/api/power")
async def power(body: dict = Body(...), user=mod, srv=SRV):
    action = body.get("action")
    name = user["username"]
    if action == "start":
        return result(await srv.start(name))
    if action == "stop":
        asyncio.create_task(srv.stop(name))
        return ok(message="Stopping...")
    if action == "restart":
        asyncio.create_task(srv.restart(name))
        return ok(message="Restarting...")
    if action == "kill":
        return result(await srv.kill(name))
    raise HTTPException(400, "Unknown action")


@app.post("/api/countdown")
async def countdown(body: dict = Body(...), user=mod, srv=SRV):
    if not srv.session_alive():
        raise HTTPException(409, "Server isn't running")
    secs = max(5, min(3600, int(body.get("seconds", 60))))
    action = "stop" if body.get("action") == "stop" else "restart"
    return result(await srv.countdown_action(action, secs, user["username"], str(body.get("reason", ""))[:80]))


@app.delete("/api/countdown")
async def cancel_countdown(user=mod, srv=SRV):
    return result(await srv.cancel_countdown(user["username"]))


# ---------------------------------------------------------------- console
@app.get("/api/console")
async def console(since: int = 0, user=viewer, srv=SRV):
    return [e for e in srv.console if e[0] > since]


@app.post("/api/console")
async def console_send(body: dict = Body(...), user=mod, srv=SRV):
    cmd = str(body.get("command", "")).strip()
    if not cmd:
        raise HTTPException(400, "Empty command")
    if not srv.session_alive():
        raise HTTPException(409, "Server isn't running")
    if cmd.lstrip("/").split()[0].lower() == "stop":
        srv.intentional_stop = True
        srv.status = "stopping"
    srv._add_line(f"> {cmd}   [{user['username']}]", process=False)
    srv.send_console(cmd)
    srv.activity(user["username"], "console", cmd)
    return ok()


@app.websocket("/ws")
async def ws(websocket: WebSocket):
    user = auth.ws_user(websocket)
    if not user:
        await websocket.close(code=4401)
        return
    await websocket.accept()
    hub.add_client(websocket)
    try:
        for srv in list(servers.registry.values()):
            await websocket.send_text(json.dumps({"type": "status", "server": srv.id, "status": srv.snapshot()}))
        while True:
            msg = await websocket.receive_text()
            if msg == "ping":
                await websocket.send_text('{"type":"pong"}')
    except WebSocketDisconnect:
        pass
    finally:
        hub.remove_client(websocket)


# ---------------------------------------------------------------- players
def _json_list(srv, name: str) -> list:
    try:
        return json.loads((srv.dir / name).read_text())
    except Exception:
        return []


@app.get("/api/players")
async def players(user=viewer, srv=SRV):
    online = {p["name"].lower() for p in srv.player_list()}
    known = [{**p, "online": p["name"].lower() in online}
             for p in sorted(srv.db.values(), key=lambda p: p.get("last_seen", 0), reverse=True)]
    props = properties.read(srv)
    return {
        "online": srv.player_list(),
        "known": known,
        "whitelist": _json_list(srv, "whitelist.json"),
        "whitelist_enabled": props.get("white-list") == "true",
        "ops": _json_list(srv, "ops.json"),
        "banned": _json_list(srv, "banned-players.json"),
        "banned_ips": _json_list(srv, "banned-ips.json"),
    }


def _edit_json_list(srv, name: str, player: str):
    data = [e for e in _json_list(srv, name) if e.get("name", "").lower() != player.lower()]
    (srv.dir / name).write_text(json.dumps(data, indent=2))


@app.post("/api/players/action")
async def player_action(body: dict = Body(...), user=mod, srv=SRV):
    action = body.get("action")
    name = str(body.get("name", "")).strip()
    reason = str(body.get("reason", "")).strip().replace("\n", " ")[:200]
    if not name or not all(c.isalnum() or c in "_." for c in name):
        raise HTTPException(400, "Invalid player name")
    offline_ok = {"whitelist_remove": "whitelist.json", "deop": "ops.json", "pardon": "banned-players.json"}
    if not srv.session_alive():
        if action in offline_ok:
            _edit_json_list(srv, offline_ok[action], name)
            srv.activity(user["username"], action, name)
            return ok(message="Updated (server is offline)")
        raise HTTPException(409, "Start the server first - this needs it running")
    if action in ("op", "deop") and not auth.has_role(user, "admin"):
        raise HTTPException(403, "Only admins can change operators")
    cmds = {
        "kick": f"kick {name} {reason or 'Kicked by an admin'}",
        "ban": f"ban {name} {reason or 'Banned by an admin'}",
        "pardon": f"pardon {name}",
        "op": f"op {name}",
        "deop": f"deop {name}",
        "whitelist_add": f"whitelist add {name}",
        "whitelist_remove": f"whitelist remove {name}",
        "message": f"tellraw {name} " + json.dumps([{"text": "[Admin] ", "color": "gold"}, {"text": reason, "color": "white"}]),
    }
    if action not in cmds:
        raise HTTPException(400, "Unknown action")
    if action == "message" and not reason:
        raise HTTPException(400, "Type a message")
    out = await srv.command(cmds[action])
    srv.activity(user["username"], action.replace("_", " "), f"{name} {reason}".strip())
    return ok(message=out or "Sent")


@app.post("/api/players/whitelist-mode")
async def whitelist_mode(body: dict = Body(...), user=admin, srv=SRV):
    on = bool(body.get("enabled"))
    if srv.session_alive():
        await srv.command(f"whitelist {'on' if on else 'off'}")
    else:
        properties.write(srv, {"white-list": "true" if on else "false"})
    srv.activity(user["username"], f"whitelist {'on' if on else 'off'}")
    return ok()


# ------------------------------------------------------------------- mods
@app.get("/api/mods")
async def mod_list(user=viewer, srv=SRV):
    return await asyncio.to_thread(mods.listing, srv)


@app.get("/api/mods/logo")
async def mod_logo(file: str, user=viewer, srv=SRV):
    res = await asyncio.to_thread(mods.logo, srv, file)
    if not res:
        raise HTTPException(404)
    return Response(res[0], media_type=res[1], headers={"Cache-Control": "max-age=86400"})


@app.post("/api/mods/toggle")
async def mod_toggle(body: dict = Body(...), user=admin, srv=SRV):
    new = mods.toggle(srv, body["file"], bool(body.get("enabled")))
    srv.activity(user["username"], "enabled mod" if body.get("enabled") else "disabled mod", new)
    return ok(file=new, restart_needed=srv.session_alive())


@app.post("/api/mods/upload")
async def mod_upload(upload: list[UploadFile] = File(...), user=admin, srv=SRV):
    saved = []
    for f in upload:
        name = Path(f.filename or "").name
        if not name.endswith(".jar"):
            raise HTTPException(400, f"{name} isn't a .jar")
        dest = mods.mods_dir(srv) / name
        tmp = dest.with_name(dest.name + ".uploading")
        with tmp.open("wb") as out:
            shutil.copyfileobj(f.file, out, 1024 * 1024)
        tmp.replace(dest)
        saved.append(name)
    srv.activity(user["username"], "uploaded mods", ", ".join(saved))
    return ok(files=saved, restart_needed=srv.session_alive())


@app.post("/api/mods/delete")
async def mod_delete(body: dict = Body(...), user=admin, srv=SRV):
    name = Path(body["file"]).name
    files.delete(srv, "mods/" + name)
    srv.activity(user["username"], "deleted mod", name)
    return ok()


# ------------------------------------------------------------------ files
@app.get("/api/files")
async def file_list(path: str = "", user=admin, srv=SRV):
    return files.listing(srv, path)


@app.get("/api/files/read")
async def file_read(path: str, user=admin, srv=SRV):
    return files.read_text(srv, path)


@app.put("/api/files/write")
async def file_write(body: dict = Body(...), user=admin, srv=SRV):
    r = files.write_text(srv, body["path"], body.get("content", ""), body.get("mtime"))
    srv.activity(user["username"], "edited file", body["path"])
    return ok(**r)


@app.post("/api/files/upload")
async def file_upload(path: str = "", upload: list[UploadFile] = File(...), user=admin, srv=SRV):
    d = files.resolve(srv, path)
    if not d.is_dir():
        raise HTTPException(400, "Upload target isn't a folder")
    saved = []
    for f in upload:
        # folder uploads include sub-paths
        relname = (f.filename or "file").replace("\\", "/").lstrip("/")
        dest = files.resolve(srv, files.rel(srv, d) + "/" + relname)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".uploading")
        with tmp.open("wb") as out:
            shutil.copyfileobj(f.file, out, 1024 * 1024)
        tmp.replace(dest)
        saved.append(files.rel(srv, dest))
    srv.activity(user["username"], "uploaded files", ", ".join(saved)[:300])
    return ok(files=saved)


@app.get("/api/files/download")
async def file_download(path: str, user=admin, srv=SRV):
    p = files.resolve(srv, path)
    if p.is_dir():
        z = await asyncio.to_thread(files.zip_folder, srv, path)
        return FileResponse(z, filename=z.name)
    if not p.is_file():
        raise HTTPException(404)
    return FileResponse(p, filename=p.name)


@app.post("/api/files/delete")
async def file_delete(body: dict = Body(...), user=admin, srv=SRV):
    for p in body.get("paths") or [body.get("path")]:
        files.delete(srv, p)
        srv.activity(user["username"], "deleted", p)
    return ok()


@app.post("/api/files/rename")
async def file_rename(body: dict = Body(...), user=admin, srv=SRV):
    new = files.rename(srv, body["path"], body["name"])
    srv.activity(user["username"], "renamed", f"{body['path']} -> {new}")
    return ok(path=new)


@app.post("/api/files/move")
async def file_move(body: dict = Body(...), user=admin, srv=SRV):
    new = files.move(srv, body["path"], body["dest"])
    srv.activity(user["username"], "moved", f"{body['path']} -> {new}")
    return ok(path=new)


@app.post("/api/files/mkdir")
async def file_mkdir(body: dict = Body(...), user=admin, srv=SRV):
    return ok(path=files.mkdir(srv, body["path"]))


@app.post("/api/files/extract")
async def file_extract(body: dict = Body(...), user=admin, srv=SRV):
    out = await asyncio.to_thread(files.extract, srv, body["path"])
    srv.activity(user["username"], "extracted", body["path"])
    return ok(path=out)


@app.get("/api/trash")
async def trash(user=admin, srv=SRV):
    return files.trash_list(srv)


@app.post("/api/trash/restore")
async def trash_restore(body: dict = Body(...), user=admin, srv=SRV):
    p = files.trash_restore(srv, body["id"])
    srv.activity(user["username"], "restored from recycle bin", p)
    return ok(path=p)


@app.post("/api/trash/empty")
async def trash_empty(user=admin, srv=SRV):
    files.trash_empty(srv, 0)
    srv.activity(user["username"], "emptied recycle bin")
    return ok()


# ---------------------------------------------------------------- configs
@app.get("/api/configs")
async def config_list(user=admin, srv=SRV):
    return await asyncio.to_thread(configs.listing, srv)


@app.get("/api/configs/search")
async def config_search(q: str, user=admin, srv=SRV):
    return await asyncio.to_thread(configs.search, srv, q)


@app.post("/api/configs/validate")
async def config_validate(body: dict = Body(...), user=admin):
    return configs.validate(body["path"], body.get("content", ""))


@app.put("/api/configs/save")
async def config_save(body: dict = Body(...), user=admin, srv=SRV):
    path, content = body["path"], body.get("content", "")
    check = configs.validate(path, content)
    if not check["ok"] and not body.get("force"):
        raise HTTPException(422, check["error"] + (f" (line {check['line']})" if check.get("line") and "line" not in check["error"] else ""))
    r = files.write_text(srv, path, content, body.get("mtime"))
    srv.activity(user["username"], "edited config", path + (f" ({body['summary']})" if body.get("summary") else ""))
    return ok(**r, restart_needed=srv.session_alive())


@app.get("/api/configs/versions")
async def config_versions(path: str, user=admin, srv=SRV):
    return configs.versions(srv, path)


@app.get("/api/configs/version")
async def config_version(path: str, id: str, user=admin, srv=SRV):
    return {"content": configs.read_version(srv, path, id)}


# ------------------------------------------------------------------- logs
@app.get("/api/logs")
async def logs(user=viewer, srv=SRV):
    out = []
    for folder in ("logs", "crash-reports"):
        d = srv.dir / folder
        if d.is_dir():
            for f in d.iterdir():
                if f.is_file() and (f.suffix in (".log", ".gz", ".txt")):
                    st = f.stat()
                    out.append({"file": f"{folder}/{f.name}", "size": st.st_size, "mtime": st.st_mtime,
                                "crash": folder == "crash-reports"})
    for name in ("console.log", "console.prev.log"):
        f = srv.data / name
        if f.exists():
            out.append({"file": f"panel/{name}", "size": f.stat().st_size, "mtime": f.stat().st_mtime, "crash": False})
    out.sort(key=lambda x: x["mtime"], reverse=True)
    return out


@app.get("/api/logs/view")
async def log_view(file: str, user=viewer, srv=SRV):
    if file.startswith("panel/"):
        if Path(file).name not in ("console.log", "console.prev.log"):
            raise HTTPException(400)
        p = srv.data / Path(file).name
    else:
        folder, _, name = file.partition("/")
        if folder not in ("logs", "crash-reports"):
            raise HTTPException(400)
        p = srv.dir / folder / Path(name).name
    if not p.is_file():
        raise HTTPException(404)

    def read():
        if p.suffix == ".gz":
            with gzip.open(p, "rb") as fh:
                data = fh.read(8_000_000)
        else:
            size = p.stat().st_size
            with p.open("rb") as fh:
                if size > 8_000_000:
                    fh.seek(size - 8_000_000)
                data = fh.read()
        return data.decode("utf-8", "replace")

    return {"file": file, "content": await asyncio.to_thread(read)}


# ---------------------------------------------------------------- backups
@app.get("/api/backups")
async def backup_list(user=viewer, srv=SRV):
    bdir = srv.backup_dir
    du = shutil.disk_usage(bdir)
    return {"backups": backups.listing(srv), "job": backups.job(srv), "dir": str(bdir),
            "keep": srv.cfg["backups"]["keep"], "disk_free": du.free}


@app.post("/api/backups")
async def backup_create(body: dict = Body(default={}), user=mod, srv=SRV):
    if backups.job(srv):
        raise HTTPException(409, f"A {backups.job(srv)['kind']} is already running")
    asyncio.create_task(backups.create(srv, user["username"], str(body.get("note", ""))[:200]))
    await asyncio.sleep(0.2)
    return ok(message="Backup started")


@app.delete("/api/backups/{name}")
async def backup_delete(name: str, user=admin, srv=SRV):
    backups.delete(srv, name)
    srv.activity(user["username"], "deleted backup", name)
    return ok()


@app.patch("/api/backups/{name}")
async def backup_patch(name: str, body: dict = Body(...), user=mod, srv=SRV):
    backups.update_meta(srv, name, body.get("note"), body.get("locked"))
    return ok()


@app.get("/api/backups/{name}/download")
async def backup_download(name: str, user=admin, srv=SRV):
    p = backups.path(srv, name)
    return FileResponse(p, filename=p.name)


@app.post("/api/backups/{name}/restore")
async def backup_restore(name: str, user=admin, srv=SRV):
    return result(await backups.restore(srv, name, user["username"]))


# --------------------------------------------------------------- schedule
@app.get("/api/schedule")
async def schedule(user=viewer, srv=SRV):
    return {"tasks": scheduler.overview(srv), "kinds": scheduler.KINDS,
            "timezone": str(scheduler.tz()), "now": time.time()}


@app.post("/api/schedule")
async def schedule_save(body: dict = Body(...), user=admin, srv=SRV):
    try:
        task = scheduler.validate(body)
    except (ValueError, TypeError) as e:
        raise HTTPException(400, str(e) or "Invalid task")
    tasks = scheduler.load(srv)
    ids = [t["id"] for t in tasks]
    if task["id"] in ids:
        tasks[ids.index(task["id"])] = task
    else:
        tasks.append(task)
    scheduler.save(srv, tasks)
    st = scheduler.state(srv)
    st.setdefault(task["id"], {}).setdefault("created", time.time())
    scheduler.set_state(srv, st)
    srv.activity(user["username"], "saved scheduled task", task["name"])
    return ok(task=task)


@app.delete("/api/schedule/{task_id}")
async def schedule_delete(task_id: str, user=admin, srv=SRV):
    scheduler.save(srv, [t for t in scheduler.load(srv) if t["id"] != task_id])
    srv.activity(user["username"], "deleted scheduled task", task_id)
    return ok()


@app.post("/api/schedule/{task_id}/run")
async def schedule_run(task_id: str, user=mod, srv=SRV):
    return ok(message=await scheduler.run_now(srv, task_id, user["username"]))


# --------------------------------------------------------------- settings
@app.get("/api/settings")
async def settings(user=viewer, srv=SRV):
    props = properties.read(srv)
    known = {f[0] for f in properties.FIELDS}
    cfg = config.get()
    is_admin = auth.has_role(user, "admin")
    scfg = srv.cfg
    return {
        "properties": props,
        "fields": [{"key": k, "type": t, "help": h, "group": g} for k, t, h, g in properties.FIELDS],
        "other": sorted(k for k in props if k not in known),
        "jvm": properties.jvm_memory(srv),
        "system_ram": psutil.virtual_memory().total,
        "server": {k: v for k, v in scfg.items() if k not in ("rcon",)} if is_admin else None,
        "backups": {**scfg["backups"], "dir_effective": str(srv.backup_dir)} if is_admin else None,
        "panel": {"title": cfg["panel"]["title"], "timezone": config.timezone(),
                  "timezone_set": bool(cfg["panel"].get("timezone")),
                  "session_hours": cfg["panel"]["session_hours"]},
    }


@app.put("/api/settings/properties")
async def settings_props(body: dict = Body(...), user=admin, srv=SRV):
    updates = {str(k): str(v) for k, v in body.items() if "\n" not in str(k)}
    properties.write(srv, updates)
    srv.activity(user["username"], "edited server.properties", ", ".join(updates)[:300])
    return ok(restart_needed=srv.session_alive())


@app.post("/api/settings/enable-rcon")
async def enable_rcon(user=admin, srv=SRV):
    props = properties.read(srv)
    updates = {"enable-rcon": "true", "rcon.port": props.get("rcon.port") or "25575"}
    if not props.get("rcon.password"):
        updates["rcon.password"] = secrets.token_urlsafe(24)
    properties.write(srv, updates)
    srv.activity(user["username"], "enabled RCON")
    return ok(restart_needed=srv.session_alive())


@app.put("/api/settings/jvm")
async def settings_jvm(body: dict = Body(...), user=admin, srv=SRV):
    xmx = int(body.get("xmx_gb", 0))
    total_gb = psutil.virtual_memory().total / 1024**3
    if xmx < 2 or xmx > total_gb:
        raise HTTPException(400, f"Pick between 2 and {int(total_gb)} GB")
    properties.set_jvm_memory(srv, xmx, int(body["xms_gb"]) if body.get("xms_gb") else None)
    srv.activity(user["username"], "set server RAM", f"{xmx} GB")
    return ok(restart_needed=srv.session_alive())


@app.put("/api/settings/panel")
async def settings_panel(body: dict = Body(...), user=admin, srv=SRV):
    cfg = config.get()
    scfg = srv.cfg
    s = body.get("server") or {}
    if "dir" in s and not Path(str(s["dir"])).expanduser().is_dir():
        raise HTTPException(400, f"Folder {s['dir']} doesn't exist")
    for k in ("name", "dir", "start_command", "address", "stop_timeout", "auto_restart_on_crash",
              "max_crash_restarts", "start_with_panel"):
        if k in s:
            scfg[k] = s[k]
    bk = body.get("backups") or {}
    for k in ("dir", "keep", "include", "compression"):
        if k in bk:
            scfg["backups"][k] = bk[k]
    pn = body.get("panel") or {}
    if pn.get("title"):
        cfg["panel"]["title"] = pn["title"]
    if "timezone" in pn:
        tz = str(pn["timezone"]).strip()
        if tz:
            from zoneinfo import ZoneInfo
            try:
                ZoneInfo(tz)
            except Exception:
                raise HTTPException(400, f"{tz} isn't a time zone name (e.g. Australia/Melbourne, Europe/London)")
        cfg["panel"]["timezone"] = tz
    config.save()
    srv.activity(user["username"], "changed panel settings")
    return ok()


# ------------------------------------------------------------------ users
@app.get("/api/users")
async def users(user=admin):
    return [{"username": u["username"], "role": u["role"]} for u in config.get()["users"]]


@app.post("/api/users")
async def user_save(body: dict = Body(...), user=admin):
    name = str(body.get("username", "")).strip()
    role = body.get("role", "viewer")
    if role not in auth.ROLES or not name or not name.replace("_", "").replace("-", "").isalnum():
        raise HTTPException(400, "Bad username or role")
    existing = auth.find_user(name)
    pw = body.get("password") or ""
    if not existing and len(pw) < 8:
        raise HTTPException(400, "Password needs at least 8 characters")
    if existing:
        if existing is user and role != "admin":
            raise HTTPException(400, "You can't remove your own admin role")
        existing["role"] = role
        if pw:
            if len(pw) < 8:
                raise HTTPException(400, "Password needs at least 8 characters")
            existing["password_hash"] = auth.hash_password(pw)
            existing["session_version"] = existing.get("session_version", 0) + 1
    else:
        config.get()["users"].append({"username": name, "role": role, "password_hash": auth.hash_password(pw)})
    config.save()
    hub.activity(user["username"], "saved panel user", f"{name} ({role})")
    return ok()


@app.delete("/api/users/{name}")
async def user_delete(name: str, user=admin):
    if name.lower() == user["username"].lower():
        raise HTTPException(400, "You can't delete yourself")
    config.get()["users"] = [u for u in config.get()["users"] if u["username"].lower() != name.lower()]
    config.save()
    hub.activity(user["username"], "deleted panel user", name)
    return ok()


@app.get("/api/activity")
async def activity(user=viewer):
    return hub.recent_activity(300)


# -------------------------------------------------------------------- pro
@app.get("/api/pro")
async def pro_status(user=viewer):
    return pro_loader.status()


@app.post("/api/pro/upload")
async def pro_upload(upload: UploadFile = File(...), user=admin):
    """Install or update the Pro add-on from the zip buyers download from Gumroad."""
    try:
        msg = await asyncio.to_thread(pro_loader.install_zip, upload.file)
    except ValueError as e:
        raise HTTPException(400, str(e))
    hub.activity(user["username"], "installed Pro add-on", msg)
    restarting = pro_loader.schedule_restart()
    return ok(message=msg, restarting=restarting)
