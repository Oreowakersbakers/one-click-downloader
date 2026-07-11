// Content script: draws a download button on the video you're hovering, and
// works out the best URL to hand to the helper app.
//
// One shared button follows the pointer between videos rather than stamping a
// button onto every <video> on the page (feeds can have dozens). It appears at
// the hovered video's top-right corner.

(() => {
  const MIN_SIZE = 150; // ignore tiny/background videos
  let currentVideo = null;

  // ---- the button ----
  const btn = document.createElement("div");
  btn.className = "ocdl-btn";
  btn.setAttribute("role", "group");
  btn.setAttribute("aria-label", "Download this video");
  btn.tabIndex = 0;
  btn.title = "Download this video";
  btn.innerHTML = `
    <svg class="ocdl-icon" viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
      <path fill="currentColor" d="M12 3a1 1 0 0 1 1 1v8.59l2.3-2.3a1 1 0 0 1 1.4 1.42l-4 4a1 1 0 0 1-1.4 0l-4-4a1 1 0 0 1 1.4-1.42l2.3 2.3V4a1 1 0 0 1 1-1Z"/>
      <path fill="currentColor" d="M5 18a1 1 0 0 1 1-1h12a1 1 0 1 1 0 2H6a1 1 0 0 1-1-1Z"/>
    </svg>
    <svg class="ocdl-spin" viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
      <path fill="currentColor" d="M12 2a10 10 0 1 0 10 10h-2a8 8 0 1 1-8-8V2Z"/>
    </svg>
    <span class="ocdl-choices">
      <button class="ocdl-choice" data-fmt="video" title="Download video (mp4/webm)">MP4</button>
      <button class="ocdl-choice" data-fmt="mp3" title="Download audio only (mp3)">MP3</button>
    </span>`;
  // Don't let the host page's hover/click handlers interfere.
  btn.addEventListener("mousedown", (e) => e.stopPropagation(), true);
  btn.addEventListener("click", onClick, true);
  btn.addEventListener("focusout", (e) => {
    if (!btn.contains(e.relatedTarget)) hide();
  });

  function ensureAttached() {
    if (!btn.isConnected) document.body.appendChild(btn);
  }

  // ---- positioning ----
  function bigEnough(v) {
    const r = v.getBoundingClientRect();
    return r.width >= MIN_SIZE && r.height >= MIN_SIZE;
  }

  function position(video) {
    // The page may have swapped the video out from under us (SPA navigation,
    // virtualized feeds). A detached element reports an all-zero rect, which
    // would strand the button floating near the viewport corner.
    if (!video.isConnected) {
      hide();
      return;
    }
    const r = video.getBoundingClientRect();
    // Hide if the video has scrolled out of view.
    if (r.bottom < 0 || r.top > innerHeight || r.right < 0 || r.left > innerWidth) {
      hide();
      return;
    }
    btn.style.top = `${Math.max(r.top + 10, 6)}px`;
    // Anchor the button's RIGHT edge near the video's top-right corner, so the
    // hover expansion (the MP4/MP3 pill) grows leftwards over the video rather
    // than spilling past its edge. Clamp so even the expanded pill (~96px,
    // content.css) stays inside the viewport.
    const right = Math.min(Math.max(innerWidth - r.right + 10, 6), innerWidth - 102);
    btn.style.right = `${right}px`;
  }

  function show(video) {
    ensureAttached();
    currentVideo = video;
    position(video);
    btn.classList.add("ocdl-visible");
  }

  function hide() {
    btn.classList.remove("ocdl-visible");
    currentVideo = null;
  }

  // Find a real video under the pointer (button sits above it, so scan the stack).
  function videoUnder(x, y) {
    const stack = document.elementsFromPoint(x, y);
    if (stack.includes(btn)) return currentVideo; // keep current while hovering button
    return stack.find((el) => el.tagName === "VIDEO" && bigEnough(el)) || null;
  }

  function onPointer(e) {
    const v = videoUnder(e.clientX, e.clientY);
    if (v) show(v);
    else hide();
  }
  document.addEventListener("mouseover", onPointer, true);

  // Keyboard users can reveal the same controls by focusing a video. The
  // focusable group then expands via :focus-within so its real buttons enter
  // the tab order and remain exposed to assistive technology.
  document.addEventListener("focusin", (e) => {
    const target = e.target;
    const video = target && target.tagName === "VIDEO" ? target : null;
    if (video && bigEnough(video)) show(video);
  }, true);

  // Keep the button glued to the video as the page scrolls.
  let raf = 0;
  function reposition() {
    raf = 0;
    if (currentVideo && btn.classList.contains("ocdl-visible")) position(currentVideo);
  }
  function scheduleReposition() {
    if (!raf) raf = requestAnimationFrame(reposition);
  }
  addEventListener("scroll", scheduleReposition, true);
  addEventListener("resize", scheduleReposition, true);

  // ---- URL resolution ----
  // Per-site rules: from the hovered video, find its permalink in the
  // surrounding card. Falls back to the page URL (right for watch pages).
  const SITE_RULES = [
    {
      test: (h) => h.includes("youtube.com") || h.includes("youtu.be"),
      container:
        "ytd-rich-item-renderer, ytd-video-renderer, ytd-compact-video-renderer, ytd-grid-video-renderer, ytd-reel-item-renderer, ytd-playlist-video-renderer",
      link: 'a#thumbnail[href], a[href*="/watch?v="], a[href*="/shorts/"]',
    },
    {
      test: (h) => h.includes("tiktok.com"),
      container:
        '[data-e2e="recommend-list-item-container"], [class*="DivItemContainer"], article',
      link: 'a[href*="/video/"], a[href*="/photo/"]',
    },
    {
      test: (h) => h.includes("twitter.com") || h.includes("x.com"),
      container: "article",
      link: 'a[href*="/status/"]',
    },
  ];

  function resolveUrl(video) {
    const host = location.hostname;
    const rule = SITE_RULES.find((r) => r.test(host));
    if (rule && video) {
      const card = video.closest(rule.container);
      if (card) {
        const links = [...card.querySelectorAll(rule.link)];
        // Prefer a permalink that wraps a <time> (the X/Twitter timestamp).
        const dated = links.find((a) => a.querySelector("time"));
        const link = dated || links[0];
        if (link && link.href) return link.href;
      }
    }
    return location.href;
  }

  // ---- click handling ----
  let busy = false;
  function flash(state) {
    btn.classList.remove("ocdl-loading", "ocdl-done", "ocdl-error");
    if (state) btn.classList.add(state);
  }

  async function onClick(e) {
    // The page and the content script share the DOM. Reject synthetic clicks
    // from page JavaScript so only a real user action can use the extension's
    // private pairing token to enqueue a download.
    if (!e.isTrusted) return;
    e.preventDefault();
    e.stopPropagation();
    if (busy) return;
    // Only the MP4/MP3 segments start a download; the pill itself is inert.
    // (They're what's under the cursor whenever the button is expanded.)
    const choice = e.target.closest(".ocdl-choice");
    if (!choice) return;
    const format = choice.dataset.fmt;
    const url = resolveUrl(currentVideo);
    busy = true;
    flash("ocdl-loading");
    try {
      const res = await chrome.runtime.sendMessage({ type: "download", url, format });
      if (res && res.ok) {
        flash("ocdl-done");
        btn.title = "Sent to downloader ✓";
      } else {
        flash("ocdl-error");
        btn.title = (res && res.error) || "Couldn't reach the helper app.";
      }
    } catch (err) {
      flash("ocdl-error");
      btn.title = "Extension error — try reloading the page.";
    } finally {
      setTimeout(() => {
        flash(null);
        btn.title = "Download this video";
        busy = false;
      }, 2200);
    }
  }
})();
