const tokenEl = document.getElementById("token");
const portEl = document.getElementById("port");
const statusEl = document.getElementById("status");

const DEFAULT_PORT = 53117;

function setStatus(msg, cls) {
  statusEl.textContent = msg;
  statusEl.className = cls || "";
}

// Settings live in storage.local (the token is per-machine, so syncing it
// across Chrome profiles would break pairing everywhere else). Fall back to
// storage.sync for values saved by older versions.
async function loadConfig() {
  let { token, port } = await chrome.storage.local.get(["token", "port"]);
  if (token === undefined && port === undefined) {
    ({ token, port } = await chrome.storage.sync.get(["token", "port"]));
  }
  return { token: token || "", port: port || DEFAULT_PORT };
}

// Returns a valid port number, or null (with the error shown) on bad input.
// An empty box just means "use the default".
function readPort() {
  const raw = String(portEl.value).trim();
  if (!raw) return DEFAULT_PORT;
  const port = /^\d{1,5}$/.test(raw) ? parseInt(raw, 10) : NaN;
  if (!(port >= 1 && port <= 65535)) {
    setStatus("Port must be a number between 1 and 65535.", "err");
    return null;
  }
  return port;
}

async function saveConfig() {
  const port = readPort();
  if (port === null) return null;
  const token = tokenEl.value.trim();
  await chrome.storage.local.set({ token, port });
  return { token, port };
}

// Load saved values.
loadConfig().then(({ token, port }) => {
  tokenEl.value = token;
  portEl.value = port;
});

document.getElementById("save").addEventListener("click", async () => {
  if (await saveConfig()) setStatus("Saved.", "ok");
});

document.getElementById("test").addEventListener("click", async () => {
  // Save first so the test uses the current values.
  if (!(await saveConfig())) return;

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
