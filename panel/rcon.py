"""Minimal async Source RCON client used by Minecraft (one per server)."""
from __future__ import annotations

import asyncio
import re
import struct

from . import properties

_COLOR = re.compile(r"§.")


class RconError(Exception):
    pass


class Rcon:
    def __init__(self, srv):
        self.srv = srv
        self._lock = asyncio.Lock()
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._id = 0

    def settings(self) -> tuple[str, int, str] | None:
        """Host/port/password from config.yml, falling back to server.properties."""
        cfg = self.srv.cfg.get("rcon") or {}
        props = properties.read(self.srv)
        if not cfg.get("password") and props.get("enable-rcon", "false").lower() != "true":
            return None
        port = cfg.get("port") or int(props.get("rcon.port", 25575) or 25575)
        pw = cfg.get("password") or props.get("rcon.password", "")
        if not pw:
            return None
        return cfg.get("host") or "127.0.0.1", int(port), pw

    async def _send(self, kind: int, body: str) -> tuple[int, str]:
        self._id = (self._id + 1) % 2_000_000_000
        payload = struct.pack("<ii", self._id, kind) + body.encode("utf-8") + b"\x00\x00"
        self._writer.write(struct.pack("<i", len(payload)) + payload)
        await self._writer.drain()
        size = struct.unpack("<i", await self._reader.readexactly(4))[0]
        data = await self._reader.readexactly(size)
        rid, _ = struct.unpack("<ii", data[:8])
        return rid, data[8:-2].decode("utf-8", "replace")

    async def _connect(self):
        s = self.settings()
        if not s:
            raise RconError("RCON isn't enabled in server.properties")
        host, port, pw = s
        try:
            self._reader, self._writer = await asyncio.wait_for(asyncio.open_connection(host, port), 3)
        except Exception as e:
            raise RconError(f"Can't reach RCON on {host}:{port} ({e.__class__.__name__})")
        rid, _ = await asyncio.wait_for(self._send(3, pw), 5)
        if rid == -1:
            self.close()
            raise RconError("RCON password rejected")

    def close(self):
        if self._writer:
            try:
                self._writer.close()
            except Exception:
                pass
        self._reader = self._writer = None

    async def command(self, cmd: str, timeout: float = 10) -> str:
        async with self._lock:
            for attempt in range(2):
                try:
                    if not self._writer:
                        await self._connect()
                    _, out = await asyncio.wait_for(self._send(2, cmd), timeout)
                    return _COLOR.sub("", out)
                except RconError:
                    self.close()
                    raise
                except Exception as e:
                    self.close()
                    if attempt:
                        raise RconError(f"RCON failed: {e.__class__.__name__}")
            return ""
