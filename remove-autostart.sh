#!/usr/bin/env bash
# Stop Savannah from starting by itself, and remove the app-menu icon.
# Your data in the data/ folder is NOT touched.
set -e
systemctl --user disable --now savannah.service 2>/dev/null || true
rm -f "$HOME/.config/systemd/user/savannah.service"
systemctl --user daemon-reload
rm -f "$HOME/.local/share/applications/savannah.desktop" "$HOME/.local/share/icons/savannah.png"
echo "Savannah will no longer start on its own. Your data is still in the data/ folder."
