const dot = document.getElementById("dot");
const statusText = document.getElementById("statusText");
const urlEl = document.getElementById("url");
const msg = document.getElementById("msg");

// Check the helper app on open.
chrome.runtime
  .sendMessage({ type: "ping" })
  .then((res) => {
    if (res && res.ok) {
      dot.className = "dot ok";
      statusText.textContent = "Helper app connected.";
    } else {
      dot.className = "dot err";
      statusText.textContent = "Helper app not running.";
    }
  })
  .catch(() => {
    dot.className = "dot err";
    statusText.textContent = "Helper app not running.";
  });

document.getElementById("go").addEventListener("click", async () => {
  const url = urlEl.value.trim();
  if (!url) {
    msg.textContent = "Paste a link first.";
    return;
  }
  msg.textContent = "Sending…";
  try {
    const res = await chrome.runtime.sendMessage({ type: "download", url });
    if (res && res.ok) {
      msg.textContent = "Sent to downloader ✓";
      urlEl.value = "";
    } else {
      msg.textContent = (res && res.error) || "Something went wrong.";
    }
  } catch (err) {
    msg.textContent = "Extension error — try reopening the popup.";
  }
});

document.getElementById("openOptions").addEventListener("click", () => {
  chrome.runtime.openOptionsPage();
});

// ---- active downloads (with cancel) ----
// Poll the helper while the popup is open. Closing the popup kills the
// interval with it, so there's nothing to clean up.
const downloadsBox = document.getElementById("downloads");
const jobsBox = document.getElementById("jobs");
const cancelling = new Set(); // ids we've asked to cancel, until they disappear

function jobLabel(job) {
  if (job.title) return job.title;
  try {
    return new URL(job.url).hostname + " — " + job.url;
  } catch {
    return job.url;
  }
}

function renderJobs(jobs) {
  downloadsBox.style.display = jobs.length ? "block" : "none";
  jobsBox.textContent = "";
  for (const job of jobs) {
    const row = document.createElement("div");
    row.className = "job";

    const top = document.createElement("div");
    top.className = "job-top";

    const name = document.createElement("span");
    name.className = "job-name";
    name.textContent = jobLabel(job);
    name.title = job.url;

    const cancel = document.createElement("button");
    cancel.className = "job-cancel";
    if (cancelling.has(job.id) || job.status === "cancelling") {
      cancel.textContent = "Cancelling…";
      cancel.disabled = true;
    } else {
      cancel.textContent = "Cancel";
      cancel.addEventListener("click", async () => {
        cancelling.add(job.id);
        cancel.textContent = "Cancelling…";
        cancel.disabled = true;
        try {
          const res = await chrome.runtime.sendMessage({ type: "cancel", id: job.id });
          if (
            !res ||
            !res.ok ||
            !Array.isArray(res.cancelled) ||
            !res.cancelled.includes(job.id)
          ) {
            // The job may still be running after a transient failure. Let the
            // next poll render an enabled button so the user can retry.
            cancelling.delete(job.id);
          }
        } catch {
          cancelling.delete(job.id);
        } finally {
          refreshJobs();
        }
      });
    }

    top.append(name, cancel);
    row.append(top);

    if (job.status === "running" || job.status === "cancelling") {
      const bar = document.createElement("div");
      bar.className = "bar";
      const fill = document.createElement("i");
      fill.style.width = `${Math.max(0, Math.min(100, job.percent || 0))}%`;
      bar.append(fill);
      row.append(bar);
    }
    jobsBox.append(row);
  }
}

async function refreshJobs() {
  try {
    const res = await chrome.runtime.sendMessage({ type: "status" });
    if (res && res.ok && Array.isArray(res.jobs)) {
      const live = new Set(res.jobs.map((j) => j.id));
      for (const id of cancelling) if (!live.has(id)) cancelling.delete(id);
      renderJobs(res.jobs);
    } else {
      renderJobs([]);
    }
  } catch {
    renderJobs([]);
  }
}

refreshJobs();
setInterval(refreshJobs, 1000);
