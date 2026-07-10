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
import signal
from dataclasses import dataclass, field
from urllib.parse import urlparse

from . import config

# ---- event names emitted to listeners ----
EV_QUEUED = "queued"
EV_STARTED = "started"
EV_PROGRESS = "progress"   # data = percent (float)
EV_LOG = "log"             # data = raw output line (str)
EV_DONE = "done"
EV_FAILED = "failed"
EV_CANCELLED = "cancelled"

# Once a job reaches one of these it's finished and can't be cancelled.
_TERMINAL = ("done", "failed", "cancelled")

_PERCENT_RE = re.compile(r"\b(\d{1,3}(?:\.\d+)?)%")

# The two ways a job can come out: the site's native video file (mp4/webm),
# or audio-only converted to mp3. Anything else is coerced to FMT_VIDEO.
FMT_VIDEO = "video"
FMT_MP3 = "mp3"
FORMATS = (FMT_VIDEO, FMT_MP3)


def _is_http_url(url):
    """True only for real http(s) URLs.

    This keeps non-URL input — and crucially anything that looks like a yt-dlp
    option flag (e.g. ``--exec=...``) — from ever reaching the downloader.
    """
    if not isinstance(url, str) or any(ord(c) < 0x20 for c in url):
        return False  # reject non-strings and embedded control chars (CR/LF/TAB)
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


