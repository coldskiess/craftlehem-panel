"""Minecraft process control (tmux), live console, status, stats and player tracking."""
from __future__ import annotations

import asyncio
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import time
from collections import deque
from pathlib import Path

import psutil

from . import config, events, hub, properties
from .rcon import Rcon, RconError

ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
RE_DONE = re.compile(r"\]: Done \(([\d.]+)s\)!")
# Join/leave lines can carry rank prefixes/suffixes from chat mods ("[Member] Bob [Admin] joined the game")
RE_JOIN = re.compile(r"\]: (.{2,80}?) joined the game")
RE_LEAVE = re.compile(r"\]: (.{2,80}?) left the game")
RE_NAME = re.compile(r"^[A-Za-z0-9_]{2,16}$")
RE_LIST_UUID = re.compile(r"([^,:]+?)\s*\(([0-9a-fA-F-]{36})\)")
RE_UUID = re.compile(r"UUID of player ([A-Za-z0-9_]{2,16}) is ([0-9a-f-]{36})")
RE_LIST = re.compile(r"There are (\d+) of a max(?: of)? (\d+) players online:?(.*)", re.S)
RE_TPS = re.compile(r"Overall\s*:?\s*(?:Mean tick time:\s*([\d.]+)\s*ms\.?\s*Mean TPS:\s*([\d.]+)|([\d.]+)\s*TPS\s*\(([\d.]+)\s*ms/tick\))", re.I)
RE_CHAT = re.compile(r"\]: <([A-Za-z0-9_]{2,16})> (.*)")


def strip_tags(s: str) -> str:
    s = re.sub(r"\u00a7.", "", s)
    return re.sub(r"\[[^\]]*\]|\([^)]*\)|\{[^}]*\}", " ", s).strip()


