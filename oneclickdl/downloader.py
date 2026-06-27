"""The download core: a queue + background worker that runs yt-dlp.

This module is deliberately UI-agnostic. It knows nothing about tkinter or
HTTP. Anyone (the GUI, the local server, a future CLI) submits a URL and
listens for events. That separation is what makes the app extensible.

Usage:
    manager = DownloadManager(settings, get_ytdlp_path)
    manager.add_listener(lambda event, job, data=None: ...)
    manager.submit("https://...")
"""

import os
import re
import queue
import itertools
import threading
import subprocess
from dataclasses import dataclass
from urllib.parse import urlparse

from . import config

# ---- event names emitted to listeners ----
EV_QUEUED = "queued"
EV_STARTED = "started"
EV_PROGRESS = "progress"   # data = percent (float)
EV_LOG = "log"             # data = raw output line (str)
EV_DONE = "done"
EV_FAILED = "failed"

_PERCENT_RE = re.compile(r"\b(\d{1,3}(?:\.\d+)?)%")


def _is_http_url(url):
    """True only for real http(s) URLs.

    This keeps non-URL input — and crucially anything that looks like a yt-dlp
    option flag (e.g. ``--exec=...``) — from ever reaching the downloader.
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


@dataclass
class Job:
    id: int
    url: str
    status: str = "queued"  # queued | running | done | failed
    title: str = ""
    percent: float = 0.0
    error: str = ""


class DownloadManager:
    """Serial download queue running on one daemon worker thread.

    `get_ytdlp` is a zero-arg callable returning the current yt-dlp path (or
    None). It's a callable rather than a fixed value because the binary may
    still be downloading when the manager is created.
    """

    def __init__(self, settings, get_ytdlp):
        self._settings = settings
        self._get_ytdlp = get_ytdlp
        self._queue = queue.Queue()
        self._jobs = {}
        self._ids = itertools.count(1)
        self._listeners = []
        self._lock = threading.Lock()
        threading.Thread(target=self._run, daemon=True).start()

    # ---- listeners ----
    def add_listener(self, callback):
        """Register callback(event:str, job:Job, data=None).

        Called from the worker thread — GUI listeners must marshal back to
        the UI thread themselves (e.g. tkinter's root.after).
        """
        self._listeners.append(callback)

    def _emit(self, event, job, data=None):
        for cb in list(self._listeners):
            try:
                cb(event, job, data)
            except Exception:  # noqa: BLE001 - a bad listener must not kill the worker
                pass

    # ---- submitting work ----
    def submit(self, url):
        """Queue a URL for download.

        Returns the Job, or None if the URL is blank or not a valid http(s)
        link (rejecting the latter is what stops option-injection into yt-dlp).
        """
        url = (url or "").strip()
        if not url or not _is_http_url(url):
            return None
        job = Job(id=next(self._ids), url=url)
        with self._lock:
            self._jobs[job.id] = job
        self._emit(EV_QUEUED, job)
        self._queue.put(job)
        return job

    # ---- worker loop ----
    def _run(self):
        while True:
            job = self._queue.get()
            try:
                self._process(job)
            finally:
                self._queue.task_done()

    def _process(self, job):
        ytdlp = self._get_ytdlp()
        if not ytdlp:
            job.status = "failed"
            job.error = "yt-dlp isn't available yet — give it a moment and retry."
            self._emit(EV_FAILED, job)
            return

        download_dir = self._settings.download_dir
        os.makedirs(download_dir, exist_ok=True)

        job.status = "running"
        self._emit(EV_STARTED, job)

        cmd = [
            ytdlp,
            "--no-playlist",
            "--newline",
            "-P", download_dir,
            "-o", "%(title).80s [%(id)s].%(ext)s",
            "--",  # everything after this is positional — never an option flag
            job.url,
        ]
        try:
            # CREATE_NO_WINDOW hides the console flash on Windows.
            creationflags = 0x08000000 if config.IS_WINDOWS else 0
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                creationflags=creationflags,
            )
            for line in proc.stdout:
                self._handle_line(job, line.rstrip("\n"))
            proc.wait()

            if proc.returncode == 0:
                job.status = "done"
                job.percent = 100.0
                self._emit(EV_DONE, job)
            else:
                job.status = "failed"
                job.error = "yt-dlp reported an error (see log)."
                self._emit(EV_FAILED, job)
        except Exception as e:  # noqa: BLE001 - report, don't crash the worker
            job.status = "failed"
            job.error = str(e)
            self._emit(EV_FAILED, job)

    def _handle_line(self, job, line):
        if not line:
            return
        self._emit(EV_LOG, job, line)

        match = _PERCENT_RE.search(line)
        if match:
            try:
                job.percent = float(match.group(1))
                self._emit(EV_PROGRESS, job, job.percent)
            except ValueError:
                pass

        if "Destination:" in line:
            job.title = os.path.basename(line.split("Destination:", 1)[1].strip())
