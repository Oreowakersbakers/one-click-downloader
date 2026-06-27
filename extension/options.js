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
  const res = await chrome.runtime.sendMessage({ type: "ping" });
  if (res && res.ok) {
    setStatus("Connected — the helper app is running. ✓", "ok");
  } else {
    setStatus("No response. Is the One-Click Downloader app open?", "err");
  }
});
