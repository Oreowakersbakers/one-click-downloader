const tokenEl = document.getElementById("token");
const portEl = document.getElementById("port");
const statusEl = document.getElementById("status");

function setStatus(msg, cls) {
  statusEl.textContent = msg;
  statusEl.className = cls || "";
}

// Load saved values.
chrome.storage.sync.get(["token", "port"]).then(({ token = "", port = 53117 }) => {
  tokenEl.value = token;
  portEl.value = port;
});

document.getElementById("save").addEventListener("click", async () => {
  const token = tokenEl.value.trim();
  const port = parseInt(portEl.value, 10) || 53117;
  await chrome.storage.sync.set({ token, port });
  setStatus("Saved.", "ok");
});

document.getElementById("test").addEventListener("click", async () => {
  // Save first so the test uses the current values.
  const token = tokenEl.value.trim();
  const port = parseInt(portEl.value, 10) || 53117;
  await chrome.storage.sync.set({ token, port });

  setStatus("Testing…");
  try {
    // /status is authenticated, unlike /ping, so this verifies both that the
    // helper is reachable and that the pasted pairing token is correct.
    const res = await chrome.runtime.sendMessage({ type: "status" });
    if (res && res.ok) {
      setStatus("Connected and paired. ✓", "ok");
    } else {
      setStatus(
        (res && res.error) || "No response. Check that the helper is open and the token is correct.",
        "err",
      );
    }
  } catch (err) {
    setStatus("No response. Is the One-Click Downloader app open?", "err");
  }
});
