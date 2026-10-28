"""Scheduled tasks (per server): restarts, backups, commands and broadcasts."""
from __future__ import annotations

import asyncio
import json
import secrets
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from . import config, server as servers

KINDS = {
    "restart": "Restart the server (players get a countdown)",
    "backup": "Back up the world",
    "command": "Run a console command",
    "broadcast": "Broadcast a message to players",
    "start": "Start the server if it's off",
    "stop": "Stop the server (players get a countdown)",
}


def _path(srv):
    return srv.data / "schedule.json"


def _state_path(srv):
    return srv.data / "schedule_state.json"


def tz() -> ZoneInfo:
    try:
        return ZoneInfo(config.timezone())
    except Exception:
        return ZoneInfo("UTC")


def load(srv) -> list[dict]:
    try:
        return json.loads(_path(srv).read_text())
    except Exception:
        return []


def save(srv, tasks: list[dict]):
    _path(srv).write_text(json.dumps(tasks, indent=1))


def defaults() -> list[dict]:
    return [
        {"id": "nightly-restart", "name": "Nightly restart", "kind": "restart", "enabled": True,
         "mode": "daily", "times": ["05:00"], "days": [0, 1, 2, 3, 4, 5, 6], "warn_minutes": 5,
         "arg": "Daily restart", "only_if_online": True},
        {"id": "backup-6h", "name": "Backup every 6 hours", "kind": "backup", "enabled": True,
         "mode": "interval", "every_minutes": 360, "only_if_played": True},
    ]


def validate(t: dict) -> dict:
    kind = t.get("kind")
    if kind not in KINDS:
        raise ValueError("Unknown task type")
    out = {
        "id": t.get("id") or secrets.token_hex(4),
        "name": (t.get("name") or KINDS[kind])[:60],
        "kind": kind,
        "enabled": bool(t.get("enabled", True)),
        "mode": "interval" if t.get("mode") == "interval" else "daily",
        "arg": (t.get("arg") or "")[:500],
        "only_if_online": bool(t.get("only_if_online", kind in ("restart", "command", "broadcast"))),
        "only_if_played": bool(t.get("only_if_played", False)),
        "warn_minutes": max(0, min(30, int(t.get("warn_minutes") or 0))),
    }
    if out["mode"] == "interval":
        out["every_minutes"] = max(5, int(t.get("every_minutes") or 60))
    else:
        times = []
        for s in t.get("times") or []:
            hh, mm = str(s).strip().split(":")
            if not (0 <= int(hh) < 24 and 0 <= int(mm) < 60):
                raise ValueError(f"{s} isn't a valid time")
            times.append(f"{int(hh):02d}:{int(mm):02d}")
        if not times:
            raise ValueError("Add at least one time")
        out["times"] = sorted(set(times))
        out["days"] = sorted({int(d) for d in (t.get("days") if t.get("days") is not None else range(7)) if 0 <= int(d) <= 6})
        if not out["days"]:
            raise ValueError("Pick at least one day")
    if kind in ("command", "broadcast") and not out["arg"]:
        raise ValueError("This task needs a command/message")
    return out


def state(srv) -> dict:
    try:
        return json.loads(_state_path(srv).read_text())
    except Exception:
        return {}


def set_state(srv, st: dict):
    _state_path(srv).write_text(json.dumps(st))


def _lead(task) -> int:
    return task.get("warn_minutes", 0) * 60 if task["kind"] in ("restart", "stop") else 0


def next_run(srv, task: dict, now: float | None = None) -> float | None:
    if not task.get("enabled"):
        return None
    now = now or time.time()
    st = state(srv).get(task["id"], {})
    if task["mode"] == "interval":
        last = st.get("last_run") or st.get("created") or now
        return max(last + task["every_minutes"] * 60, now)
    z = tz()
    local = datetime.fromtimestamp(now, z)
    for add in range(8):
        d = (local + timedelta(days=add)).date()
        if d.weekday() not in task["days"]:
            continue
        for t in task["times"]:
            hh, mm = map(int, t.split(":"))
            when = datetime(d.year, d.month, d.day, hh, mm, tzinfo=z).timestamp()
            if when - _lead(task) > now - 1:
                return when
    return None


