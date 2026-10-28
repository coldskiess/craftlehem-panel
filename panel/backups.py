"""World backups: safe (save-off/flush) tar archives with progress, retention and restore."""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import time
from pathlib import Path

from fastapi import HTTPException

jobs: dict[str, dict] = {}   # server id -> current backup/restore job, shown in the UI
_NAME = re.compile(r"^[\w.\-]+\.tar\.(gz|zst)$")


def job(srv) -> dict | None:
    return jobs.get(srv.id)


def _compression(srv):
    want = srv.cfg["backups"].get("compression", "gzip")
    if want == "zstd" and shutil.which("zstd"):
        return "zst", ["-I", "zstd -T0 -3"]
    if shutil.which("pigz"):
        return "gz", ["-I", "pigz"]
    return "gz", ["-z"]


def _meta_path(archive: Path) -> Path:
    return archive.with_name(archive.name + ".json")


def listing(srv) -> list[dict]:
    out = []
    for f in srv.backup_dir.iterdir():
        if not _NAME.match(f.name):
            continue
        meta = {}
        try:
            meta = json.loads(_meta_path(f).read_text())
        except Exception:
            pass
        st = f.stat()
        out.append({
            "file": f.name, "size": st.st_size, "created": meta.get("created", st.st_mtime),
            "note": meta.get("note", ""), "auto": meta.get("auto", False), "by": meta.get("by"),
            "paths": meta.get("paths", []), "locked": meta.get("locked", False),
        })
    out.sort(key=lambda b: b["created"], reverse=True)
    return out


def _paths_to_backup(srv) -> list[str]:
    sdir = srv.dir
    world = srv.world_path().name
    paths = [world]
    for extra in srv.cfg["backups"].get("include") or []:
        extra = extra.strip().strip("/")
        if extra and (sdir / extra).exists() and extra not in paths:
            paths.append(extra)
    return [p for p in paths if (sdir / p).exists()]


def _dir_size(sdir: Path, paths: list[str]) -> int:
    total = 0
    for p in paths:
        for root, _, files in os.walk(sdir / p):
            for f in files:
                try:
                    total += os.lstat(os.path.join(root, f)).st_size
                except OSError:
                    pass
    return total


async def _push(srv):
    await srv.broadcast({"type": "job", "job": jobs.get(srv.id)})


async def _wait_for_line(srv, pattern: str, after_line: int, timeout: float) -> bool:
    end = time.time() + timeout
    rx = re.compile(pattern)
    while time.time() < end:
        for n, line in list(srv.console)[-200:]:
            if n > after_line and rx.search(line):
                return True
        await asyncio.sleep(0.5)
    return False


