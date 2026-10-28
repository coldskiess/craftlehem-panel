#!/usr/bin/env python3
"""Craftlehem Panel - web control panel for a Minecraft server on Linux.

  python3 run.py                       start the panel
  python3 run.py add-user NAME [ROLE]  add/replace a panel user (admin|moderator|viewer)
  python3 run.py reset-password NAME   set a new password for a user
  python3 run.py list-users
"""
import getpass
import sys

from panel import auth, config


def ask_password() -> str:
    while True:
        pw = getpass.getpass("Password (8+ characters): ")
        if len(pw) < 8:
            print("Too short.")
            continue
        if getpass.getpass("Again: ") != pw:
            print("Didn't match.")
            continue
        return pw


def main():
    cfg = config.load()
    args = sys.argv[1:]
    if not args:
        import uvicorn
        if not cfg["users"]:
            print("No panel users yet. Create one first:\n  python3 run.py add-user admin admin")
            sys.exit(1)
        uvicorn.run("panel.app:app", host=cfg["panel"]["host"], port=int(cfg["panel"]["port"]),
                    proxy_headers=True, forwarded_allow_ips="127.0.0.1", log_level="warning")
        return
    cmd = args[0]
    if cmd == "add-user":
        name = args[1] if len(args) > 1 else input("Username: ").strip()
        role = args[2] if len(args) > 2 else "admin"
        if role not in auth.ROLES:
            sys.exit("Role must be admin, moderator or viewer")
        pw = ask_password()
        cfg["users"] = [u for u in cfg["users"] if u["username"].lower() != name.lower()]
        cfg["users"].append({"username": name, "role": role, "password_hash": auth.hash_password(pw)})
        config.save()
        print(f"Saved {name} ({role}).")
    elif cmd == "reset-password":
        u = auth.find_user(args[1])
        if not u:
            sys.exit("No such user")
        u["password_hash"] = auth.hash_password(ask_password())
        u["session_version"] = u.get("session_version", 0) + 1
        config.save()
        print("Password updated - existing logins for that user are signed out.")
    elif cmd == "list-users":
        for u in cfg["users"]:
            print(f"{u['username']:20} {u['role']}")
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
