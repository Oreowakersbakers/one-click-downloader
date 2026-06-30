"""The small desktop window.

It does two jobs:
  1. A manual fallback — paste a link and hit Download (for sites the browser
     button doesn't cover, or when you just have a URL).
  2. Visibility — a status "heartbeat" (state dot + progress + percentage) and a
     colour-coded activity log so you can see what's happening, plus the
     connection details the browser extension needs.

Look & feel
-----------
The palette is built around the app's own icon colour — indigo ``#4F46E5`` — so
the window reads as one product with the tray/browser marks. To keep the
project's "nothing to install" promise (see tray.py), everything here is pure
stdlib tkinter: the header gradient and the download glyph are *drawn* on a
Canvas rather than loaded from an image, so there's no Pillow dependency.

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
SURFACE = "#FFFFFF"     # raised cards
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

HEADER_TOP = "#5B53F0"  # header gradient — lighter at the top...
HEADER_BOT = "#3F37C9"  # ...deeper at the bottom (a downward "descent")

PAD = 18                # outer content padding


def _mix(a, b, t):
    """Linear-interpolate two ``#rrggbb`` colours; ``t`` in [0, 1]."""
    ar, ag, ab = int(a[1:3], 16), int(a[3:5], 16), int(a[5:7], 16)
    br, bg, bb = int(b[1:3], 16), int(b[3:5], 16), int(b[5:7], 16)
    return "#%02x%02x%02x" % (
        round(ar + (br - ar) * t),
        round(ag + (bg - ag) * t),
        round(ab + (bb - ab) * t),
    )


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

        root.title("One-Click Downloader")
        # Sized to show every panel (incl. the pairing token) without clipping;
        # the activity log takes any extra height when the window is enlarged.
        root.geometry("620x710")
        root.minsize(560, 670)
        root.configure(bg=BG)
        # Replace tkinter's default feather with the app's own icon.
        try:
            root.iconbitmap(ICON_PATH)
        except tk.TclError:
            pass

        self._setup_styles()
        self._build_header(root)

        body = tk.Frame(root, bg=BG)
        body.pack(fill="both", expand=True, padx=PAD, pady=PAD)

        self._build_url_row(body)
        self._build_status_card(body)
        self._build_activity(body)
        self._build_extension_card(body)

        # Listen for download events (called from the worker thread).
        manager.add_listener(self._on_event)

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
                thickness=8,
                borderwidth=0,
            )

    # ---- widget factories -------------------------------------------------
    def _eyebrow(self, parent, text, bg=BG):
        """A small, muted section label."""
        return tk.Label(
            parent, text=text, bg=bg, fg=MUTED, font=("Segoe UI Semibold", 8)
        )

    def _card(self, parent):
        """A white panel with a hairline border."""
        return tk.Frame(
            parent, bg=SURFACE, bd=0,
            highlightthickness=1, highlightbackground=LINE, highlightcolor=LINE,
        )

    def _primary_btn(self, parent, text, command):
        return tk.Button(
            parent, text=text, command=command, cursor="hand2",
            font=("Segoe UI Semibold", 10),
            bg=ACCENT, fg="#FFFFFF",
            activebackground=ACCENT_D, activeforeground="#FFFFFF",
            disabledforeground="#D8D6F2",
            relief="flat", bd=0, padx=18, pady=8,
            highlightthickness=2, highlightbackground=ACCENT, highlightcolor="#BBB6F2",
        )

    def _ghost_btn(self, parent, text, command):
        # A quiet, recognisable button: a faint fill (so it reads as clickable
        # against the white cards) with a hairline border — subordinate to the
        # filled primary Download button.
        return tk.Button(
            parent, text=text, command=command, cursor="hand2",
            font=("Segoe UI", 10),
            bg=BG, fg=INK,
            activebackground=ACCENT_SOFT, activeforeground=ACCENT_D,
            disabledforeground=FAINT,
            relief="flat", bd=0, padx=14, pady=7,
            highlightthickness=1, highlightbackground=LINE, highlightcolor=ACCENT,
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

    # ---- header (gradient + drawn brand mark) -----------------------------
    def _build_header(self, parent):
        self.header = tk.Canvas(parent, height=78, highlightthickness=0, bd=0)
        self.header.pack(fill="x")
        # Redraw on resize so the gradient always spans the full width.
        self.header.bind(
            "<Configure>", lambda e: self._draw_header(e.width, e.height)
        )

    def _draw_header(self, w, h):
        c = self.header
        c.delete("all")
        if w <= 1:
            return
        # Vertical gradient: one 1px line per row.
        for y in range(h):
            c.create_line(0, y, w, y, fill=_mix(HEADER_TOP, HEADER_BOT, y / (h - 1)))

        # The brand mark: a download arrow landing in a tray (matches the icon),
        # drawn in white directly on the gradient.
        cx, cy = 42, h // 2
        c.create_line(cx, cy - 16, cx, cy + 1, fill="#FFFFFF", width=4, capstyle="round")
        c.create_polygon(
            cx - 10, cy - 5, cx + 10, cy - 5, cx, cy + 8, fill="#FFFFFF", outline="#FFFFFF"
        )
        c.create_line(cx - 13, cy + 15, cx + 13, cy + 15, fill="#FFFFFF", width=4, capstyle="round")

        # Lockup: product name + a plain-language tagline.
        tx = cx + 36
        c.create_text(
            tx, cy - 9, text="One-Click Downloader", anchor="w",
            fill="#FFFFFF", font=("Segoe UI Semibold", 15),
        )
        c.create_text(
            tx, cy + 13,
            text="Paste a link, or grab video straight from your browser",
            anchor="w", fill="#D9D7F7", font=("Segoe UI", 9),
        )

    # ---- URL row (the one-click action) -----------------------------------
    def _build_url_row(self, parent):
        self._eyebrow(parent, "VIDEO URL").pack(anchor="w", pady=(0, 6))

        row = tk.Frame(parent, bg=BG)
        row.pack(fill="x")

        self.url_var = tk.StringVar()
        self.url_entry = self._entry(row, textvariable=self.url_var)
        self.url_entry.pack(side="left", fill="x", expand=True, ipady=7)
        self.url_entry.bind("<Return>", lambda _e: self.start_download())
        self.url_entry.bind("<FocusIn>", self._clear_placeholder)
        self.url_entry.bind("<FocusOut>", self._maybe_placeholder)
        self._set_placeholder()  # show the hint until the box is clicked

        self.dl_btn = self._primary_btn(row, "Download", self.start_download)
        self.dl_btn.pack(side="left", padx=(10, 0))

    # ---- status card (the signature: a download "heartbeat") --------------
    def _build_status_card(self, parent):
        card = self._card(parent)
        card.pack(fill="x", pady=(16, 0))
        inner = tk.Frame(card, bg=SURFACE)
        inner.pack(fill="x", padx=14, pady=12)

        top = tk.Frame(inner, bg=SURFACE)
        top.pack(fill="x")
        self.state_dot = tk.Label(
            top, text="●", bg=SURFACE, fg=FAINT, font=("Segoe UI", 11)
        )
        self.state_dot.pack(side="left")
        self.status = tk.StringVar(value="Getting things ready…")
        tk.Label(
            top, textvariable=self.status, bg=SURFACE, fg=INK,
            font=("Segoe UI Semibold", 11), anchor="w",
        ).pack(side="left", padx=(8, 0))
        self.pct_var = tk.StringVar(value="")
        tk.Label(
            top, textvariable=self.pct_var, bg=SURFACE, fg=MUTED,
            font=("Segoe UI Semibold", 11),
        ).pack(side="right")

        self.progress = ttk.Progressbar(
            inner, mode="determinate", maximum=100,
            style="Accent.Horizontal.TProgressbar",
        )
        self.progress.pack(fill="x", pady=(11, 12))

        actions = tk.Frame(inner, bg=SURFACE)
        actions.pack(fill="x")
        # Enabled only while a download is running (see _apply_event). Cancelling
        # the running job frees the serial queue so later jobs can proceed.
        self.cancel_btn = self._ghost_btn(actions, "Cancel", self.cancel_download)
        self.cancel_btn.config(state="disabled")
        self.cancel_btn.pack(side="left")
        self._ghost_btn(actions, "Open folder", self.open_folder).pack(side="right")

    # ---- activity log (calm, colour-coded) --------------------------------
    def _build_activity(self, parent):
        self._eyebrow(parent, "ACTIVITY").pack(anchor="w", pady=(16, 6))
        self.log_box = tk.Text(
            parent, height=7, wrap="word", state="disabled",
            bg="#FBFBFE", fg=MUTED, font=("Cascadia Mono", 9),
            relief="flat", bd=0, padx=12, pady=10, insertbackground=INK,
            highlightthickness=1, highlightbackground=LINE, highlightcolor=LINE,
        )
        self.log_box.pack(fill="both", expand=True)
        # Each event type gets its own colour so the log scans at a glance.
        self.log_box.tag_configure("queued", foreground=ACCENT)
        self.log_box.tag_configure("ok", foreground=OK)
        self.log_box.tag_configure("err", foreground=ERR)
        self.log_box.tag_configure("warn", foreground=AMBER)
        self.log_box.tag_configure("ink", foreground=INK)

    # ---- browser-extension panel ------------------------------------------
    def _build_extension_card(self, parent):
        card = self._card(parent)
        card.pack(fill="x", pady=(16, 0))
        inner = tk.Frame(card, bg=SURFACE)
        inner.pack(fill="x", padx=14, pady=12)

        self._eyebrow(inner, "BROWSER EXTENSION", bg=SURFACE).pack(anchor="w")

        srow = tk.Frame(inner, bg=SURFACE)
        srow.pack(fill="x", pady=(8, 0))
        self.server_dot = tk.Label(
            srow, text="●", bg=SURFACE, fg=AMBER, font=("Segoe UI", 10)
        )
        self.server_dot.pack(side="left")
        self.conn_var = tk.StringVar(value="Helper server: starting…")
        tk.Label(
            srow, textvariable=self.conn_var, bg=SURFACE, fg=MUTED,
            font=("Segoe UI", 9), anchor="w",
        ).pack(side="left", padx=(8, 0))
        # Keep the status dot in sync no matter who sets the text (the launcher
        # sets a failure message directly on conn_var).
        self.conn_var.trace_add("write", self._sync_server_dot)

        tk.Label(
            inner, text="Pairing token", bg=SURFACE, fg=INK,
            font=("Segoe UI Semibold", 9),
        ).pack(anchor="w", pady=(12, 4))

        trow = tk.Frame(inner, bg=SURFACE)
        trow.pack(fill="x")
        self.token_var = tk.StringVar(value=self.settings.token)
        token_entry = self._entry(
            trow, textvariable=self.token_var, state="readonly",
            readonlybackground=BG, font=("Cascadia Mono", 9),
        )
        token_entry.pack(side="left", fill="x", expand=True, ipady=6, padx=(0, 10))
        self.copy_btn = self._ghost_btn(trow, "Copy", self._copy_token)
        self.copy_btn.pack(side="left")

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
            lambda: self.conn_var.set(
                f"Helper server running · http://127.0.0.1:{port}"
            ),
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
        if not self.manager.submit(url):
            messagebox.showinfo(
                "That isn't a link",
                "It should be a web address starting with http:// or https://.",
            )
            return
        self.url_var.set("")

    def cancel_download(self):
        if self._active_job_id is not None:
            self.manager.cancel(self._active_job_id)

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
        self.copy_btn.config(text="Copied!")
        self.set_status("Token copied — paste it into the extension's options.")
        # Revert the button label after a moment.
        self.root.after(1400, lambda: self.copy_btn.config(text="Copy"))

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
            self._append_log(f"↓ queued  {job.url}\n", "queued")
        elif event == downloader.EV_STARTED:
            self._active_job_id = job.id
            self.cancel_btn.config(state="normal")
            self._set_bar("Accent", 0)
            self.state_dot.config(fg=ACCENT)
            self.pct_var.set("0%")
            self._set_status("Downloading…")
        elif event == downloader.EV_PROGRESS:
            pct = data or 0
            self.progress["value"] = pct
            self.pct_var.set(f"{pct:.0f}%")
            self._set_status("Downloading…")
        elif event == downloader.EV_LOG:
            self._append_log(data + "\n")
        elif event == downloader.EV_DONE:
            self._clear_active(job)
            self._set_bar("OK", 100)
            self.state_dot.config(fg=OK)
            self.pct_var.set("100%")
            self._set_status("Done — saved to your downloads folder.")
            self._append_log("✓ finished\n", "ok")
        elif event == downloader.EV_FAILED:
            self._clear_active(job)
            self._set_bar("Err", 0)
            self.state_dot.config(fg=ERR)
            self.pct_var.set("")
            self._set_status("Couldn't finish — see the activity log.")
            self._append_log(f"✗ {job.error}\n", "err")
        elif event == downloader.EV_CANCELLED:
            self._clear_active(job)
            self._set_bar("Accent", 0)
            self.state_dot.config(fg=AMBER)
            self.pct_var.set("")
            self._set_status("Cancelled.")
            self._append_log("■ cancelled\n", "warn")

    def _clear_active(self, job):
        """Drop Cancel-button state once the active job reaches a terminal state."""
        if job.id == self._active_job_id:
            self._active_job_id = None
            self.cancel_btn.config(state="disabled")
