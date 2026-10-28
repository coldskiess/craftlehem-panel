"""Users, password hashing, sessions and roles."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time

from fastapi import HTTPException, Request, WebSocket
from itsdangerous import BadSignature, URLSafeTimedSerializer

from . import config

COOKIE = "cpanel_session"
ROLES = {"viewer": 0, "moderator": 1, "admin": 2}
ROLE_HELP = {
    "viewer": "See status, console output, players and stats. Can't change anything.",
    "moderator": "Viewer + start/stop/restart, run console commands, manage players, make backups.",
    "admin": "Everything: files, mods, settings, restores, schedules and panel users.",
}

_ITER = 240_000
_failed: dict[str, list[float]] = {}  # ip -> recent failure timestamps


def hash_password(pw: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, _ITER)
    return f"pbkdf2${_ITER}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        _, iters, salt, dk = stored.split("$")
        calc = hashlib.pbkdf2_hmac("sha256", pw.encode(), base64.b64decode(salt), int(iters))
        return hmac.compare_digest(calc, base64.b64decode(dk))
    except Exception:
        return False


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(config.get()["panel"]["secret_key"], salt="session")


def find_user(username: str) -> dict | None:
    for u in config.get()["users"]:
        if u["username"].lower() == username.lower():
            return u
    return None


def rate_limited(ip: str) -> bool:
    now = time.time()
    recent = [t for t in _failed.get(ip, []) if now - t < 600]
    _failed[ip] = recent
    return len(recent) >= 8


def record_failure(ip: str) -> None:
    _failed.setdefault(ip, []).append(time.time())


def make_session(user: dict) -> str:
    # session_version lets "log out everywhere" / password changes invalidate old cookies
    return _serializer().dumps({"u": user["username"], "v": user.get("session_version", 0)})


def _user_from_token(token: str | None) -> dict | None:
    if not token:
        return None
    max_age = int(config.get()["panel"]["session_hours"]) * 3600
    try:
        data = _serializer().loads(token, max_age=max_age)
    except BadSignature:
        return None
    user = find_user(data.get("u", ""))
    if not user or user.get("session_version", 0) != data.get("v"):
        return None
    return user


def current_user(request: Request) -> dict:
    user = _user_from_token(request.cookies.get(COOKIE))
    if not user:
        raise HTTPException(401, "Not logged in")
    # CSRF guard: state-changing requests must come from our own JS (custom header
    # can't be set cross-site without CORS, and we never enable CORS).
    if request.method not in ("GET", "HEAD", "OPTIONS") and request.headers.get("x-panel") != "1":
        raise HTTPException(403, "Missing request header")
    return user


def ws_user(ws: WebSocket) -> dict | None:
    origin = ws.headers.get("origin")
    if origin:
        # Accept the page's own host, including when a proxy/tunnel rewrites Host
        allowed = {h for h in (ws.headers.get("host"), ws.headers.get("x-forwarded-host")) if h}
        if allowed and origin.split("://", 1)[-1] not in allowed:
            return None
    return _user_from_token(ws.cookies.get(COOKIE))


def require(role: str):
    def dep(request: Request) -> dict:
        user = current_user(request)
        if ROLES.get(user.get("role", "viewer"), 0) < ROLES[role]:
            raise HTTPException(403, f"This needs the {role} role")
        return user
    return dep


def has_role(user: dict, role: str) -> bool:
    return ROLES.get(user.get("role", "viewer"), 0) >= ROLES[role]
