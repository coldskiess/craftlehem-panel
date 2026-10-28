"""Tiny in-process event bus. Core emits; add-ons (Pro) subscribe.

Events (all carry server=<id>, server_name=<name>):
  server.starting, server.online(startup_seconds), server.stopped, server.crashed(report, auto_restart),
  server.countdown(action, seconds, reason), player.join(name), player.leave(name),
  backup.done(file, size), backup.failed(error), tps.sample(tps)
"""
from __future__ import annotations

import asyncio
import inspect
from collections import defaultdict

_handlers: dict[str, list] = defaultdict(list)


def on(event: str, fn):
    """Subscribe. event may end with '*' (e.g. 'server.*' or '*')."""
    _handlers[event].append(fn)


def emit(event: str, **data):
    data["event"] = event
    targets = list(_handlers.get(event, []))
    for pattern, fns in list(_handlers.items()):
        if pattern.endswith("*") and pattern != event and event.startswith(pattern[:-1]):
            targets += fns
    for fn in targets:
        try:
            r = fn(**data)
            if inspect.isawaitable(r):
                try:
                    asyncio.get_running_loop().create_task(_guard(r))
                except RuntimeError:
                    pass
        except Exception as e:  # a broken add-on must never break the panel
            print(f"event handler error ({event}):", e)


async def _guard(coro):
    try:
        await coro
    except Exception as e:
        print("event handler error:", e)
