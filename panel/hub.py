"""Live event hub (websocket fan-out) and the panel activity log."""
from __future__ import annotations

import asyncio
import json
import time
from collections import deque

from . import config

_clients: set = set()
_activity: deque = deque(maxlen=500)
_loaded = False


def _activity_file():
    return config.data_dir() / "activity.jsonl"


def _load():
    global _loaded
    if _loaded:
        return
    _loaded = True
    f = _activity_file()
    if f.exists():
        for line in f.read_text().splitlines()[-500:]:
            try:
                _activity.append(json.loads(line))
            except Exception:
                pass


def add_client(ws):
    _clients.add(ws)


def remove_client(ws):
    _clients.discard(ws)


async def broadcast(msg: dict):
    if not _clients:
        return
    data = json.dumps(msg)
    dead = []
    for ws in list(_clients):
        try:
            await asyncio.wait_for(ws.send_text(data), 5)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _clients.discard(ws)


def activity(user: str, action: str, detail: str = "", server: str | None = None):
    """Record who did what. Safe to call from sync code."""
    _load()
    entry = {"t": time.time(), "user": user, "action": action, "detail": detail[:500]}
    if server:
        entry["server"] = server
    _activity.append(entry)
    try:
        f = _activity_file()
        with f.open("a") as fh:
            fh.write(json.dumps(entry) + "\n")
        if f.stat().st_size > 2_000_000:  # trim
            lines = f.read_text().splitlines()[-2000:]
            f.write_text("\n".join(lines) + "\n")
    except Exception:
        pass
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(broadcast({"type": "activity", "entry": entry}))
    except RuntimeError:
        pass


def recent_activity(limit: int = 200) -> list:
    _load()
    return list(_activity)[-limit:][::-1]
