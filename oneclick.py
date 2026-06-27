"""One-Click Downloader — launcher.

Double-click this file, or run:  python oneclick.py

It wires the pieces together:
  * loads settings (and creates the pairing token on first run)
  * starts the download worker
  * starts the localhost helper server (for the browser extension)
  * opens the small desktop window
  * resolves / downloads yt-dlp in the background

The actual logic lives in the `oneclickdl` package — see oneclickdl/__init__.py
for the module map.
"""

import os
import sys
import threading
import tkinter as tk

# Make the package importable when double-clicked from any working directory.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from oneclickdl import config, ytdlp, tray  # noqa: E402
from oneclickdl.downloader import DownloadManager  # noqa: E402
from oneclickdl.server import make_server  # noqa: E402
from oneclickdl.gui import Window  # noqa: E402


def main():
    settings = config.Settings.load()

    # yt-dlp may still be downloading when the first job arrives, so the
    # manager asks for the path lazily via this holder.
    state = {"ytdlp": None}
    manager = DownloadManager(settings, lambda: state["ytdlp"])

    root = tk.Tk()
    window = Window(root, manager, settings)

    # Resolve / download yt-dlp without blocking the UI.
    def setup_ytdlp():
        state["ytdlp"] = ytdlp.ensure_ytdlp(window.log)
        if state["ytdlp"]:
            window.set_status("Ready. Click a video's download button, or paste a link.")

    threading.Thread(target=setup_ytdlp, daemon=True).start()

    # Start the local server the browser extension connects to.
    try:
        server = make_server(manager, settings, window.log)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        window.set_server_running(settings.port, settings.token)
    except OSError as e:
        window.log(f"Could not start helper server: {e}\n")
        window.conn_var.set("Helper server: failed to start (port in use?)")

    # Add a system-tray icon (Windows). Menu/double-click actions arrive on the
    # tray thread, so bounce them onto the GUI thread via root.after.
    tray_icon = tray.start(
        on_open=lambda: root.after(0, window.restore),
        on_quit=lambda: root.after(0, window.quit_app),
    )
    if tray_icon:
        window.enable_tray(tray_icon)

    root.mainloop()


if __name__ == "__main__":
    main()
