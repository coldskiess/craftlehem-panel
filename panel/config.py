"""Panel configuration (config.yml): loading, saving, migration and per-server settings."""
from __future__ import annotations

import os
import re
import secrets
import shutil
import threading
from pathlib import Path

import yaml

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = Path(os.environ.get("PANEL_CONFIG", BASE_DIR / "config.yml"))
VERSION = "1.2.0"


def detect_timezone() -> str:
    """The machine's own time zone, so schedules run on local time out of the box."""
    tz = os.environ.get("TZ")
    if tz and "/" in tz:
        return tz
    try:
        t = Path("/etc/timezone").read_text().strip()
        if t:
            return t
    except OSError:
        pass
    try:
        link = os.readlink("/etc/localtime")
        m = re.search(r"zoneinfo/(.+)$", link)
        if m:
            return m.group(1)
    except OSError:
        pass
    return "UTC"


PANEL_DEFAULTS = {
    "title": "Craftlehem Panel",
    "host": "0.0.0.0",
    "port": 8080,
    "secret_key": "",          # generated on first run
    "session_hours": 72,
    "data_dir": "data",        # panel state (relative to panel folder)
    "secure_cookies": False,   # set true when served over HTTPS
    "timezone": "",            # blank = the machine's time zone
    "check_updates": True,     # once a day, ask GitHub if a newer release exists
}

SERVER_DEFAULTS = {
    "id": "main",
    "name": "My Server",
    "dir": "",
    # NeoForge server packs ship run.sh (uses user_jvm_args.txt). Avoid a pack's
    # startserver.sh if it has its own restart loop - the panel handles restarts.
    "start_command": "bash run.sh nogui",
    "tmux_session": "minecraft",
    "stop_timeout": 180,         # seconds to wait for a clean stop before killing
    "auto_restart_on_crash": True,
    "start_with_panel": True,    # bring the server back after a reboot if it was running
    "max_crash_restarts": 3,     # within 10 minutes, then give up
    "address": "",               # what players type to join (shown on the dashboard)
    "rcon": {"host": "127.0.0.1", "port": None, "password": None},  # blank = from server.properties
    "backups": {
        "dir": "",               # blank = <server folder>/../backups (or backups-<id> for extra servers)
        "keep": 10,              # automatic backups kept beyond this are deleted
        "include": [],           # extra paths relative to the server folder; world is always included
        "compression": "gzip",   # gzip | zstd (needs the zstd program - much faster)
    },
}

_lock = threading.RLock()
_config: dict = {}


def _merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def _migrate(raw: dict) -> tuple[dict, bool]:
    """v1.0/1.1 kept one server under server:/rcon:/backups:. Move it into servers: [...]."""
    if "servers" in raw or "server" not in raw:
        return raw, False
    old = dict(raw.pop("server") or {})
    old["rcon"] = raw.pop("rcon", {}) or {}
    old["backups"] = raw.pop("backups", {}) or {}
    old["id"] = "main"
    raw["servers"] = [old]
    return raw, True


def load() -> dict:
    global _config
    with _lock:
        raw = {}
        if CONFIG_PATH.exists():
            raw = yaml.safe_load(CONFIG_PATH.read_text()) or {}
        raw, changed = _migrate(raw)
        cfg = {
            "panel": _merge(PANEL_DEFAULTS, raw.get("panel") or {}),
            "servers": [_merge(SERVER_DEFAULTS, s) for s in (raw.get("servers") or [])] or [dict(SERVER_DEFAULTS)],
            "users": raw.get("users") or [],
        }
        for k, v in raw.items():  # keep unknown top-level sections (e.g. written by Pro)
            cfg.setdefault(k, v)
        if not cfg["panel"].get("secret_key"):
            cfg["panel"]["secret_key"] = secrets.token_urlsafe(48)
            changed = True
        _config = cfg
    if changed or not CONFIG_PATH.exists():
        save()
    _migrate_data()
    return _config


def get() -> dict:
    if not _config:
        load()
    return _config


def save() -> None:
    with _lock:
        tmp = CONFIG_PATH.with_suffix(".tmp")
        tmp.write_text(yaml.safe_dump(_config, sort_keys=False, allow_unicode=True))
        os.chmod(tmp, 0o600)
        tmp.replace(CONFIG_PATH)


def timezone() -> str:
    return get()["panel"].get("timezone") or detect_timezone()


def data_dir() -> Path:
    d = Path(get()["panel"]["data_dir"])
    if not d.is_absolute():
        d = BASE_DIR / d
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------- servers
def servers() -> list[dict]:
    return get()["servers"]


def server_cfg(sid: str) -> dict:
    for s in servers():
        if s["id"] == sid:
            return s
    raise KeyError(sid)


def server_data_dir(sid: str) -> Path:
    d = data_dir() / "servers" / sid
    d.mkdir(parents=True, exist_ok=True)
    return d


def server_backup_dir(sid: str) -> Path:
    s = server_cfg(sid)
    d = s["backups"].get("dir")
    if not d:
        base = Path(s["dir"]).expanduser().resolve().parent
        d = base / ("backups" if sid == servers()[0]["id"] else f"backups-{sid}")
    d = Path(d).expanduser()
    d.mkdir(parents=True, exist_ok=True)
    return d.resolve()


def new_server_id(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:20] or "server"
    sid, n = base, 2
    taken = {s["id"] for s in servers()}
    while sid in taken:
        sid, n = f"{base}-{n}", n + 1
    return sid


def _migrate_data():
    """Move v1.0/1.1 single-server state files into data/servers/main/."""
    root = data_dir()
    first = servers()[0]["id"]
    target = None
    for name in ("players.json", "console.log", "console.prev.log", "run.json", "launch.sh",
                 "schedule.json", "schedule_state.json", "recycle-bin"):
        src = root / name
        if src.exists():
            target = target or server_data_dir(first)
            dest = target / name
            if not dest.exists():
                shutil.move(str(src), str(dest))
