/**
 * Runs in the page MAIN world so we can read ytcfg (signed-in *viewer* channel)
 * and player response metadata (language, live).
 * Must never report the video uploader as the viewer.
 */
(function () {
  const SOURCE = "immersion-tracker-page-bridge";

  function cfgGet(cfg, k) {
    try {
      if (typeof cfg.get === "function") {
        const v = cfg.get(k);
        if (v != null && v !== "") return v;
      }
    } catch (_) {}
    try {
      if (cfg.data_ && cfg.data_[k] != null && cfg.data_[k] !== "") return cfg.data_[k];
    } catch (_) {}
    return undefined;
  }

  function readIdentity() {
    const out = {
      viewerChannelId: "",
      viewerHandle: "",
      loggedIn: false,
      source: "",
    };

    try {
      const cfg = window.ytcfg;
      if (cfg) {
        const logged = cfgGet(cfg, "LOGGED_IN");
        out.loggedIn = logged === true || logged === 1 || logged === "true" || logged === "1";

        // CHANNEL_ID in ytcfg is the signed-in account's channel (not the video owner).
        const cid = cfgGet(cfg, "CHANNEL_ID") || cfgGet(cfg, "CHANNEL_ID_ENCODED") || "";
        if (typeof cid === "string" && /^UC[\w-]{22}$/.test(cid)) {
          out.viewerChannelId = cid;
          out.source = "ytcfg";
        }
      }
    } catch (_) {}

    // Optional: handle from open account switcher / masthead only (never watch metadata).
    try {
      if (!out.viewerHandle) {
        const avatarRoot =
          document.querySelector("ytd-topbar-menu-button-renderer#button") ||
          document.querySelector("#avatar-btn") ||
          document.querySelector("button#avatar-btn");
        if (avatarRoot) {
          const a = avatarRoot.querySelector('a[href^="/@"], a[href*="/@"]');
          if (a) {
            const href = a.getAttribute("href") || "";
            const m = href.match(/\/@([^/?#]+)/);
            if (m) {
              let h = m[1];
              try {
                if (/%[0-9A-Fa-f]{2}/.test(h)) h = decodeURIComponent(h);
              } catch (_) {}
              out.viewerHandle = "@" + h;
              out.source = out.source || "avatar-dom";
            }
          }
        }
      }
    } catch (_) {}

    return out;
  }

  function getPlayerResponse() {
    try {
      if (window.ytInitialPlayerResponse && typeof window.ytInitialPlayerResponse === "object") {
        return window.ytInitialPlayerResponse;
      }
    } catch (_) {}
    try {
      const raw = window.ytplayer && window.ytplayer.config && window.ytplayer.config.args;
      if (raw && raw.player_response) {
        const pr = typeof raw.player_response === "string"
          ? JSON.parse(raw.player_response)
          : raw.player_response;
        if (pr) return pr;
      }
      if (raw && raw.raw_player_response) return raw.raw_player_response;
    } catch (_) {}
    try {
      // Some SPA navigations stash the last response on the player element
      const p = document.querySelector("#movie_player");
      if (p && typeof p.getPlayerResponse === "function") {
        const pr = p.getPlayerResponse();
        if (pr) return pr;
      }
    } catch (_) {}
    return null;
  }

  function normalizeLang(code) {
    if (!code) return "";
    let c = String(code).trim().toLowerCase().replace(/_/g, "-");
    // "ja-JP" → "ja", "en-US" → "en", "jp" → "ja"
    if (c === "jp") c = "ja";
    const base = c.split("-")[0];
    return base || "";
  }

  function readVideoMeta() {
    const out = {
      language: "",
      languages: [],
      isLive: false,
      isLiveContent: false,
      category: "",
      videoId: "",
      source: "",
    };

    const pr = getPlayerResponse();
    if (!pr) return out;
    out.source = "playerResponse";

    try {
      const vd = pr.videoDetails || {};
      if (vd.videoId) out.videoId = String(vd.videoId);
      if (vd.isLive === true || vd.isLive === "true") out.isLive = true;
      if (vd.isLiveContent === true || vd.isLiveContent === "true") out.isLiveContent = true;
      if (vd.isLiveDvrEnabled === true) out.isLive = true;
    } catch (_) {}

    try {
      const mf = pr.microformat && pr.microformat.playerMicroformatRenderer;
      if (mf) {
        if (mf.category) out.category = String(mf.category);
        if (mf.liveBroadcastDetails && mf.liveBroadcastDetails.isLiveNow) out.isLive = true;
      }
    } catch (_) {}

    const codes = new Set();
    try {
      const cap =
        pr.captions &&
        pr.captions.playerCaptionsTracklistRenderer;
      if (cap) {
        const tracks = cap.captionTracks || [];
        for (const t of tracks) {
          const lc = normalizeLang(t.languageCode || t.vssId);
          if (lc && lc.length <= 3) codes.add(lc);
          // ASR default often indicates spoken language
          if (t.kind === "asr" || (t.vssId && String(t.vssId).startsWith("a."))) {
            const asr = normalizeLang(t.languageCode);
            if (asr && !out.language) out.language = asr;
          }
        }
        const audioTracks = cap.audioTracks || [];
        for (const a of audioTracks) {
          // audioTrackId often like "ja.4" or "en.0"
          const id = String(a.audioTrackId || a.id || "");
          const m = id.match(/^([a-z]{2,3})[.\-]/i);
          if (m) codes.add(normalizeLang(m[1]));
        }
        if (typeof cap.defaultAudioTrackIndex === "number" && audioTracks[cap.defaultAudioTrackIndex]) {
          const a = audioTracks[cap.defaultAudioTrackIndex];
          const id = String(a.audioTrackId || a.id || "");
          const m = id.match(/^([a-z]{2,3})[.\-]/i);
          if (m) out.language = normalizeLang(m[1]);
        }
      }
    } catch (_) {}

    // Default audio language fields (vary by client)
    try {
      const al =
        (pr.videoDetails && pr.videoDetails.defaultAudioLanguage) ||
        (pr.microformat &&
          pr.microformat.playerMicroformatRenderer &&
          pr.microformat.playerMicroformatRenderer.audioLanguage) ||
        "";
      const n = normalizeLang(al);
      if (n) {
        codes.add(n);
        if (!out.language) out.language = n;
      }
    } catch (_) {}

    out.languages = Array.from(codes);

    // Prefer Japanese if present among tracks; else first detected
    if (!out.language) {
      if (codes.has("ja")) out.language = "ja";
      else if (codes.has("en")) out.language = "en";
      else if (out.languages.length) out.language = out.languages[0];
    }

    return out;
  }

  function publish() {
    window.postMessage(
      { source: SOURCE, type: "VIEWER_IDENTITY", payload: readIdentity() },
      "*"
    );
    window.postMessage(
      { source: SOURCE, type: "VIDEO_META", payload: readVideoMeta() },
      "*"
    );
  }

  publish();
  setTimeout(publish, 800);
  setTimeout(publish, 2500);
  setTimeout(publish, 6000);
  document.addEventListener("yt-navigate-finish", publish, true);
  window.addEventListener("yt-page-data-updated", publish, true);
})();
