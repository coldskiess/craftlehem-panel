"""Loads the optional Craftlehem Pro add-on (sold separately) if it has been installed.

The free panel is complete on its own. Pro lives in ./pro/ and plugs in through:
  panel_pro.setup(app)        - called once at startup; may add routes, event handlers and raise
                                panel.server.max_servers
  panel_pro.started()         - called once the event loop is running (background jobs)
  panel_pro.status() -> dict  - shown on Settings -> Pro
  panel_pro.frontend_tags()   - extra <script>/<link> tags for the page
"""
from __future__ import annotations

import io
import json
import os
import shutil
import sys
import zipfile
from pathlib import Path

from . import config

PRO_DIR = config.BASE_DIR / "pro"
BUY_URL = "https://coldskiess.gumroad.com/l/craftlehem-pro"
FEATURES = [
    {"id": "config_form", "name": "Config settings view",
     "text": "Edit mod configs with switches, dropdowns and checked number ranges instead of raw text."},
    {"id": "discord", "name": "Discord alerts",
     "text": "Crashes, restarts, backups, low TPS and player joins posted to your Discord."},
    {"id": "mod_updates", "name": "Mod update checker",
     "text": "See which mods have updates on Modrinth and CurseForge and install them in one click."},
    {"id": "multi_server", "name": "Multiple servers",
     "text": "Run and switch between several Minecraft servers from one panel."},
]

_module = None
_error: str | None = None


def installed() -> bool:
    return (PRO_DIR / "panel_pro" / "__init__.py").is_file()


def manifest() -> dict:
    try:
        return json.loads((PRO_DIR / "manifest.json").read_text())
    except Exception:
        return {}


def load(app):
    global _module, _error
    if not installed():
        return
    try:
        if str(PRO_DIR) not in sys.path:
            sys.path.insert(0, str(PRO_DIR))
        import panel_pro  # noqa: WPS433 (optional add-on)
        panel_pro.setup(app)
        _module = panel_pro
    except Exception as e:  # a broken add-on must never stop the free panel from starting
        _error = f"{e.__class__.__name__}: {e}"
        print("Pro add-on failed to load:", _error)


def started():
    if _module and hasattr(_module, "started"):
        try:
            _module.started()
        except Exception as e:
            print("Pro add-on start error:", e)


def status() -> dict:
    base = {"installed": installed(), "loaded": bool(_module), "error": _error, "buy_url": BUY_URL,
            "features": FEATURES, "version": manifest().get("version"), "licensed": False, "active": []}
    if _module:
        try:
            base.update(_module.status())
        except Exception as e:
            base["error"] = str(e)
    return base


def active(feature: str) -> bool:
    return feature in status().get("active", [])


def frontend_tags() -> list[str]:
    if not _module:
        return []
    try:
        return list(_module.frontend_tags())
    except Exception:
        return []


def install_zip(fileobj) -> str:
    """Unpack an uploaded Pro zip into ./pro (keeping the old copy as ./pro.old)."""
    data = fileobj.read()
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ValueError("That isn't a zip file")
    names = z.namelist()
    # accept either a zip with the files at the top or inside one folder
    prefix = ""
    if "manifest.json" not in names:
        tops = {n.split("/", 1)[0] for n in names if "/" in n}
        if len(tops) == 1 and f"{next(iter(tops))}/manifest.json" in names:
            prefix = next(iter(tops)) + "/"
    try:
        man = json.loads(z.read(prefix + "manifest.json"))
    except KeyError:
        raise ValueError("This zip isn't the Craftlehem Pro add-on (no manifest.json)")
    if man.get("name") != "craftlehem-pro" or f"{prefix}panel_pro/__init__.py" not in names:
        raise ValueError("This zip isn't the Craftlehem Pro add-on")
    need = man.get("requires_core")
    if need and _ver(config.VERSION) < _ver(need):
        raise ValueError(f"This Pro version needs panel {need} or newer (you have {config.VERSION}). Update the panel first.")
    new = PRO_DIR.with_name("pro.new")
    shutil.rmtree(new, ignore_errors=True)
    new.mkdir()
    for info in z.infolist():
        if not info.filename.startswith(prefix) or info.is_dir():
            continue
        rel = info.filename[len(prefix):]
        target = (new / rel).resolve()
        if new.resolve() not in target.parents:
            raise ValueError("Zip contains unsafe paths")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(z.read(info))
    old = PRO_DIR.with_name("pro.old")
    if PRO_DIR.exists():
        shutil.rmtree(old, ignore_errors=True)
        PRO_DIR.rename(old)
    new.rename(PRO_DIR)
    return f"Pro {man.get('version', '')} installed".strip()


def _ver(v: str) -> tuple:
    return tuple(int(x) for x in "".join(c for c in v if c in "0123456789.").split(".") if x)


def schedule_restart() -> bool:
    """Restart the panel process so new Python code loads. Minecraft keeps running (tmux).
    Only safe when a supervisor (systemd) will start us again."""
    if not os.environ.get("INVOCATION_ID"):
        return False
    import asyncio
    asyncio.get_event_loop().call_later(1.5, lambda: os._exit(0))
    return True

