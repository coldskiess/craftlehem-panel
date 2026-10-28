#!/usr/bin/env bash
# One-line installer:
#   curl -fsSL https://raw.githubusercontent.com/coldskiess/craftlehem-panel/main/get.sh | sudo bash
# Installs to /opt/craftlehem-panel (set CRAFTLEHEM_DIR to change). If it's already installed, updates it.
set -euo pipefail
REPO="coldskiess/craftlehem-panel"
DEST="${CRAFTLEHEM_DIR:-/opt/craftlehem-panel}"
[[ $EUID -eq 0 ]] || { echo "Run with sudo:  curl -fsSL https://raw.githubusercontent.com/$REPO/main/get.sh | sudo bash"; exit 1; }
if [[ -f "$DEST/config.yml" ]]; then
  echo "Craftlehem Panel is already installed in $DEST - updating it instead."
  exec bash "$DEST/update.sh"
fi
command -v unzip >/dev/null || { command -v apt-get >/dev/null && apt-get install -y -qq unzip >/dev/null; } || { command -v dnf >/dev/null && dnf install -y -q unzip; }
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
echo "Downloading Craftlehem Panel..."
curl -fsSL "https://github.com/$REPO/releases/latest/download/craftlehem-panel.zip" -o "$TMP/p.zip"
unzip -q "$TMP/p.zip" -d "$TMP"
mkdir -p "$DEST"
cp -a "$TMP/craftlehem-panel/." "$DEST/"
exec bash "$DEST/install.sh"