class Server:
    def __init__(self, sid: str):
        self.id = sid
        self.rcon = Rcon(self)
        self.task: asyncio.Task | None = None
        self.status = "offline"          # offline | starting | online | stopping | crashed
        self.started_at: float | None = None
        self.online_at: float | None = None
        self.startup_seconds: float | None = None
        self.intentional_stop = False
        self.console: deque = deque(maxlen=3000)
        self.line_no = 0
        self.players: dict[str, float] = {}  # online name -> joined at
        self.max_players: int | None = None
        self.tps: float | None = None
        self.mspt: float | None = None
        self.history: deque = deque(maxlen=720)  # 1h at 5s
        self.crash_times: list[float] = []
        self.last_crash: dict | None = None
        self.pending_restart_task: asyncio.Task | None = None
        self.countdown: dict | None = None   # {"action","ends_at"}
        self.world_size: int | None = None
        self.busy: str | None = None          # long action in progress (backup/restore)
        self._tail_file: Path | None = None
        self._tail_pos = 0
        self._tail_ino = None
        self._partial = ""
        self._java: psutil.Process | None = None
        self._db = None
        self._db_dirty = False
        self._last_list = 0.0
        self._last_tps = 0.0
        self._new_lines: list = []

    # ------------------------------------------------------------------ paths
    @property
    def cfg(self) -> dict:
        return config.server_cfg(self.id)

    @property
    def name(self) -> str:
        return self.cfg.get("name") or self.id

    @property
    def dir(self) -> Path:
        return Path(self.cfg["dir"] or "/nonexistent").expanduser().resolve()

    @property
    def data(self) -> Path:
        return config.server_data_dir(self.id)

    @property
    def backup_dir(self) -> Path:
        return config.server_backup_dir(self.id)

    @property
    def session(self) -> str:
        return self.cfg["tmux_session"]

    def emit(self, event: str, **data):
        events.emit(event, server=self.id, server_name=self.name, **data)

    def activity(self, user: str, action: str, detail: str = ""):
        hub.activity(user, action, detail, server=self.id)

    async def broadcast(self, msg: dict):
        msg["server"] = self.id
        await hub.broadcast(msg)

    def _console_file(self) -> Path:
        return self.data / "console.log"

    def _run_file(self) -> Path:
        return self.data / "run.json"

    def _get_run(self) -> dict:
        try:
            return json.loads(self._run_file().read_text())
        except Exception:
            return {}

    def _set_run(self, **kw):
        d = self._get_run()
        d.update(kw)
        self._run_file().write_text(json.dumps(d))

    # ------------------------------------------------------------------- tmux
    def _tmux(self, *args, check=False) -> subprocess.CompletedProcess:
        return subprocess.run(["tmux", *args], capture_output=True, text=True, check=check)

    def session_alive(self) -> bool:
        return self._tmux("has-session", "-t", f"={self.session}").returncode == 0

    def java_process(self) -> psutil.Process | None:
        if self._java and self._java.is_running():
            return self._java
        self._java = None
        r = self._tmux("list-panes", "-t", f"={self.session}:", "-F", "#{pane_pid}")
        if r.returncode != 0:
            return None
        for pid in r.stdout.split():
            try:
                root = psutil.Process(int(pid))
                for p in [root, *root.children(recursive=True)]:
                    if "java" in p.name().lower():
                        self._java = p
                        p.cpu_percent(None)
                        return p
            except (psutil.Error, ValueError):
                continue
        return None

    # ---------------------------------------------------------------- control
    async def start(self, user="panel") -> str:
        if self.busy:
            return f"Can't start while {self.busy} is running"
        if self.session_alive():
            return "Server is already running"
        sdir = self.dir
        if not sdir.is_dir():
            return f"Server folder {sdir} doesn't exist - fix it in Settings"
        cmd = self.cfg["start_command"]
        cfile = self._console_file()
        # rotate previous console capture
        if cfile.exists() and cfile.stat().st_size:
            prev = cfile.with_name("console.prev.log")
            cfile.replace(prev)
        cfile.write_text("")
        launch = self.data / "launch.sh"
        launch.write_text(
            "#!/usr/bin/env bash\n"
            f"cd {shlex.quote(str(sdir))} || exit 1\n"
            "{ echo \"[Panel] Starting server: $PANEL_CMD\"; "
            "eval \"$PANEL_CMD\"; echo \"[Panel] Server process exited with code $?\"; } 2>&1 "
            f"| tee -a {shlex.quote(str(cfile))}\n"
        )
        launch.chmod(0o755)
        env_cmd = f"PANEL_CMD={shlex.quote(cmd)} exec bash {shlex.quote(str(launch))}"
        r = self._tmux("new-session", "-d", "-s", self.session, "-x", "220", "-y", "50", "-c", str(sdir), env_cmd)
        if r.returncode != 0:
            return f"tmux failed: {r.stderr.strip()}"
        self.intentional_stop = False
        self.status = "starting"
        self.started_at = time.time()
        self.online_at = None
        self.players.clear()
        self.tps = self.mspt = None
        self._java = None
        self._set_run(by_panel=True, started_at=self.started_at, wanted=True)
        self._open_tail(cfile, from_start=True)
        self.activity(user, "start")
        self.emit("server.starting", by=user)
        await self._push_status()
        return "ok"

    async def stop(self, user="panel", wait=True) -> str:
        if not self.session_alive():
            self.status = "offline"
            return "Server isn't running"
        self.intentional_stop = True
        self.status = "stopping"
        await self._push_status()
        self.activity(user, "stop")
        self.send_console("stop")
        if not wait:
            return "ok"
        return await self.wait_stopped()

    async def wait_stopped(self) -> str:
        timeout = int(self.cfg["stop_timeout"])
        end = time.time() + timeout
        while time.time() < end:
            if not self.session_alive():
                return "ok"
            await asyncio.sleep(1)
        self._add_line(f"[Panel] Server didn't stop within {timeout}s - force killing")
        await self.kill("panel")
        return "Server was force killed after timing out"

    async def kill(self, user="panel") -> str:
        self.intentional_stop = True
        p = self.java_process()
        if p:
            try:
                p.send_signal(signal.SIGTERM)
                p.wait(15)
            except psutil.TimeoutExpired:
                p.kill()
            except psutil.Error:
                pass
        self._tmux("kill-session", "-t", f"={self.session}")
        if user != "panel":
            self.activity(user, "kill")
        self._add_line("[Panel] Server process killed")
        return "ok"

    async def restart(self, user="panel") -> str:
        if self.session_alive():
            r = await self.stop(user)
            if r not in ("ok",) and self.session_alive():
                return r
            await asyncio.sleep(2)
        return await self.start(user)

    def send_console(self, cmd: str) -> bool:
        cmd = cmd.strip().lstrip("/")
        if not cmd or not self.session_alive():
            return False
        self._tmux("send-keys", "-t", f"={self.session}:", "-l", cmd)
        self._tmux("send-keys", "-t", f"={self.session}:", "Enter")
        return True

    async def command(self, cmd: str, prefer_rcon=True) -> str | None:
        """Run a command, returning its output when RCON is available."""
        if prefer_rcon:
            try:
                return await self.rcon.command(cmd)
            except RconError:
                pass
        self.send_console(cmd)
        return None

    async def say(self, text: str):
        payload = json.dumps(["", {"text": "[Server] ", "color": "gold", "bold": True},
                              {"text": text, "color": "yellow"}])
        await self.command(f"tellraw @a {payload}")

    # -------------------------------------------------------------- countdown
    async def countdown_action(self, action: str, seconds: int, user: str, reason: str = ""):
        """Warn players then restart/stop. action in {restart, stop}."""
        if self.countdown:
            return "A countdown is already running"
        self.countdown = {"action": action, "ends_at": time.time() + seconds, "by": user}
        self.activity(user, f"scheduled {action}", f"in {seconds}s {reason}".strip())
        self.emit("server.countdown", action=action, seconds=seconds, reason=reason, by=user)
        await self._push_status()

        async def run():
            try:
                warn_at = [600, 300, 120, 60, 30, 10, 5, 4, 3, 2, 1]
                end = self.countdown["ends_at"]

                def nice(w):
                    if w >= 60:
                        m = round(w / 60)
                        return f"{m} minute{'s' if m != 1 else ''}"
                    return f"{w} second{'s' if w != 1 else ''}"

                verb = "restarting" if action == "restart" else "stopping"
                await self.say(f"Server {verb} in {nice(seconds)}" + (f" ({reason})" if reason else ""))
                announced = {w for w in warn_at if w >= seconds}
                while True:
                    left = end - time.time()
                    if left <= 0:
                        break
                    for w in warn_at:
                        if w not in announced and left <= w:
                            announced.add(w)
                            if left >= w - 1.5:
                                await self.say(f"Server {verb} in {nice(w)}")
                    await asyncio.sleep(0.25)
                if action == "restart":
                    await self.command("save-all", prefer_rcon=False)
                    await asyncio.sleep(3)
                    await self.restart(user)
                else:
                    await self.stop(user)
            finally:
                self.countdown = None
                await self._push_status()

        self.pending_restart_task = asyncio.create_task(run())
        return "ok"

    async def cancel_countdown(self, user: str):
        if self.pending_restart_task and not self.pending_restart_task.done():
            self.pending_restart_task.cancel()
            self.countdown = None
            await self.say("Scheduled restart cancelled")
            self.activity(user, "cancelled countdown")
            await self._push_status()
            return "ok"
        return "Nothing to cancel"

    # ------------------------------------------------------------------- tail
    def _open_tail(self, path: Path, from_start=False):
        self._tail_file = path
        self._partial = ""
        try:
            st = path.stat()
            self._tail_ino = st.st_ino
            if from_start:
                self._tail_pos = 0
            else:
                # adopt: show the last ~200KB
                self._tail_pos = max(0, st.st_size - 200_000)
        except FileNotFoundError:
            self._tail_pos = 0
            self._tail_ino = None

    def _choose_tail(self):
        """Pick the console source: our captured stdout if we launched the server,
        otherwise the server's logs/latest.log."""
        run = {}
        try:
            run = json.loads(self._run_file().read_text())
        except Exception:
            pass
        if run.get("by_panel") and self._console_file().exists():
            return self._console_file()
        return self.dir / "logs" / "latest.log"

    def _read_tail(self) -> list[str]:
        f = self._tail_file
        if not f:
            return []
        try:
            st = f.stat()
        except FileNotFoundError:
            return []
        if st.st_ino != self._tail_ino or st.st_size < self._tail_pos:
            self._tail_ino = st.st_ino
            self._tail_pos = 0
            self._partial = ""
        if st.st_size == self._tail_pos:
            return []
        with f.open("rb") as fh:
            fh.seek(self._tail_pos)
            data = fh.read(min(st.st_size - self._tail_pos, 2_000_000))
            self._tail_pos = fh.tell()
        text = self._partial + data.decode("utf-8", "replace")
        parts = text.split("\n")
        self._partial = parts.pop()
        return [ANSI.sub("", p).rstrip("\r") for p in parts]

    def _add_line(self, line: str, process=True):
        self.line_no += 1
        entry = (self.line_no, line)
        self.console.append(entry)
        self._new_lines.append(entry)
        if process:
            self._process_line(line)

    def _process_line(self, line: str):
        if "]: Stopping the server" in line or ": Stopping the server]" in line:
            # someone ran /stop in-game or in the console - not a crash
            self.intentional_stop = True
            if self.status in ("starting", "online"):
                self.status = "stopping"
        if self.status == "starting":
            m = RE_DONE.search(line)
            if m:
                self.status = "online"
                self.online_at = time.time()
                self.startup_seconds = float(m.group(1))
                self.emit("server.online", startup_seconds=self.startup_seconds)
                asyncio.get_event_loop().create_task(self._push_status())
        m = RE_UUID.search(line)
        if m:
            p = self._player(m.group(1))
            p["uuid"] = m.group(2)
        m = RE_JOIN.search(line)
        if m:
            name = self.real_name(m.group(1))
            if name:
                self._join(name)
            return
        m = RE_LEAVE.search(line)
        if m:
            name = self.real_name(m.group(1))
            if name:
                self._leave(name)
            return
        m = RE_CHAT.search(line)
        if m:
            p = self._player(m.group(1))
            p["messages"] = p.get("messages", 0) + 1

    # ---------------------------------------------------------------- players
    def _db_path(self):
        return self.data / "players.json"

    @property
    def db(self) -> dict:
        if self._db is None:
            try:
                self._db = json.loads(self._db_path().read_text())
            except Exception:
                self._db = {}
            self._merge_display_names()
        return self._db

    def real_name(self, shown: str) -> str | None:
        """Turn a display name like '[Member] Bob [Admin]' into the account name 'Bob'."""
        shown = shown.strip()
        if RE_NAME.match(shown):
            return shown
        tokens = [t for t in re.split(r"[\s:|»>\-]+", strip_tags(shown)) if RE_NAME.match(t)]
        if not tokens:
            return None
        known = [t for t in tokens if t.lower() in (self._db or {}) and (self._db or {})[t.lower()].get("uuid")]
        if known:
            return known[-1]
        return tokens[-1]

    def _merge_display_names(self):
        """Fold entries saved under a display name (from older versions) into the real player."""
        for key in [k for k in self._db if not RE_NAME.match(k)]:
            bad = self._db.pop(key)
            name = self.real_name(bad.get("name", key))
            self._db_dirty = True
            if not name:
                continue
            good = self._db.setdefault(name.lower(), {"name": name, "playtime": 0, "sessions": 0})
            good["playtime"] = good.get("playtime", 0) + bad.get("playtime", 0)
            good["sessions"] = max(good.get("sessions", 0), bad.get("sessions", 0))
            good["first_seen"] = min(good.get("first_seen") or 1e12, bad.get("first_seen") or 1e12)
            good["last_seen"] = max(good.get("last_seen") or 0, bad.get("last_seen") or 0)
            good.setdefault("uuid", bad.get("uuid"))

    def _player(self, name: str) -> dict:
        key = name.lower()
        p = self.db.setdefault(key, {"name": name, "first_seen": time.time(), "playtime": 0, "sessions": 0})
        p["name"] = name
        self._db_dirty = True
        return p

    def _join(self, name: str):
        if name in self.players:
            return
        self.players[name] = time.time()
        p = self._player(name)
        p["sessions"] = p.get("sessions", 0) + 1
        p["last_seen"] = time.time()
        self.emit("player.join", name=name)
        asyncio.get_event_loop().create_task(self.broadcast({"type": "players", "players": self.player_list()}))

    def _leave(self, name: str):
        t = self.players.pop(name, None)
        p = self._player(name)
        if t:
            p["playtime"] = p.get("playtime", 0) + (time.time() - t)
            self.emit("player.leave", name=name, session_seconds=time.time() - t)
        p["last_seen"] = time.time()
        asyncio.get_event_loop().create_task(self.broadcast({"type": "players", "players": self.player_list()}))

    def _leave_all(self):
        for name in list(self.players):
            self._leave(name)

    def player_list(self) -> list[dict]:
        now = time.time()
        out = []
        for name, t in sorted(self.players.items(), key=lambda kv: kv[0].lower()):
            p = self.db.get(name.lower(), {})
            out.append({"name": name, "uuid": p.get("uuid"), "online_for": now - t})
        return out

    def save_db(self):
        if self._db_dirty and self._db is not None:
            tmp = self._db_path().with_suffix(".tmp")
            tmp.write_text(json.dumps(self._db))
            tmp.replace(self._db_path())
            self._db_dirty = False

    async def reconcile_players(self):
        """Use RCON 'list uuids' to correct the online list (covers joins we missed).
        'list uuids' prints account names, unlike plain 'list' which shows rank prefixes."""
        try:
            out = await self.rcon.command("list uuids", timeout=5)
        except RconError:
            return
        m = RE_LIST.search(out)
        if not m:
            return
        self.max_players = int(m.group(2))
        body = m.group(3)
        names = []
        pairs = RE_LIST_UUID.findall(body)
        if pairs:
            for shown, uuid in pairs:
                n = self.real_name(shown)
                if n:
                    names.append(n)
                    self._player(n)["uuid"] = uuid
        else:
            names = [n for n in (self.real_name(x) for x in body.replace("\n", ",").split(",") if x.strip()) if n]
        current = set(names)
        for n in current - set(self.players):
            self._join(n)
        for n in set(self.players) - current:
            self._leave(n)
        for n in [n for n in self.players if not RE_NAME.match(n)]:
            self.players.pop(n, None)

    async def poll_tps(self):
        for cmd in ("neoforge tps", "forge tps"):
            try:
                out = await self.rcon.command(cmd, timeout=8)
            except RconError:
                return
            m = RE_TPS.search(out)
            if m:
                if m.group(2):
                    self.mspt, self.tps = float(m.group(1)), float(m.group(2))
                else:
                    self.tps, self.mspt = float(m.group(3)), float(m.group(4))
                self.tps = min(self.tps, 20.0)
                self.emit("tps.sample", tps=self.tps, mspt=self.mspt, players=len(self.players))
                return

    # ---------------------------------------------------------------- status
    def snapshot(self) -> dict:
        java = self.java_process() if self.status != "offline" else None
        mem = cpu = None
        if java:
            try:
                mem = java.memory_info().rss
            except psutil.Error:
                pass
        last = self.history[-1] if self.history else {}
        cpu = last.get("cpu")
        props = properties.read(self)
        disk = None
        try:
            du = shutil.disk_usage(self.dir)
            disk = {"total": du.total, "used": du.used, "free": du.free}
        except Exception:
            pass
        jvm = properties.jvm_memory(self)
        return {
            "id": self.id,
            "status": self.status,
            "name": self.name,
            "address": self.cfg.get("address"),
            "started_at": self.started_at,
            "online_at": self.online_at,
            "startup_seconds": self.startup_seconds,
            "pid": java.pid if java else None,
            "cpu": cpu,
            "mem": mem,
            "mem_max": (jvm.get("xmx_gb") or 0) * 1024**3 or None,
            "sys_mem": psutil.virtual_memory()._asdict(),
            "sys_cpu": last.get("sys_cpu"),
            "cores": psutil.cpu_count(),
            "disk": disk,
            "world_size": self.world_size,
            "players": self.player_list(),
            "max_players": self.max_players or (int(props["max-players"]) if props.get("max-players", "").isdigit() else None),
            "tps": self.tps,
            "mspt": self.mspt,
            "rcon": props.get("enable-rcon", "false") == "true",
            "countdown": self.countdown,
            "last_crash": self.last_crash,
            "busy": self.busy,
            "auto_restart": bool(self.cfg.get("auto_restart_on_crash")),
        }

    async def _push_status(self):
        await self.broadcast({"type": "status", "status": self.snapshot()})

    # ------------------------------------------------------------------ loops
    async def run(self):
        """Background loops. Call once at startup."""
        alive = self.session_alive()
        if alive:
            # Panel restarted while the server kept running - adopt it.
            self.status = "online"
            self.started_at = (self.java_process().create_time() if self.java_process() else time.time())
            self.online_at = self.started_at
            self._open_tail(self._choose_tail())
            self._add_line("[Panel] Reattached to the running server")
        else:
            self._open_tail(self._choose_tail())
            for line in self._read_tail()[-300:]:
                self._add_line(line, process=False)
            # Machine rebooted (or panel was down) while the server was meant to be running
            if self.cfg.get("start_with_panel", True) and self._get_run().get("wanted"):
                self._add_line("[Panel] Server was running before the panel restarted - starting it again")
                asyncio.get_event_loop().call_later(3, lambda: asyncio.ensure_future(self.start("panel boot")))
        await asyncio.gather(self._tail_loop(), self._watch_loop(), self._stats_loop(), self._slow_loop())

    async def _tail_loop(self):
        while True:
            try:
                want = self._choose_tail()
                if want != self._tail_file:
                    self._open_tail(want)
                lines = self._read_tail()
                for line in lines:
                    self._add_line(line)
                if self._new_lines:
                    batch, self._new_lines[:] = list(self._new_lines), []
                    await self.broadcast({"type": "console", "lines": batch})
            except Exception as e:  # never let the loop die
                print("tail error", e)
            await asyncio.sleep(0.25)

    async def _watch_loop(self):
        while True:
            try:
                alive = self.session_alive()
                if not alive and self.status in ("starting", "online", "stopping"):
                    await asyncio.sleep(0.6)  # let the tail flush final lines
                    for line in self._read_tail():
                        self._add_line(line)
                    was = self.status
                    self._leave_all()
                    self._java = None
                    if self.intentional_stop or was == "stopping":
                        self.status = "offline"
                        self._set_run(wanted=False)
                        self._add_line("[Panel] Server stopped")
                        self.emit("server.stopped")
                    else:
                        await self._on_crash()
                    self.save_db()
                    await self._push_status()
                elif alive and self.status in ("offline", "crashed"):
                    self.status = "online" if self.java_process() else "starting"
                    self.started_at = self.started_at or time.time()
                    await self._push_status()
            except Exception as e:
                print("watch error", e)
            await asyncio.sleep(1)

    async def _on_crash(self):
        self.status = "crashed"
        now = time.time()
        report = None
        cr = self.dir / "crash-reports"
        if cr.is_dir():
            reports = sorted(cr.glob("*.txt"), key=lambda p: p.stat().st_mtime, reverse=True)
            if reports and reports[0].stat().st_mtime > (self.started_at or now) - 5:
                report = reports[0].name
        self.last_crash = {"t": now, "report": report}
        self._add_line("[Panel] The server stopped unexpectedly" + (f" - crash report: {report}" if report else ""))
        self.activity("panel", "crash detected", report or "")
        self.crash_times = [t for t in self.crash_times if now - t < 600] + [now]
        cfg = self.cfg
        will_restart = bool(cfg.get("auto_restart_on_crash")) and not self.busy and \
            len(self.crash_times) <= int(cfg.get("max_crash_restarts", 3))
        self.emit("server.crashed", report=report, auto_restart=will_restart,
                  crashes_10min=len(self.crash_times))
        if cfg.get("auto_restart_on_crash") and not self.busy:
            if len(self.crash_times) <= int(cfg.get("max_crash_restarts", 3)):
                self._add_line("[Panel] Auto-restarting in 10 seconds...")
                await self._push_status()
                await asyncio.sleep(10)
                if self.status == "crashed" and not self.session_alive():
                    await self.start("auto-restart")
            else:
                self._add_line("[Panel] Crashed too many times in 10 minutes - not restarting automatically")

    async def _stats_loop(self):
        psutil.cpu_percent(None)
        cores = psutil.cpu_count() or 1
        while True:
            try:
                java = self.java_process() if self.status != "offline" else None
                cpu = mem = None
                if java:
                    try:
                        cpu = java.cpu_percent(None) / cores
                        mem = java.memory_info().rss
                    except psutil.Error:
                        pass
                vm = psutil.virtual_memory()
                point = {
                    "t": time.time(), "cpu": cpu, "mem": mem,
                    "sys_cpu": psutil.cpu_percent(None), "sys_mem": vm.used,
                    "tps": self.tps if self.status == "online" else None,
                    "players": len(self.players),
                }
                self.history.append(point)
                await self.broadcast({"type": "stats", "point": point, "status": self.snapshot()})
            except Exception as e:
                print("stats error", e)
            await asyncio.sleep(5)

    async def _slow_loop(self):
        last_size = 0.0
        while True:
            try:
                now = time.time()
                if self.status == "online":
                    if now - self._last_list > 30:
                        self._last_list = now
                        await self.reconcile_players()
                    if now - self._last_tps > 20:
                        self._last_tps = now
                        await self.poll_tps()
                if now - last_size > 600:
                    last_size = now
                    self.world_size = await asyncio.to_thread(self._world_size)
                self.save_db()
            except Exception as e:
                print("slow loop error", e)
            await asyncio.sleep(5)

    def world_path(self) -> Path:
        return self.dir / (properties.read(self).get("level-name") or "world")

    def _world_size(self) -> int | None:
        w = self.world_path()
        if not w.is_dir():
            return None
        total = 0
        for root, _, files in os.walk(w):
            for f in files:
                try:
                    total += os.lstat(os.path.join(root, f)).st_size
                except OSError:
                    pass
        return total



# ------------------------------------------------------------------ registry
registry: dict[str, Server] = {}
max_servers = 1   # the free version runs one server; the Pro add-on raises this


def get(sid: str | None) -> Server | None:
    if sid and sid in registry:
        return registry[sid]
    return first()


def first() -> Server | None:
    return next(iter(registry.values()), None)


def start_loops(srv: Server):
    srv.task = asyncio.create_task(srv.run())


def load_all() -> list[Server]:
    """Create Server objects for configured servers (up to max_servers) and start their loops."""
    for i, scfg in enumerate(config.servers()):
        if i >= max_servers:
            break
        if scfg["id"] not in registry:
            srv = Server(scfg["id"])
            registry[srv.id] = srv
            start_loops(srv)
    return list(registry.values())


def add(sid: str) -> Server:
    srv = Server(sid)
    registry[sid] = srv
    start_loops(srv)
    return srv


async def remove(sid: str):
    srv = registry.pop(sid, None)
    if srv and srv.task:
        srv.task.cancel()
        srv.save_db()
