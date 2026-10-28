"""Config browser: find every config file, group by mod, search, validate, version history."""
from __future__ import annotations

import json
import os
import re
import time
import tomllib
from pathlib import Path

import yaml
from fastapi import HTTPException

from . import files, mods

EXTS = {".toml", ".json", ".json5", ".cfg", ".properties", ".yml", ".yaml", ".txt", ".snbt", ".ini", ".conf"}
MAX_SIZE = 2_000_000

# Hand-tuned names for common config folders/prefixes that don't match a mod id
ALIASES = {"ae2": "Applied Energistics 2", "ftbquests": "FTB Quests", "ftbchunks": "FTB Chunks", "ftbessentials": "FTB Essentials",
           "ftbranks": "FTB Ranks", "neoforge": "NeoForge", "fml": "NeoForge (loader)", "jei": "Just Enough Items",
           "mekanism": "Mekanism", "allthemodium": "Allthemodium", "sophisticatedbackpacks": "Sophisticated Backpacks"}


def roots(srv) -> list[tuple[str, Path, str]]:
    sdir = srv.dir
    world = srv.world_path()
    out = [
        ("config", sdir / "config", "Main mod configs"),
        ("world", world / "serverconfig", "This world's server configs"),
        ("defaults", sdir / "defaultconfigs", "Defaults copied into new worlds"),
        ("kubejs", sdir / "kubejs" / "config", "KubeJS"),
    ]
    return [(k, p, label) for k, p, label in out if p.is_dir()]


def _side(name: str) -> str:
    n = name.lower()
    if re.search(r"(^|[-_.])client([-_.]|$)", n):
        return "client"
    if re.search(r"(^|[-_.])server([-_.]|$)", n):
        return "server"
    if re.search(r"(^|[-_.])common([-_.]|$)", n):
        return "common"
    return ""


def _group(rel_parts: tuple[str, ...]) -> str:
    """Guess which mod a config belongs to from its folder or file name."""
    first = rel_parts[0]
    if len(rel_parts) > 1:
        return first.lower()
    stem = first.split(".")[0]
    stem = re.split(r"[-_](client|server|common|config|general|startup)\b", stem, flags=re.I)[0]
    stem = re.split(r"-", stem)[0]
    return stem.lower() or first.lower()


def _mod_names(srv) -> dict[str, str]:
    names = {}
    try:
        for m in mods.listing(srv):
            if m.get("id"):
                names[m["id"].lower()] = m["name"]
    except Exception:
        pass
    names.update(ALIASES)
    return names


def listing(srv) -> dict:
    names = _mod_names(srv)
    groups: dict[str, dict] = {}
    count = 0
    sdir = srv.dir
    for key, root, label in roots(srv):
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for fn in filenames:
                p = Path(dirpath) / fn
                if p.suffix.lower() not in EXTS or fn.startswith("."):
                    continue
                try:
                    st = p.stat()
                except OSError:
                    continue
                if st.st_size > MAX_SIZE:
                    continue
                parts = p.relative_to(root).parts
                gid = _group(parts)
                g = groups.setdefault(gid, {"id": gid, "name": names.get(gid) or gid.replace("_", " ").title(), "files": []})
                g["files"].append({
                    "path": str(p.relative_to(sdir)).replace("\\", "/"),
                    "name": "/".join(parts),
                    "where": key, "where_label": label,
                    "side": _side(fn), "size": st.st_size, "mtime": st.st_mtime,
                })
                count += 1
                if count > 6000:
                    break
    out = sorted(groups.values(), key=lambda g: g["name"].lower())
    for g in out:
        g["files"].sort(key=lambda f: (f["where"] != "config", f["name"]))
    return {"groups": out, "count": count, "roots": [{"key": k, "label": l, "path": str(p.relative_to(sdir))} for k, p, l in roots(srv)]}


def search(srv, q: str, limit: int = 300) -> list[dict]:
    """Find settings by name or value inside config files."""
    q = q.strip().lower()
    if len(q) < 2:
        return []
    sdir = srv.dir
    hits = []
    for _, root, _ in roots(srv):
        for dirpath, _, filenames in os.walk(root):
            for fn in filenames:
                p = Path(dirpath) / fn
                if p.suffix.lower() not in EXTS:
                    continue
                try:
                    if p.stat().st_size > MAX_SIZE:
                        continue
                    text = p.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                low = text.lower()
                if q not in low and q not in fn.lower():
                    continue
                lines = []
                for i, line in enumerate(text.splitlines(), 1):
                    if q in line.lower():
                        lines.append({"line": i, "text": line.strip()[:200]})
                        if len(lines) >= 8:
                            break
                hits.append({"path": str(p.relative_to(sdir)).replace("\\", "/"), "lines": lines,
                             "name_match": q in fn.lower()})
                if len(hits) >= limit:
                    return hits
    hits.sort(key=lambda h: (not h["name_match"], -len(h["lines"])))
    return hits


def validate(path: str, content: str) -> dict:
    ext = Path(path).suffix.lower()
    try:
        if ext == ".toml":
            tomllib.loads(content)
        elif ext == ".json":
            json.loads(content)
        elif ext in (".yml", ".yaml"):
            yaml.safe_load(content)
        else:
            return {"ok": True, "checked": False}
        return {"ok": True, "checked": True}
    except tomllib.TOMLDecodeError as e:
        m = re.search(r"line (\d+)", str(e))
        return {"ok": False, "error": str(e), "line": int(m.group(1)) if m else None}
    except json.JSONDecodeError as e:
        return {"ok": False, "error": f"{e.msg} (line {e.lineno}, column {e.colno})", "line": e.lineno}
    except yaml.YAMLError as e:
        line = getattr(getattr(e, "problem_mark", None), "line", None)
        return {"ok": False, "error": str(e).splitlines()[0], "line": line + 1 if line is not None else None}


def _hist_key(path: str) -> str:
    return path.replace("\\", "/").lstrip("/").replace("/", "__")


def versions(srv, path: str) -> list[dict]:
    files.resolve(srv, path)
    hist = srv.data / "recycle-bin" / "_edits"
    if not hist.is_dir():
        return []
    key = _hist_key(path)
    out = []
    for f in hist.glob(f"{glob_escape(key)}.*"):
        ts = f.name[len(key) + 1:]
        if ts.isdigit():
            out.append({"id": f.name, "saved": int(ts), "size": f.stat().st_size})
    return sorted(out, key=lambda v: v["saved"], reverse=True)


def glob_escape(s: str) -> str:
    return re.sub(r"([*?\[])", r"[\1]", s)


def read_version(srv, path: str, vid: str) -> str:
    if not any(v["id"] == vid for v in versions(srv, path)):
        raise HTTPException(404, "Version not found")
    return (srv.data / "recycle-bin" / "_edits" / vid).read_text(encoding="utf-8", errors="replace")
