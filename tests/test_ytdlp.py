import os
import time
import tempfile
import unittest
import subprocess
from unittest import mock

from oneclickdl import config, ytdlp


class FakeCompleted:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class JsRuntimeTests(unittest.TestCase):
    def setUp(self):
        ytdlp.find_js_runtime.cache_clear()
        self.addCleanup(ytdlp.find_js_runtime.cache_clear)

    def test_prefers_deno_when_several_are_installed(self):
        with mock.patch.object(ytdlp.shutil, "which", side_effect=lambda n: f"/bin/{n}"):
            self.assertEqual(ytdlp.find_js_runtime(), "deno")
            self.assertEqual(ytdlp.js_runtime_args(), ["--js-runtimes", "deno"])

    def test_falls_back_to_node_when_deno_is_missing(self):
        installed = {"node": "/usr/bin/node"}
        with mock.patch.object(ytdlp.shutil, "which", side_effect=installed.get):
            self.assertEqual(ytdlp.find_js_runtime(), "node")
            self.assertEqual(ytdlp.js_runtime_args(), ["--js-runtimes", "node"])

    def test_no_runtime_yields_no_arguments(self):
        with mock.patch.object(ytdlp.shutil, "which", return_value=None):
            self.assertIsNone(ytdlp.find_js_runtime())
            # No flag at all, so yt-dlp keeps its own default behaviour.
            self.assertEqual(ytdlp.js_runtime_args(), [])


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.bin_dir = self.temp.name
        self.binary = os.path.join(self.bin_dir, "yt-dlp.exe")
        with open(self.binary, "w", encoding="utf-8") as f:
            f.write("x")
        self.stamp = os.path.join(self.bin_dir, ".last-update-check")

        for target, value in (
            ("BIN_DIR", self.bin_dir),
            ("YTDLP_BIN", self.binary),
        ):
            patcher = mock.patch.object(config, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(ytdlp, "_STAMP_PATH", self.stamp)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_skips_a_binary_we_do_not_own(self):
        """A yt-dlp from brew/pip/winget belongs to its package manager."""
        with mock.patch.object(ytdlp.subprocess, "run") as run:
            ytdlp.update("/usr/local/bin/yt-dlp")
        run.assert_not_called()

    def test_updates_when_no_stamp_exists(self):
        with mock.patch.object(
            ytdlp.subprocess, "run", return_value=FakeCompleted(stdout="Updated!")
        ) as run:
            ytdlp.update(self.binary)
        run.assert_called_once()
        self.assertEqual(run.call_args[0][0], [self.binary, "-U"])
        self.assertTrue(os.path.exists(self.stamp))

    def test_skips_while_the_stamp_is_fresh(self):
        with open(self.stamp, "w", encoding="utf-8") as f:
            f.write("0")
        with mock.patch.object(ytdlp.subprocess, "run") as run:
            ytdlp.update(self.binary)
        run.assert_not_called()

    def test_updates_again_once_the_stamp_is_stale(self):
        with open(self.stamp, "w", encoding="utf-8") as f:
            f.write("0")
        stale = time.time() - (ytdlp.UPDATE_INTERVAL_DAYS + 1) * 86400
        os.utime(self.stamp, (stale, stale))
        with mock.patch.object(
            ytdlp.subprocess, "run", return_value=FakeCompleted()
        ) as run:
            ytdlp.update(self.binary)
        run.assert_called_once()

    def test_force_ignores_a_fresh_stamp(self):
        with open(self.stamp, "w", encoding="utf-8") as f:
            f.write("0")
        with mock.patch.object(
            ytdlp.subprocess, "run", return_value=FakeCompleted()
        ) as run:
            ytdlp.update(self.binary, force=True)
        run.assert_called_once()

    def test_timeout_is_reported_and_leaves_the_stamp_alone(self):
        """An offline machine should retry next launch, not wait a week."""
        logged = []
        with mock.patch.object(
            ytdlp.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(cmd="yt-dlp", timeout=1),
        ):
            ytdlp.update(self.binary, logged.append)
        self.assertFalse(os.path.exists(self.stamp))
        self.assertTrue(any("timed out" in line for line in logged))

    def test_a_failed_update_is_logged_but_not_raised(self):
        logged = []
        with mock.patch.object(
            ytdlp.subprocess,
            "run",
            return_value=FakeCompleted(returncode=1, stderr="ERROR: no write access"),
        ):
            ytdlp.update(self.binary, logged.append)
        self.assertTrue(any("no write access" in line for line in logged))

    def test_launcher_errors_do_not_propagate(self):
        logged = []
        with mock.patch.object(
            ytdlp.subprocess, "run", side_effect=OSError("not executable")
        ):
            ytdlp.update(self.binary, logged.append)
        self.assertTrue(any("not executable" in line for line in logged))


if __name__ == "__main__":
    unittest.main()
