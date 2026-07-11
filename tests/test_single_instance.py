import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parents[1]))

from oneclickdl import single_instance as si


class SingleInstanceTests(unittest.TestCase):
    def setUp(self):
        # Point the lock at a throwaway path so we never touch the real one.
        self._orig_lock = si.LOCK_PATH
        tmp = Path(self.__class__.__name__ + "_lock.json").resolve()
        si.LOCK_PATH = str(tmp)
        self.addCleanup(self._restore)

    def _restore(self):
        try:
            os.remove(si.LOCK_PATH)
        except OSError:
            pass
        si.LOCK_PATH = self._orig_lock

    def test_our_own_pid_reports_a_start_time(self):
        self.assertIsNotNone(si.current_start_time())
        self.assertEqual(si.start_time_of(os.getpid()), si.current_start_time())

    def test_write_then_read_round_trips_our_identity(self):
        si._write_lock()
        pid, start = si._read_lock()
        self.assertEqual(pid, os.getpid())
        self.assertEqual(start, si.current_start_time())

    def test_read_lock_returns_none_for_junk(self):
        with open(si.LOCK_PATH, "w", encoding="utf-8") as f:
            f.write("not json{")
        self.assertIsNone(si._read_lock())

    def test_release_only_removes_our_own_lock(self):
        # A lock owned by someone else must survive our _release().
        with open(si.LOCK_PATH, "w", encoding="utf-8") as f:
            json.dump({"pid": os.getpid() + 1, "start": "x"}, f)
        si._release()
        self.assertTrue(os.path.exists(si.LOCK_PATH))

        # Our own lock should be cleaned up.
        si._write_lock()
        si._release()
        self.assertFalse(os.path.exists(si.LOCK_PATH))

    def test_acquire_terminates_a_matching_predecessor(self):
        # Lock names a "previous instance"; start time matches -> terminate it.
        prev_pid = os.getpid() + 1
        with open(si.LOCK_PATH, "w", encoding="utf-8") as f:
            json.dump({"pid": prev_pid, "start": "MATCH"}, f)

        with mock.patch.object(si, "start_time_of", return_value="MATCH"), \
                mock.patch.object(si, "terminate") as killed, \
                mock.patch.object(si.atexit, "register"):
            si.acquire(log=lambda *_: None)

        killed.assert_called_once_with(prev_pid)
        # Lock is now ours.
        self.assertEqual(si._read_lock()[0], os.getpid())

    def test_acquire_spares_a_stale_lock_with_mismatched_start(self):
        # Same PID could be recycled; a mismatched start time must NOT kill it.
        with open(si.LOCK_PATH, "w", encoding="utf-8") as f:
            json.dump({"pid": os.getpid() + 1, "start": "OLD"}, f)

        with mock.patch.object(si, "start_time_of", return_value="DIFFERENT"), \
                mock.patch.object(si, "terminate") as killed, \
                mock.patch.object(si.atexit, "register"):
            si.acquire(log=lambda *_: None)

        killed.assert_not_called()

    def test_acquire_never_targets_our_own_pid(self):
        with open(si.LOCK_PATH, "w", encoding="utf-8") as f:
            json.dump({"pid": os.getpid(), "start": si.current_start_time()}, f)

        with mock.patch.object(si, "terminate") as killed, \
                mock.patch.object(si.atexit, "register"):
            si.acquire(log=lambda *_: None)

        killed.assert_not_called()


if __name__ == "__main__":
    unittest.main()
