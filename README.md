# One-Click Downloader

Download videos from almost any site (YouTube, TikTok, X/Twitter, etc.) with one
click. It wraps [yt-dlp](https://github.com/yt-dlp/yt-dlp), the open-source engine
that does the real work.

## How it's built

Two cooperating parts:

```
┌──────────────────────────┐   sends URL    ┌───────────────────────────┐
│  Browser extension       │ ─────────────► │  Local helper (this app)  │
│  download button on the  │                │  Python + yt-dlp          │
│  video + popup w/ cancel │ ◄───────────── │  runs the download        │
└──────────────────────────┘  status/done   └───────────────────────────┘
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

The easiest way is a packaged build from the project's GitHub Releases page:

1. Download `OneClickDownloader-<version>-Setup.exe` and run it.
2. The installer places the unpacked extension in its `browser-extension`
   folder. Portable users should download and extract
   `OneClickDownloader-Extension-<version>.zip` themselves.
3. Extract the extension ZIP, then follow **Install the browser extension**
   below and select the extracted folder when Chrome asks for a folder.

The portable `OneClickDownloader-<version>-Portable.exe` is available for
people who do not want an installer. Python is not needed for either build.

To build the standalone exe locally instead:

1. Double-click **`build-exe.bat`** (this one-time step needs Python installed).
2. When it finishes, grab **`dist\One-Click Downloader.exe`** and move it
   anywhere — Desktop, a tools folder, wherever. Double-click it to run.

The exe is fully self-contained (Python and the app are packed inside); yt-dlp
still downloads itself automatically on first run, same as running from source.

Running from source works too:

- Double-click **`Start One-Click Downloader.vbs`** — this opens just the app
  window, with no black console window behind it.
- Or from a terminal: `python oneclick.py`.

Pick **Video** (mp4/webm, the site's native file) or **MP3** from the dropdown
next to the Download button before starting a download. While a download runs,
a **Cancel** link appears next to the percentage — it stops yt-dlp and cleans
up the half-finished file.

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

1. Start the helper app (the exe, the `.vbs`, or `python oneclick.py`) and
   leave it running (the tray icon is enough).
2. In Chrome/Edge/Brave, go to `chrome://extensions`.
3. Turn on **Developer mode** (top-right).
4. Click **Load unpacked** and select the installed `browser-extension` folder.
   Portable users should select their extracted extension ZIP folder; when
   running from source, select `extension/` instead.
5. Open the extension's **options** (right-click its icon → Options, or click the
   icon → "Pairing / settings"), paste the **pairing token** from the app
   window, and click **Test connection** — it should say connected.

Now hover any video on YouTube/TikTok/X and hover the download button — it
expands into **MP4 | MP3**. Click MP4 for the video file or MP3 for audio only
(MP3 needs ffmpeg — see the caveat above). The file lands in
`Downloads/OneClickDL/`.

Click the extension's **toolbar icon** for the popup: it has a paste-a-link
box, and while anything is downloading it shows a live **Downloading** list
with a progress bar and a **Cancel** button per download — so you can stop a
download without switching to the app window.

### How URLs are picked

On a video's own page (a YouTube watch page, a tweet, a TikTok) the page URL is
used. In a feed, the extension finds that specific video's permalink from its
card. Sites it doesn't have a special rule for fall back to the page URL.

## Status

- [x] Restructured into a maintainable package
- [x] Local helper server + manual desktop fallback
- [x] Browser extension with the on-video download button
- [x] Minimize/close to the Windows system tray
- [x] Standalone Windows exe (`build-exe.bat`)
- [x] Versioned GitHub release assets and Windows installer
- [x] Cancel a download from the app window or the extension popup
- [ ] Polish: auto-start on login, per-download history, more site rules
