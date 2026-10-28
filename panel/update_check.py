"""Once a day, ask GitHub whether a newer release exists (turn off with panel.check_updates: false)."""
from __future__ import annotations

import asyncio
import json
import time
import urllib.request

from . import config

REPO = "coldskiess/craftlehem-panel"
_latest: dict = {}


def _ver(v: str) -> tuple:
    return tuple(int(x) for x in v.lstrip("v").split(".") if x.isdigit())


def _fetch() -> dict:
    req = urllib.request.Request(f"https://api.github.com/repos/{REPO}/releases/latest",
                                 headers={"User-Agent": f"craftlehem-panel/{config.VERSION}", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        d = json.loads(r.read())
    return {"version": d.get("tag_name", "").lstrip("v"), "url": d.get("html_url"), "checked": time.time()}


def info() -> dict | None:
    if _latest.get("version") and _ver(_latest["version"]) > _ver(config.VERSION):
        return {"version": _latest["version"], "url": _latest.get("url")}
    return None


async def loop():
    while True:
        if config.get()["panel"].get("check_updates", True):
            try:
                _latest.update(await asyncio.to_thread(_fetch))
            except Exception:
                pass   # offline, rate limited or no releases yet - try again tomorrow
        await asyncio.sleep(86400)
