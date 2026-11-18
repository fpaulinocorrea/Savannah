"""Where Savannah keeps things, and which port it listens on."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Everything personal lives in data/ — back up this one folder and you have it all.
DATA_DIR = Path(os.environ.get("SAVANNAH_DATA", ROOT / "data"))
DB_PATH = DATA_DIR / "savannah.db"
CONVERSATIONS_DIR = DATA_DIR / "conversations"  # past guest chats (Phase 2)

WEB_DIR = ROOT / "web" / "dist"  # the built screens
IMPORTS_DIR = ROOT / "imports"  # drop QuickBooks exports here

HOST = os.environ.get("SAVANNAH_HOST", "0.0.0.0")  # 0.0.0.0 = reachable from your phone on Wi-Fi
PORT = int(os.environ.get("SAVANNAH_PORT", "8800"))

SESSION_DAYS = 30


def ensure_folders() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CONVERSATIONS_DIR.mkdir(parents=True, exist_ok=True)
    IMPORTS_DIR.mkdir(parents=True, exist_ok=True)
