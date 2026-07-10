# One-Click Downloader

Download videos from almost any site (YouTube, TikTok, X/Twitter, etc.) with one
click. It wraps [yt-dlp](https://github.com/yt-dlp/yt-dlp), the open-source engine
that does the real work.

## How it's built

Two cooperating parts (the browser extension lands in the next phase):

```
┌──────────────────────────┐   sends URL    ┌───────────────────────────┐
│  Browser extension       │ ─────────────► │  Local helper (this app)  │
│  download button on the  │                │  Python + yt-dlp          │
│  video — coming next      │ ◄───────────── │  runs the download        │
└──────────────────────────┘    "done"      └───────────────────────────┘
```

A desktop program can't draw a button inside a web page, and a browser
extension can't run yt-dlp. So the extension only captures the video URL and
hands it to this local helper over `http://127.0.0.1`.

### Project layout

| File | Responsibility |
|------|----------------|
| `oneclick.py` | Launcher — wires everything together |
| `oneclickdl/config.py` | Paths, saved settings, the pairing token |
| `oneclickdl/ytdlp.py` | Finds / auto-downloads the yt-dlp binary |
| `oneclickdl/downloader.py` | The download queue + worker (UI-agnostic) |
| `oneclickdl/server.py` | Localhost API the extension talks to |
| `oneclickdl/gui.py` | The small desktop window |
| `oneclickdl/tray.py` | Windows system-tray icon (pure ctypes, no deps) |
| `extension/` | The browser extension (the on-video download button) |

Each module has one job, so adding features (a settings screen, a download
history, more sites) touches one file instead of all of them.

## Requirements

- Python 3.8+ (on Windows tick **Add to PATH** when installing).
- That's it — yt-dlp downloads itself on first run (Windows). On Mac/Linux:
  `brew install yt-dlp` or `pip install yt-dlp`.
- Optional, for best YouTube quality: install `ffmpeg` (`winget install ffmpeg`).

## Run it

Double-click **`Start One-Click Downloader.vbs`** — this opens just the app
window, with no black console window behind it. (Closing the app window quits
everything, including the helper server.)

Alternatively, from a terminal: `python oneclick.py`.

Pick **Video** (mp4/webm, the site's native file) or **MP3** from the dropdown
next to the Download button before starting a download.

> **Caveat:** MP3 downloads require `ffmpeg` to be installed and on PATH (see
> Requirements above) — yt-dlp uses it to convert the audio. Without it, MP3
> downloads will fail; Video downloads don't need it (though ffmpeg is still
> recommended for best YouTube quality).

Files land in `Downloads/OneClickDL/`. On Windows the app lives in the **system
tray** (the icons by the clock): minimizing or closing the window tucks it down
there instead of quitting. Double-click the tray icon to reopen the window, or
right-click it → **Quit** to fully exit. It keeps running quietly so the
extension can always reach it.

## The pairing token

On first run the app generates a random token and shows it in the window under
**Browser extension**. When the extension exists, you'll paste this token into
its options once. It stops random web pages from triggering downloads on your
machine. The helper only listens on `127.0.0.1`, so nothing on your network can
reach it either.

## Install the browser extension

The extension adds a download button to the top-right of any video you hover.

1. Start the helper app (`python oneclick.py`) and leave its window open.
2. In Chrome/Edge/Brave, go to `chrome://extensions`.
3. Turn on **Developer mode** (top-right).
4. Click **Load unpacked** and select the `extension/` folder.
5. Open the extension's **options** (right-click its icon → Options, or click the
   icon → "Pairing / settings"), paste the **pairing token** from the app
   window, and click **Test connection** — it should say connected.

Now hover any video on YouTube/TikTok/X and click the download button. The file
lands in `Downloads/OneClickDL/`. The toolbar icon also has a paste-a-link box.

### How URLs are picked

On a video's own page (a YouTube watch page, a tweet, a TikTok) the page URL is
used. In a feed, the extension finds that specific video's permalink from its
card. Sites it doesn't have a special rule for fall back to the page URL.

## Status

- [x] Restructured into a maintainable package
- [x] Local helper server + manual desktop fallback
- [x] Browser extension with the on-video download button
- [x] Minimize/close to the Windows system tray
- [ ] Polish: auto-start on login, per-download history, more site rules
