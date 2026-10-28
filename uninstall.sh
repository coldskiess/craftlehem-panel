#!/usr/bin/env bash
# Remove Craftlehem Panel. Your Minecraft server, world and backups are NOT touched.
set -euo pipefail
cd "$(dirname "$0")"
PANEL_DIR="$(pwd)"
[[ $EUID -eq 0 ]] || { echo "Run this with sudo:  sudo bash uninstall.sh"; exit 1; }
read -rp "Remove Craftlehem Panel from this machine? [y/N] " yn </dev/tty
[[ "${yn:-N}" =~ ^[Yy] ]] || exit 0

if [[ -f /etc/systemd/system/craftlehem-panel.service ]]; then
  systemctl disable --now craftlehem-panel >/dev/null 2>&1 || true
  rm -f /etc/systemd/system/craftlehem-panel.service
  systemctl daemon-reload
  echo "Stopped and removed the panel service."
fi

SESSIONS="$(grep -oP 'tmux_session:\s*\K\S+' config.yml 2>/dev/null || true)"
RUN_USER="$(stat -c %U config.yml 2>/dev/null || echo root)"
for s in $SESSIONS; do
  if sudo -u "$RUN_USER" tmux has-session -t "=$s" 2>/dev/null; then
    echo "Note: a Minecraft server is still running in tmux session '$s'."
    echo "      Stop it with:  sudo -u $RUN_USER tmux send-keys -t $s stop Enter"
  fi
done

read -rp "Also delete the panel folder ($PANEL_DIR) with its settings, users and player stats? [y/N] " yn </dev/tty
if [[ "${yn:-N}" =~ ^[Yy] ]]; then
  cd / && rm -rf "$PANEL_DIR"
  echo "Deleted $PANEL_DIR."
else
  echo "Kept $PANEL_DIR. Delete it yourself whenever you like."
fi
echo "Done. Your server files, world and backups were not touched."
