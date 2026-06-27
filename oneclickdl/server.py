"""A tiny localhost-only HTTP API that the browser extension talks to.

The browser extension can't run yt-dlp itself (browsers are sandboxed), so it
sends the video URL here and this process does the download. Built on the
standard library only — no extra dependencies.

Endpoints:
    GET  /ping       -> {"ok": true, ...}     (lets the extension detect us)
    POST /download   -> {"ok": true, "id": N} (body: {"url": "..."}; needs token)

Security model (for a personal tool):
    * Bound to 127.0.0.1 only — nothing on the network can reach it.
    * /download requires the shared token (header X-OneClick-Token) so a random
      web page that happens to know the port still can't trigger downloads.
"""

import hmac
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# The body is only ever a tiny JSON object ({"url": "..."}); cap it so a client
# can't claim a huge Content-Length and make us allocate / read unbounded data.
MAX_BODY_BYTES = 64 * 1024


def make_server(manager, settings, log=lambda msg: None):
    """Build (but don't start) the HTTP server. Call .serve_forever() on it."""

    class Handler(BaseHTTPRequestHandler):
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

        # ---- routes ----
        def do_OPTIONS(self):
            self.send_response(204)
            self._cors()
            self.end_headers()

        def do_GET(self):
            if self._path() == "/ping":
                self._reply(200, {"ok": True, "app": "oneclick-dl"})
            else:
                self._reply(404, {"ok": False, "error": "not found"})

        def do_POST(self):
            if self._path() != "/download":
                self._reply(404, {"ok": False, "error": "not found"})
                return

            # Constant-time compare so the token can't be guessed by timing the
            # response. Encode to bytes first: compare_digest rejects non-ASCII
            # str input with a TypeError, and a header value is attacker-supplied.
            sent = self.headers.get("X-OneClick-Token", "").encode("utf-8")
            if not hmac.compare_digest(sent, settings.token.encode("utf-8")):
                self._reply(403, {"ok": False, "error": "bad or missing token"})
                return

            try:
                length = int(self.headers.get("Content-Length", 0) or 0)
            except ValueError:
                self._reply(400, {"ok": False, "error": "invalid Content-Length"})
                return
            if length < 0 or length > MAX_BODY_BYTES:
                self._reply(413, {"ok": False, "error": "request body too large"})
                return

            raw = self.rfile.read(length) if length else b"{}"
            try:
                data = json.loads(raw.decode("utf-8") or "{}")
            except ValueError:
                self._reply(400, {"ok": False, "error": "invalid JSON"})
                return

            job = manager.submit(data.get("url", ""))
            if not job:
                self._reply(400, {"ok": False, "error": "missing or invalid url"})
                return

            log(f"Extension requested: {job.url}\n")
            self._reply(200, {"ok": True, "id": job.id})

    return ThreadingHTTPServer(("127.0.0.1", settings.port), Handler)
