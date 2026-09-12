(() => {
  const api =
    typeof ImmersionExt !== "undefined"
      ? ImmersionExt
      : typeof browser !== "undefined"
        ? browser
        : typeof chrome !== "undefined"
          ? chrome
          : null;

  if (!api) {
    console.error("[immersion-tracker] content: no extension API");
    return;
  }

  // Settings must match popup: local only (webhook secret never goes to sync).
  const storage = api.storage && api.storage.local ? api.storage.local : null;
  const PAGE_SOURCE = "immersion-tracker-page-bridge";

  const DEFAULTS = {
    serverUrl: "http://127.0.0.1:8000",
    webhookSecret: "",
    threshold: 0.9,
    enabled: true,
    allowedViewers: "",
    channelMode: "all", // "all" | "allowlist"
    channelAllowlist: "",
    channelBlocklist: "",
    videoBlocklist: "",
    preferJapanese: true,
    languageUnknownPolicy: "log", // "log" | "skip"
    blockShorts: true,
    blockLive: true,
    minDurationSeconds: 60,
    /** Min content seconds actually advanced while playing (default 5 min). */
    minWatchedSeconds: 300,
  };

  const STATE = {
    videoId: null,
    maxRatio: 0,
    duration: 0,
    /** Accumulated content seconds (positive currentTime deltas while playing). */
    watchedContentSeconds: 0,
    lastSampleTime: null,
    reported: false,
    localStatus: "", // watching | pending | accepted | duplicate | error | rejected
    localKey: "",
    localLogId: null,
    title: "",
    channelId: "",
    channelTitle: "",
    // Signed-in *viewer* only (never the video uploader)
    viewerChannelId: "",
    viewerHandle: "",
    viewerLoggedIn: null,
    viewerSource: "",
    // Media meta from page bridge / URL
    language: "",
    languages: [],
    isLive: false,
    isLiveContent: false,
    category: "",
    metaSource: "",
    restorePending: false,
    lastProgressSentAt: 0,
    lastProgressRatio: 0,
  };

  function storageGet(defaults) {
    if (!storage) return Promise.resolve(defaults);
    try {
      const result = storage.get(defaults);
      if (result && typeof result.then === "function") return result;
      return new Promise((resolve) => storage.get(defaults, resolve));
    } catch (_) {
      return new Promise((resolve) => storage.get(defaults, resolve));
    }
  }

  function sendMessage(message) {
    try {
      const result = api.runtime.sendMessage(message);
      if (result && typeof result.then === "function") return result;
      return new Promise((resolve) => {
        api.runtime.sendMessage(message, (res) => {
          const err = api.runtime.lastError;
          if (err) resolve({ ok: false, error: err.message });
          else resolve(res);
        });
      });
    } catch (e) {
      return Promise.resolve({ ok: false, error: String(e) });
    }
  }

  function normAccount(value) {
    let v = String(value || "").trim();
    if (!v) return "";
    try {
      if (/%[0-9A-Fa-f]{2}/.test(v)) v = decodeURIComponent(v);
    } catch (_) {}
    if (v.startsWith("UC") && v.length >= 22) return v;
    const fold = (s) => s.replace(/[A-Za-z]+/g, (m) => m.toLowerCase());
    if (v.startsWith("@")) return "@" + fold(v.slice(1));
    if (!v.includes("/") && !v.includes(" ")) return "@" + fold(v);
    return v;
  }

  function parseList(raw) {
    if (!raw) return [];
    return String(raw)
      .split(/[\n,]+/)
      .map((s) => s.trim())
      .filter(Boolean);
  }

  function parseAccountList(raw) {
    return parseList(raw).map((s) => normAccount(s)).filter(Boolean);
  }

  function tokensFor(...parts) {
    const present = new Set();
    for (const p of parts) {
      const a = normAccount(p);
      if (!a) continue;
      present.add(a);
      if (a.startsWith("@")) present.add(a.slice(1));
      else present.add("@" + a);
    }
    return present;
  }

  function listMatches(list, ...ids) {
    if (!list.length) return false;
    const present = tokensFor(...ids);
    if (!present.size) return false;
    for (const token of list) {
      if (present.has(token)) return true;
      if (token.startsWith("@") && present.has(token.slice(1))) return true;
      if (!token.startsWith("@") && present.has("@" + token)) return true;
    }
    return false;
  }

  function viewerMatchesAllowlist(allowed, viewerChannelId, viewerHandle) {
    if (!allowed.length) return true;
    const present = tokensFor(viewerChannelId, viewerHandle);
    if (!present.size) return false;
    for (const token of allowed) {
      if (present.has(token)) return true;
      if (token.startsWith("@") && present.has(token.slice(1))) return true;
      if (!token.startsWith("@") && present.has("@" + token)) return true;
    }
    return false;
  }

  function channelMatchesList(list, channelId, channelTitle) {
    return listMatches(list, channelId, channelTitle && channelTitle.startsWith("@") ? channelTitle : "");
  }

  function videoInBlocklist(list, videoId) {
    if (!list.length || !videoId) return false;
    const id = String(videoId).trim();
    return list.some((v) => String(v).trim() === id);
  }

  function isShortsUrl(href) {
    try {
      return /\/shorts\//i.test(href || location.href);
    } catch (_) {
      return false;
    }
  }

  function hasJapaneseScript(text) {
    return /[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]/.test(String(text || ""));
  }

  function normalizeLang(code) {
    if (!code) return "";
    let c = String(code).trim().toLowerCase().replace(/_/g, "-");
    if (c === "jp") c = "ja";
    return c.split("-")[0] || "";
  }

  function resolveLanguage(title) {
    let lang = normalizeLang(STATE.language);
    if (lang) return lang;
    // Weak title signal only when player meta is missing
    if (hasJapaneseScript(title || STATE.title)) return "ja";
    return "";
  }

  /**
   * Returns skip reason string, or null if this watch may be logged.
   */
  function evaluateFilters(cfg, ctx) {
    if (cfg.enabled === false) return "extension off";

    const allowedViewers = parseAccountList(cfg.allowedViewers);
    if (
      allowedViewers.length &&
      !viewerMatchesAllowlist(allowedViewers, ctx.viewerChannelId, ctx.viewerHandle)
    ) {
      return "viewer not allowed";
    }

    const videoBlock = parseList(cfg.videoBlocklist);
    if (videoInBlocklist(videoBlock, ctx.videoId)) return "video blocked";

    const blocklist = parseAccountList(cfg.channelBlocklist);
    if (channelMatchesList(blocklist, ctx.channelId, ctx.channelTitle)) {
      return "channel blocked";
    }

    const mode = cfg.channelMode === "allowlist" ? "allowlist" : "all";
    const allowlist = parseAccountList(cfg.channelAllowlist);
    if (mode === "allowlist") {
      if (!allowlist.length) return "channel allowlist empty";
      if (!ctx.channelId && !ctx.channelTitle) return "channel unknown";
      if (!channelMatchesList(allowlist, ctx.channelId, ctx.channelTitle)) {
        return "channel not on allowlist";
      }
    }

    if (cfg.blockShorts !== false && ctx.isShorts) return "Shorts off";
    if (cfg.blockLive !== false && (ctx.isLive || ctx.isLiveContent)) return "Live off";

    const minDur = Number(cfg.minDurationSeconds);
    if (
      Number.isFinite(minDur) &&
      minDur > 0 &&
      ctx.durationSeconds > 0 &&
      ctx.durationSeconds < minDur
    ) {
      return "too short (<" + minDur + "s)";
    }

    if (cfg.preferJapanese !== false) {
      const lang = resolveLanguage(ctx.title);
      if (lang === "en") return "language: en";
      if (lang && lang !== "ja") return "language: " + lang;
      if (!lang) {
        const policy = cfg.languageUnknownPolicy === "skip" ? "skip" : "log";
        if (policy === "skip") return "language: unknown";
      }
    }

    return null;
  }

  function getVideoId() {
    try {
      const u = new URL(location.href);
      if (u.pathname === "/watch") return u.searchParams.get("v");
      const m = u.pathname.match(/\/shorts\/([^/?]+)/);
      if (m) return m[1];
    } catch (_) {}
    return null;
  }

  function getMeta() {
    const titleEl =
      document.querySelector("h1.ytd-watch-metadata yt-formatted-string") ||
      document.querySelector("h1.title") ||
      document.querySelector("yt-formatted-string.style-scope.ytd-watch-metadata") ||
      document.querySelector("h2.slim-video-information-title");
    const title =
      (titleEl && titleEl.textContent && titleEl.textContent.trim()) ||
      document.title.replace(/ - YouTube$/, "").trim();

    let channelId = "";
    let channelTitle = "";
    const channelLink =
      document.querySelector("ytd-video-owner-renderer a[href*='/@']") ||
      document.querySelector("ytd-video-owner-renderer a[href*='/channel/']") ||
      document.querySelector("#channel-name a") ||
      document.querySelector("a.ytp-title-channel-name") ||
      document.querySelector("a.slim-owner-channel-name");
    if (channelLink) {
      channelTitle = (channelLink.textContent || "").trim();
      const href = channelLink.getAttribute("href") || "";
      const cm = href.match(/\/channel\/([^/?]+)/);
      if (cm) channelId = cm[1];
      else {
        const hm = href.match(/\/@([^/?]+)/);
        if (hm) channelId = "@" + decodeHandlePart(hm[1]);
      }
    }
    return { title, channelId, channelTitle };
  }

  function isUploaderOrContentContext(el) {
    if (!el || !el.closest) return true;
    return !!(
      el.closest("ytd-video-owner-renderer") ||
      el.closest("#owner") ||
      el.closest("#upload-info") ||
      el.closest("ytd-watch-metadata") ||
      el.closest("ytd-video-meta-block") ||
      el.closest("ytd-video-secondary-info-renderer") ||
      el.closest("ytd-reel-player-header-renderer") ||
      el.closest("ytd-channel-renderer") ||
      el.closest("ytd-grid-video-renderer") ||
      el.closest("ytd-rich-item-renderer") ||
      el.closest("ytd-compact-video-renderer") ||
      el.closest("ytd-playlist-panel-video-renderer") ||
      el.closest("ytd-video-renderer") ||
      el.closest("ytd-channel-name") ||
      el.closest("#channel-name") ||
      el.closest("ytd-comment-renderer") ||
      el.closest("ytd-comment-view-model")
    );
  }

  function decodeHandlePart(raw) {
    if (!raw) return "";
    let s = String(raw).trim();
    try {
      if (/%[0-9A-Fa-f]{2}/.test(s)) s = decodeURIComponent(s);
    } catch (_) {}
    return s;
  }

  function extractChannelFromHref(href) {
    if (!href) return { channelId: "", handle: "" };
    const cm = href.match(/\/channel\/(UC[\w-]{22})/);
    if (cm) return { channelId: cm[1], handle: "" };
    const hm = href.match(/\/@([^/?#]+)/);
    if (hm) return { channelId: "", handle: "@" + decodeHandlePart(hm[1]) };
    return { channelId: "", handle: "" };
  }

  function detectViewerFromDom() {
    if (STATE.viewerChannelId && STATE.viewerHandle) return;

    const YOUR_CHANNEL = /your channel|あなたのチャンネル|我的頻道|我的频道|내 채널|ваш канал/i;

    const avatarRoots = document.querySelectorAll(
      "#avatar-btn, button#avatar-btn, ytd-topbar-menu-button-renderer#button, ytd-topbar-menu-button-renderer"
    );
    for (const root of avatarRoots) {
      if (isUploaderOrContentContext(root)) continue;
      const links = root.querySelectorAll('a[href*="/channel/UC"], a[href*="/@"]');
      for (const a of links) {
        if (isUploaderOrContentContext(a)) continue;
        const { channelId, handle } = extractChannelFromHref(a.getAttribute("href") || "");
        if (channelId && !STATE.viewerChannelId) {
          STATE.viewerChannelId = channelId;
          STATE.viewerSource = STATE.viewerSource || "dom-avatar";
        }
        if (handle && !STATE.viewerHandle) {
          STATE.viewerHandle = handle;
          STATE.viewerSource = STATE.viewerSource || "dom-avatar";
        }
      }
    }

    const guideEntries = document.querySelectorAll("ytd-guide-entry-renderer");
    for (const entry of guideEntries) {
      const label = (entry.textContent || "").trim();
      if (!YOUR_CHANNEL.test(label)) continue;
      const a = entry.querySelector('a[href*="/channel/UC"], a[href*="/@"]');
      if (!a || isUploaderOrContentContext(a)) continue;
      const { channelId, handle } = extractChannelFromHref(a.getAttribute("href") || "");
      if (channelId && !STATE.viewerChannelId) {
        STATE.viewerChannelId = channelId;
        STATE.viewerSource = STATE.viewerSource || "dom-guide-your-channel";
      }
      if (handle && !STATE.viewerHandle) {
        STATE.viewerHandle = handle;
        STATE.viewerSource = STATE.viewerSource || "dom-guide-your-channel";
      }
    }
  }

  function rejectIfLooksLikeUploader() {
    if (STATE.viewerSource === "ytcfg") return;
    const uploader = STATE.channelId || getMeta().channelId || "";
    const upNorm = normAccount(uploader);
    if (!upNorm) return;
    if (STATE.viewerChannelId && normAccount(STATE.viewerChannelId) === upNorm) {
      console.warn(
        "[immersion-tracker] ignoring viewer id that matches video uploader",
        STATE.viewerChannelId
      );
      STATE.viewerChannelId = "";
      STATE.viewerSource = "";
    }
    if (STATE.viewerHandle && normAccount(STATE.viewerHandle) === upNorm) {
      console.warn(
        "[immersion-tracker] ignoring viewer handle that matches video uploader",
        STATE.viewerHandle
      );
      STATE.viewerHandle = "";
    }
  }

  function getViewer() {
    detectViewerFromDom();
    if (!STATE.channelId) {
      const meta = getMeta();
      STATE.channelId = meta.channelId;
      STATE.channelTitle = meta.channelTitle;
    }
    rejectIfLooksLikeUploader();
    return {
      viewerChannelId: STATE.viewerChannelId || "",
      viewerHandle: STATE.viewerHandle || "",
      source: STATE.viewerSource || "",
      uploaderChannelId: STATE.channelId || "",
      uploaderTitle: STATE.channelTitle || "",
    };
  }

  function applyLocalEntry(entry) {
    if (!entry) return;
    STATE.localStatus = entry.status || "";
    STATE.localKey = entry.key || "";
    STATE.localLogId = entry.logId != null ? entry.logId : null;
    if (Number(entry.maxRatio) > STATE.maxRatio) {
      STATE.maxRatio = Number(entry.maxRatio) || 0;
    }
    if (Number(entry.watchedSeconds) > STATE.watchedContentSeconds) {
      STATE.watchedContentSeconds = Number(entry.watchedSeconds) || 0;
    }
    if (Number(entry.durationSeconds) > 0 && !STATE.duration) {
      STATE.duration = Number(entry.durationSeconds);
    }
    if (entry.title && !STATE.title) STATE.title = entry.title;
    if (entry.channelId && !STATE.channelId) STATE.channelId = entry.channelId;
    if (entry.channelTitle && !STATE.channelTitle) {
      STATE.channelTitle = entry.channelTitle;
    }
    // Already queued or delivered once — don't re-send (rejected can be retried after filter changes)
    if (
      entry.status === "accepted" ||
      entry.status === "duplicate" ||
      entry.status === "pending" ||
      entry.status === "error" ||
      entry.status === "ready"
    ) {
      STATE.reported = true;
    }
    updateLoggedBadge();
  }

  /** On-page pill so you can see logged / pending without opening the popup. */
  function ensureLoggedBadge() {
    let el = document.getElementById("immersion-tracker-badge");
    if (el) return el;
    el = document.createElement("div");
    el.id = "immersion-tracker-badge";
    el.setAttribute("role", "status");
    el.hidden = true;
    Object.assign(el.style, {
      position: "fixed",
      top: "72px",
      right: "12px",
      zIndex: "2147483646",
      padding: "6px 10px",
      borderRadius: "999px",
      fontFamily: 'system-ui, "Segoe UI", sans-serif',
      fontSize: "12px",
      fontWeight: "700",
      letterSpacing: "0.02em",
      boxShadow: "0 2px 10px rgba(0,0,0,0.35)",
      pointerEvents: "none",
      maxWidth: "min(220px, 70vw)",
      whiteSpace: "nowrap",
      overflow: "hidden",
      textOverflow: "ellipsis",
    });
    (document.documentElement || document.body).appendChild(el);
    return el;
  }

  function updateLoggedBadge() {
    const el = ensureLoggedBadge();
    if (!STATE.videoId) {
      el.hidden = true;
      return;
    }
    const st = STATE.localStatus || "";
    let label = "";
    let bg = "#1f2937";
    let fg = "#f9fafb";
    if (st === "accepted" || st === "duplicate") {
      label = st === "duplicate" ? "Already logged" : "Logged";
      bg = "#166534";
      fg = "#ecfdf5";
    } else if (st === "pending" || st === "ready") {
      label = "Queued…";
      bg = "#a16207";
      fg = "#fffbeb";
    } else if (st === "error" || st === "rejected") {
      label = st === "rejected" ? "Rejected" : "Log error";
      bg = "#991b1b";
      fg = "#fef2f2";
    } else if (STATE.reported) {
      label = "Logged";
      bg = "#166534";
      fg = "#ecfdf5";
    } else {
      el.hidden = true;
      return;
    }
    el.textContent = "IT · " + label;
    el.style.background = bg;
    el.style.color = fg;
    el.hidden = false;
  }

  /**
   * Accrue real content watch time from positive currentTime deltas.
   * Ignores seeks (jumps > 2.5s) so end-skips do not count as watch time.
   */
  function sampleWatchTime(video) {
    if (!video || !isFinite(video.currentTime)) return;
    const t = video.currentTime;
    if (STATE.lastSampleTime != null && !video.paused && !video.ended) {
      const d = t - STATE.lastSampleTime;
      if (d > 0 && d < 2.5) {
        STATE.watchedContentSeconds += d;
      }
    }
    STATE.lastSampleTime = t;
  }

  function effectiveWatchedSeconds(duration, ratio) {
    const peak = duration > 0 ? duration * Math.min(1, Math.max(0, ratio || 0)) : 0;
    return Math.max(STATE.watchedContentSeconds || 0, peak);
  }

  function restoreLocalForVideo(id) {
    STATE.restorePending = true;
    sendMessage({ type: "LOCAL_LOG_STATUS", videoId: id })
      .then((res) => {
        if (res && res.ok && res.entry && STATE.videoId === id) {
          applyLocalEntry(res.entry);
          console.info(
            "[immersion-tracker] restored local state",
            id,
            res.entry.status,
            Math.round((res.entry.maxRatio || 0) * 100) + "%"
          );
        }
      })
      .finally(() => {
        if (STATE.videoId === id) STATE.restorePending = false;
      });
  }

  function persistProgress(force) {
    if (!STATE.videoId) return;
    const now = Date.now();
    const ratio = STATE.maxRatio || 0;
    if (
      !force &&
      now - STATE.lastProgressSentAt < 4000 &&
      Math.abs(ratio - STATE.lastProgressRatio) < 0.03 &&
      ratio < 0.9
    ) {
      return;
    }
    STATE.lastProgressSentAt = now;
    STATE.lastProgressRatio = ratio;
    const meta = getMeta();
    const watched = effectiveWatchedSeconds(STATE.duration || 0, ratio);
    const viewer = getViewer();
    sendMessage({
      type: "YOUTUBE_PROGRESS",
      patch: {
        videoId: STATE.videoId,
        title: meta.title || STATE.title || STATE.videoId,
        channelId: meta.channelId || STATE.channelId || "",
        channelTitle: meta.channelTitle || STATE.channelTitle || "",
        url: location.href,
        durationSeconds: STATE.duration || 0,
        maxRatio: ratio,
        watchedSeconds: watched,
        force: !!force,
        viewerChannelId: viewer.viewerChannelId || STATE.viewerChannelId || "",
        viewerHandle: viewer.viewerHandle || STATE.viewerHandle || "",
      },
    }).then((res) => {
      if (res && res.entry && STATE.videoId === res.entry.videoId) {
        STATE.localStatus = res.entry.status || STATE.localStatus;
        STATE.localKey = res.entry.key || STATE.localKey;
        // Terminal once-ever — stop re-queueing
        if (
          res.entry.status === "accepted" ||
          res.entry.status === "duplicate" ||
          res.already
        ) {
          STATE.reported = true;
        }
      }
    });
  }

  function resetForVideo(id) {
    STATE.videoId = id;
    STATE.maxRatio = 0;
    STATE.duration = 0;
    STATE.watchedContentSeconds = 0;
    STATE.lastSampleTime = null;
    STATE.reported = false;
    STATE.localStatus = "";
    STATE.localKey = "";
    STATE.localLogId = null;
    STATE.language = "";
    STATE.languages = [];
    STATE.isLive = false;
    STATE.isLiveContent = false;
    STATE.category = "";
    STATE.metaSource = "";
    STATE.lastProgressSentAt = 0;
    STATE.lastProgressRatio = 0;
    const meta = getMeta();
    STATE.title = meta.title;
    STATE.channelId = meta.channelId;
    STATE.channelTitle = meta.channelTitle;
    updateLoggedBadge();
    restoreLocalForVideo(id);
  }

  function buildFilterContext(meta, durationSeconds) {
    const viewer = getViewer();
    return {
      videoId: STATE.videoId || getVideoId() || "",
      title: (meta && meta.title) || STATE.title || "",
      channelId: (meta && meta.channelId) || STATE.channelId || "",
      channelTitle: (meta && meta.channelTitle) || STATE.channelTitle || "",
      viewerChannelId: viewer.viewerChannelId,
      viewerHandle: viewer.viewerHandle,
      durationSeconds: durationSeconds || STATE.duration || 0,
      isShorts: isShortsUrl(location.href),
      isLive: !!STATE.isLive,
      isLiveContent: !!STATE.isLiveContent,
      language: resolveLanguage((meta && meta.title) || STATE.title),
      languages: STATE.languages || [],
    };
  }

  function reportIfNeeded(video) {
    if (STATE.reported || !STATE.videoId || STATE.restorePending) return;
    const duration = video.duration;
    if (!duration || !isFinite(duration) || duration <= 0) return;

    STATE.duration = duration;
    sampleWatchTime(video);
    const instantaneous = video.currentTime / duration;
    if (instantaneous > STATE.maxRatio) {
      const jump = instantaneous - STATE.maxRatio;
      if (jump <= 0.35 || STATE.maxRatio >= 0.5 || video.ended) {
        STATE.maxRatio = instantaneous;
      }
    }

    // Always keep progress durable (survives extension reload)
    persistProgress(false);

    storageGet(DEFAULTS).then((cfg) => {
      if (cfg.enabled === false) return;
      const thr = typeof cfg.threshold === "number" ? cfg.threshold : 0.9;
      const minWatched =
        cfg.minWatchedSeconds != null && cfg.minWatchedSeconds !== ""
          ? Number(cfg.minWatchedSeconds)
          : 300;
      const ratio = STATE.maxRatio;
      if (ratio < thr && video.ended !== true) return;
      const finalRatio = video.ended && ratio >= 0.5 ? Math.max(ratio, 0.99) : ratio;
      if (finalRatio < thr) return;

      const watched = effectiveWatchedSeconds(duration, finalRatio);
      // Require both ≥ threshold % and ≥ min watch time (default 5 min)
      if (Number.isFinite(minWatched) && minWatched > 0 && watched < minWatched) {
        return;
      }
      if (STATE.reported) return;

      const meta = getMeta();
      const ctx = buildFilterContext(meta, duration);
      const skip = evaluateFilters(cfg, ctx);
      if (skip) {
        console.info("[immersion-tracker] skip:", skip, ctx);
        // Still persist that we hit threshold so popup can show "ready but filtered"
        persistProgress(true);
        return;
      }

      // Mark reported immediately so we don't double-queue; local store is source of truth
      STATE.reported = true;
      STATE.localStatus = "pending";
      updateLoggedBadge();
      const payload = {
        video_id: STATE.videoId,
        title: meta.title || STATE.title || STATE.videoId,
        channel_id: meta.channelId || STATE.channelId || "",
        channel_title: meta.channelTitle || STATE.channelTitle || "",
        duration_seconds: duration,
        watched_seconds: Math.min(duration, watched),
        ratio: finalRatio,
        url: location.href,
        finished_at: new Date().toISOString(),
        viewer_channel_id: ctx.viewerChannelId || "",
        viewer_handle: ctx.viewerHandle || "",
      };

      sendMessage({ type: "YOUTUBE_COMPLETE", payload, config: cfg }).then((res) => {
        console.info("[immersion-tracker] report result", res);
        if (res && res.entry) {
          applyLocalEntry(res.entry);
        }
        if (!res || res.ok === false) {
          const reason =
            (res && res.body && res.body.reason) ||
            (res && res.error) ||
            "";
          // Permanent rejects stay reported; network/transient stay reported too
          // (background retries). Only clear if we never enqueued.
          if (reason === "extension_disabled" || reason === "no_video_id") {
            STATE.reported = false;
            STATE.localStatus = "";
          } else if (
            typeof reason === "string" &&
            reason.startsWith("below_min_watched")
          ) {
            // Can still earn more watch time — allow re-queue later
            STATE.reported = false;
            STATE.localStatus = "";
          } else if (res && res.entry) {
            STATE.reported = true;
            STATE.localStatus = res.entry.status || "error";
          } else {
            // Message failed entirely — keep progress, allow re-queue next tick
            STATE.reported = false;
            STATE.localStatus = "error";
          }
        } else {
          STATE.reported = true;
          const st =
            (res.entry && res.entry.status) ||
            (res.body && res.body.accepted ? "accepted" : "pending");
          STATE.localStatus = st;
        }
        updateLoggedBadge();
      });
    });
  }

  function tick() {
    const id = getVideoId();
    // Only track real watch pages — ignore homepage / feed (no /watch?v=)
    if (!id) {
      if (STATE.videoId) {
        // Left the watch page (homepage, search, …) — clear active tracking
        STATE.videoId = null;
        STATE.reported = false;
        STATE.localStatus = "";
        STATE.maxRatio = 0;
        STATE.watchedContentSeconds = 0;
        STATE.lastSampleTime = null;
        updateLoggedBadge();
      }
      return;
    }
    if (id !== STATE.videoId) resetForVideo(id);

    const video = document.querySelector("video");
    if (!video) return;

    sampleWatchTime(video);
    if (video.duration && isFinite(video.duration) && video.duration > 0) {
      const r = video.currentTime / video.duration;
      if (r > STATE.maxRatio) {
        const jump = r - STATE.maxRatio;
        if (jump <= 0.35 || STATE.maxRatio >= 0.5) STATE.maxRatio = r;
      }
    }

    reportIfNeeded(video);
  }

  window.addEventListener("message", (event) => {
    if (event.source !== window) return;
    const data = event.data;
    if (!data || data.source !== PAGE_SOURCE) return;

    if (data.type === "VIEWER_IDENTITY") {
      const p = data.payload || {};
      if (p.viewerChannelId && /^UC[\w-]{22}$/.test(String(p.viewerChannelId))) {
        STATE.viewerChannelId = String(p.viewerChannelId);
        STATE.viewerSource = p.source || "ytcfg";
      }
      if (p.viewerHandle) {
        const h = String(p.viewerHandle).trim();
        STATE.viewerHandle = h.startsWith("@") ? h : "@" + h;
        STATE.viewerSource = STATE.viewerSource || p.source || "ytcfg";
      }
      if (typeof p.loggedIn === "boolean") {
        STATE.viewerLoggedIn = p.loggedIn;
      }
      // Cache for history scan when no YouTube tab is active
      if (STATE.viewerChannelId || STATE.viewerHandle) {
        sendMessage({
          type: "CACHE_VIEWER",
          viewer: {
            viewerChannelId: STATE.viewerChannelId || "",
            viewerHandle: STATE.viewerHandle || "",
            source: STATE.viewerSource || "ytcfg",
          },
        }).catch(() => {});
      }
      return;
    }

    if (data.type === "VIDEO_META") {
      const p = data.payload || {};
      if (p.language) STATE.language = normalizeLang(p.language);
      if (Array.isArray(p.languages)) {
        STATE.languages = p.languages.map(normalizeLang).filter(Boolean);
      }
      if (typeof p.isLive === "boolean") STATE.isLive = p.isLive;
      if (typeof p.isLiveContent === "boolean") STATE.isLiveContent = p.isLiveContent;
      if (p.category) STATE.category = String(p.category);
      if (p.source) STATE.metaSource = p.source;
    }
  });

  function getWatchSnapshot(cfg) {
    const meta = getMeta();
    const video = document.querySelector("video");
    let currentTime = 0;
    let duration = STATE.duration || 0;
    let maxRatio = STATE.maxRatio || 0;
    if (video && video.duration && isFinite(video.duration) && video.duration > 0) {
      duration = video.duration;
      currentTime = video.currentTime || 0;
      const r = currentTime / duration;
      if (r > maxRatio) maxRatio = r;
    }

    const ctx = buildFilterContext(meta, duration);
    const skipReason = cfg ? evaluateFilters(cfg, ctx) : null;
    const channelAllow = parseAccountList(cfg && cfg.channelAllowlist);
    const channelBlock = parseAccountList(cfg && cfg.channelBlocklist);
    const videoBlock = parseList(cfg && cfg.videoBlocklist);
    const mode = cfg && cfg.channelMode === "allowlist" ? "allowlist" : "all";

    const watchedSec = effectiveWatchedSeconds(duration || 0, maxRatio || 0);
    const thr = cfg && typeof cfg.threshold === "number" ? cfg.threshold : 0.9;
    const minWatched =
      cfg && cfg.minWatchedSeconds != null && cfg.minWatchedSeconds !== ""
        ? Number(cfg.minWatchedSeconds)
        : 300;
    const meetsRatio = (maxRatio || 0) >= thr;
    const meetsWatch =
      !Number.isFinite(minWatched) || minWatched <= 0 || watchedSec >= minWatched;
    return {
      videoId: ctx.videoId,
      title: ctx.title,
      channelId: ctx.channelId,
      channelTitle: ctx.channelTitle,
      durationSeconds: duration || 0,
      currentTimeSeconds: currentTime || 0,
      maxRatio: maxRatio || 0,
      watchedSeconds: watchedSec,
      minWatchedSeconds: Number.isFinite(minWatched) ? minWatched : 300,
      reported: !!STATE.reported,
      localStatus: STATE.localStatus || "",
      localKey: STATE.localKey || "",
      localLogId: STATE.localLogId,
      href: location.href,
      isShorts: ctx.isShorts,
      isLive: ctx.isLive || ctx.isLiveContent,
      language: ctx.language || "",
      languages: ctx.languages || [],
      category: STATE.category || "",
      skipReason: skipReason,
      willLog: !skipReason && !STATE.reported && meetsRatio && meetsWatch,
      channelOnAllowlist: channelMatchesList(channelAllow, ctx.channelId, ctx.channelTitle),
      channelOnBlocklist: channelMatchesList(channelBlock, ctx.channelId, ctx.channelTitle),
      videoOnBlocklist: videoInBlocklist(videoBlock, ctx.videoId),
      channelMode: mode,
      filters: {
        preferJapanese: cfg ? cfg.preferJapanese !== false : true,
        blockShorts: cfg ? cfg.blockShorts !== false : true,
        blockLive: cfg ? cfg.blockLive !== false : true,
        minDurationSeconds: cfg ? Number(cfg.minDurationSeconds) || 0 : 60,
        minWatchedSeconds: Number.isFinite(minWatched) ? minWatched : 300,
        languageUnknownPolicy: (cfg && cfg.languageUnknownPolicy) || "log",
      },
    };
  }

  function forceQueueCurrent(opts) {
    const video = document.querySelector("video");
    const videoId = STATE.videoId || getVideoId();
    if (!videoId) return Promise.resolve({ ok: false, error: "no_video" });

    return storageGet(DEFAULTS).then((cfg) => {
      if (cfg.enabled === false && !(opts && opts.ignoreEnabled)) {
        return { ok: false, error: "extension_disabled" };
      }
      const meta = getMeta();
      const duration =
        (video && video.duration && isFinite(video.duration) && video.duration > 0
          ? video.duration
          : 0) ||
        STATE.duration ||
        0;
      let ratio = STATE.maxRatio || 0;
      if (video && duration > 0) {
        const inst = video.currentTime / duration;
        if (inst > ratio) ratio = inst;
        if (video.ended) ratio = Math.max(ratio, 0.99);
      }
      if (opts && opts.minRatio != null) {
        ratio = Math.max(ratio, Number(opts.minRatio) || 0);
      }
      // Manual force from popup: treat as complete if user insists
      if (opts && opts.forceComplete) {
        ratio = Math.max(ratio, 0.99);
      }
      if (!duration || duration <= 0) {
        return { ok: false, error: "no_duration" };
      }

      const thr = typeof cfg.threshold === "number" ? cfg.threshold : 0.9;
      if (ratio < thr && !(opts && opts.forceComplete)) {
        return {
          ok: false,
          error: "below_threshold",
          ratio,
          threshold: thr,
        };
      }

      const minWatched =
        cfg.minWatchedSeconds != null && cfg.minWatchedSeconds !== ""
          ? Number(cfg.minWatchedSeconds)
          : 300;
      let watched = effectiveWatchedSeconds(duration, ratio);
      // Manual force from popup may bypass min watch time
      if (opts && opts.forceComplete && Number.isFinite(minWatched) && minWatched > 0) {
        watched = Math.max(watched, minWatched);
      } else if (
        Number.isFinite(minWatched) &&
        minWatched > 0 &&
        watched < minWatched &&
        !(opts && opts.forceComplete)
      ) {
        return {
          ok: false,
          error: "below_min_watched",
          watched,
          minWatched,
        };
      }

      const ctx = buildFilterContext(meta, duration);
      if (!(opts && opts.ignoreFilters)) {
        const skip = evaluateFilters(cfg, ctx);
        if (skip) return { ok: false, error: "filtered", skip };
      }

      STATE.reported = true;
      STATE.localStatus = "pending";
      updateLoggedBadge();
      STATE.maxRatio = Math.max(STATE.maxRatio, ratio);
      // Force may pad watched_seconds so server min_watched floor is met
      const watchedOut =
        opts && opts.forceComplete
          ? Math.max(Math.min(duration, watched), Number(minWatched) || 0)
          : Math.min(duration, watched);
      const payload = {
        video_id: videoId,
        title: meta.title || STATE.title || videoId,
        channel_id: meta.channelId || STATE.channelId || "",
        channel_title: meta.channelTitle || STATE.channelTitle || "",
        duration_seconds: duration,
        watched_seconds: watchedOut,
        ratio: Math.min(1, ratio),
        url: location.href,
        finished_at: new Date().toISOString(),
        viewer_channel_id: ctx.viewerChannelId || "",
        viewer_handle: ctx.viewerHandle || "",
      };

      // forceRedeliver: ignore stale local "duplicate"/"accepted" and re-POST
      return sendMessage({
        type: "YOUTUBE_COMPLETE",
        payload,
        config: cfg,
        force: true,
        forceRedeliver: true,
      }).then((res) => {
        console.info("[immersion-tracker] force queue result", res);
        if (res && res.entry) applyLocalEntry(res.entry);
        return res || { ok: false, error: "no_response" };
      });
    });
  }

  api.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    if (!msg) return false;

    if (msg.type === "FORCE_QUEUE") {
      forceQueueCurrent(msg.opts || { forceComplete: true })
        .then(sendResponse)
        .catch((e) => sendResponse({ ok: false, error: String(e) }));
      return true;
    }

    if (msg.type !== "GET_VIEWER" && msg.type !== "GET_PAGE_STATUS") {
      return false;
    }
    storageGet(DEFAULTS).then((cfg) => {
      const viewer = getViewer();
      const watch = getWatchSnapshot(cfg);
      sendResponse({
        ok: true,
        viewerChannelId: viewer.viewerChannelId,
        viewerHandle: viewer.viewerHandle,
        source: viewer.source,
        uploaderChannelId: viewer.uploaderChannelId,
        uploaderTitle: viewer.uploaderTitle,
        loggedIn: STATE.viewerLoggedIn,
        href: location.href,
        watch,
        config: {
          channelMode: cfg.channelMode === "allowlist" ? "allowlist" : "all",
          preferJapanese: cfg.preferJapanese !== false,
          blockShorts: cfg.blockShorts !== false,
          blockLive: cfg.blockLive !== false,
          minDurationSeconds: Number(cfg.minDurationSeconds) || 0,
          minWatchedSeconds:
            cfg.minWatchedSeconds != null && cfg.minWatchedSeconds !== ""
              ? Number(cfg.minWatchedSeconds)
              : 300,
          languageUnknownPolicy: cfg.languageUnknownPolicy || "log",
          enabled: cfg.enabled !== false,
          threshold: typeof cfg.threshold === "number" ? cfg.threshold : 0.9,
        },
      });
    });
    return true;
  });

  let lastHref = location.href;
  setInterval(() => {
    if (location.href !== lastHref) {
      lastHref = location.href;
      const id = getVideoId();
      if (id) resetForVideo(id);
    }
    tick();
  }, 2000);

  document.addEventListener(
    "ended",
    (e) => {
      if (e.target && e.target.tagName === "VIDEO") reportIfNeeded(e.target);
    },
    true
  );

  console.info("[immersion-tracker] YouTube content script loaded (Firefox/Chromium)");
})();
