import json
import os
import queue
import tempfile
import threading
import time
import unittest
from unittest import mock
import urllib.error
import urllib.request

from oneclickdl import config
from oneclickdl.config import Settings
from oneclickdl.downloader import (
    DownloadManager,
    EV_CANCELLED,
    EV_DONE,
    EV_FAILED,
    EV_PROGRESS,
)
from oneclickdl.server import make_server


class FakeProc:
    """Stands in for the yt-dlp process: scripted output, then an exit."""

    def __init__(self, lines, on_wait=None, returncode=0):
        self.returncode = returncode
        self.pid = 4242
        self.stdout = iter(lines)
        self._on_wait = on_wait

    def poll(self):
        return self.returncode

    def wait(self):
        if self._on_wait:
            self._on_wait()
        return self.returncode


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


    def test_cancel_racing_a_clean_exit_keeps_the_file(self):
        """A cancel that lands after yt-dlp already exited cleanly must not
        delete the finished download — the clean exit wins."""
        events = queue.Queue()

        with tempfile.TemporaryDirectory() as download_dir:
            out_path = os.path.join(download_dir, "video [abc].mp4")
            with open(out_path, "w", encoding="utf-8") as handle:
                handle.write("finished download")

            settings = Settings(download_dir=download_dir)
            manager = DownloadManager(settings, lambda: "fake-yt-dlp")
            manager.add_listener(
                lambda event, job, data=None: events.put((event, job))
            )

            job_box = {}
            popen_kwargs = {}

            def fake_popen(cmd, **kwargs):
                popen_kwargs.update(kwargs)
                return FakeProc(
                    [
                        f"[download] Destination: {out_path}\n",
                        "[download] 100% of 1.00MiB\n",
                    ],
                    # Fires inside proc.wait(), i.e. after the process has
                    # exited but before the worker resolves the final status —
                    # exactly the window the race lives in.
                    on_wait=lambda: manager.cancel(job_box["job"].id),
                )

            with mock.patch("oneclickdl.downloader.subprocess.Popen", fake_popen):
                job_box["job"] = manager.submit("https://example.com/v")

                deadline = time.monotonic() + 2
                terminal = None
                while terminal is None and time.monotonic() < deadline:
                    event, _job = events.get(timeout=2)
                    if event in (EV_DONE, EV_CANCELLED, EV_FAILED):
                        terminal = event

            self.assertEqual(terminal, EV_DONE)
            self.assertTrue(os.path.exists(out_path), "finished file was deleted")
            # The pipe must be decoded as UTF-8, never the locale codec — a
            # title cp1252 can't decode used to abort the read loop and orphan
            # the process.
            self.assertEqual(popen_kwargs.get("encoding"), "utf-8")
            self.assertEqual(popen_kwargs.get("errors"), "replace")


    def test_playlist_cancel_keeps_finished_entries(self):
        """A playlist job folds per-entry progress into one overall bar, and
        cancelling mid-playlist only removes the entry still in flight."""
        events = queue.Queue()
        progress = []

        with tempfile.TemporaryDirectory() as download_dir:
            sub = os.path.join(download_dir, "My Playlist")
            os.makedirs(sub)
            done_path = os.path.join(sub, "first [a1].mp4")
            partial_path = os.path.join(sub, "second [b2].mp4")
            for path in (done_path, partial_path):
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write("x")

            settings = Settings(download_dir=download_dir)
            manager = DownloadManager(settings, lambda: "fake-yt-dlp")

            def listener(event, job, data=None):
                if event == EV_PROGRESS:
                    progress.append(data)
                events.put((event, job))

            manager.add_listener(listener)

            job_box = {}
            captured_cmd = []

            def fake_popen(cmd, **kwargs):
                captured_cmd.extend(cmd)
                return FakeProc(
                    [
                        "[download] Downloading playlist: My Playlist\n",
                        "[download] Downloading item 1 of 2\n",
                        f"[download] Destination: {done_path}\n",
                        "[download] 100% of 1.00MiB\n",
                        "[download] Downloading item 2 of 2\n",
                        f"[download] Destination: {partial_path}\n",
                        "[download]  50.0% of 1.00MiB\n",
                    ],
                    # Cancel lands while entry 2 is mid-download; the process
                    # "dies" with a nonzero code, as a killed yt-dlp would.
                    on_wait=lambda: manager.cancel(job_box["job"].id),
                    returncode=1,
                )

            with mock.patch("oneclickdl.downloader.subprocess.Popen", fake_popen):
                job_box["job"] = manager.submit(
                    "https://youtube.com/playlist?list=PL1", playlist=True
                )

                deadline = time.monotonic() + 2
                terminal = None
                while terminal is None and time.monotonic() < deadline:
                    event, _job = events.get(timeout=2)
                    if event in (EV_DONE, EV_CANCELLED, EV_FAILED):
                        terminal = event

            self.assertEqual(terminal, EV_CANCELLED)
            self.assertIn("--yes-playlist", captured_cmd)
            # Overall progress: entry 1 done -> 50%, entry 2 at 50% -> 75%.
            self.assertEqual(progress, [50.0, 75.0])
            # Entry 1 finished before the cancel — it must survive; only the
            # in-flight entry 2 gets cleaned up (inside the playlist subfolder).
            self.assertTrue(os.path.exists(done_path), "finished entry deleted")
            self.assertFalse(os.path.exists(partial_path), "partial entry kept")


class SettingsPersistenceTests(unittest.TestCase):
    def test_corrupt_settings_file_is_replaced(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_path = os.path.join(temp_dir, "settings.json")
            with open(settings_path, "w", encoding="utf-8") as handle:
                handle.write("{ this is not json")

            with mock.patch.multiple(
                config, APP_DIR=temp_dir, SETTINGS_PATH=settings_path
            ):
                loaded = Settings.load()
                self.assertTrue(loaded.token)
                # The corrupt file was replaced with valid JSON, atomically
                # (no leftover temp file).
                with open(settings_path, encoding="utf-8") as handle:
                    data = json.load(handle)
                self.assertEqual(data["token"], loaded.token)
                self.assertFalse(os.path.exists(settings_path + ".tmp"))

    def test_unreadable_settings_file_is_not_overwritten(self):
        """A transient read failure (file locked by AV/backup) must not
        clobber the settings on disk — that would break extension pairing."""
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_path = os.path.join(temp_dir, "settings.json")
            original = '{"token": "keep-me"}'
            with open(settings_path, "w", encoding="utf-8") as handle:
                handle.write(original)

            with mock.patch.multiple(
                config, APP_DIR=temp_dir, SETTINGS_PATH=settings_path
            ):
                with mock.patch(
                    "builtins.open", side_effect=PermissionError("locked")
                ):
                    loaded = Settings.load()
                # The session still gets a usable (ephemeral) token...
                self.assertTrue(loaded.token)
                # ...but the file on disk is untouched.
                with open(settings_path, encoding="utf-8") as handle:
                    self.assertEqual(handle.read(), original)


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
