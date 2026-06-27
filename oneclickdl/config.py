"""Paths, persisted settings, and the shared security token.

Everything that needs to know "where do files go" or "what port are we on"
reads it from here, so there's a single source of truth.
"""

import os
import json
import secrets
from dataclasses import dataclass, asdict

# ---------------------------------------------------------------------------
# Fixed locations
# ---------------------------------------------------------------------------
APP_DIR = os.path.join(os.path.expanduser("~"), ".oneclick-dl")
BIN_DIR = os.path.join(APP_DIR, "bin")
SETTINGS_PATH = os.path.join(APP_DIR, "settings.json")

DEFAULT_DOWNLOAD_DIR = os.path.join(
    os.path.expanduser("~"), "Downloads", "OneClickDL"
)

IS_WINDOWS = os.name == "nt"

# yt-dlp ships a standalone binary per-OS; we keep our own copy under BIN_DIR.
YTDLP_EXE_NAME = "yt-dlp.exe" if IS_WINDOWS else "yt-dlp"
YTDLP_BIN = os.path.join(BIN_DIR, YTDLP_EXE_NAME)
YTDLP_URL = (
    "https://github.com/yt-dlp/yt-dlp/releases/latest/download/" + YTDLP_EXE_NAME
)

# An uncommon high port, bound to localhost only (see server.py).
DEFAULT_PORT = 53117


def _coerce_port(value):
    """Return a valid TCP port, falling back to DEFAULT_PORT on bad input."""
    try:
        port = int(value)
    except (TypeError, ValueError):
        return DEFAULT_PORT
    return port if 1 <= port <= 65535 else DEFAULT_PORT


def _coerce_dir(value):
    """Return a usable download dir, falling back to the default on bad input."""
    return value if isinstance(value, str) and value.strip() else DEFAULT_DOWNLOAD_DIR


# ---------------------------------------------------------------------------
# User-editable settings (persisted to APP_DIR/settings.json)
# ---------------------------------------------------------------------------
@dataclass
class Settings:
    download_dir: str = DEFAULT_DOWNLOAD_DIR
    port: int = DEFAULT_PORT
    # Shared secret: the browser extension must send this so that random web
    # pages can't silently trigger downloads on your machine.
    token: str = ""

    @classmethod
    def load(cls):
        """Load settings, creating a token on first run."""
        try:
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            data = {}

        token = data.get("token", "")
        if not isinstance(token, str):
            token = ""

        settings = cls(
            download_dir=_coerce_dir(data.get("download_dir")),
            port=_coerce_port(data.get("port")),
            token=token,
        )
        if not settings.token:
            settings.token = secrets.token_urlsafe(24)
            settings.save()
        return settings

    def save(self):
        os.makedirs(APP_DIR, exist_ok=True)
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, indent=2)
