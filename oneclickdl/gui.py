"""The small desktop window.

It does two jobs:
  1. A manual fallback — paste a link and hit Download (for sites the browser
     button doesn't cover, or when you just have a URL).
  2. Visibility — a progress bar + log so you can see what's happening, plus
     the connection details the browser extension needs.

The clipboard-watching from the old version is intentionally gone; the browser
button (and this manual box) replace it.
"""

import os
import sys
import subprocess
import tkinter as tk
from tkinter import ttk, messagebox

from . import config, downloader


class Window:
    def __init__(self, root, manager, settings):
        self.root = root
        self.manager = manager
        self.settings = settings
        self.tray = None

        root.title("One-Click Downloader")
        root.geometry("600x520")
        root.minsize(520, 460)

        pad = {"padx": 12, "pady": 6}

        # ---- manual URL row ----
        ttk.Label(root, text="Video URL", font=("Segoe UI", 10, "bold")).pack(
            anchor="w", **pad
        )
        self.url_var = tk.StringVar()
        entry = ttk.Entry(root, textvariable=self.url_var)
        entry.pack(fill="x", padx=12)
        entry.bind("<Return>", lambda _e: self.start_download())

        btn_row = ttk.Frame(root)
        btn_row.pack(fill="x", **pad)
        self.dl_btn = ttk.Button(btn_row, text="Download", command=self.start_download)
        self.dl_btn.pack(side="left")
        ttk.Button(btn_row, text="Open folder", command=self.open_folder).pack(
            side="left", padx=8
        )

        # ---- progress + status ----
        self.progress = ttk.Progressbar(root, mode="determinate", maximum=100)
        self.progress.pack(fill="x", padx=12, pady=(4, 0))

        self.status = tk.StringVar(value="Starting up...")
        ttk.Label(root, textvariable=self.status, foreground="#555").pack(
            anchor="w", padx=12, pady=(6, 0)
        )

        # ---- log box ----
        self.log_box = tk.Text(
            root, height=10, wrap="word", state="disabled",
            bg="#111", fg="#0f0", font=("Consolas", 9),
        )
        self.log_box.pack(fill="both", expand=True, padx=12, pady=(8, 4))

        # ---- browser-extension connection panel ----
        ext = ttk.LabelFrame(root, text="Browser extension")
        ext.pack(fill="x", padx=12, pady=(0, 12))
        self.conn_var = tk.StringVar(value="Helper server: starting...")
        ttk.Label(ext, textvariable=self.conn_var).pack(anchor="w", padx=8, pady=(6, 0))

        token_row = ttk.Frame(ext)
        token_row.pack(fill="x", padx=8, pady=(2, 8))
        ttk.Label(token_row, text="Pairing token:").pack(side="left")
        self.token_var = tk.StringVar(value=settings.token)
        token_entry = ttk.Entry(
            token_row, textvariable=self.token_var, state="readonly"
        )
        token_entry.pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(token_row, text="Copy", command=self._copy_token).pack(side="left")

        # Listen for download events (called from the worker thread).
        manager.add_listener(self._on_event)

    # ---- system tray ----
    def enable_tray(self, tray):
        """Route the window's close/minimize buttons to the tray icon."""
        self.tray = tray
        # Closing [X] hides to the tray instead of quitting.
        self.root.protocol("WM_DELETE_WINDOW", self.hide_to_tray)
        # Minimizing also tucks it into the tray (off the taskbar).
        self.root.bind("<Unmap>", self._on_unmap)

    def _on_unmap(self, event):
        if event.widget is self.root and self.root.state() == "iconic":
            self.hide_to_tray()

    def hide_to_tray(self):
        self.root.withdraw()
        if self.tray:
            self.tray.notify_once(
                "One-Click Downloader",
                "Still running here. Right-click to quit.",
            )

    def restore(self):
        self.root.deiconify()
        self.root.state("normal")
        self.root.lift()
        self.root.focus_force()

    def quit_app(self):
        if self.tray:
            self.tray.stop()
        self.root.destroy()

    # ---- thread-safe helpers ----
    def log(self, msg):
        self.root.after(0, lambda: self._append_log(msg))

    def _append_log(self, msg):
        self.log_box.config(state="normal")
        self.log_box.insert("end", msg)
        self.log_box.see("end")
        self.log_box.config(state="disabled")

    def set_status(self, text):
        self.root.after(0, lambda: self.status.set(text))

    def set_server_running(self, port, token):
        self.root.after(
            0,
            lambda: self.conn_var.set(
                f"Helper server: running on http://127.0.0.1:{port}"
            ),
        )

    # ---- actions ----
    def start_download(self):
        url = self.url_var.get().strip()
        if not url:
            messagebox.showinfo("No URL", "Paste a video link first.")
            return
        self.manager.submit(url)
        self.url_var.set("")

    def open_folder(self):
        path = self.settings.download_dir
        os.makedirs(path, exist_ok=True)
        if config.IS_WINDOWS:
            os.startfile(path)  # noqa: B606
        elif sys.platform == "darwin":
            subprocess.run(["open", path])
        else:
            subprocess.run(["xdg-open", path])

    def _copy_token(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.token_var.get())
        self.set_status("Token copied — paste it into the extension's options.")

    # ---- download events ----
    def _on_event(self, event, job, data=None):
        self.root.after(0, lambda: self._apply_event(event, job, data))

    def _apply_event(self, event, job, data):
        if event == downloader.EV_QUEUED:
            self.log(f"\n>>> queued: {job.url}\n")
        elif event == downloader.EV_STARTED:
            self.progress["value"] = 0
            self.set_status("Downloading...")
        elif event == downloader.EV_PROGRESS:
            self.progress["value"] = data or 0
            self.set_status(f"Downloading... {data:.0f}%")
        elif event == downloader.EV_LOG:
            self._append_log(data + "\n")
        elif event == downloader.EV_DONE:
            self.progress["value"] = 100
            self.set_status("Done! Saved to your downloads folder.")
            self._append_log("✓ Finished.\n")
        elif event == downloader.EV_FAILED:
            self.set_status("Failed — see log.")
            self._append_log(f"✗ {job.error}\n")
