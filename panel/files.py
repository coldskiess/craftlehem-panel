"""File manager confined to the server folder. Deletes go to a recycle bin."""
from __future__ import annotations

import mimetypes
import os
import shutil
import time
import zipfile
from pathlib import Path

from fastapi import HTTPException


TEXT_EXT = {
    ".txt", ".properties", ".json", ".json5", ".toml", ".yml", ".yaml", ".cfg", ".conf", ".ini",
    ".log", ".sh", ".bat", ".js", ".zs", ".mcmeta", ".snbt", ".md", ".csv", ".xml", ".lang", ".mcfunction",
}
MAX_EDIT = 3_000_000


def root(srv) -> Path:
    return srv.dir


def resolve(srv, rel: str) -> Path:
    rel = (rel or "").replace("\\", "/").lstrip("/")
    r = root(srv)
    p = (r / rel).resolve()
    if p != r and r not in p.parents:
        raise HTTPException(400, "Path is outside the server folder")
    return p


def rel(srv, p: Path) -> str:
    r = root(srv)
    return str(p.relative_to(r)).replace("\\", "/") if p != r else ""


def is_text(p: Path) -> bool:
    if p.suffix.lower() in TEXT_EXT or p.name in ("eula.txt", "ops.json", "whitelist.json"):
        return True
    if p.suffix:
        mt = mimetypes.guess_type(p.name)[0] or ""
        return mt.startswith("text/")
    try:
        with p.open("rb") as fh:
            chunk = fh.read(2048)
        return b"\x00" not in chunk
    except OSError:
        return False


def listing(srv, path: str) -> dict:
    d = resolve(srv, path)
    if not d.is_dir():
        raise HTTPException(404, "Folder not found")
    entries = []
    with os.scandir(d) as it:
        for e in it:
            try:
                st = e.stat(follow_symlinks=False)
            except OSError:
                continue
            is_dir = e.is_dir(follow_symlinks=False)
            entries.append({
                "name": e.name,
                "dir": is_dir,
                "size": None if is_dir else st.st_size,
                "mtime": st.st_mtime,
                "text": (not is_dir) and is_text(Path(e.path)),
                "link": e.is_symlink(),
            })
    entries.sort(key=lambda x: (not x["dir"], x["name"].lower()))
    return {"path": rel(srv, d), "entries": entries}


def read_text(srv, path: str) -> dict:
    p = resolve(srv, path)
    if not p.is_file():
        raise HTTPException(404, "File not found")
    if p.stat().st_size > MAX_EDIT:
        raise HTTPException(413, "File is too big to edit here - download it instead")
    data = p.read_bytes()
    if b"\x00" in data[:4096]:
        raise HTTPException(415, "That's a binary file - download it instead")
    return {"path": rel(srv, p), "content": data.decode("utf-8", "replace"), "mtime": p.stat().st_mtime}


def write_text(srv, path: str, content: str, expected_mtime: float | None = None) -> dict:
    p = resolve(srv, path)
    if expected_mtime and p.exists() and abs(p.stat().st_mtime - expected_mtime) > 0.001:
        raise HTTPException(409, "The file changed on disk since you opened it - reload before saving")
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        _snapshot(srv, p)
    tmp = p.with_name(f".{p.name}.panel-tmp")
    tmp.write_text(content, encoding="utf-8")
    if p.exists():
        shutil.copymode(p, tmp)
    tmp.replace(p)
    return {"mtime": p.stat().st_mtime}


def _trash_dir(srv) -> Path:
    d = srv.data / "recycle-bin"
    d.mkdir(exist_ok=True)
    return d


def _snapshot(srv, p: Path):
    """Keep the previous version of edited files (last 5 per file) in the recycle bin."""
    hist = _trash_dir(srv) / "_edits"
    hist.mkdir(exist_ok=True)
    key = rel(srv, p).replace("/", "__")
    shutil.copy2(p, hist / f"{key}.{int(time.time())}")
    versions = sorted(hist.glob(f"{key}.*"))
    for old in versions[:-10]:
        old.unlink(missing_ok=True)


