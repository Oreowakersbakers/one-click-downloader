"""Locating — and, on Windows, auto-downloading — the yt-dlp binary.

yt-dlp is the open-source engine that does the real work of pulling a video
off YouTube/TikTok/X/etc. We never reimplement that; we just make sure a copy
is present and hand it URLs.
"""

import os
import shutil
import hashlib
import urllib.request

from . import config

# Where to find the matching checksums for the binary we download.
YTDLP_SUMS_URL = (
    "https://github.com/yt-dlp/yt-dlp/releases/latest/download/SHA2-256SUMS"
)
_DOWNLOAD_TIMEOUT = 60  # seconds, per network read


def find_ytdlp():
    """Return a path/command for yt-dlp, or None if it must be fetched."""
    # 1. Our own downloaded copy (must be a real, non-empty file — a half-
    #    finished download must not look "present" or it'll never be re-fetched).
    if os.path.isfile(config.YTDLP_BIN) and os.path.getsize(config.YTDLP_BIN) > 0:
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

    # Download to a temp file, then atomically swap it into place — so an
    # interrupted download can never leave a corrupt binary that find_ytdlp()
    # would happily hand back (and execute) next run.
    tmp = config.YTDLP_BIN + ".part"
    try:
        with urllib.request.urlopen(
            config.YTDLP_URL, timeout=_DOWNLOAD_TIMEOUT
        ) as resp, open(tmp, "wb") as out:
            shutil.copyfileobj(resp, out)

        if os.path.getsize(tmp) == 0:
            raise OSError("downloaded file was empty")

        if not _checksum_ok(tmp, log):
            raise OSError("checksum mismatch — refusing to use this binary")

        os.replace(tmp, config.YTDLP_BIN)
        log("yt-dlp ready.\n")
        return config.YTDLP_BIN
    except Exception as e:  # noqa: BLE001 - surface any network/IO failure
        _cleanup(tmp)
        log(f"Failed to download yt-dlp: {e}\n")
        return None


def _checksum_ok(path, log):
    """Verify `path` against yt-dlp's published SHA2-256SUMS.

    A definite mismatch returns False (the binary gets rejected). If the
    checksum file itself can't be fetched/parsed, we log a warning and accept
    the download — it already came over HTTPS from GitHub, and failing here
    would otherwise brick the app on a transient hiccup.
    """
    try:
        with urllib.request.urlopen(
            YTDLP_SUMS_URL, timeout=_DOWNLOAD_TIMEOUT
        ) as resp:
            sums = resp.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001 - network/IO; degrade gracefully
        log(f"(could not fetch checksum, skipping verification: {e})\n")
        return True

    expected = None
    for line in sums.splitlines():
        parts = line.split()
        if len(parts) == 2 and os.path.basename(parts[1]) == config.YTDLP_EXE_NAME:
            expected = parts[0].lower()
            break
    if not expected:
        log("(no matching checksum entry, skipping verification)\n")
        return True

    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest().lower() == expected


def _cleanup(path):
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass
