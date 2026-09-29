"""Locating — and, on Windows, auto-downloading — the yt-dlp binary.

yt-dlp is the open-source engine that does the real work of pulling a video
off YouTube/TikTok/X/etc. We never reimplement that; we just make sure a copy
is present, kept reasonably fresh, and hand it URLs.

Two things here exist purely to keep YouTube working:

  * `update()` — YouTube changes constantly and yt-dlp ships fixes within
    days, so a binary downloaded once and never touched again slowly rots
    into "Sign in to confirm you're not a bot" errors.
  * `find_js_runtime()` — modern YouTube extraction needs a JavaScript
    runtime for signature deciphering. yt-dlp only enables deno by default,
    so we look for whatever the machine actually has and name it explicitly.
"""

import os
import time
import shutil
import hashlib
import functools
import subprocess
import urllib.request

from . import config

# Where to find the matching checksums for the binary we download.
YTDLP_SUMS_URL = (
    "https://github.com/yt-dlp/yt-dlp/releases/latest/download/SHA2-256SUMS"
)
_DOWNLOAD_TIMEOUT = 60  # seconds, per network read

# ---- self-update ----
# How long a binary is considered fresh. Long enough that we're not hitting
# GitHub on every launch, short enough to stay ahead of YouTube's changes.
UPDATE_INTERVAL_DAYS = 7
_UPDATE_TIMEOUT = 120  # seconds for the whole `yt-dlp -U` run
# Touched after each completed check, so "already up to date" doesn't make us
# re-check on every single launch (a no-op -U leaves the binary's mtime alone).
_STAMP_PATH = os.path.join(config.BIN_DIR, ".last-update-check")

# ---- JavaScript runtimes ----
# In preference order. deno first because it's the one yt-dlp enables by
# default; the others need naming via --js-runtimes before it will use them.
JS_RUNTIMES = ("deno", "node", "bun")


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


@functools.lru_cache(maxsize=1)
def find_js_runtime():
    """Return the name of an installed JS runtime, or None if there isn't one.

    YouTube extraction is deprecated without one — formats go missing and the
    bot-check trips more often. Cached because PATH won't change mid-run.
    """
    for name in JS_RUNTIMES:
        if shutil.which(name):
            return name
    return None


def js_runtime_args():
    """`--js-runtimes` arguments for the yt-dlp command line, or []."""
    runtime = find_js_runtime()
    return ["--js-runtimes", runtime] if runtime else []


def _no_window():
    """Keep `yt-dlp -U` from flashing a console window on Windows."""
    if config.IS_WINDOWS:
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


def _update_due():
    try:
        return (time.time() - os.path.getmtime(_STAMP_PATH)) > (
            UPDATE_INTERVAL_DAYS * 86400
        )
    except OSError:
        return True  # never checked (or the stamp is unreadable)


def _stamp_checked():
    try:
        os.makedirs(config.BIN_DIR, exist_ok=True)
        with open(_STAMP_PATH, "w", encoding="utf-8") as f:
            f.write(str(int(time.time())))
    except OSError:
        pass  # a missing stamp only costs us an extra check next launch


def update(path, log=lambda msg: None, force=False):
    """Update our own yt-dlp copy in place, at most once every interval.

    Deliberately a no-op unless `path` is the binary we downloaded ourselves:
    a yt-dlp found on PATH belongs to the system's package manager (brew, pip,
    winget) and is not ours to overwrite.

    Failures are logged and swallowed — a stale binary still works well enough
    to be worth running, so an update problem must never block downloading.
    """
    if path != config.YTDLP_BIN:
        return
    if not force and not _update_due():
        return

    log("Checking for a yt-dlp update...\n")
    try:
        proc = subprocess.run(
            [path, "-U"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_UPDATE_TIMEOUT,
            check=False,
            **_no_window(),
        )
    except subprocess.TimeoutExpired:
        log("yt-dlp update timed out — continuing with the current version.\n")
        return
    except OSError as e:
        log(f"Could not run the yt-dlp updater: {e}\n")
        return

    # Only stamp after a run that actually completed, so a machine that's
    # offline retries next launch instead of waiting out the whole interval.
    _stamp_checked()

    output = (proc.stdout or "") + (proc.stderr or "")
    last = next(
        (ln.strip() for ln in reversed(output.splitlines()) if ln.strip()), ""
    )
    if proc.returncode == 0:
        log(f"{last or 'yt-dlp is up to date.'}\n")
    else:
        log(f"yt-dlp update failed ({last or 'unknown error'}) — using current version.\n")


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
