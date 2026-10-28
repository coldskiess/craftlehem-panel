"""Mod list: reads NeoForge/Forge/Fabric metadata from jars."""
from __future__ import annotations

import json
import re
import tomllib
import zipfile
from pathlib import Path

from fastapi import HTTPException


_cache: dict[str, tuple[tuple, dict]] = {}


def mods_dir(srv) -> Path:
    d = srv.dir / "mods"
    d.mkdir(exist_ok=True)
    return d


def _manifest_version(z: zipfile.ZipFile) -> str | None:
    try:
        mf = z.read("META-INF/MANIFEST.MF").decode("utf-8", "replace")
        m = re.search(r"^Implementation-Version:\s*(.+)$", mf, re.M)
        return m.group(1).strip() if m else None
    except KeyError:
        return None


def _parse(path: Path) -> dict:
    info = {"loader": None, "mods": []}
    try:
        with zipfile.ZipFile(path) as z:
            names = set(z.namelist())
            for toml_name, loader in (("META-INF/neoforge.mods.toml", "neoforge"), ("META-INF/mods.toml", "forge")):
                if toml_name in names:
                    raw = z.read(toml_name).decode("utf-8", "replace")
                    try:
                        data = tomllib.loads(raw)
                    except tomllib.TOMLDecodeError:
                        data = {}
                    info["loader"] = loader
                    info["logo"] = data.get("logoFile")
                    for m in data.get("mods", []):
                        ver = str(m.get("version", ""))
                        if "${" in ver:
                            ver = _manifest_version(z) or ver
                        info["mods"].append({
                            "id": m.get("modId"),
                            "name": m.get("displayName") or m.get("modId"),
                            "version": ver,
                            "description": (m.get("description") or "").strip()[:400],
                            "authors": m.get("authors") if isinstance(m.get("authors"), str) else ", ".join(m.get("authors") or []),
                        })
                        info["logo"] = m.get("logoFile") or info.get("logo")
                    break
            else:
                if "fabric.mod.json" in names:
                    data = json.loads(z.read("fabric.mod.json").decode("utf-8", "replace"), strict=False)
                    info["loader"] = "fabric"
                    info["logo"] = data.get("icon") if isinstance(data.get("icon"), str) else None
                    authors = data.get("authors") or []
                    info["mods"].append({
                        "id": data.get("id"), "name": data.get("name") or data.get("id"),
                        "version": data.get("version"), "description": (data.get("description") or "")[:400],
                        "authors": ", ".join(a if isinstance(a, str) else a.get("name", "") for a in authors),
                    })
            if info.get("logo") and info["logo"] not in names:
                info["logo"] = None
    except (zipfile.BadZipFile, OSError) as e:
        info["error"] = f"Couldn't read jar ({e.__class__.__name__})"
    return info


def listing(srv) -> list[dict]:
    out = []
    for p in sorted(mods_dir(srv).iterdir(), key=lambda x: x.name.lower()):
        if not p.is_file():
            continue
        enabled = p.suffix == ".jar"
        if not (enabled or p.name.endswith(".jar.disabled")):
            continue
        st = p.stat()
        key = (st.st_size, st.st_mtime)
        cached = _cache.get(str(p))
        if not cached or cached[0] != key:
            cached = (key, _parse(p))
            _cache[str(p)] = cached
        meta = cached[1]
        primary = meta["mods"][0] if meta["mods"] else {}
        out.append({
            "file": p.name,
            "enabled": enabled,
            "size": st.st_size,
            "mtime": st.st_mtime,
            "loader": meta.get("loader"),
            "id": primary.get("id"),
            "name": primary.get("name") or p.name.removesuffix(".disabled").removesuffix(".jar"),
            "version": primary.get("version"),
            "description": primary.get("description"),
            "authors": primary.get("authors"),
            "bundled": [m["id"] for m in meta["mods"][1:]],
            "has_logo": bool(meta.get("logo")),
            "error": meta.get("error"),
        })
    return out


def _file(srv, name: str) -> Path:
    p = (mods_dir(srv) / Path(name).name)
    if not p.is_file():
        raise HTTPException(404, "Mod file not found")
    return p


def logo(srv, name: str) -> tuple[bytes, str] | None:
    p = _file(srv, name)
    meta = _cache.get(str(p), (None, _parse(p)))[1]
    if not meta.get("logo"):
        return None
    with zipfile.ZipFile(p) as z:
        data = z.read(meta["logo"])
    return data, "image/png"


def toggle(srv, name: str, enabled: bool) -> str:
    p = _file(srv, name)
    if enabled and p.name.endswith(".jar.disabled"):
        dest = p.with_name(p.name.removesuffix(".disabled"))
    elif not enabled and p.suffix == ".jar":
        dest = p.with_name(p.name + ".disabled")
    else:
        return p.name
    p.rename(dest)
    _cache.pop(str(p), None)
    return dest.name
