"""The small desktop window.

It does two jobs:
  1. A manual fallback — paste a link and hit Download (for sites the browser
     button doesn't cover, or when you just have a URL).
  2. Visibility — a status "heartbeat" (state dot + progress + percentage) and a
     colour-coded activity log so you can see what's happening, plus the
     connection details the browser extension needs.

Look & feel
-----------
Deliberately compact: the window is a strip, not a dashboard. One row to paste
a link, one status line with a progress bar, and a single footer line that
holds everything else (open folder, activity toggle, extension status, copy
token). The activity log is collapsed by default and only claims height when
you expand it — or when a download fails, since the error details live there.

The palette is built around the app's own icon colour — indigo ``#4F46E5``.
To keep the project's "nothing to install" promise (see tray.py), everything
here is pure stdlib tkinter.

The clipboard-watching from the old version is intentionally gone; the browser
button (and this manual box) replace it.
"""

import os
import sys
import subprocess
import tkinter as tk
from tkinter import ttk, messagebox

from . import config, downloader

ICON_PATH = os.path.join(os.path.dirname(__file__), "assets", "oneclick.ico")

# ---------------------------------------------------------------------------
# Design tokens — one source of truth for colour, derived from the app icon.
# ---------------------------------------------------------------------------
BG = "#F4F5FB"          # window background — a soft indigo-tinted white
SURFACE = "#FFFFFF"     # input fields
INK = "#1E1B33"         # primary text — a deep, near-black indigo
MUTED = "#6E6A86"       # secondary text
FAINT = "#9A96B0"       # tertiary text / placeholder / idle dot
LINE = "#E4E3F0"        # hairline borders

ACCENT = "#4F46E5"      # brand indigo (straight from oneclick.ico)
ACCENT_D = "#4338CA"    # accent, pressed/hover
ACCENT_SOFT = "#ECEBFB" # subtle accent fill / progress trough

OK = "#0E9F6E"          # success
ERR = "#E02424"         # failure
AMBER = "#C2710C"       # cancelled / warming up

PAD = 14                # outer content padding


