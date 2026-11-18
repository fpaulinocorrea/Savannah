#!/usr/bin/env bash
# Make Savannah start by itself whenever this computer turns on,
# and add a Savannah icon to your app menu.
# Run once from a terminal in this folder:   bash install-autostart.sh
set -e
cd "$(dirname "$0")"
DIR="$(pwd)"
source scripts/common.sh
ensure_uv
UV="$(command -v uv)"

echo "Getting Savannah's Python packages ready…"
uv sync --quiet

echo "Setting Savannah to start on its own…"
mkdir -p "$HOME/.config/systemd/user"
cat > "$HOME/.config/systemd/user/savannah.service" <<EOF
[Unit]
Description=Savannah
After=network-online.target

[Service]
WorkingDirectory=$DIR
ExecStart=$UV run python -m server
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload
systemctl --user enable --now savannah.service

# Keep Savannah running even before you sign in to the computer (after a power cut, say).
loginctl enable-linger "$USER" 2>/dev/null || echo "(Savannah will start when you sign in to the computer.)"

echo "Adding Savannah to your app menu…"
mkdir -p "$HOME/.local/share/applications" "$HOME/.local/share/icons"
cp web/public/icon-512.png "$HOME/.local/share/icons/savannah.png"
cat > "$HOME/.local/share/applications/savannah.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Savannah
Comment=Guest replies and bookkeeping
Exec=xdg-open http://localhost:8800
Icon=$HOME/.local/share/icons/savannah.png
Terminal=false
Categories=Office;
EOF

sleep 3
echo
echo "Done. Savannah is running and will start on its own from now on."
echo "Open it from your app menu (search \"Savannah\") or at http://localhost:8800"
open_browser