@dataclass
class Job:
    # queued -> running -> done | failed | cancelled
    # (cancelling is a brief internal state while the process is being killed)
    id: int
    url: str
    fmt: str = FMT_VIDEO
    status: str = "queued"
    title: str = ""
    percent: float = 0.0
    error: str = ""
    output_paths: list = field(default_factory=list)


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
        self._ids = itertools.count(1)
        self._listeners = []
        self._lock = threading.Lock()
        # Active (queued or running) jobs, so cancel() can find one by id.
        # Entries are removed the moment a job reaches a terminal state, so this
        # stays bounded by the number of in-flight jobs — never grows unbounded.
        self._active = {}
        # id -> Popen for the job currently running (at most one; serial worker).
        self._procs = {}
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
    def submit(self, url, fmt=FMT_VIDEO):
        """Queue a URL for download.

        `fmt` is one of FORMATS; anything unrecognised falls back to video so
        callers (like the HTTP server) can pass user input straight through.

        Returns the Job, or None if the URL is blank or not a valid http(s)
        link (rejecting the latter is what stops option-injection into yt-dlp).
        """
        if not isinstance(url, str):
            return None
        url = url.strip()
        if not url or not _is_http_url(url):
            return None
        if fmt not in FORMATS:
            fmt = FMT_VIDEO
        # Guard id allocation + registration: submit() is called from multiple
        # HTTP worker threads as well as the GUI thread.
        with self._lock:
            job = Job(id=next(self._ids), url=url, fmt=fmt)
            self._active[job.id] = job
        self._emit(EV_QUEUED, job)
        self._queue.put(job)
        return job

    def active_jobs(self):
        """Snapshot of in-flight (queued/running) jobs, as plain dicts.

        Used by the local server's /status endpoint so the browser extension
        can show what's downloading and offer to cancel it.
        """
        with self._lock:
            return [
                {
                    "id": job.id,
                    "url": job.url,
                    "format": job.fmt,
                    "status": job.status,
                    "title": job.title,
                    "percent": job.percent,
                }
                for job in self._active.values()
            ]

    def cancel(self, job_id):
        """Cancel a queued or running job. Returns True if it was cancellable.

        A queued job is dropped before it starts; a running job's yt-dlp process
        is terminated so the serial worker can move on to the next job (this is
        what stops one wedged download from blocking the whole queue).
        """
        with self._lock:
            job = self._active.get(job_id)
            if job is None or job.status in _TERMINAL:
                return False
            if job.status == "queued":
                # Not started yet — mark it so the worker skips it when dequeued.
                job.status = "cancelled"
                self._active.pop(job_id, None)
                proc = None
                queued = True
            else:
                # running (or already cancelling) — kill the process. proc may
                # be None for the brief window before Popen returns; _process
                # re-checks the status right after spawning and kills it then.
                job.status = "cancelling"
                proc = self._procs.get(job_id)
                queued = False
        if proc is not None:
            self._terminate(proc)
        if queued:
            self._emit(EV_CANCELLED, job)
        return True

    @staticmethod
    def _popen_kwargs():
        """Options that let cancel() stop yt-dlp and any children it starts."""
        if config.IS_WINDOWS:
            return {
                "creationflags": (
                    subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
                )
            }
        return {"start_new_session": True}

    @staticmethod
    def _terminate(proc):
        try:
            if config.IS_WINDOWS:
                subprocess.run(
                    ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                    check=False,
                )
            else:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except Exception:  # noqa: BLE001 - already gone / race on exit
            try:
                proc.terminate()
            except Exception:  # noqa: BLE001 - already gone / race on exit
                pass

    # ---- worker loop ----
    def _run(self):
        while True:
            job = self._queue.get()
            try:
                # Claim the job. Done under the lock so a cancel() racing right
                # at start-up either wins (status already "cancelled", we skip)
                # or loses (we flip to "running" and it takes the kill path).
                with self._lock:
                    skip = job.status == "cancelled"
                    if not skip:
                        job.status = "running"
                if not skip:
                    try:
                        self._process(job)
                    except Exception as e:  # noqa: BLE001 - keep the worker alive
                        # _process handles expected subprocess failures itself.
                        # This boundary covers setup errors such as an invalid
                        # download directory so one bad job cannot permanently
                        # kill the application's only worker thread.
                        if job.status == "cancelling":
                            job.status = "cancelled"
                            self._emit(EV_CANCELLED, job)
                        else:
                            job.status = "failed"
                            job.error = str(e)
                            self._emit(EV_FAILED, job)
            finally:
                with self._lock:
                    self._active.pop(job.id, None)
                    self._procs.pop(job.id, None)
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

        self._emit(EV_STARTED, job)

        cmd = [
            ytdlp,
            "--no-playlist",
            "--newline",
            "-P", download_dir,
            "-o", "%(title).80s [%(id)s].%(ext)s",
        ]
        if job.fmt == FMT_MP3:
            # Grab the best audio-only stream and convert it to mp3 (the
            # conversion step needs ffmpeg, which yt-dlp finds on PATH).
            cmd += ["-f", "bestaudio/best", "-x", "--audio-format", "mp3"]
        cmd += [
            "--",  # everything after this is positional — never an option flag
            job.url,
        ]
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                **self._popen_kwargs(),
            )
            # Register the process so cancel() can reach it. If a cancel landed
            # while we were spawning, honor it now.
            with self._lock:
                self._procs[job.id] = proc
                kill_now = job.status == "cancelling"
            if kill_now:
                self._terminate(proc)

            for line in proc.stdout:
                self._handle_line(job, line.rstrip("\n"))
            proc.wait()

            if job.status == "cancelling":
                self._cleanup_cancelled_outputs(job, download_dir)
                job.status = "cancelled"
                self._emit(EV_CANCELLED, job)
            elif proc.returncode == 0:
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

        # Only treat yt-dlp's own progress lines as progress — otherwise a "%"
        # anywhere in a title or message would jiggle the bar. With --newline,
        # progress arrives as "[download]  12.3% of ...".
        if line.startswith("[download]"):
            match = _PERCENT_RE.search(line)
            if match:
                try:
                    job.percent = float(match.group(1))
                    self._emit(EV_PROGRESS, job, job.percent)
                except ValueError:
                    pass

        if "Destination:" in line:
            path = line.split("Destination:", 1)[1].strip()
            job.title = os.path.basename(path)
            self._remember_output_path(job, path)
        elif "Merging formats into" in line:
            path = line.split("Merging formats into", 1)[1].strip().strip('"')
            job.title = os.path.basename(path)
            self._remember_output_path(job, path)

    def _remember_output_path(self, job, path):
        if not path:
            return
        if not os.path.isabs(path):
            path = os.path.join(self._settings.download_dir, path)
        path = os.path.normpath(path)
        if path not in job.output_paths:
            job.output_paths.append(path)

    def _cleanup_cancelled_outputs(self, job, download_dir):
        download_dir = os.path.normcase(os.path.abspath(download_dir))
        candidates = set()
        for path in job.output_paths:
            path = os.path.abspath(path)
            candidates.update(
                (
                    path,
                    path + ".part",
                    path + ".ytdl",
                    path + ".temp",
                    path + ".tmp",
                )
            )
            base = os.path.basename(path)
            parent = os.path.dirname(path)
            try:
                for name in os.listdir(parent):
                    if name.startswith(base + ".part-"):
                        candidates.add(os.path.join(parent, name))
            except OSError:
                pass

        for path in candidates:
            abs_path = os.path.abspath(path)
            parent = os.path.normcase(os.path.dirname(abs_path))
            if parent != download_dir:
                continue
            try:
                if os.path.isfile(abs_path):
                    os.remove(abs_path)
            except OSError:
                pass
