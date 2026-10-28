"""server.properties and user_jvm_args.txt helpers (order/comments preserved)."""
from __future__ import annotations

import re



def _path(srv):
    return srv.dir / "server.properties"


def _unescape(v: str) -> str:
    return v.replace("\\:", ":").replace("\\=", "=").replace("\\!", "!").replace("\\#", "#")


def read(srv) -> dict[str, str]:
    p = _path(srv)
    out: dict[str, str] = {}
    if not p.exists():
        return out
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if not s or s[0] in "#!" or "=" not in s:
            continue
        k, v = s.split("=", 1)
        out[k.strip()] = _unescape(v.strip())
    return out


def write(srv, updates: dict[str, str]) -> None:
    p = _path(srv)
    lines = p.read_text(encoding="utf-8", errors="replace").splitlines() if p.exists() else []
    seen = set()
    for i, line in enumerate(lines):
        s = line.strip()
        if not s or s[0] in "#!" or "=" not in s:
            continue
        k = s.split("=", 1)[0].strip()
        if k in updates:
            lines[i] = f"{k}={_esc(updates[k])}"
            seen.add(k)
    for k, v in updates.items():
        if k not in seen:
            lines.append(f"{k}={_esc(v)}")
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _esc(v) -> str:
    # Colons/equals inside a value are fine for Java's parser; just keep it on one line.
    return str(v).replace("\r", " ").replace("\n", " ")


# Field metadata for the friendly editor. Anything else still shows under "Other".
FIELDS = [
    ("motd", "text", "Message of the day shown in the server list", "General"),
    ("max-players", "number", "Maximum players online at once", "General"),
    ("difficulty", ["peaceful", "easy", "normal", "hard"], "Difficulty", "Gameplay"),
    ("gamemode", ["survival", "creative", "adventure", "spectator"], "Default game mode for new players", "Gameplay"),
    ("hardcore", "bool", "Hardcore mode", "Gameplay"),
    ("pvp", "bool", "Players can hurt each other", "Gameplay"),
    ("allow-flight", "bool", "Don't kick players for flying (keep ON for modded - jetpacks, airships)", "Gameplay"),
    ("spawn-protection", "number", "Radius around spawn only ops can build in (0 = off)", "Gameplay"),
    ("view-distance", "number", "Chunks sent to players (lower = less lag)", "Performance"),
    ("simulation-distance", "number", "Chunks that tick around players", "Performance"),
    ("max-tick-time", "number", "Watchdog: ms a tick may take before the server force-stops (-1 = off)", "Performance"),
    ("sync-chunk-writes", "bool", "Safer but slower chunk saving", "Performance"),
    ("white-list", "bool", "Only whitelisted players can join", "Access"),
    ("enforce-whitelist", "bool", "Kick non-whitelisted players when the whitelist is reloaded", "Access"),
    ("online-mode", "bool", "Check accounts with Mojang (keep ON)", "Access"),
    ("server-port", "number", "Game port", "Network"),
    ("enable-rcon", "bool", "Remote console - the panel uses this for player lists and TPS", "Network"),
    ("rcon.port", "number", "RCON port", "Network"),
    ("rcon.password", "password", "RCON password", "Network"),
    ("level-name", "text", "World folder name", "World"),
    ("level-seed", "text", "World seed (only used when creating a new world)", "World"),
    ("allow-nether", "bool", "Allow the Nether", "World"),
]


# ---- JVM memory (NeoForge user_jvm_args.txt) ----

def _jvm_path(srv):
    return srv.dir / "user_jvm_args.txt"


def jvm_memory(srv) -> dict:
    p = _jvm_path(srv)
    if not p.exists():
        return {"available": False}
    text = p.read_text(errors="replace")
    xmx = re.search(r"^\s*-Xmx(\d+)([GgMm])", text, re.M)
    xms = re.search(r"^\s*-Xms(\d+)([GgMm])", text, re.M)

    def gb(m):
        if not m:
            return None
        n = int(m.group(1))
        return n if m.group(2).lower() == "g" else round(n / 1024, 1)

    return {"available": True, "xmx_gb": gb(xmx), "xms_gb": gb(xms), "raw": text}


def set_jvm_memory(srv, xmx_gb: int, xms_gb: int | None) -> None:
    p = _jvm_path(srv)
    text = p.read_text(errors="replace") if p.exists() else ""
    lines = [l for l in text.splitlines() if not re.match(r"^\s*-Xm[xs]\d", l)]
    # NeoForge's template has these lines commented out - drop old commented ones too
    lines = [l for l in lines if not re.match(r"^\s*#\s*-Xm[xs]\d", l)]
    lines.append(f"-Xmx{int(xmx_gb)}G")
    if xms_gb:
        lines.append(f"-Xms{int(xms_gb)}G")
    p.write_text("\n".join(lines).strip() + "\n")
