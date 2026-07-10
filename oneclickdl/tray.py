"""A Windows system-tray icon, using only ctypes (no third-party packages).

Keeps with the project's "nothing to install" design. Importing this module is
always safe; `start()` returns a Tray on Windows and None elsewhere, so the app
just runs without a tray on other platforms.

The tray runs its own Win32 message loop on a background thread. Menu clicks are
handed back through the `on_open` / `on_quit` callbacks you pass in — those fire
on the tray thread, so they should marshal to the GUI thread themselves
(e.g. tkinter's root.after).
"""

import os
import threading
import ctypes
from ctypes import wintypes

IS_WINDOWS = os.name == "nt"
ICON_PATH = os.path.join(os.path.dirname(__file__), "assets", "oneclick.ico")

# ---- Win32 message / flag constants ----
WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_COMMAND = 0x0111
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONUP = 0x0205
WM_USER = 0x0400
TRAY_CALLBACK = WM_USER + 20

NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP, NIF_INFO = 0x01, 0x02, 0x04, 0x10

IMAGE_ICON = 1
LR_LOADFROMFILE, LR_DEFAULTSIZE = 0x10, 0x40

MF_STRING = 0x0000
TPM_RIGHTBUTTON = 0x0002

ID_OPEN, ID_QUIT = 1, 2

if IS_WINDOWS:
    # WINFUNCTYPE and the Win32 structure types are unavailable on POSIX.
    # Keep every platform-specific declaration behind the same guard as
    # start(), so importing the application remains safe on macOS/Linux.
    LRESULT = ctypes.c_ssize_t
    WNDPROC = ctypes.WINFUNCTYPE(
        LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
    )

    class WNDCLASSEX(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.UINT),
            ("style", wintypes.UINT),
            ("lpfnWndProc", WNDPROC),
            ("cbClsExtra", ctypes.c_int),
            ("cbWndExtra", ctypes.c_int),
            ("hInstance", wintypes.HINSTANCE),
            ("hIcon", wintypes.HICON),
            ("hCursor", wintypes.HANDLE),
            ("hbrBackground", wintypes.HBRUSH),
            ("lpszMenuName", wintypes.LPCWSTR),
            ("lpszClassName", wintypes.LPCWSTR),
            ("hIconSm", wintypes.HICON),
        ]

    class NOTIFYICONDATA(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("hWnd", wintypes.HWND),
            ("uID", wintypes.UINT),
            ("uFlags", wintypes.UINT),
            ("uCallbackMessage", wintypes.UINT),
            ("hIcon", wintypes.HICON),
            ("szTip", wintypes.WCHAR * 128),
            ("dwState", wintypes.DWORD),
            ("dwStateMask", wintypes.DWORD),
            ("szInfo", wintypes.WCHAR * 256),
            ("uVersion", wintypes.UINT),
            ("szInfoTitle", wintypes.WCHAR * 64),
            ("dwInfoFlags", wintypes.DWORD),
            ("guidItem", ctypes.c_byte * 16),
            ("hBalloonIcon", wintypes.HICON),
        ]


def _setup_prototypes():
    """Declare restype/argtypes so 64-bit handles/pointers aren't truncated."""
    u, k, s = ctypes.windll.user32, ctypes.windll.kernel32, ctypes.windll.shell32
    HWND, HMENU, HINST = wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE
    UINT, DWORD, INT = wintypes.UINT, wintypes.DWORD, ctypes.c_int
    LPVOID, LPCWSTR = wintypes.LPVOID, wintypes.LPCWSTR
    UINT_PTR = ctypes.c_size_t

    k.GetModuleHandleW.restype = wintypes.HMODULE
    k.GetModuleHandleW.argtypes = [LPCWSTR]

    u.DefWindowProcW.restype = LRESULT
    u.DefWindowProcW.argtypes = [HWND, UINT, wintypes.WPARAM, wintypes.LPARAM]
    u.RegisterClassExW.restype = wintypes.ATOM
    u.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEX)]
    u.CreateWindowExW.restype = HWND
    u.CreateWindowExW.argtypes = [
        DWORD, LPCWSTR, LPCWSTR, DWORD, INT, INT, INT, INT,
        HWND, HMENU, HINST, LPVOID,
    ]
    u.DestroyWindow.argtypes = [HWND]
    u.LoadImageW.restype = wintypes.HANDLE
    u.LoadImageW.argtypes = [HINST, LPCWSTR, UINT, INT, INT, UINT]
    u.CreatePopupMenu.restype = HMENU
    u.AppendMenuW.argtypes = [HMENU, UINT, UINT_PTR, LPCWSTR]
    u.TrackPopupMenu.argtypes = [HMENU, UINT, INT, INT, INT, HWND, LPVOID]
    u.DestroyMenu.argtypes = [HMENU]
    u.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
    u.SetForegroundWindow.argtypes = [HWND]
    u.PostMessageW.argtypes = [HWND, UINT, wintypes.WPARAM, wintypes.LPARAM]
    u.GetMessageW.argtypes = [
        ctypes.POINTER(wintypes.MSG), HWND, UINT, UINT
    ]

    s.Shell_NotifyIconW.restype = wintypes.BOOL
    s.Shell_NotifyIconW.argtypes = [DWORD, ctypes.POINTER(NOTIFYICONDATA)]
    return u, k


