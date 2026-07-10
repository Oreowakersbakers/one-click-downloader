import json
import os
import queue
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request

from oneclickdl.config import Settings
from oneclickdl.downloader import DownloadManager, EV_FAILED
from oneclickdl.server import make_server


class DownloadManagerTests(unittest.TestCase):
    def test_submit_rejects_non_string_urls(self):
        manager = DownloadManager(Settings(), lambda: None)

        for value in (123, True, [], {}, object()):
            with self.subTest(value=value):
                self.assertIsNone(manager.submit(value))

    def test_setup_failure_does_not_kill_worker(self):
        failures = queue.Queue()
        ytdlp = {"path": "fake-yt-dlp"}

        with tempfile.TemporaryDirectory() as temp_dir:
            invalid_dir = os.path.join(temp_dir, "not-a-directory")
            with open(invalid_dir, "w", encoding="utf-8") as handle:
                handle.write("x")

            settings = Settings(download_dir=invalid_dir)
            manager = DownloadManager(settings, lambda: ytdlp["path"])
            manager.add_listener(
                lambda event, job, _data: failures.put(job)
                if event == EV_FAILED
                else None
            )

            first = manager.submit("https://example.com/first")
            first_failure = failures.get(timeout=2)
            self.assertEqual(first_failure.id, first.id)
            self.assertIn("not-a-directory", first_failure.error)

            # A second job must still be consumed by the same worker. Returning
            # no yt-dlp gives it a deterministic, side-effect-free failure.
            settings.download_dir = os.path.join(temp_dir, "downloads")
            ytdlp["path"] = None
            second = manager.submit("https://example.com/second")
            second_failure = failures.get(timeout=2)
            self.assertEqual(second_failure.id, second.id)
            self.assertIn("isn't available", second_failure.error)

            deadline = time.monotonic() + 2
            while manager.active_jobs() and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertEqual(manager.active_jobs(), [])


class ServerValidationTests(unittest.TestCase):
    def test_download_rejects_non_string_url_with_400(self):
        settings = Settings(port=0, token="test-token")
        manager = DownloadManager(settings, lambda: None)
        server = make_server(manager, settings)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_port}/download",
            data=json.dumps({"url": 123}).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-OneClick-Token": settings.token,
            },
            method="POST",
        )
        try:
            with self.assertRaises(urllib.error.HTTPError) as raised:
                urllib.request.urlopen(request, timeout=2)
            self.assertEqual(raised.exception.code, 400)
            payload = json.loads(raised.exception.read().decode("utf-8"))
            raised.exception.close()
            self.assertEqual(payload["error"], "missing or invalid url")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