def delete(srv, path: str) -> str:
    p = resolve(srv, path)
    if p == root(srv):
        raise HTTPException(400, "Can't delete the server folder")
    if not p.exists() and not p.is_symlink():
        raise HTTPException(404, "Not found")
    dest = _trash_dir(srv) / f"{int(time.time())}__{rel(srv, p).replace('/', '__')}"
    shutil.move(str(p), str(dest))
    return dest.name


def trash_list(srv) -> list:
    out = []
    for e in sorted(_trash_dir(srv).iterdir(), key=lambda x: x.name, reverse=True):
        if e.name == "_edits":
            continue
        ts, _, orig = e.name.partition("__")
        out.append({"id": e.name, "original": orig.replace("__", "/"), "deleted": int(ts) if ts.isdigit() else None,
                    "dir": e.is_dir()})
    return out


def trash_restore(srv, item: str) -> str:
    src = _trash_dir(srv) / Path(item).name
    if not src.exists():
        raise HTTPException(404, "Not in the recycle bin")
    _, _, orig = src.name.partition("__")
    dest = resolve(srv, orig.replace("__", "/"))
    if dest.exists():
        dest = dest.with_name(dest.name + ".restored")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dest))
    return rel(srv, dest)


def trash_empty(srv, older_than_days: float = 0):
    cutoff = time.time() - older_than_days * 86400
    for e in _trash_dir(srv).iterdir():
        if e.name == "_edits":
            continue
        ts = e.name.split("__", 1)[0]
        if ts.isdigit() and int(ts) <= cutoff:
            shutil.rmtree(e) if e.is_dir() and not e.is_symlink() else e.unlink(missing_ok=True)


def rename(srv, path: str, new_name: str) -> str:
    p = resolve(srv, path)
    if "/" in new_name or "\\" in new_name or new_name in ("", ".", ".."):
        raise HTTPException(400, "Invalid name")
    dest = resolve(srv, rel(srv, p.parent) + "/" + new_name)
    if dest.exists():
        raise HTTPException(409, "Something with that name already exists")
    p.rename(dest)
    return rel(srv, dest)


def move(srv, path: str, dest_dir: str) -> str:
    p = resolve(srv, path)
    d = resolve(srv, dest_dir)
    if not d.is_dir():
        raise HTTPException(400, "Destination isn't a folder")
    target = d / p.name
    if target.exists():
        raise HTTPException(409, "Destination already has that name")
    shutil.move(str(p), str(target))
    return rel(srv, target)


def mkdir(srv, path: str) -> str:
    p = resolve(srv, path)
    p.mkdir(parents=True, exist_ok=False)
    return rel(srv, p)


def extract(srv, path: str) -> str:
    p = resolve(srv, path)
    if not zipfile.is_zipfile(p):
        raise HTTPException(400, "Not a zip file")
    dest = p.with_suffix("")
    if dest.exists():
        dest = dest.with_name(dest.name + "-extracted")
    with zipfile.ZipFile(p) as z:
        for m in z.infolist():
            target = (dest / m.filename).resolve()
            if dest.resolve() not in target.parents and target != dest.resolve():
                raise HTTPException(400, "Zip contains unsafe paths")
        z.extractall(dest)
    return rel(srv, dest)


def zip_folder(srv, path: str) -> Path:
    p = resolve(srv, path)
    tmp = srv.data / "tmp"
    tmp.mkdir(exist_ok=True)
    for old in tmp.glob("*.zip"):
        if time.time() - old.stat().st_mtime > 3600:
            old.unlink(missing_ok=True)
    out = tmp / f"{p.name or 'server'}-{int(time.time())}.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in p.rglob("*"):
            if f.is_file():
                z.write(f, f.relative_to(p.parent))
    return out
