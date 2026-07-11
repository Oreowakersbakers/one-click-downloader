"""Make the app single-instance: a fresh launch takes over and kills the old one.

Nothing else stops you from double-clicking the app several times and ending up
with a pile of windows and tray icons all fighting over the same localhost port.
So on startup we record our PID in a lock file; the *next* launch reads that
file, terminates the process it names, then installs itself in the same way.

The lock stores the PID together with the process's start time. That pair
uniquely identifies a running process, so a stale lock left behind by a crash —
whose PID the OS may since have handed to some unrelated program — can never
make us kill an innocent bystander: the start time won't match.

Everything here is best-effort. If any step fails we just carry on starting the
app (running alongside an old copy is worse than crashing on launch would be).
"""

import os
import json
import time
import atexit
import signal

from . import config

LOCK_PATH = os.path.join(config.APP_DIR, "instance.lock")
IS_WINDOWS = config.IS_WINDOWS


# ---------------------------------------------------------------------------
# Per-platform primitives: read a process's start time, and terminate it.
#
# The start time is treated as an opaque token — we only ever compare it for
# equality with one we recorded earlier, never interpret it — so the two
# platforms are free to use whatever value is cheap to obtain.
# ---------------------------------------------------------------------------
if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    _PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    _PROCESS_TERMINATE = 0x0001
    _SYNCHRONIZE = 0x00100000

    class _FILETIME(ctypes.Structure):
        _fields_ = [
            ("dwLowDateTime", wintypes.DWORD),
            ("dwHighDateTime", wintypes.DWORD),
        ]

    # Declare signatures so handles round-trip as full-width pointers on 64-bit
    # (the ctypes default of c_int would truncate them).
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    _kernel32.GetCurrentProcess.argtypes = []
    _kernel32.GetProcessTimes.restype = wintypes.BOOL
    _kernel32.GetProcessTimes.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(_FILETIME),
        ctypes.POINTER(_FILETIME),
        ctypes.POINTER(_FILETIME),
        ctypes.POINTER(_FILETIME),
    ]
    _kernel32.TerminateProcess.restype = wintypes.BOOL
    _kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _kernel32.WaitForSingleObject.restype = wintypes.DWORD
    _kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    _kernel32.CloseHandle.restype = wintypes.BOOL
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    def _start_time_from_handle(handle):
        creation = _FILETIME()
        dummy = _FILETIME()
        if not _kernel32.GetProcessTimes(
            handle,
            ctypes.byref(creation),
            ctypes.byref(dummy),
            ctypes.byref(dummy),
            ctypes.byref(dummy),
        ):
            return None
        return (creation.dwHighDateTime << 32) | creation.dwLowDateTime

    def current_start_time():
        # GetCurrentProcess returns a pseudo-handle; no need to close it.
        return _start_time_from_handle(_kernel32.GetCurrentProcess())

    def start_time_of(pid):
        """Start-time token for a running pid, or None if it's gone/unreadable.

        Note: never use ``os.kill(pid, 0)`` on Windows as a liveness probe —
        signal 0 isn't special there, so it would call TerminateProcess and
        actually kill the process. Opening a handle is the safe check.
        """
        handle = _kernel32.OpenProcess(
            _PROCESS_QUERY_LIMITED_INFORMATION, False, pid
        )
        if not handle:
            return None
        try:
            return _start_time_from_handle(handle)
        finally:
            _kernel32.CloseHandle(handle)

    def terminate(pid):
        """Force-terminate pid and wait (briefly) for it to actually exit."""
        handle = _kernel32.OpenProcess(
            _PROCESS_TERMINATE | _SYNCHRONIZE, False, pid
        )
        if not handle:
            return
        try:
            _kernel32.TerminateProcess(handle, 1)
            _kernel32.WaitForSingleObject(handle, 5000)  # ms
        finally:
            _kernel32.CloseHandle(handle)

else:

    def start_time_of(pid):
        """Start-time token for a running pid, from /proc (Linux)."""
        try:
            with open("/proc/%d/stat" % pid, "r", encoding="utf-8") as f:
                data = f.read()
        except OSError:
            return None
        # The 22nd field is starttime. comm (2nd field) is wrapped in parens and
        # may itself contain spaces or ')', so split from the last ')'.
        rparen = data.rfind(")")
        if rparen == -1:
            return None
        fields = data[rparen + 2:].split()
        # After comm, index 0 is the 3rd field (state); starttime is the 22nd,
        # i.e. 22 - 3 = 19 positions along.
        return fields[19] if len(fields) > 19 else None

    def current_start_time():
        return start_time_of(os.getpid())

    def terminate(pid):
        """Ask pid to exit (SIGTERM), then escalate to SIGKILL if it lingers."""
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            return
        for _ in range(50):  # up to ~5s
            try:
                os.kill(pid, 0)
            except OSError:
                return  # gone
            time.sleep(0.1)
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Lock file
# ---------------------------------------------------------------------------
def _read_lock():
    """Return (pid, start_time) recorded in the lock, or None if unusable."""
    try:
        with open(LOCK_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return int(data["pid"]), data["start"]
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _write_lock():
    os.makedirs(config.APP_DIR, exist_ok=True)
    tmp = LOCK_PATH + ".tmp"
    payload = {"pid": os.getpid(), "start": current_start_time()}
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    os.replace(tmp, LOCK_PATH)  # atomic; no half-written lock


def _release():
    """On clean exit, remove the lock — but only if it's still ours.

    A successor that took over will have overwritten it with its own PID; we
    must not delete that one out from under it.
    """
    lock = _read_lock()
    if lock and lock[0] == os.getpid():
        try:
            os.remove(LOCK_PATH)
        except OSError:
            pass


def acquire(log=print):
    """Become the one running instance, terminating any predecessor.

    Safe to call once at startup. Any failure is logged and swallowed so the
    app still starts.
    """
    try:
        lock = _read_lock()
        if lock:
            pid, start = lock
            # Only kill a process that is genuinely the previous instance:
            # a live PID whose start time matches what the lock recorded.
            if pid != os.getpid() and start_time_of(pid) == start:
                log("Another instance is running (pid %d); shutting it down.\n" % pid)
                terminate(pid)
        _write_lock()
        atexit.register(_release)
    except Exception as e:  # never let instance management block startup
        log("Single-instance check skipped: %s\n" % e)
