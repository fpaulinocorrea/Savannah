#!/usr/bin/env bash
# Start Savannah and open it in your browser.
# Run from a terminal in this folder:   bash start.sh
set -e
cd "$(dirname "$0")"
source scripts/common.sh

if savannah_is_running; then
  echo "Savannah is already running. Opening it…"
  open_browser
  exit 0
fi

ensure_uv
( sleep 4; open_browser ) &
exec uv run python -m server
