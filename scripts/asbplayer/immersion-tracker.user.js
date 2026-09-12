// ==UserScript==
// @name         Immersion Tracker — asbplayer
// @namespace    immersion-tracker
// @version      1.1.0
// @description  POST finished HTML5 video watches to Immersion Tracker (asbplayer / local media)
// @match        *://*/*
// @grant        GM_xmlhttpRequest
// @connect      127.0.0.1
// @connect      localhost
// @run-at       document-idle
// ==/UserScript==

(function () {
  "use strict";

  // --- configure (do NOT commit real secrets) ---
  // Copy WEBHOOK_SECRET from your local .env into SECRET after installing the script.
  const SERVER = "http://127.0.0.1:8000";
  const SECRET = ""; // set locally in Tampermonkey; leave empty in git
  const COMPLETION = 0.9;
  const MIN_WATCHED_S = 60;
  // -----------------------------------------------

  const posted = new Set();

  function mediaKey(video) {
    const src = video.currentSrc || video.src || "";
    if (src) return src;
    return location.href + "#" + (video.id || "video");
  }

  function basename(src) {
    try {
      const u = src.split("?")[0];
      const parts = u.split(/[/\\]/);
      return parts[parts.length - 1] || src;
    } catch {
      return src;
    }
  }

  function payload(video) {
    const src = video.currentSrc || video.src || location.href;
    const duration = Number(video.duration) || 0;
    const watched = Number(video.currentTime) || 0;
    const ratio = duration > 0 ? Math.min(1, watched / duration) : 0;
    return {
      media_id: basename(src),
      path: src,
      title: document.title || basename(src),
      duration_seconds: duration,
      watched_seconds: watched,
      ratio: ratio,
      url: location.href,
      finished_at: new Date().toISOString(),
    };
  }

  function maybeReport(video, force) {
    const duration = Number(video.duration) || 0;
    const watched = Number(video.currentTime) || 0;
    if (duration <= 0) return;
    const ratio = Math.min(1, watched / duration);
    if (!force && ratio < COMPLETION) return;
    if (watched < MIN_WATCHED_S && duration * ratio < MIN_WATCHED_S) return;

    const key = mediaKey(video);
    if (posted.has(key)) return;
    posted.add(key);

    const body = JSON.stringify(payload(video));
    // Secret goes in header only — never in the URL (avoids browser history / proxy logs)
    const url = SERVER.replace(/\/$/, "") + "/api/webhooks/asbplayer";
    const headers = { "Content-Type": "application/json" };
    if (SECRET) {
      headers["X-Webhook-Secret"] = SECRET;
    }

    const onDone = (status, text) => {
      console.log("[immersion-tracker/asbplayer]", status, text);
    };

    if (typeof GM_xmlhttpRequest === "function") {
      GM_xmlhttpRequest({
        method: "POST",
        url: url,
        headers: headers,
        data: body,
        onload: (r) => onDone(r.status, r.responseText),
        onerror: (e) => console.warn("[immersion-tracker/asbplayer] error", e),
      });
    } else {
      fetch(url, {
        method: "POST",
        headers: headers,
        body: body,
      })
        .then(async (r) => onDone(r.status, await r.text()))
        .catch((e) => console.warn("[immersion-tracker/asbplayer] error", e));
    }
  }

  function bind(video) {
    if (video.dataset.itBound) return;
    video.dataset.itBound = "1";
    video.addEventListener("ended", () => maybeReport(video, true));
    video.addEventListener("timeupdate", () => {
      const d = Number(video.duration) || 0;
      const t = Number(video.currentTime) || 0;
      if (d > 0 && t / d >= COMPLETION) maybeReport(video, false);
    });
  }

  function scan() {
    document.querySelectorAll("video").forEach(bind);
  }

  scan();
  const mo = new MutationObserver(scan);
  mo.observe(document.documentElement, { childList: true, subtree: true });
  console.log("[immersion-tracker/asbplayer] watching for <video> elements");
})();
