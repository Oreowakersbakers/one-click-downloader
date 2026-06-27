const dot = document.getElementById("dot");
const statusText = document.getElementById("statusText");
const urlEl = document.getElementById("url");
const msg = document.getElementById("msg");

// Check the helper app on open.
chrome.runtime.sendMessage({ type: "ping" }).then((res) => {
  if (res && res.ok) {
    dot.className = "dot ok";
    statusText.textContent = "Helper app connected.";
  } else {
    dot.className = "dot err";
    statusText.textContent = "Helper app not running.";
  }
});

document.getElementById("go").addEventListener("click", async () => {
  const url = urlEl.value.trim();
  if (!url) {
    msg.textContent = "Paste a link first.";
    return;
  }
  msg.textContent = "Sending…";
  const res = await chrome.runtime.sendMessage({ type: "download", url });
  if (res && res.ok) {
    msg.textContent = "Sent to downloader ✓";
    urlEl.value = "";
  } else {
    msg.textContent = (res && res.error) || "Something went wrong.";
  }
});

document.getElementById("openOptions").addEventListener("click", () => {
  chrome.runtime.openOptionsPage();
});