async def create(srv, user: str, note: str = "", auto: bool = False) -> str:
    server = srv
    if jobs.get(srv.id):
        return f"A {jobs[srv.id]['kind']} is already running"
    paths = _paths_to_backup(srv)
    if not paths:
        return "Couldn't find the world folder to back up"
    ext, comp = _compression(srv)
    stamp = time.strftime("%Y-%m-%d_%H-%M-%S")
    archive = srv.backup_dir / f"{'auto' if auto else 'manual'}_{stamp}.tar.{ext}"
    job = jobs[srv.id] = {"kind": "backup", "stage": "Preparing", "progress": 0, "started": time.time(), "file": archive.name}
    server.busy = "a backup"
    await _push(srv)
    online = server.status == "online" and server.session_alive()
    try:
        if online:
            job["stage"] = "Saving the world"
            await _push(srv)
            mark = server.line_no
            await server.command("save-off", prefer_rcon=False)
            await asyncio.sleep(0.5)
            await server.command("save-all flush", prefer_rcon=False)
            await _wait_for_line(srv, r"Saved the game|All dimensions are saved|Saved the world", mark, 120)
            await asyncio.sleep(1)
        job["stage"] = "Measuring"
        await _push(srv)
        total = await asyncio.to_thread(_dir_size, srv.dir, paths) or 1
        job.update(stage="Compressing", total=total)
        await _push(srv)
        tmp = archive.with_name(archive.name + ".partial")
        proc = await asyncio.create_subprocess_exec(
            "tar", *comp, "-cf", str(tmp), "--exclude=session.lock", "--warning=no-file-changed",
            "--checkpoint=500", "--checkpoint-action=echo=CP%u", *paths,
            cwd=str(srv.dir), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        last_push = 0.0
        err_lines = []
        while True:
            line = await proc.stderr.readline()
            if not line:
                break
            s = line.decode(errors="replace").strip()
            m = re.search(r"CP(\d+)$", s)
            if m:
                job["progress"] = min(99, int(int(m.group(1)) * 10240 * 100 / total))
                if time.time() - last_push > 1:
                    last_push = time.time()
                    await _push(srv)
            elif s:
                err_lines.append(s)
        rc = await proc.wait()
        if rc not in (0, 1):  # 1 = "some files changed while reading" - fine with save-off
            tmp.unlink(missing_ok=True)
            raise RuntimeError("tar failed: " + "; ".join(err_lines[-3:]))
        tmp.replace(archive)
        _meta_path(archive).write_text(json.dumps({
            "created": time.time(), "note": note, "auto": auto, "by": user, "paths": paths,
        }))
        srv.activity(user, "backup created", archive.name)
        srv.emit("backup.done", file=archive.name, size=archive.stat().st_size, auto=auto, by=user)
        await prune(srv)
        return "ok"
    except Exception as e:
        srv.activity(user, "backup failed", str(e))
        srv.emit("backup.failed", error=str(e), auto=auto, by=user)
        return f"Backup failed: {e}"
    finally:
        if online and server.session_alive():
            await server.command("save-on", prefer_rcon=False)
        server.busy = None
        jobs.pop(srv.id, None)
        await _push(srv)


async def prune(srv):
    keep = int(srv.cfg["backups"].get("keep", 10))
    autos = [b for b in listing(srv) if b["auto"] and not b["locked"]]
    for b in autos[keep:]:
        delete(srv, b["file"])


def _file(srv, name: str) -> Path:
    if not _NAME.match(name):
        raise HTTPException(400, "Bad backup name")
    p = srv.backup_dir / name
    if not p.is_file():
        raise HTTPException(404, "Backup not found")
    return p


def delete(srv, name: str):
    p = _file(srv, name)
    p.unlink()
    _meta_path(p).unlink(missing_ok=True)


def update_meta(srv, name: str, note: str | None = None, locked: bool | None = None):
    p = _file(srv, name)
    mp = _meta_path(p)
    meta = {}
    try:
        meta = json.loads(mp.read_text())
    except Exception:
        meta = {"created": p.stat().st_mtime}
    if note is not None:
        meta["note"] = note[:200]
    if locked is not None:
        meta["locked"] = locked
    mp.write_text(json.dumps(meta))


def path(srv, name: str) -> Path:
    return _file(srv, name)


async def restore(srv, name: str, user: str) -> str:
    """Server must be stopped. Current world is kept as <world>.before-restore-<time>."""
    server = srv
    if jobs.get(srv.id):
        return f"A {jobs[srv.id]['kind']} is already running"
    if server.session_alive():
        return "Stop the server before restoring a backup"
    archive = _file(srv, name)
    sdir = srv.dir
    job = jobs[srv.id] = {"kind": "restore", "stage": "Checking archive", "progress": 0, "started": time.time(), "file": name}
    server.busy = "a restore"
    await _push(srv)
    try:
        _, comp = ("", ["-I", "zstd -d"]) if archive.name.endswith(".zst") else ("", ["-z"])
        proc = await asyncio.create_subprocess_exec("tar", *comp, "-tf", str(archive),
                                                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, err = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError("Archive is damaged: " + err.decode(errors="replace")[:200])
        members = out.decode(errors="replace").splitlines()
        tops = set()
        for m in members:
            if m.startswith("/") or ".." in Path(m).parts:
                raise RuntimeError("Archive contains unsafe paths")
            if m.strip():
                tops.add(Path(m).parts[0])
        stamp = time.strftime("%Y%m%d-%H%M%S")
        job["stage"] = "Moving current world aside"
        await _push(srv)
        kept = []
        for t in sorted(tops):
            cur = sdir / t
            if cur.exists():
                aside = sdir / f"{t}.before-restore-{stamp}"
                cur.rename(aside)
                kept.append(aside.name)
        job.update(stage="Extracting", progress=50)
        await _push(srv)
        proc = await asyncio.create_subprocess_exec("tar", *comp, "-xf", str(archive), "-C", str(sdir),
                                                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        _, err = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError("Extract failed: " + err.decode(errors="replace")[:200])
        srv.activity(user, "backup restored", f"{name} (previous world kept as {', '.join(kept) or 'n/a'})")
        return "ok" + (f" - your previous world was kept as {', '.join(kept)}" if kept else "")
    except Exception as e:
        srv.activity(user, "restore failed", str(e))
        return f"Restore failed: {e}"
    finally:
        server.busy = None
        jobs.pop(srv.id, None)
        await _push(srv)