async def _execute(srv, task: dict) -> str:
    kind, arg = task["kind"], task.get("arg", "")
    online = srv.status == "online"
    who = f"schedule:{task['name']}"
    if task.get("only_if_online") and not online and kind != "start":
        return "skipped (server offline)"
    if kind in ("restart", "stop"):
        if not srv.session_alive():
            return "skipped (server offline)"
        r = await srv.countdown_action(kind, task.get("warn_minutes", 0) * 60 or 10, who, arg)
        return "countdown started" if r == "ok" else r
    if kind == "start":
        return await srv.start(who) if not srv.session_alive() else "skipped (already running)"
    if kind == "backup":
        from . import backups
        if task.get("only_if_played"):
            last = state(srv).get(task["id"], {}).get("prev_run", 0)
            played = srv.players or any(p.get("last_seen", 0) > last for p in srv.db.values())
            if not played:
                return "skipped (nobody played since last backup)"
        r = await backups.create(srv, who, note=task["name"], auto=True)
        return "backup made" if r == "ok" else r
    if kind == "command":
        out = await srv.command(arg)
        return (out or "sent")[:200]
    if kind == "broadcast":
        await srv.say(arg)
        return "sent"
    return "unknown"


async def run_now(srv, task_id: str, user: str) -> str:
    task = next((t for t in load(srv) if t["id"] == task_id), None)
    if not task:
        return "Task not found"
    srv.activity(user, "ran task", task["name"])
    _mark(srv, task)
    return await _record(srv, task, await _execute(srv, task))


def _mark(srv, task):
    st = state(srv)
    entry = st.setdefault(task["id"], {})
    entry["prev_run"] = entry.get("last_run", 0)
    entry["last_run"] = time.time()
    set_state(srv, st)


async def _record(srv, task, result) -> str:
    st = state(srv)
    st.setdefault(task["id"], {}).update(last_result=result)
    set_state(srv, st)
    await srv.broadcast({"type": "schedule"})
    return result


def ensure(srv):
    """First run for a server: create the default tasks."""
    if not _path(srv).exists():
        save(srv, defaults())
    st = state(srv)
    for t in load(srv):
        st.setdefault(t["id"], {}).setdefault("created", time.time())
    set_state(srv, st)


def _due(srv, task, now) -> bool:
    s = state(srv).get(task["id"], {})
    if task["mode"] == "interval":
        last = s.get("last_run") or s.get("created") or now
        return now >= last + task["every_minutes"] * 60
    z = tz()
    local = datetime.fromtimestamp(now, z)
    for t in task["times"]:
        hh, mm = map(int, t.split(":"))
        for add in (-1, 0, 1):
            d = (local + timedelta(days=add)).date()
            if d.weekday() not in task["days"]:
                continue
            fire = datetime(d.year, d.month, d.day, hh, mm, tzinfo=z).timestamp() - _lead(task)
            if fire <= now < fire + 600 and s.get("last_run", 0) < fire:   # 10 minute grace, once
                return True
    return False


async def loop():
    while True:
        try:
            now = time.time()
            for srv in list(servers.registry.values()):
                ensure(srv)
                for task in load(srv):
                    if task.get("enabled") and _due(srv, task, now):
                        _mark(srv, task)   # record first so a slow task can't fire twice
                        asyncio.create_task(_run_task(srv, task))
        except Exception as e:
            print("scheduler error", e)
        await asyncio.sleep(10)


async def _run_task(srv, task):
    try:
        result = await _execute(srv, task)
    except Exception as e:
        result = f"error: {e}"
    srv.activity("schedule", task["name"], str(result))
    await _record(srv, task, result)


def overview(srv) -> list[dict]:
    ensure(srv)
    st = state(srv)
    out = []
    for t in load(srv):
        s = st.get(t["id"], {})
        out.append({**t, "last_run": s.get("last_run"), "last_result": s.get("last_result"),
                    "next_run": next_run(srv, t)})
    return out
