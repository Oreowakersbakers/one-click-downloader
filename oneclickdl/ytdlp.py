"""Locating — and, on Windows, auto-downloading — the yt-dlp binary.

yt-dlp is the open-source engine that does the real work of pulling a video
off YouTube/TikTok/X/etc. We never reimplement that; we just make sure a copy
is present and hand it URLs.
"""

import os
import shutil
import urllib.request

from . import config


def find_ytdlp():
    """Return a path/command for yt-dlp, or None if it must be fetched."""
    # 1. Our own downloaded copy.
    if os.path.exists(config.YTDLP_BIN):
        return config.YTDLP_BIN
    # 2. Anything already on PATH (Mac/Linux installs, or a manual one).
    found = shutil.which("yt-dlp")
    if found:
        return found
    return None


def ensure_ytdlp(log=lambda msg: None):
    """Return a usable yt-dlp path, downloading it on Windows if needed.

    `log` is an optional callback so the caller (GUI) can show progress.
    """
    path = find_ytdlp()
    if path:
        return path

    if not config.IS_WINDOWS:
        log(
            "yt-dlp not found. Install it once with:  brew install yt-dlp  (Mac)"
            "  or  pip install yt-dlp\n"
        )
        return None

    os.makedirs(config.BIN_DIR, exist_ok=True)
    log("First run: downloading yt-dlp (one-time, ~15 MB)...\n")
    try:
        urllib.request.urlretrieve(config.YTDLP_URL, config.YTDLP_BIN)
        log("yt-dlp ready.\n")
        return config.YTDLP_BIN
    except Exception as e:  # noqa: BLE001 - surface any network/IO failure
        log(f"Failed to download yt-dlp: {e}\n")
        return None
