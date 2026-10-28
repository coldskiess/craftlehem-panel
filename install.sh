#!/usr/bin/env bash
# Craftlehem Panel installer (Debian / Ubuntu / Fedora-style Linux).
#   sudo bash install.sh
# Safe to run again: an existing config.yml and users are kept.
set -euo pipefail
cd "$(dirname "$0")"
PANEL_DIR="$(pwd)"

bold() { printf '\033[1m%s\033[0m\n' "$*"; }
note() { printf '  %s\n' "$*"; }
# read from the terminal even when this script was piped in (curl ... | sudo bash)
ask() { local q="$1" def="${2:-}" ans; read -rp "$q${def:+ [$def]}: " ans </dev/tty; echo "${ans:-$def}"; }
yes_no() { local ans; read -rp "$1 " ans </dev/tty; [[ "${ans:-$2}" =~ ^[Yy] ]]; }

if [[ $EUID -ne 0 ]]; then echo "Run this with sudo:  sudo bash install.sh"; exit 1; fi

bold "Craftlehem Panel setup"
echo

# ------------------------------------------------------------- packages
bold "Installing what the panel needs (tmux, Python, zstd)..."
if command -v apt-get &>/dev/null; then
  apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq tmux python3 python3-venv python3-pip zstd unzip >/dev/null
elif command -v dnf &>/dev/null; then
  dnf install -y -q tmux python3 python3-pip zstd unzip
elif command -v pacman &>/dev/null; then
  pacman -Sy --noconfirm --needed tmux python python-pip zstd unzip >/dev/null
else
  note "Couldn't find apt, dnf or pacman. Install tmux, python3 (3.11+) and zstd yourself, then run this again."
  command -v tmux >/dev/null || exit 1
fi
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' || {
  echo "Python 3.11 or newer is needed (this machine has $(python3 -V 2>&1)). Ubuntu 24.04 / Debian 12 or newer have it."; exit 1; }

if ! command -v java &>/dev/null; then
  echo
  note "Java isn't installed. Minecraft 1.20.5+ (and NeoForge 1.21) needs Java 21."
  if command -v apt-get &>/dev/null && yes_no "Install Java 21 now? [Y/n]" Y; then
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq openjdk-21-jre-headless >/dev/null && note "Java 21 installed."
  fi
fi

