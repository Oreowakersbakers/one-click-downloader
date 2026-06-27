// Background service worker.
//
// This is the ONLY part of the extension that talks to the local helper app.
// We do it from here (not the content script) on purpose: an extension
// background worker with host_permissions can call http://127.0.0.1 without
// tripping over CORS or Chrome's Private Network Access blocking that would
// stop an in-page script from reaching localhost.

const DEFAULT_PORT = 53117;
const FETCH_TIMEOUT_MS = 5000; // a helper that accepts but never replies must not hang us

async function getConfig() {
  const { port = DEFAULT_PORT, token = "" } = await chrome.storage.sync.get([
    "port",
    "token",
  ]);
  return { port, token };
}

async function pingHelper() {
  const { port } = await getConfig();
  try {
    const res = await fetch(`http://127.0.0.1:${port}/ping`, {
      cache: "no-store",
      signal: AbortSignal.timeout(FETCH_TIMEOUT_MS),
    });
    const data = await res.json().catch(() => ({}));
    return { ok: res.ok && data.app === "oneclick-dl" };
  } catch (e) {
    return { ok: false, error: "not running" };
  }
}

async function sendDownload(url) {
  if (!url) return { ok: false, error: "No video URL found on this page." };

  const { port, token } = await getConfig();
  if (!token) {
    return { ok: false, error: "Not paired yet — set the token in extension options." };
  }

  try {
    const res = await fetch(`http://127.0.0.1:${port}/download`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-OneClick-Token": token,
      },
      body: JSON.stringify({ url }),
      signal: AbortSignal.timeout(FETCH_TIMEOUT_MS),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      if (res.status === 403) {
        return { ok: false, error: "Wrong token — re-copy it from the app into options." };
      }
      return { ok: false, error: data.error || `Helper error (HTTP ${res.status}).` };
    }
    return { ok: true, id: data.id };
  } catch (e) {
    return {
      ok: false,
      error: "Helper app isn't running. Open One-Click Downloader first.",
    };
  }
}

// Route messages from the content script and the popup.
chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (!msg || !msg.type) return;
  if (msg.type === "download") {
    sendDownload(msg.url).then(sendResponse);
    return true; // keep the channel open for the async reply
  }
  if (msg.type === "ping") {
    pingHelper().then(sendResponse);
    return true;
  }
});
