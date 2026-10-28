#!/usr/bin/env bash
# Update Craftlehem Panel to the latest release (or to a zip you downloaded).
#   sudo bash update.sh                     download the latest release from GitHub
#   sudo bash update.sh craftlehem-panel.zip   use a zip you already have
# Keeps config.yml, data/ (players, schedules, history), pro/ and your Minecraft server untouched.
# The Minecraft server keeps running while the panel restarts.
set -euo pipefail
cd "$(dirname "$0")"
PANEL_DIR="$(pwd)"
REPO="coldskiess/craftlehem-panel"
[[ $EUID -eq 0 ]] || { echo "Run this with sudo:  sudo bash update.sh"; exit 1; }
[[ -f config.yml ]] || { echo "No config.yml here - run install.sh for a new install."; exit 1; }

OLD="$(grep -m1 -oP 'VERSION = "\K[^"]+' panel/config.py || echo '?')"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
if [[ -n "${1:-}" ]]; then
  cp "$1" "$TMP/p.zip"
else
  echo "Downloading the latest release..."
  curl -fsSL "https://github.com/$REPO/releases/latest/download/craftlehem-panel.zip" -o "$TMP/p.zip" \
    || { echo "Download failed. Check this machine can reach github.com, or download the zip yourself and run: sudo bash update.sh /path/to/craftlehem-panel.zip"; exit 1; }
fi
unzip -q "$TMP/p.zip" -d "$TMP/new"
SRC="$TMP/new/craftlehem-panel"; [[ -d "$SRC" ]] || SRC="$TMP/new"
[[ -f "$SRC/panel/app.py" ]] || { echo "That zip isn't Craftlehem Panel."; exit 1; }
NEW="$(grep -m1 -oP 'VERSION = "\K[^"]+' "$SRC/panel/config.py" || echo '?')"
echo "Installed: $OLD   ->   New: $NEW"

# keep a copy of the current code so a bad update can be rolled back
rm -rf .previous && mkdir .previous
for item in panel static run.py requirements.txt install.sh update.sh uninstall.sh craftlehem-panel.service; do
  [[ -e "$item" ]] && cp -a "$item" .previous/
done
for item in panel static run.py requirements.txt install.sh update.sh uninstall.sh get.sh craftlehem-panel.service README.md LICENSE CHANGELOG.md docs; do
  [[ -e "$SRC/$item" ]] || continue
  rm -rf "./$item"
  cp -a "$SRC/$item" "./$item"
done

RUN_USER="$(stat -c %U config.yml)"
venv/bin/pip install -q -r requirements.txt
chown -R "$RUN_USER":"$RUN_USER" "$PANEL_DIR"
if [[ -d /run/systemd/system ]] && systemctl list-unit-files craftlehem-panel.service &>/dev/null; then
  sed -e "s#__USER__#$RUN_USER#g" -e "s#__DIR__#$PANEL_DIR#g" craftlehem-panel.service > /etc/systemd/system/craftlehem-panel.service
  systemctl daemon-reload
  systemctl restart craftlehem-panel
  echo "Updated to $NEW and restarted the panel. Your Minecraft server kept running."
else
  echo "Updated to $NEW. Restart the panel to load it."
fi
echo "If something's wrong, the previous version is saved in $PANEL_DIR/.previous"