# ------------------------------------------------------------ the server
FRESH=1
[[ -f config.yml ]] && FRESH=0
if [[ $FRESH == 1 ]]; then
  echo
  bold "Your Minecraft server"
  GUESS=""
  for d in /opt/minecraft/server /opt/minecraft /srv/minecraft /home/*/minecraft* /home/*/server* /home/*/ServerFiles* /home/*/*/ServerFiles* /home/*/*/server*; do
    [[ -f "$d/server.properties" || -f "$d/run.sh" ]] && { GUESS="$d"; break; }
  done
  while true; do
    SERVER_DIR="$(ask "Full path of the server folder (the one with run.sh / server.properties)" "$GUESS")"
    SERVER_DIR="$(realpath -m "$SERVER_DIR")"
    [[ -d "$SERVER_DIR" ]] && break
    note "$SERVER_DIR doesn't exist. Type the full path, e.g. /home/you/minecraft"
  done
  [[ -f "$SERVER_DIR/server.properties" || -f "$SERVER_DIR/run.sh" ]] || note "(No server.properties or run.sh there yet - that's fine if you're about to set it up.)"

  OWNER="$(stat -c %U "$SERVER_DIR")"
  if [[ "$OWNER" == "root" ]]; then
    note "That folder belongs to root. Running Minecraft as root is risky, so the panel will use its own user."
    RUN_USER="$(ask "Linux user to run the panel and server as" "minecraft")"
    id "$RUN_USER" &>/dev/null || { useradd -r -m -s /bin/bash "$RUN_USER"; note "Created user $RUN_USER"; }
    chown -R "$RUN_USER":"$RUN_USER" "$SERVER_DIR"
  else
    RUN_USER="$(ask "Linux user to run the panel and server as" "$OWNER")"
    id "$RUN_USER" &>/dev/null || { echo "There's no user called $RUN_USER."; exit 1; }
  fi

  if ! sudo -u "$RUN_USER" test -x "$PANEL_DIR"; then
    echo
    echo "The user $RUN_USER can't open $PANEL_DIR (one of its parent folders is private)."
    echo "Move the panel somewhere shared and run the installer again, e.g.:"
    echo "  sudo mv \"$PANEL_DIR\" /opt/craftlehem-panel && sudo bash /opt/craftlehem-panel/install.sh"
    exit 1
  fi

  if [[ -f "$SERVER_DIR/run.sh" ]]; then START_DEFAULT="bash run.sh nogui"
  elif ls "$SERVER_DIR"/*.jar &>/dev/null; then START_DEFAULT="java -Xmx6G -jar $(basename "$(ls "$SERVER_DIR"/*.jar | head -1)") nogui"
  else START_DEFAULT="bash run.sh nogui"; fi
  note "Tip: for modpacks use run.sh, not a start script that restarts itself in a loop -"
  note "the panel handles restarts, crash recovery and backups."
  START_CMD="$(ask "Start command" "$START_DEFAULT")"
  NAME="$(ask "Server name (shown in the panel)" "$(basename "$SERVER_DIR")")"
  ADDRESS="$(ask "Address players join with (optional, e.g. play.example.com)" "")"

  echo
  bold "The panel"
  free_port() { python3 - "$1" <<'PY'
import socket, sys
p = int(sys.argv[1])
for port in range(p, p + 50):
    s = socket.socket()
    try:
        s.bind(("0.0.0.0", port)); print(port); break
    except OSError:
        continue
    finally:
        s.close()
PY
  }
  PORT_DEFAULT="$(free_port 8080)"
  [[ "$PORT_DEFAULT" != "8080" ]] && note "Port 8080 is already in use here, so $PORT_DEFAULT is suggested."
  PORT="$(ask "Web port for the panel" "$PORT_DEFAULT")"
  TZ_DETECTED="$(python3 -c 'import sys; sys.path.insert(0, "."); from panel.config import detect_timezone; print(detect_timezone())' 2>/dev/null || echo UTC)"
  note "Schedules (like nightly restarts) will use this machine's time zone: $TZ_DETECTED"
  note "(change it any time in Settings -> Panel)"
else
  RUN_USER="$(stat -c %U config.yml)"
  note "Existing install found - keeping config.yml, users and data."
fi

# --------------------------------------------------------------- python env
echo
bold "Setting up..."
[[ -d venv ]] || python3 -m venv venv
venv/bin/pip install -q --upgrade pip
venv/bin/pip install -q -r requirements.txt

if [[ $FRESH == 1 ]]; then
  python3 - "$SERVER_DIR" "$START_CMD" "$NAME" "$ADDRESS" "$PORT" <<'PY'
import sys, yaml
d, cmd, name, addr, port = sys.argv[1:]
cfg = {
    "panel": {"title": "Craftlehem Panel", "host": "0.0.0.0", "port": int(port)},
    "servers": [{"id": "main", "name": name, "dir": d, "start_command": cmd, "address": addr,
                 "backups": {"keep": 10, "include": ["config", "serverconfig", "defaultconfigs"], "compression": "zstd"}}],
    "users": [],
}
open("config.yml", "w").write(yaml.safe_dump(cfg, sort_keys=False))
PY
  chmod 600 config.yml
fi
chown -R "$RUN_USER":"$RUN_USER" "$PANEL_DIR"
# load + save once so defaults and a secret key are filled in
sudo -u "$RUN_USER" venv/bin/python -c 'import sys; sys.path.insert(0, "."); from panel import config; config.load()'

# RCON lets the panel read TPS and the real player list
if [[ $FRESH == 1 ]]; then
  PROPS="$SERVER_DIR/server.properties"
  if [[ -f "$PROPS" ]] && ! grep -q '^enable-rcon=true' "$PROPS"; then
    echo
    if yes_no "Turn on RCON? The panel uses it for TPS and the player list (only needs to be reachable from this machine). [Y/n]" Y; then
      PW="$(head -c 32 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 24)"
      sed -i '/^enable-rcon=/d;/^rcon.password=/d' "$PROPS"
      grep -q '^rcon.port=' "$PROPS" || echo "rcon.port=25575" >> "$PROPS"
      printf 'enable-rcon=true\nrcon.password=%s\n' "$PW" >> "$PROPS"
      note "RCON on (takes effect next time the server starts). Keep port 25575 closed to the internet."
    fi
  fi
fi

if ! grep -q 'password_hash' config.yml; then
  echo
  bold "Create your admin login for the panel"
  ADMIN="$(ask "Admin username" "admin")"
  sudo -u "$RUN_USER" venv/bin/python run.py add-user "$ADMIN" admin </dev/tty
fi

# ------------------------------------------------------------------ service
PORT="$(grep -m1 -E '^\s+port:' config.yml | awk '{print $2}')"
if [[ -d /run/systemd/system ]]; then
  sed -e "s#__USER__#$RUN_USER#g" -e "s#__DIR__#$PANEL_DIR#g" craftlehem-panel.service > /etc/systemd/system/craftlehem-panel.service
  systemctl daemon-reload
  systemctl enable craftlehem-panel >/dev/null 2>&1
  systemctl restart craftlehem-panel
  STARTED="as a service (starts on boot)"
else
  note "This machine doesn't use systemd, so the panel can't start on boot automatically."
  sudo -u "$RUN_USER" tmux new-session -d -s craftlehem-panel "cd '$PANEL_DIR' && venv/bin/python run.py" 2>/dev/null || true
  STARTED="in a tmux session called craftlehem-panel (start it again after a reboot with: sudo -u $RUN_USER tmux new -d -s craftlehem-panel 'cd $PANEL_DIR && venv/bin/python run.py')"
fi

if command -v ufw &>/dev/null && ufw status 2>/dev/null | grep -q "Status: active"; then
  echo
  yes_no "Allow port $PORT through the firewall (ufw) so other devices on your network can open the panel? [y/N]" N && ufw allow "$PORT"/tcp >/dev/null
fi

IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
echo
bold "Done! The panel is running $STARTED."
echo
echo "  Open:  http://${IP:-this-machine}:$PORT"
echo
note "If your Minecraft server is already running some other way, stop it there first,"
note "then press Start in the panel so the panel manages it."
note "Reaching the panel from outside your network: see docs/SETUP.md (Cloudflare Tunnel - no port forwarding)."
note "Update later with:  sudo bash $PANEL_DIR/update.sh"