class Tray:
    def __init__(self, on_open, on_quit, tooltip="One-Click Downloader"):
        self._on_open = on_open
        self._on_quit = on_quit
        self._tooltip = tooltip
        self._hwnd = None
        self._nid = None
        self._wndproc = None  # keep a ref so the callback isn't GC'd
        self._wndclass = None
        self._notified = False
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    # ---- the tray thread ----
    def _run(self):
        user32, kernel32 = _setup_prototypes()
        hinst = kernel32.GetModuleHandleW(None)

        self._wndproc = WNDPROC(self._handle)
        wc = WNDCLASSEX()
        wc.cbSize = ctypes.sizeof(WNDCLASSEX)
        wc.lpfnWndProc = self._wndproc
        wc.hInstance = hinst
        wc.lpszClassName = "OneClickDLTray"
        self._wndclass = wc
        user32.RegisterClassExW(ctypes.byref(wc))

        self._hwnd = user32.CreateWindowExW(
            0, "OneClickDLTray", "OneClickDL", 0, 0, 0, 0, 0, None, None, hinst, None
        )

        hicon = user32.LoadImageW(
            None, ICON_PATH, IMAGE_ICON, 0, 0, LR_LOADFROMFILE | LR_DEFAULTSIZE
        )

        nid = NOTIFYICONDATA()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATA)
        nid.hWnd = self._hwnd
        nid.uID = 1
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        nid.uCallbackMessage = TRAY_CALLBACK
        nid.hIcon = hicon
        nid.szTip = self._tooltip
        self._nid = nid
        ctypes.windll.shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid))

        # Standard Win32 message pump.
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

        ctypes.windll.shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))

    # ---- window procedure ----
    def _handle(self, hwnd, msg, wparam, lparam):
        user32 = ctypes.windll.user32
        if msg == TRAY_CALLBACK:
            event = lparam & 0xFFFF
            if event == WM_LBUTTONDBLCLK:
                self._safe(self._on_open)
            elif event == WM_RBUTTONUP:
                self._show_menu(hwnd)
            return 0
        if msg == WM_COMMAND:
            cmd = wparam & 0xFFFF
            if cmd == ID_OPEN:
                self._safe(self._on_open)
            elif cmd == ID_QUIT:
                self._safe(self._on_quit)
            return 0
        if msg == WM_CLOSE:
            user32.DestroyWindow(hwnd)
            return 0
        if msg == WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _show_menu(self, hwnd):
        user32 = ctypes.windll.user32
        menu = user32.CreatePopupMenu()
        user32.AppendMenuW(menu, MF_STRING, ID_OPEN, "Open window")
        user32.AppendMenuW(menu, MF_STRING, ID_QUIT, "Quit")
        pt = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        # Required so the menu closes when you click elsewhere.
        user32.SetForegroundWindow(hwnd)
        user32.TrackPopupMenu(
            menu, TPM_RIGHTBUTTON, pt.x, pt.y, 0, hwnd, None
        )
        user32.DestroyMenu(menu)

    @staticmethod
    def _safe(fn):
        try:
            fn()
        except Exception:
            pass

    # ---- public API (called from the GUI thread) ----
    def notify(self, title, message):
        """Show a one-shot balloon from the tray icon."""
        if not self._nid:
            return
        nid = self._nid
        nid.uFlags = NIF_INFO
        nid.szInfoTitle = title
        nid.szInfo = message
        try:
            ctypes.windll.shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))
        except Exception:
            pass

    def notify_once(self, title, message):
        if not self._notified:
            self._notified = True
            self.notify(title, message)

    def stop(self):
        if self._hwnd:
            ctypes.windll.user32.PostMessageW(self._hwnd, WM_CLOSE, 0, 0)


def start(on_open, on_quit, tooltip="One-Click Downloader"):
    """Create the tray icon. Returns a Tray, or None if unavailable."""
    if not IS_WINDOWS:
        return None
    try:
        return Tray(on_open, on_quit, tooltip)
    except Exception:
        return None
