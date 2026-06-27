"""One-Click Downloader — package root.

The app is split into focused modules so each part can grow independently:

    config.py      paths, persisted settings, the shared security token
    ytdlp.py       locating / auto-downloading the yt-dlp binary
    downloader.py  DownloadManager — the queue + worker that actually downloads
    server.py      a localhost-only HTTP API the browser extension talks to
    gui.py         the small desktop window (progress + manual fallback)

Nothing in here knows about the browser extension specifically; the extension
is just one more client of the local server (see server.py).
"""

__version__ = "0.2.0"