class Window:
    def __init__(self, root, manager, settings):
        self.root = root
        self.manager = manager
        self.settings = settings
        self.tray = None
        # The job currently running, so the Cancel button knows what to stop.
        self._active_job_id = None
        # True while the URL box shows greyed placeholder text (not real input).
        self._placeholder_on = False
        # True while the activity log is expanded.
        self._activity_shown = False

        root.title("One-Click Downloader")
        root.configure(bg=BG)
        # Replace tkinter's default feather with the app's own icon.
        try:
            root.iconbitmap(ICON_PATH)
        except tk.TclError:
            pass

        self._setup_styles()

        body = tk.Frame(root, bg=BG)
        body.pack(fill="both", expand=True, padx=PAD, pady=PAD)

        self._build_url_row(body)
        self._build_status(body)
        self._build_footer(body)
        self._build_activity(body)  # created unpacked; the footer toggle shows it

        # Listen for download events (called from the worker thread).
        manager.add_listener(self._on_event)

        # Size the window to exactly fit the collapsed layout, and remember
        # that height so the activity toggle can grow/shrink around it.
        root.update_idletasks()
        self._collapsed_h = root.winfo_reqheight()
        root.geometry(f"560x{self._collapsed_h}")
        root.minsize(500, self._collapsed_h)

    # ---- one-time theming -------------------------------------------------
    def _setup_styles(self):
        """Style the only ttk widget we use (the progress bar).

        Everything else is a classic tk widget so we get exact colour control;
        ttk's Progressbar is the exception because it's the cleanest way to get a
        smooth determinate bar. ``clam`` is the one built-in theme that lets us
        recolour the trough and bar freely.
        """
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        # A bar per state, swapped in as the download progresses.
        for name, colour in (("Accent", ACCENT), ("OK", OK), ("Err", ERR)):
            style.configure(
                f"{name}.Horizontal.TProgressbar",
                troughcolor=ACCENT_SOFT,
                bordercolor=ACCENT_SOFT,
                background=colour,
                lightcolor=colour,
                darkcolor=colour,
                thickness=6,
                borderwidth=0,
            )

    # ---- widget factories -------------------------------------------------
    def _primary_btn(self, parent, text, command):
        return tk.Button(
            parent, text=text, command=command, cursor="hand2",
            font=("Segoe UI Semibold", 10),
            bg=ACCENT, fg="#FFFFFF",
            activebackground=ACCENT_D, activeforeground="#FFFFFF",
            disabledforeground="#D8D6F2",
            relief="flat", bd=0, padx=16, pady=6,
            highlightthickness=2, highlightbackground=ACCENT, highlightcolor="#BBB6F2",
        )

    def _link_btn(self, parent, text, command, fg=MUTED):
        # A quiet text-only button for the footer: no fill, no border, just an
        # accent hover — everything down there is secondary to Download.
        return tk.Button(
            parent, text=text, command=command, cursor="hand2",
            font=("Segoe UI", 9),
            bg=BG, fg=fg,
            activebackground=BG, activeforeground=ACCENT_D,
            disabledforeground=FAINT,
            relief="flat", bd=0, padx=4, pady=1,
            highlightthickness=0,
        )

    def _entry(self, parent, **kw):
        """A flat text field that grows an indigo focus ring (the highlight)."""
        opts = dict(
            font=("Segoe UI", 10), bg=SURFACE, fg=INK,
            relief="flat", bd=0, insertbackground=ACCENT,
            disabledforeground=FAINT,
            highlightthickness=1, highlightbackground=LINE, highlightcolor=ACCENT,
        )
        opts.update(kw)
        return tk.Entry(parent, **opts)

    # ---- URL row (the one-click action) -----------------------------------
    def _build_url_row(self, parent):
        row = tk.Frame(parent, bg=BG)
        row.pack(fill="x")

        self.url_var = tk.StringVar()
        self.url_entry = self._entry(row, textvariable=self.url_var)
        self.url_entry.pack(side="left", fill="x", expand=True, ipady=7)
        self.url_entry.bind("<Return>", lambda _e: self.start_download())
        self.url_entry.bind("<FocusIn>", self._clear_placeholder)
        self.url_entry.bind("<FocusOut>", self._maybe_placeholder)
        self._set_placeholder()  # show the hint until the box is clicked

        # Format picker: the site's native video file, or audio-only as mp3.
        # Display labels map to the downloader's format ids in start_download.
        self.fmt_var = tk.StringVar(value="Video")
        fmt_menu = tk.OptionMenu(row, self.fmt_var, "Video", "MP3")
        fmt_menu.config(
            font=("Segoe UI", 9), bg=SURFACE, fg=INK, cursor="hand2",
            activebackground=ACCENT_SOFT, activeforeground=INK,
            relief="flat", bd=0, padx=10, pady=6,
            highlightthickness=1, highlightbackground=LINE, highlightcolor=ACCENT,
            indicatoron=False,  # drop the ugly raised indicator; act like a button
        )
        fmt_menu["menu"].config(
            font=("Segoe UI", 9), bg=SURFACE, fg=INK,
            activebackground=ACCENT_SOFT, activeforeground=INK,
            relief="flat", bd=0,
        )
        fmt_menu.pack(side="left", padx=(8, 0))

        # Whole-playlist mode: fetch every entry of a playlist link (into a
        # subfolder named after the playlist) instead of the single video.
        self.playlist_var = tk.BooleanVar(value=False)
        playlist_check = tk.Checkbutton(
            row, text="Playlist", variable=self.playlist_var,
            font=("Segoe UI", 9), bg=BG, fg=MUTED, cursor="hand2",
            activebackground=BG, activeforeground=INK,
            selectcolor=SURFACE, relief="flat", bd=0,
            highlightthickness=0, padx=2,
        )
        playlist_check.pack(side="left", padx=(6, 0))

        self.dl_btn = self._primary_btn(row, "Download", self.start_download)
        self.dl_btn.pack(side="left", padx=(10, 0))

    # ---- status line (the download "heartbeat") ---------------------------
    def _build_status(self, parent):
        srow = tk.Frame(parent, bg=BG)
        srow.pack(fill="x", pady=(12, 0))

        self.state_dot = tk.Label(
            srow, text="●", bg=BG, fg=FAINT, font=("Segoe UI", 10)
        )
        self.state_dot.pack(side="left")
        self.status = tk.StringVar(value="Getting things ready…")
        tk.Label(
            srow, textvariable=self.status, bg=BG, fg=INK,
            font=("Segoe UI Semibold", 10), anchor="w",
        ).pack(side="left", padx=(6, 0))

        # Rightmost: Cancel (only visible while a download runs), then the
        # percentage. Cancelling the running job frees the serial queue so
        # later jobs can proceed.
        self.cancel_btn = self._link_btn(srow, "Cancel", self.cancel_download, fg=ERR)
        self.cancel_btn.pack(side="right")
        self.pct_label = tk.Label(
            srow, text="", bg=BG, fg=MUTED, font=("Segoe UI Semibold", 10)
        )
        self.pct_label.pack(side="right", padx=(0, 6))
        self.cancel_btn.pack_forget()  # hidden until EV_STARTED

        self.progress = ttk.Progressbar(
            parent, mode="determinate", maximum=100,
            style="Accent.Horizontal.TProgressbar",
        )
        self.progress.pack(fill="x", pady=(8, 0))

    def _show_cancel(self, show):
        if show:
            # Re-enable it: cancel_download disables the button while a cancel
            # is in flight, and that state would otherwise stick to the next
            # download (the bug that made Cancel look permanently dead).
            self.cancel_btn.config(state="normal")
            # Re-pack ahead of the percentage so it lands rightmost again.
            self.cancel_btn.pack(side="right", before=self.pct_label)
        else:
            self.cancel_btn.pack_forget()

    # ---- footer (everything secondary, on one line) ------------------------
    def _build_footer(self, parent):
        self.footer = tk.Frame(parent, bg=BG)
        self.footer.pack(fill="x", pady=(10, 0))

        self._link_btn(self.footer, "Open folder", self.open_folder).pack(side="left")
        self.activity_btn = self._link_btn(
            self.footer, "Activity ▸", self.toggle_activity
        )
        self.activity_btn.pack(side="left", padx=(8, 0))

        # Right side: extension pairing, reduced to a status dot + copy button.
        self.copy_btn = self._link_btn(
            self.footer, "Copy token", self._copy_token, fg=ACCENT
        )
        self.copy_btn.pack(side="right")

        self.conn_var = tk.StringVar(value="Helper starting…")
        tk.Label(
            self.footer, textvariable=self.conn_var, bg=BG, fg=MUTED,
            font=("Segoe UI", 9), anchor="e",
        ).pack(side="right", padx=(0, 8))
        self.server_dot = tk.Label(
            self.footer, text="●", bg=BG, fg=AMBER, font=("Segoe UI", 9)
        )
        self.server_dot.pack(side="right", padx=(0, 4))
        # Keep the status dot in sync no matter who sets the text (the launcher
        # sets a failure message directly on conn_var).
        self.conn_var.trace_add("write", self._sync_server_dot)

    # ---- activity log (collapsed by default) -------------------------------
    def _build_activity(self, parent):
        self.log_box = tk.Text(
            parent, height=8, wrap="word", state="disabled",
            bg="#FBFBFE", fg=MUTED, font=("Cascadia Mono", 9),
            relief="flat", bd=0, padx=12, pady=10, insertbackground=INK,
            highlightthickness=1, highlightbackground=LINE, highlightcolor=LINE,
        )
        # Not packed here — toggle_activity slots it in above the footer.
        # Each event type gets its own colour so the log scans at a glance.
        self.log_box.tag_configure("queued", foreground=ACCENT)
        self.log_box.tag_configure("ok", foreground=OK)
        self.log_box.tag_configure("err", foreground=ERR)
        self.log_box.tag_configure("warn", foreground=AMBER)
        self.log_box.tag_configure("ink", foreground=INK)

    def toggle_activity(self):
        if self._activity_shown:
            self.log_box.pack_forget()
            self._activity_shown = False
            self.activity_btn.config(text="Activity ▸")
        else:
            # Slot the log between the progress bar and the footer, and let it
            # soak up any extra height if the user enlarges the window.
            self.log_box.pack(
                fill="both", expand=True, pady=(10, 0), before=self.footer
            )
            self._activity_shown = True
            self.activity_btn.config(text="Activity ▾")
            self.log_box.see("end")
        # Grow/shrink the window to fit, keeping whatever width the user chose.
        self.root.update_idletasks()
        w = max(self.root.winfo_width(), 500)
        self.root.geometry(f"{w}x{self.root.winfo_reqheight()}")

    # ---- placeholder handling for the URL box -----------------------------
    def _set_placeholder(self):
        self._placeholder_on = True
        self.url_entry.config(fg=FAINT)
        self.url_var.set("Paste a video link, then press Enter")

    def _clear_placeholder(self, _event=None):
        if self._placeholder_on:
            self._placeholder_on = False
            self.url_var.set("")
            self.url_entry.config(fg=INK)

    def _maybe_placeholder(self, _event=None):
        if not self.url_var.get():
            self._set_placeholder()

    # ---- system tray ------------------------------------------------------
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

    # ---- thread-safe helpers ----------------------------------------------
    def log(self, msg, tag=None):
        self.root.after(0, lambda: self._append_log(msg, tag))

    def _append_log(self, msg, tag=None):
        self.log_box.config(state="normal")
        self.log_box.insert("end", msg, tag or ())
        self.log_box.see("end")
        self.log_box.config(state="disabled")

    def set_status(self, text):
        self.root.after(0, lambda: self._set_status(text))

    def _set_status(self, text):
        self.status.set(text)
        # Let plain-language status text light the dot when no download event is
        # driving it (e.g. the launcher's "Ready" message, or "copied").
        low = text.lower()
        if any(k in low for k in ("ready", "copied", "saved", "finished")):
            self.state_dot.config(fg=OK)

    def set_server_running(self, port):
        self.root.after(
            0,
            lambda: self.conn_var.set(f"Helper running · 127.0.0.1:{port}"),
        )

    def _sync_server_dot(self, *_):
        text = self.conn_var.get().lower()
        if "running" in text:
            self.server_dot.config(fg=OK)
        elif any(k in text for k in ("fail", "could not", "in use", "error")):
            self.server_dot.config(fg=ERR)
        else:
            self.server_dot.config(fg=AMBER)

    # ---- actions ----------------------------------------------------------
    def start_download(self):
        url = "" if self._placeholder_on else self.url_var.get().strip()
        if not url:
            messagebox.showinfo("Add a link", "Paste a video link into the box first.")
            return
        fmt = (
            downloader.FMT_MP3
            if self.fmt_var.get() == "MP3"
            else downloader.FMT_VIDEO
        )
        if not self.manager.submit(url, fmt, playlist=self.playlist_var.get()):
            messagebox.showinfo(
                "That isn't a link",
                "It should be a web address starting with http:// or https://.",
            )
            return
        self.url_var.set("")

    def cancel_download(self):
        if self._active_job_id is not None:
            if self.manager.cancel(self._active_job_id):
                self.cancel_btn.config(state="disabled")
                self.set_status("Cancelling...")

    def open_folder(self):
        path = self.settings.download_dir
        try:
            os.makedirs(path, exist_ok=True)
            if config.IS_WINDOWS:
                os.startfile(path)  # noqa: B606
            elif sys.platform == "darwin":
                subprocess.run(["open", path])
            else:
                subprocess.run(["xdg-open", path])
        except OSError as e:
            # An invalid configured folder (removed drive, bad path) must not
            # die silently inside the Tk callback — say what went wrong.
            messagebox.showerror(
                "Can't open folder", f"Couldn't open:\n{path}\n\n{e}"
            )

    def _copy_token(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.settings.token)
        self.copy_btn.config(text="Copied ✓")
        self.set_status("Token copied — paste it into the extension's options.")
        # Revert the button label after a moment.
        self.root.after(1400, lambda: self.copy_btn.config(text="Copy token"))

    # ---- download events --------------------------------------------------
    def _on_event(self, event, job, data=None):
        self.root.after(0, lambda: self._apply_event(event, job, data))

    def _set_bar(self, style, value):
        self.progress.config(style=f"{style}.Horizontal.TProgressbar")
        self.progress["value"] = value

    def _apply_event(self, event, job, data):
        if event == downloader.EV_QUEUED:
            # Already on the GUI thread here — append directly rather than
            # re-deferring through self.log (which schedules another after()).
            kind = "mp3" if job.fmt == downloader.FMT_MP3 else "video"
            if job.playlist:
                kind += " playlist"
            self._append_log(f"↓ queued ({kind})  {job.url}\n", "queued")
        elif event == downloader.EV_STARTED:
            self._active_job_id = job.id
            self._show_cancel(True)
            self._set_bar("Accent", 0)
            self.state_dot.config(fg=ACCENT)
            self.pct_label.config(text="0%")
            self._set_status("Downloading…")
        elif event == downloader.EV_PROGRESS:
            # Buffered progress lines keep arriving for a moment after the
            # user clicks Cancel; don't let them stomp "Cancelling...".
            if job.status == "cancelling":
                return
            pct = data or 0
            self.progress["value"] = pct
            self.pct_label.config(text=f"{pct:.0f}%")
            if job.item_count:
                # Playlist: the bar is overall progress; say where we are.
                self._set_status(f"Downloading… {job.item} of {job.item_count}")
            else:
                self._set_status("Downloading…")
        elif event == downloader.EV_LOG:
            self._append_log(data + "\n")
        elif event == downloader.EV_DONE:
            self._clear_active(job)
            self._set_bar("OK", 100)
            self.state_dot.config(fg=OK)
            self.pct_label.config(text="100%")
            self._set_status("Done — saved to your downloads folder.")
            self._append_log("✓ finished\n", "ok")
        elif event == downloader.EV_FAILED:
            self._clear_active(job)
            self._set_bar("Err", 0)
            self.state_dot.config(fg=ERR)
            self.pct_label.config(text="")
            self._set_status("Couldn't finish — see the activity log.")
            self._append_log(f"✗ {job.error}\n", "err")
            # The status points at the log, so make sure the log is visible.
            if not self._activity_shown:
                self.toggle_activity()
        elif event == downloader.EV_CANCELLED:
            self._clear_active(job)
            self._set_bar("Accent", 0)
            self.state_dot.config(fg=AMBER)
            self.pct_label.config(text="")
            self._set_status("Cancelled.")
            self._append_log("■ cancelled\n", "warn")

    def _clear_active(self, job):
        """Drop Cancel-button state once the active job reaches a terminal state."""
        if job.id == self._active_job_id:
            self._active_job_id = None
            self._show_cancel(False)
