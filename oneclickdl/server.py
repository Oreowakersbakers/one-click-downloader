"""A tiny localhost-only HTTP API that the browser extension talks to.

The browser extension can't run yt-dlp itself (browsers are sandboxed), so it
sends the video URL here and this process does the download. Built on the
standard library only — no extra dependencies.

Endpoints:
    GET  /ping       -> {"ok": true, ...}     (lets the extension detect us)
    GET  /status     -> {"ok": true, "jobs": [...]}          (needs token)
    POST /download   -> {"ok": true, "id": N} (body: {"url": "..."}; needs token)
    POST /cancel     -> {"ok": true, "cancelled": [ids]}
                        (body: {"id": N}, or {} to cancel everything; needs token)

Security model (for a personal tool):
    * Bound to 127.0.0.1 only — nothing on the network can reach it.
    * Everything except /ping requires the shared token (header
      X-OneClick-Token) so a random web page that happens to know the port
      still can't trigger — or spy on — downloads.
"""

import hmac
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import config


class _Server(ThreadingHTTPServer):
    # HTTPServer turns on SO_REUSEADDR, which on Windows lets a SECOND copy of
    # the app silently bind the same port instead of failing — requests then go
    # to whichever instance won, which looks like the app randomly ignoring
    # you. Windows doesn't need the flag (no TIME_WAIT rebinding problem), so
    # turn it off there; keep it on elsewhere, where it exists for exactly that
    # rebinding reason and double-binding is already impossible.
    allow_reuse_address = not config.IS_WINDOWS

# The body is only ever a tiny JSON object ({"url": "..."}); cap it so a client
# can't claim a huge Content-Length and make us allocate / read unbounded data.
MAX_BODY_BYTES = 64 * 1024


def make_server(manager, settings, log=lambda msg: None):
    """Build (but don't start) the HTTP server. Call .serve_forever() on it."""

    class Handler(BaseHTTPRequestHandler):
        # Each request runs on its own thread; a client that connects and then
        # goes quiet would pin that thread forever. Time out idle sockets so
        # they get closed instead.
        timeout = 10

        # Silence the default stderr request logging.
        def log_message(self, *args):
            pass

        # ---- helpers ----
        def _cors(self):
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header(
                "Access-Control-Allow-Headers", "Content-Type, X-OneClick-Token"
            )
            # Allow browsers' Private Network Access preflight (page -> localhost).
            self.send_header("Access-Control-Allow-Private-Network", "true")

        def _reply(self, code, payload):
            body = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self._cors()
            self.end_headers()
            self.wfile.write(body)

        def _path(self):
            return self.path.split("?", 1)[0]

        def _authorized(self):
            """Token check shared by every endpoint except /ping.

            Replies 403 and returns False on failure, so callers can just
            ``if not self._authorized(): return``.
            """
            # Defense in depth: with no token configured, refuse everything
            # rather than let an empty header match an empty token. Not reachable
            # today (config always generates one), but cheap insurance.
            if not settings.token:
                self._reply(403, {"ok": False, "error": "server has no token configured"})
                return False

            # Constant-time compare so the token can't be guessed by timing the
            # response. Encode to bytes first: compare_digest rejects non-ASCII
            # str input with a TypeError, and a header value is attacker-supplied.
            sent = self.headers.get("X-OneClick-Token", "").encode("utf-8")
            if not hmac.compare_digest(sent, settings.token.encode("utf-8")):
                self._reply(403, {"ok": False, "error": "bad or missing token"})
                return False
            return True

        def _read_json(self):
            """Parse the request body as JSON. Replies with the right 4xx and
            returns None on any problem (so callers bail on falsy)."""
            try:
                length = int(self.headers.get("Content-Length", 0) or 0)
            except ValueError:
                self._reply(400, {"ok": False, "error": "invalid Content-Length"})
                return None
            if length < 0:
                self._reply(400, {"ok": False, "error": "invalid Content-Length"})
                return None
            if length > MAX_BODY_BYTES:
                self._reply(413, {"ok": False, "error": "request body too large"})
                return None

            raw = self.rfile.read(length) if length else b"{}"
            try:
                data = json.loads(raw.decode("utf-8") or "{}")
            except ValueError:
                self._reply(400, {"ok": False, "error": "invalid JSON"})
                return None
            if not isinstance(data, dict):
                self._reply(400, {"ok": False, "error": "body must be a JSON object"})
                return None
            return data

        # ---- routes ----
        def do_OPTIONS(self):
            self.send_response(204)
            self._cors()
            self.end_headers()

        def do_GET(self):
            path = self._path()
            if path == "/ping":
                self._reply(200, {"ok": True, "app": "oneclick-dl"})
            elif path == "/status":
                # What's queued/downloading right now — lets the extension
                # popup show progress and offer a Cancel button.
                if not self._authorized():
                    return
                self._reply(200, {"ok": True, "jobs": manager.active_jobs()})
            else:
                self._reply(404, {"ok": False, "error": "not found"})

        def do_POST(self):
            path = self._path()
            if path == "/download":
                self._handle_download()
            elif path == "/cancel":
                self._handle_cancel()
            else:
                self._reply(404, {"ok": False, "error": "not found"})

        def _handle_download(self):
            if not self._authorized():
                return
            data = self._read_json()
            if data is None:
                return

            # Optional "format": "video" (default) or "mp3", and optional
            # "playlist": true to fetch every entry of a playlist URL.
            # submit() coerces anything unrecognised, so no validation here.
            job = manager.submit(
                data.get("url", ""),
                data.get("format", "video"),
                playlist=data.get("playlist", False),
            )
            if not job:
                self._reply(400, {"ok": False, "error": "missing or invalid url"})
                return

            log(f"Extension requested: {job.url}\n")
            self._reply(200, {"ok": True, "id": job.id})

        def _handle_cancel(self):
            if not self._authorized():
                return
            data = self._read_json()
            if data is None:
                return

            job_id = data.get("id")
            if job_id is None:
                # No id -> cancel everything in flight (queued and running).
                ids = [j["id"] for j in manager.active_jobs()]
            elif isinstance(job_id, int) and not isinstance(job_id, bool):
                ids = [job_id]
            else:
                self._reply(400, {"ok": False, "error": "id must be an integer"})
                return

            cancelled = [i for i in ids if manager.cancel(i)]
            if cancelled:
                log(f"Extension cancelled job(s): {cancelled}\n")
            self._reply(200, {"ok": True, "cancelled": cancelled})

    return _Server(("127.0.0.1", settings.port), Handler)
