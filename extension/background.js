/**
 * Background: local durable watch log + queue to Immersion Tracker server.
 * Survives extension reload; retries pending/error deliveries.
 *
 * Works as Chromium service worker or Firefox background script.
 */
/* global browser, chrome */

(function initBackground() {
  const api =
    typeof browser !== "undefined"
      ? browser
      : typeof chrome !== "undefined"
        ? chrome
        : null;

  if (!api || !api.runtime) {
    console.error("[immersion-tracker] background: no extension runtime");
    return;
  }

  const STORAGE_KEY = "ytLocalLog";
  /** Compact set of videoIds ever accepted/duplicated — survives log trimming. */
  const LOGGED_IDS_KEY = "ytLoggedVideoIds";
  /** videoId -> ISO when user rejected during log-from-history (don't re-offer). */
  const HISTORY_REJECTED_KEY = "ytHistoryRejectedIds";
  const MAX_ENTRIES = 100;
  const MAX_LOGGED_IDS = 5000;
  const MAX_HISTORY_REJECTED = 8000;
  const MAX_ATTEMPTS = 25;
  const RETRY_MS = 45_000;
  const FLUSH_COOLDOWN_MS = 2_000;
  const HISTORY_MAX_PAGES = 12;
  const HISTORY_MAX_VIDEOS = 400;
  /** videoId -> { durationSeconds, language, title, channelId, channelTitle, at } */
  const VIDEO_META_CACHE_KEY = "ytVideoMetaCache";
  const VIDEO_META_CACHE_MAX = 2500;
  const VIDEO_META_CACHE_TTL_MS = 30 * 86400000;

  /** @type {Map<string, number>} videoId -> last progress write ms */
  const progressThrottle = new Map();
  let flushTimer = null;
  let flushInFlight = false;
  let lastFlushAt = 0;

  // --- storage helpers ---

  /** Settings + queue live in storage.local only (never sync — secrets stay on device). */
  function storageArea() {
    return api.storage && api.storage.local ? api.storage.local : null;
  }

  function storageGet(keys) {
    const area = storageArea();
    if (!area) {
      return Promise.resolve(typeof keys === "object" && !Array.isArray(keys) ? keys : {});
    }
    try {
      const result = area.get(keys);
      if (result && typeof result.then === "function") return result;
      return new Promise((resolve) => area.get(keys, resolve));
    } catch (_) {
      return new Promise((resolve) => area.get(keys, resolve));
    }
  }

  function storageSet(data) {
    const area = storageArea();
    if (!area) return Promise.reject(new Error("no storage"));
    try {
      const result = area.set(data);
      if (result && typeof result.then === "function") return result;
      return new Promise((resolve, reject) => {
        area.set(data, () => {
          const err = api.runtime && api.runtime.lastError;
          if (err) reject(new Error(err.message));
          else resolve();
        });
      });
    } catch (e) {
      return Promise.reject(e);
    }
  }

  function dayKey(iso) {
    try {
      const d = iso ? new Date(iso) : new Date();
      if (Number.isNaN(d.getTime())) return new Date().toISOString().slice(0, 10);
      return d.toISOString().slice(0, 10);
    } catch (_) {
      return new Date().toISOString().slice(0, 10);
    }
  }

  /** Once-ever key: videoId only (not videoId:day). */
  function entryKey(videoId) {
    return String(videoId || "").trim();
  }

  function nowIso() {
    return new Date().toISOString();
  }

  async function loadLog() {
    const data = await storageGet({ [STORAGE_KEY]: [] });
    const list = data[STORAGE_KEY];
    return Array.isArray(list) ? list : [];
  }

  async function saveLog(entries) {
    // Newest first; cap size
    const trimmed = entries.slice(0, MAX_ENTRIES);
    await storageSet({ [STORAGE_KEY]: trimmed });
    return trimmed;
  }

  async function loadLoggedIds() {
    const data = await storageGet({ [LOGGED_IDS_KEY]: {} });
    const raw = data[LOGGED_IDS_KEY];
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) return {};
    return raw;
  }

  async function markVideoLogged(videoId) {
    const vid = String(videoId || "").trim();
    if (!vid) return;
    const map = await loadLoggedIds();
    map[vid] = true;
    const keys = Object.keys(map);
    if (keys.length > MAX_LOGGED_IDS) {
      // Drop oldest arbitrary third when over cap (object key order is insert order)
      const drop = keys.slice(0, keys.length - MAX_LOGGED_IDS);
      for (const k of drop) delete map[k];
    }
    await storageSet({ [LOGGED_IDS_KEY]: map });
  }

  async function isVideoEverLogged(videoId) {
    const vid = String(videoId || "").trim();
    if (!vid) return false;
    const map = await loadLoggedIds();
    if (map[vid]) return true;
    // Also trust any terminal entry still in the ring buffer
    const entries = await loadLog();
    return entries.some(
      (e) => e && e.videoId === vid && isTerminalOk(e.status)
    );
  }

  function findIndex(entries, key) {
    return entries.findIndex((e) => e && e.key === key);
  }

  /**
   * Find any local entry for this videoId (once-ever).
   * Prefer terminal/queued rows over stale "watching" if multiple legacy day-keys exist.
   */
  function findByVideo(entries, videoId) {
    const vid = String(videoId || "").trim();
    if (!vid) return -1;
    let best = -1;
    let bestRank = -1;
    const rank = (status) => {
      if (status === "accepted" || status === "duplicate") return 5;
      if (status === "pending" || status === "ready" || status === "error") return 4;
      if (status === "rejected") return 2;
      if (status === "watching") return 1;
      return 0;
    };
    for (let i = 0; i < entries.length; i++) {
      const e = entries[i];
      if (!e || e.videoId !== vid) continue;
      // Also match legacy keys "vid:YYYY-MM-DD"
      const r = rank(e.status);
      if (r > bestRank) {
        bestRank = r;
        best = i;
      }
    }
    return best;
  }

  function isTerminalOk(status) {
    return status === "accepted" || status === "duplicate";
  }

  function isPermanentReject(reason) {
    if (!reason) return false;
    const r = String(reason);
    return (
      r === "duplicate" ||
      r === "channel_blocked" ||
      r === "channel_not_allowlisted" ||
      r === "channel_unknown_with_allowlist" ||
      r === "viewer_not_allowlisted" ||
      r === "viewer_unknown_with_allowlist" ||
      r === "extension_disabled" ||
      r.startsWith("below_threshold") ||
      r.startsWith("below_min_watched")
    );
  }

  /** Human-readable reason for popup / badges */
  function friendlyReason(reason, httpStatus) {
    const r = String(reason || "");
    if (httpStatus === 401 || r === "http_401") {
      return "wrong webhook secret (401) — fix secret in Logging & connection, Save, then Retry";
    }
    if (httpStatus === 403 || r === "http_403") {
      return "forbidden (403) — check webhook secret / server auth";
    }
    if (r === "viewer_not_allowlisted") {
      return "viewer not on server allowlist (signed-in YouTube account)";
    }
    if (r === "viewer_unknown_with_allowlist") {
      return "viewer unknown — Detect account / open youtube.com signed in";
    }
    if (r === "channel_blocked") return "uploader channel blocked on server";
    if (r === "channel_not_allowlisted") return "uploader not on server allowlist";
    if (r === "duplicate") return "already logged (this video was logged before)";
    if (r.startsWith("below_threshold")) return "below watch threshold on server";
    if (r.startsWith("below_min_watched")) {
      return "need ≥5 min watch progress (and ≥ threshold %) on server";
    }
    if (r === "network_error") return "network error — will retry";
    return r || (httpStatus ? "http_" + httpStatus : "");
  }

  function needsDelivery(entry) {
    if (!entry || !entry.payload) return false;
    if (entry.status === "accepted") return false; // hard success
    // "duplicate" is re-checked on manual retry only (not auto-flush spam)
    if (entry.status === "duplicate") return false;
    if (entry.status === "rejected") return false;
    if (entry.status === "watching") return false;
    if ((entry.attempts || 0) >= MAX_ATTEMPTS) return false;
    return entry.status === "pending" || entry.status === "error" || entry.status === "ready";
  }

  // --- brand icons ---

  function applyBrandIcons() {
    const paths = {
      16: "icons/icon-16.png",
      32: "icons/icon-32.png",
      48: "icons/icon-48.png",
      64: "icons/icon-64.png",
      96: "icons/icon-96.png",
      128: "icons/icon-128.png",
    };
    try {
      const action = api.action || api.browserAction;
      if (action && action.setIcon) {
        const result = action.setIcon({ path: paths });
        if (result && typeof result.then === "function") {
          result.catch((e) => console.warn("[immersion-tracker] setIcon", e));
        }
      }
      if (action && action.setTitle) {
        try {
          action.setTitle({ title: "Lucid Immersion Tracker" });
        } catch (_) {}
      }
    } catch (e) {
      console.warn("[immersion-tracker] setIcon failed", e);
    }
  }

  applyBrandIcons();
  if (api.runtime.onInstalled) {
    api.runtime.onInstalled.addListener(() => {
      applyBrandIcons();
      scheduleFlush(500);
    });
  }
  if (api.runtime.onStartup) {
    api.runtime.onStartup.addListener(() => {
      applyBrandIcons();
      scheduleFlush(1000);
    });
  }
  setTimeout(applyBrandIcons, 500);

  // --- progress + complete ---

  /**
   * Upsert in-progress watch so reloads keep maxRatio / metadata.
   */
  async function upsertProgress(patch) {
    const videoId = String((patch && patch.videoId) || "").trim();
    if (!videoId) return { ok: false, error: "no_video_id" };

    // Remember signed-in viewer whenever content script reports it
    if (patch && (patch.viewerChannelId || patch.viewerHandle)) {
      rememberViewer({
        viewerChannelId: patch.viewerChannelId,
        viewerHandle: patch.viewerHandle,
        source: "progress",
      }).catch(() => {});
    }

    const now = Date.now();
    const last = progressThrottle.get(videoId) || 0;
    const force = !!(patch && patch.force);
    const maxRatio = Number(patch.maxRatio) || 0;
    // Throttle routine ticks; always write when force or past 90% or big jump
    if (!force && now - last < 4000 && maxRatio < 0.9) {
      return { ok: true, throttled: true };
    }
    progressThrottle.set(videoId, now);

    // Never create a fresh "watching" row for a video already logged once
    if (await isVideoEverLogged(videoId)) {
      const entries = await loadLog();
      let idx = findByVideo(entries, videoId);
      if (idx >= 0) {
        const prev = entries[idx];
        const mergedRatio = Math.max(Number(prev.maxRatio) || 0, maxRatio);
        if (mergedRatio > (prev.maxRatio || 0)) {
          prev.maxRatio = mergedRatio;
          prev.updatedAt = nowIso();
          entries[idx] = prev;
          await saveLog(entries);
        }
        return { ok: true, entry: prev, already: true };
      }
      // Logged-id set hit but ring buffer trimmed — synthetic terminal entry
      return {
        ok: true,
        already: true,
        entry: {
          key: entryKey(videoId),
          videoId,
          status: "duplicate",
          serverReason: "duplicate",
          maxRatio,
          title: (patch && patch.title) || videoId,
        },
      };
    }

    const entries = await loadLog();
    const finishedAt = patch.finishedAt || null;
    const key = entryKey(videoId);
    let idx = findByVideo(entries, videoId);
    if (idx < 0) idx = findIndex(entries, key);

    const prev = idx >= 0 ? entries[idx] : null;
    // Never downgrade terminal delivery states via progress pings
    if (prev && isTerminalOk(prev.status)) {
      const mergedRatio = Math.max(Number(prev.maxRatio) || 0, maxRatio);
      if (mergedRatio > (prev.maxRatio || 0)) {
        prev.maxRatio = mergedRatio;
        prev.updatedAt = nowIso();
        entries[idx] = prev;
        await saveLog(entries);
      }
      return { ok: true, entry: prev };
    }
    if (prev && (prev.status === "pending" || prev.status === "error" || prev.status === "ready")) {
      // Keep queue entry; only bump progress metadata
      prev.maxRatio = Math.max(Number(prev.maxRatio) || 0, maxRatio);
      if (patch.title) prev.title = patch.title;
      if (patch.channelId) prev.channelId = patch.channelId;
      if (patch.channelTitle) prev.channelTitle = patch.channelTitle;
      if (patch.durationSeconds) prev.durationSeconds = patch.durationSeconds;
      if (patch.watchedSeconds) {
        prev.watchedSeconds = Math.max(
          Number(prev.watchedSeconds) || 0,
          Number(patch.watchedSeconds) || 0
        );
      }
      prev.updatedAt = nowIso();
      // Normalize key to once-ever form
      prev.key = key;
      entries[idx] = prev;
      entries.splice(idx, 1);
      entries.unshift(prev);
      await saveLog(entries);
      return { ok: true, entry: prev };
    }

    const entry = {
      key: key,
      videoId,
      title: (patch.title || (prev && prev.title) || videoId).trim(),
      channelId: patch.channelId || (prev && prev.channelId) || "",
      channelTitle: patch.channelTitle || (prev && prev.channelTitle) || "",
      url: patch.url || (prev && prev.url) || "",
      durationSeconds:
        Number(patch.durationSeconds) ||
        Number(prev && prev.durationSeconds) ||
        0,
      maxRatio: Math.max(Number(prev && prev.maxRatio) || 0, maxRatio),
      watchedSeconds: Math.max(
        Number(patch.watchedSeconds) || 0,
        Number(prev && prev.watchedSeconds) || 0
      ),
      finishedAt: (prev && prev.finishedAt) || null,
      updatedAt: nowIso(),
      day: dayKey(finishedAt || nowIso()),
      status: (prev && prev.status) || "watching",
      serverReason: (prev && prev.serverReason) || "",
      logId: (prev && prev.logId) || null,
      attempts: (prev && prev.attempts) || 0,
      lastAttemptAt: (prev && prev.lastAttemptAt) || null,
      lastError: (prev && prev.lastError) || "",
      payload: (prev && prev.payload) || null,
    };

    if (idx >= 0) entries.splice(idx, 1);
    entries.unshift(entry);
    await saveLog(entries);
    return { ok: true, entry };
  }

  /**
   * Queue a completion for delivery.
   * - accepted / ever-logged: skip re-POST unless force
   * - force re-POST rechecks server (may have deleted the log)
   */
  async function enqueueComplete(payload, cfg) {
    const videoId = String((payload && payload.video_id) || "").trim();
    if (!videoId) return { ok: false, error: "no_video_id" };

    if (cfg && cfg.enabled === false) {
      return { ok: false, error: "extension_disabled" };
    }

    const force = !!(cfg && (cfg.forceRedeliver || cfg.force));
    const finishedAt = (payload && payload.finished_at) || nowIso();
    const key = entryKey(videoId);
    const entries = await loadLog();
    let idx = findByVideo(entries, videoId);
    if (idx < 0) idx = findIndex(entries, key);
    const prev = idx >= 0 ? entries[idx] : null;

    // Once-ever: short-circuit if this video was ever accepted (or compact id set says so)
    if (!force) {
      if (prev && prev.status === "accepted") {
        await markVideoLogged(videoId);
        return {
          ok: true,
          status: 201,
          body: {
            accepted: true,
            reason: prev.serverReason || "accepted",
            log_id: prev.logId,
          },
          entry: prev,
          already: true,
        };
      }
      if (prev && prev.status === "duplicate") {
        await markVideoLogged(videoId);
        return {
          ok: true,
          status: 200,
          body: {
            accepted: false,
            reason: "duplicate",
            log_id: prev.logId,
          },
          entry: prev,
          already: true,
        };
      }
      if (!prev && (await isVideoEverLogged(videoId))) {
        const synthetic = {
          key,
          videoId,
          status: "duplicate",
          serverReason: "duplicate",
          title: (payload && payload.title) || videoId,
          maxRatio: Number(payload && payload.ratio) || 0,
          finishedAt,
          updatedAt: nowIso(),
          day: dayKey(finishedAt),
        };
        return {
          ok: true,
          status: 200,
          body: { accepted: false, reason: "duplicate" },
          entry: synthetic,
          already: true,
        };
      }
    }

    const entry = {
      key: key,
      videoId,
      title: (payload.title || (prev && prev.title) || videoId).trim(),
      channelId: payload.channel_id || (prev && prev.channelId) || "",
      channelTitle: payload.channel_title || (prev && prev.channelTitle) || "",
      url: payload.url || (prev && prev.url) || "",
      durationSeconds:
        Number(payload.duration_seconds) ||
        Number(prev && prev.durationSeconds) ||
        0,
      maxRatio: Math.max(
        Number(payload.ratio) || 0,
        Number(prev && prev.maxRatio) || 0
      ),
      watchedSeconds: Math.max(
        Number(payload.watched_seconds) || 0,
        Number(prev && prev.watchedSeconds) || 0
      ),
      finishedAt: finishedAt || (prev && prev.finishedAt) || nowIso(),
      updatedAt: nowIso(),
      day: dayKey(finishedAt),
      status: "pending",
      serverReason: "",
      logId: force ? null : (prev && prev.logId) || null,
      attempts: force ? 0 : (prev && prev.attempts) || 0,
      lastAttemptAt: null,
      lastError: "",
      payload: Object.assign({}, payload, {
        finished_at: finishedAt || (prev && prev.finishedAt) || nowIso(),
      }),
    };

    if (idx >= 0) entries.splice(idx, 1);
    entries.unshift(entry);
    await saveLog(entries);

    const result = await deliverEntry(entry.key);
    return result;
  }

  async function postToServer(payload, cfg) {
    const base = String((cfg && cfg.serverUrl) || "http://127.0.0.1:8000").replace(
      /\/$/,
      ""
    );
    const url = base + "/api/webhooks/youtube";
    const headers = { "Content-Type": "application/json" };
    if (cfg && cfg.webhookSecret) {
      headers["X-Webhook-Secret"] = cfg.webhookSecret;
    }
    const r = await fetch(url, {
      method: "POST",
      headers,
      body: JSON.stringify(payload),
    });
    const body = await r.json().catch(() => ({}));
    return { ok: r.ok, status: r.status, body };
  }

  async function deliverEntry(key) {
    const cfg = await storageGet({
      serverUrl: "http://127.0.0.1:8000",
      webhookSecret: "",
      enabled: true,
    });
    if (cfg.enabled === false) {
      return { ok: false, error: "extension_disabled" };
    }

    const entries = await loadLog();
    const idx = findIndex(entries, key);
    if (idx < 0) return { ok: false, error: "not_found" };
    const entry = entries[idx];
    if (!needsDelivery(entry) && !isTerminalOk(entry.status)) {
      // allow forced retry from popup even if attempts high? needsDelivery handles max
      if (!entry.payload) return { ok: false, error: "no_payload", entry };
    }
    if (isTerminalOk(entry.status)) {
      return {
        ok: true,
        status: entry.status === "duplicate" ? 200 : 201,
        body: {
          accepted: entry.status === "accepted",
          reason: entry.serverReason || entry.status,
          log_id: entry.logId,
        },
        entry,
      };
    }
    if (!entry.payload) {
      return { ok: false, error: "no_payload", entry };
    }

    entry.status = "pending";
    entry.attempts = (entry.attempts || 0) + 1;
    entry.lastAttemptAt = nowIso();
    entry.updatedAt = nowIso();
    entries[idx] = entry;
    await saveLog(entries);

    try {
      const res = await postToServer(entry.payload, cfg);
      const body = res.body || {};
      const reason = body.reason || "";

      const fresh = await loadLog();
      const j = findIndex(fresh, key);
      if (j < 0) return { ok: res.ok, status: res.status, body, entry };

      const e = fresh[j];
      if (body.accepted === true || res.status === 201) {
        e.status = "accepted";
        e.serverReason = reason || "logged";
        e.lastError = "";
        e.logId = body.log_id != null ? body.log_id : e.logId;
        await markVideoLogged(e.videoId);
      } else if (reason === "duplicate") {
        e.status = "duplicate";
        e.serverReason = "duplicate";
        e.logId = body.log_id != null ? body.log_id : e.logId;
        e.lastError = "";
        await markVideoLogged(e.videoId);
      } else if (res.status === 401 || res.status === 403) {
        // Auth mistakes are fixable — keep payload, mark rejected with clear text, allow Retry
        e.status = "rejected";
        e.serverReason = "http_" + res.status;
        e.lastError = friendlyReason("", res.status);
      } else if (isPermanentReject(reason)) {
        e.status = "rejected";
        e.serverReason = reason;
        e.lastError = friendlyReason(reason, res.status);
      } else if (!res.ok) {
        e.status = "error";
        e.serverReason = reason || "http_" + res.status;
        e.lastError = friendlyReason(reason, res.status) || "HTTP " + res.status;
      } else {
        // 200 with accepted:false
        if (isPermanentReject(reason)) {
          e.status = "rejected";
          e.serverReason = reason;
          e.lastError = friendlyReason(reason, res.status);
        } else {
          e.status = "error";
          e.serverReason = reason || "not_accepted";
          e.lastError = friendlyReason(reason, res.status) || "not_accepted";
        }
      }
      e.updatedAt = nowIso();
      fresh[j] = e;
      await saveLog(fresh);

      const terminalOk = isTerminalOk(e.status);
      console.info("[immersion-tracker] deliver", e.videoId, e.status, e.serverReason);
      return {
        ok: terminalOk || res.ok,
        status: res.status,
        body,
        entry: e,
      };
    } catch (err) {
      const fresh = await loadLog();
      const j = findIndex(fresh, key);
      if (j >= 0) {
        fresh[j].status = "error";
        fresh[j].lastError = String(err);
        fresh[j].serverReason = "network_error";
        fresh[j].updatedAt = nowIso();
        await saveLog(fresh);
        return { ok: false, error: String(err), entry: fresh[j] };
      }
      return { ok: false, error: String(err) };
    }
  }

  function scheduleFlush(delayMs) {
    if (flushTimer) clearTimeout(flushTimer);
    flushTimer = setTimeout(() => {
      flushTimer = null;
      flushPending().catch((e) =>
        console.warn("[immersion-tracker] flush failed", e)
      );
    }, delayMs == null ? 300 : delayMs);
  }

  async function flushPending() {
    if (flushInFlight) {
      scheduleFlush(FLUSH_COOLDOWN_MS);
      return { skipped: true };
    }
    const now = Date.now();
    if (now - lastFlushAt < FLUSH_COOLDOWN_MS) {
      scheduleFlush(FLUSH_COOLDOWN_MS - (now - lastFlushAt));
      return { skipped: true };
    }
    flushInFlight = true;
    lastFlushAt = now;
    try {
      const entries = await loadLog();
      const todo = entries.filter(needsDelivery);
      const results = [];
      for (const e of todo) {
        // Soft backoff: wait 15s * min(attempts, 8) between tries
        if (e.lastAttemptAt) {
          const wait = 15_000 * Math.min(e.attempts || 1, 8);
          const elapsed = now - new Date(e.lastAttemptAt).getTime();
          if (Number.isFinite(elapsed) && elapsed < wait) continue;
        }
        results.push(await deliverEntry(e.key));
      }
      return { ok: true, attempted: results.length, results };
    } finally {
      flushInFlight = false;
    }
  }

  async function getLocalStatusForVideo(videoId) {
    const vid = String(videoId || "").trim();
    const entries = await loadLog();
    const idx = findByVideo(entries, vid);
    if (idx >= 0) return { ok: true, entry: entries[idx] };
    // Compact id set (ring buffer may have dropped the row)
    if (vid && (await isVideoEverLogged(vid))) {
      return {
        ok: true,
        entry: {
          key: entryKey(vid),
          videoId: vid,
          status: "duplicate",
          serverReason: "duplicate",
          maxRatio: 1,
        },
      };
    }
    return { ok: true, entry: null };
  }

  async function listLocalLog(opts) {
    const entries = await loadLog();
    const limit = (opts && opts.limit) || 40;
    const includeWatching = !!(opts && opts.includeWatching);
    let list = entries;
    if (!includeWatching) {
      // Hide early watches; keep ≥50% progress and anything queued/done
      list = entries.filter((e) => {
        if (!e) return false;
        if (e.status !== "watching") return true;
        return Number(e.maxRatio) >= 0.5;
      });
    }
    const pendingCount = entries.filter(needsDelivery).length;
    const errorCount = entries.filter((e) => e && e.status === "error").length;
    return {
      ok: true,
      entries: list.slice(0, limit),
      pendingCount,
      errorCount,
      total: entries.length,
    };
  }

  async function retryLocal(key) {
    const entries = await loadLog();
    const idx = findIndex(entries, key);
    if (idx < 0) return { ok: false, error: "not_found" };
    const e = entries[idx];
    if (!e.payload) return { ok: false, error: "no_payload", entry: e };
    // Reset attempt gate — also re-check stale duplicate/accepted against server
    e.attempts = 0;
    e.status = "pending";
    e.lastError = "";
    e.serverReason = "";
    e.lastAttemptAt = null;
    e.updatedAt = nowIso();
    entries[idx] = e;
    await saveLog(entries);
    return deliverEntry(key);
  }

  async function retryAllPending() {
    const entries = await loadLog();
    for (const e of entries) {
      if (!e || !e.payload) continue;
      const authReject =
        e.status === "rejected" &&
        (String(e.serverReason || "").includes("401") ||
          String(e.serverReason || "").includes("403") ||
          String(e.lastError || "").includes("webhook secret"));
      const recheckTerminal =
        e.status === "duplicate" || e.status === "accepted";
      if (
        e.status === "error" ||
        e.status === "pending" ||
        e.status === "ready" ||
        authReject ||
        recheckTerminal
      ) {
        e.attempts = 0;
        e.status = "pending";
        e.lastError = "";
        e.serverReason = "";
        e.lastAttemptAt = null;
      }
    }
    await saveLog(entries);
    return flushPending();
  }

  /** Drop a local terminal entry so the video can be queued fresh. */
  async function resetLocalVideo(videoId) {
    const vid = String(videoId || "").trim();
    if (!vid) return { ok: false, error: "no_video_id" };
    const entries = await loadLog();
    const next = entries.filter((e) => !(e && e.videoId === vid));
    await saveLog(next);
    // Also clear compact once-ever set so force-queue can re-attempt
    const map = await loadLoggedIds();
    if (map[vid]) {
      delete map[vid];
      await storageSet({ [LOGGED_IDS_KEY]: map });
    }
    return { ok: true, removed: entries.length - next.length };
  }

  async function clearLocalDone() {
    const entries = await loadLog();
    const kept = entries.filter(
      (e) => e && !isTerminalOk(e.status) && e.status !== "rejected"
    );
    await saveLog(kept);
    return { ok: true, remaining: kept.length };
  }

  async function dismissLocal(key) {
    const entries = await loadLog();
    const next = entries.filter((e) => e && e.key !== key);
    await saveLog(next);
    return { ok: true };
  }

  // --- Log from history (YouTube watch history scan + batch log) ---

  async function loadHistoryRejected() {
    const data = await storageGet({ [HISTORY_REJECTED_KEY]: {} });
    const raw = data[HISTORY_REJECTED_KEY];
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) return {};
    return raw;
  }

  async function markHistoryRejected(videoIds) {
    const map = await loadHistoryRejected();
    const now = nowIso();
    const ids = Array.isArray(videoIds) ? videoIds : [videoIds];
    for (const raw of ids) {
      const vid = String(raw || "").trim();
      if (vid) map[vid] = now;
    }
    const keys = Object.keys(map);
    if (keys.length > MAX_HISTORY_REJECTED) {
      // Drop oldest by timestamp
      const sorted = keys
        .map((k) => ({ k, t: map[k] || "" }))
        .sort((a, b) => String(a.t).localeCompare(String(b.t)));
      const drop = sorted.slice(0, keys.length - MAX_HISTORY_REJECTED);
      for (const d of drop) delete map[d.k];
    }
    await storageSet({ [HISTORY_REJECTED_KEY]: map });
    return { ok: true, count: ids.filter(Boolean).length };
  }

  async function unrejectHistory(videoIds) {
    const map = await loadHistoryRejected();
    const ids = Array.isArray(videoIds) ? videoIds : [videoIds];
    let n = 0;
    for (const raw of ids) {
      const vid = String(raw || "").trim();
      if (vid && map[vid]) {
        delete map[vid];
        n++;
      }
    }
    await storageSet({ [HISTORY_REJECTED_KEY]: map });
    return { ok: true, removed: n };
  }

  function extractBetween(html, re) {
    const m = String(html || "").match(re);
    return m ? m[1] : "";
  }

  function extractJsonAssignment(html, varName) {
    const marker = "var " + varName + " = ";
    let idx = html.indexOf(marker);
    if (idx < 0) {
      const alt = "window[\"" + varName + "\"] = ";
      idx = html.indexOf(alt);
      if (idx < 0) {
        const alt2 = varName + " = ";
        idx = html.indexOf(alt2);
        if (idx < 0) return null;
        idx = idx + alt2.length;
      } else {
        idx = idx + alt.length;
      }
    } else {
      idx = idx + marker.length;
    }
    // Walk balanced braces from first {
    const start = html.indexOf("{", idx);
    if (start < 0) return null;
    let depth = 0;
    let inStr = false;
    let quote = "";
    let esc = false;
    for (let i = start; i < html.length; i++) {
      const ch = html[i];
      if (inStr) {
        if (esc) {
          esc = false;
          continue;
        }
        if (ch === "\\") {
          esc = true;
          continue;
        }
        if (ch === quote) inStr = false;
        continue;
      }
      if (ch === '"' || ch === "'") {
        inStr = true;
        quote = ch;
        continue;
      }
      if (ch === "{") depth++;
      else if (ch === "}") {
        depth--;
        if (depth === 0) {
          try {
            return JSON.parse(html.slice(start, i + 1));
          } catch (_) {
            return null;
          }
        }
      }
    }
    return null;
  }

  function parseDurationText(text) {
    const s = String(text || "").trim();
    if (!s) return 0;
    // Relative times are not media length ("3 days ago", "1時間前", "5分前")
    if (
      (/\bago\b/i.test(s) || /前/.test(s) || /\d+\s*日前/.test(s)) &&
      !/\d+:\d{2}/.test(s)
    ) {
      return 0;
    }
    // "12:34" or "1:02:03" (allow surrounding punctuation)
    const hms = s.match(/(?:^|[^\d])(\d+):(\d{1,2}):(\d{2})(?:[^\d]|$)/);
    if (hms) {
      return (
        parseInt(hms[1], 10) * 3600 +
        parseInt(hms[2], 10) * 60 +
        parseInt(hms[3], 10)
      );
    }
    const ms = s.match(/(?:^|[^\d])(\d+):(\d{2})(?:[^\d]|$)/);
    if (ms) return parseInt(ms[1], 10) * 60 + parseInt(ms[2], 10);
    // Japanese media length: 1時間2分3秒 / 12分34秒 / 45秒
    const jHr = s.match(/(\d+)\s*時間/);
    const jMin = s.match(/(\d+)\s*分(?!前)/);
    const jSec = s.match(/(\d+)\s*秒/);
    if (jHr || jMin || jSec) {
      let jTotal =
        (jHr ? parseInt(jHr[1], 10) * 3600 : 0) +
        (jMin ? parseInt(jMin[1], 10) * 60 : 0) +
        (jSec ? parseInt(jSec[1], 10) : 0);
      if (jTotal > 0) return jTotal;
    }
    // accessibility: "1 hour, 2 minutes, 3 seconds" / "12 minutes, 34 seconds"
    let total = 0;
    let matched = false;
    const hr = s.match(/(\d+)\s*h(?:ou)?rs?/i);
    const min = s.match(/(\d+)\s*m(?:in(?:ute)?s?)?/i);
    const sec = s.match(/(\d+)\s*s(?:ec(?:ond)?s?)?/i);
    // Prefer explicit words over bare "m"/"s" to avoid false positives
    const hrW = s.match(/(\d+)\s*hours?/i);
    const minW = s.match(/(\d+)\s*min(?:ute)?s?/i);
    const secW = s.match(/(\d+)\s*sec(?:ond)?s?/i);
    if (hrW || minW || secW) {
      if (hrW) total += parseInt(hrW[1], 10) * 3600;
      if (minW) total += parseInt(minW[1], 10) * 60;
      if (secW) total += parseInt(secW[1], 10);
      matched = true;
    } else if (hr || (min && /min/i.test(s)) || (sec && /sec/i.test(s))) {
      if (hr) total += parseInt(hr[1], 10) * 3600;
      if (min && /min/i.test(s)) total += parseInt(min[1], 10) * 60;
      if (sec && /sec/i.test(s)) total += parseInt(sec[1], 10);
      matched = true;
    }
    if (matched && total > 0) return total;
    // ISO-ish PT#H#M#S
    const iso = s.match(/PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?/i);
    if (iso && (iso[1] || iso[2] || iso[3])) {
      return (
        (parseInt(iso[1] || "0", 10) || 0) * 3600 +
        (parseInt(iso[2] || "0", 10) || 0) * 60 +
        (parseInt(iso[3] || "0", 10) || 0)
      );
    }
    return 0;
  }

  /**
   * Watch progress from history thumbnails (resume bar / percentDurationWatched).
   * Returns 0–100 or null when YouTube did not expose progress.
   */
  function extractWatchProgress(obj, depth) {
    if (!obj || typeof obj !== "object" || depth > 8) return null;
    if (typeof obj.percentDurationWatched === "number") {
      return Math.min(100, Math.max(0, obj.percentDurationWatched));
    }
    if (obj.thumbnailOverlayResumePlaybackRenderer) {
      const p = obj.thumbnailOverlayResumePlaybackRenderer.percentDurationWatched;
      if (typeof p === "number") return Math.min(100, Math.max(0, p));
    }
    if (obj.progressBar && typeof obj.progressBar === "object") {
      const end =
        obj.progressBar.endPercent != null
          ? obj.progressBar.endPercent
          : obj.progressBar.percent != null
            ? obj.progressBar.percent
            : obj.progressBar.watchedPercent;
      if (typeof end === "number") return Math.min(100, Math.max(0, end));
    }
    if (typeof obj.endPercent === "number" && obj.endPercent >= 0) {
      return Math.min(100, Math.max(0, obj.endPercent));
    }
    if (Array.isArray(obj)) {
      let best = null;
      for (const item of obj) {
        const p = extractWatchProgress(item, depth + 1);
        if (p != null && (best == null || p > best)) best = p;
      }
      return best;
    }
    let best = null;
    for (const k of Object.keys(obj)) {
      if (
        /overlay|progress|resume|playback|bottomPanel|contentImage|thumbnailViewModel|badge/i.test(
          k
        )
      ) {
        const p = extractWatchProgress(obj[k], depth + 1);
        if (p != null && (best == null || p > best)) best = p;
      }
    }
    return best;
  }

  function hasJapaneseScript(text) {
    return /[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]/.test(String(text || ""));
  }

  function thumbnailFromRenderer(vr, videoId) {
    try {
      const thumbs =
        (vr && vr.thumbnail && vr.thumbnail.thumbnails) ||
        (vr &&
          vr.richThumbnail &&
          vr.richThumbnail.movingThumbnailRenderer &&
          vr.richThumbnail.movingThumbnailRenderer.movingThumbnailDetails &&
          vr.richThumbnail.movingThumbnailRenderer.movingThumbnailDetails.thumbnails) ||
        [];
      if (Array.isArray(thumbs) && thumbs.length) {
        // Mid quality if available
        const mid = thumbs[Math.min(thumbs.length - 1, Math.floor(thumbs.length / 2))];
        const url = (mid && mid.url) || (thumbs[0] && thumbs[0].url) || "";
        if (url) return url;
      }
    } catch (_) {}
    return videoId ? "https://i.ytimg.com/vi/" + videoId + "/hqdefault.jpg" : "";
  }

  function durationFromOverlays(overlays) {
    if (!Array.isArray(overlays)) return { text: "", seconds: 0 };
    for (const o of overlays) {
      const r = o && o.thumbnailOverlayTimeStatusRenderer;
      if (!r) continue;
      const text = runsText(r.text);
      const sec = parseDurationText(text);
      if (sec > 0 || text) return { text: text || "", seconds: sec };
    }
    return { text: "", seconds: 0 };
  }

  function digDurationInObject(obj, depth) {
    if (!obj || typeof obj !== "object" || depth > 6) return 0;
    if (typeof obj === "string") return parseDurationText(obj);
    if (Array.isArray(obj)) {
      for (const item of obj) {
        const s = digDurationInObject(item, depth + 1);
        if (s > 0) return s;
      }
      return 0;
    }
    // Common badge / badge text shapes
    for (const k of [
      "lengthText",
      "durationText",
      "thumbnailOverlayTimeStatusRenderer",
      "badgeText",
      "accessibilityText",
      "label",
    ]) {
      if (obj[k] != null) {
        const t = runsText(obj[k]) || (typeof obj[k] === "string" ? obj[k] : "");
        const s = parseDurationText(t);
        if (s > 0) return s;
        if (obj[k] && typeof obj[k] === "object") {
          const nested = digDurationInObject(obj[k], depth + 1);
          if (nested > 0) return nested;
        }
      }
    }
    if (obj.text != null) {
      const s = parseDurationText(runsText(obj) || String(obj.text));
      if (s > 0) return s;
    }
    return 0;
  }

  function runsText(node) {
    if (!node) return "";
    if (typeof node === "string") return node;
    if (node.simpleText) return String(node.simpleText);
    if (Array.isArray(node.runs)) {
      return node.runs.map((r) => (r && r.text) || "").join("");
    }
    if (node.text && typeof node.text === "string") return node.text;
    if (node.content && typeof node.content === "string") return node.content;
    return "";
  }

  function walkCollect(obj, out, sectionDate) {
    if (!obj || typeof obj !== "object") return;
    if (Array.isArray(obj)) {
      for (const item of obj) walkCollect(item, out, sectionDate);
      return;
    }

    // Date section headers in history feed
    let nextSection = sectionDate;
    if (obj.itemSectionHeaderRenderer) {
      const t = runsText(obj.itemSectionHeaderRenderer.title).trim();
      if (t) nextSection = t;
    }
    if (obj.shelfRenderer && obj.shelfRenderer.title) {
      const t = runsText(obj.shelfRenderer.title).trim();
      if (t && /today|yesterday|watched|月|日|週/i.test(t)) nextSection = t;
    }

    const vr = obj.videoRenderer || obj.compactVideoRenderer || obj.gridVideoRenderer;
    if (vr && vr.videoId) {
      const videoId = String(vr.videoId).trim();
      if (/^[\w-]{11}$/.test(videoId)) {
        const title = runsText(vr.title) || videoId;
        let channelId = "";
        let channelTitle = "";
        try {
          const owner =
            (vr.ownerText && vr.ownerText.runs && vr.ownerText.runs[0]) ||
            (vr.shortBylineText && vr.shortBylineText.runs && vr.shortBylineText.runs[0]) ||
            null;
          if (owner) {
            channelTitle = owner.text || "";
            const ep =
              owner.navigationEndpoint ||
              (vr.ownerText &&
                vr.ownerText.runs &&
                vr.ownerText.runs[0] &&
                vr.ownerText.runs[0].navigationEndpoint);
            const browse =
              (ep && ep.browseEndpoint && ep.browseEndpoint.browseId) ||
              (vr.ownerEndpoint &&
                vr.ownerEndpoint.browseEndpoint &&
                vr.ownerEndpoint.browseEndpoint.browseId) ||
              "";
            if (typeof browse === "string" && browse.startsWith("UC")) channelId = browse;
            const url =
              (ep &&
                ep.commandMetadata &&
                ep.commandMetadata.webCommandMetadata &&
                ep.commandMetadata.webCommandMetadata.url) ||
              "";
            if (!channelId && url) {
              const m = String(url).match(/\/channel\/(UC[\w-]{22})/);
              if (m) channelId = m[1];
            }
          }
        } catch (_) {}

        const overlayDur = durationFromOverlays(vr.thumbnailOverlays);
        const len =
          (vr.lengthText && runsText(vr.lengthText)) ||
          overlayDur.text ||
          "";
        let durationSeconds =
          parseDurationText(len) ||
          overlayDur.seconds ||
          digDurationInObject(vr.lengthText, 0) ||
          0;
        // accessibility label often "12 minutes, 34 seconds"
        if (!durationSeconds && vr.lengthText && vr.lengthText.accessibility) {
          durationSeconds = parseDurationText(
            runsText(vr.lengthText.accessibility.accessibilityData) ||
              (vr.lengthText.accessibility.accessibilityData &&
                vr.lengthText.accessibility.accessibilityData.label) ||
              ""
          );
        }
        if (!durationSeconds && vr.title && vr.title.accessibility) {
          const acc =
            (vr.title.accessibility.accessibilityData &&
              vr.title.accessibility.accessibilityData.label) ||
            "";
          // "... 12 minutes, 34 seconds ..."
          durationSeconds = parseDurationText(acc);
        }

        const percentWatched = extractWatchProgress(vr, 0);

        const isShort =
          !!(vr.navigationEndpoint && vr.navigationEndpoint.reelWatchEndpoint) ||
          /short/i.test(len) ||
          (durationSeconds > 0 &&
            durationSeconds <= 60 &&
            /shorts/i.test(JSON.stringify(vr.navigationEndpoint || {})));

        const isLive =
          (vr.badges || []).some((b) =>
            /live/i.test(
              runsText(
                (b && b.metadataBadgeRenderer && b.metadataBadgeRenderer.label) || ""
              )
            )
          ) ||
          (vr.thumbnailOverlays || []).some((o) => {
            const style =
              o &&
              o.thumbnailOverlayTimeStatusRenderer &&
              o.thumbnailOverlayTimeStatusRenderer.style;
            return style === "LIVE";
          });

        out.push({
          videoId,
          title: title.trim(),
          channelId,
          channelTitle: (channelTitle || "").trim(),
          durationSeconds,
          durationText: len || "",
          percentWatched: percentWatched,
          thumbnail: thumbnailFromRenderer(vr, videoId),
          sectionLabel: nextSection || sectionDate || "",
          isShort: !!isShort,
          isLive: !!isLive,
          url: "https://www.youtube.com/watch?v=" + videoId,
        });
      }
    }

    // Newer lockup / rich item shapes (history feed often uses these)
    if (obj.lockupViewModel) {
      try {
        const lvm = obj.lockupViewModel;
        const contentId = lvm.contentId || "";
        if (/^[\w-]{11}$/.test(contentId)) {
          const meta =
            (lvm.metadata && lvm.metadata.lockupMetadataViewModel) ||
            lvm.metadata ||
            {};
          let title =
            runsText(meta.title) ||
            runsText(lvm.metadata && lvm.metadata.title) ||
            contentId;
          if (!title || title === contentId) {
            try {
              const rows =
                meta.contentMetadata &&
                meta.contentMetadata.metadataRows;
              // title often separate; keep contentId fallback
            } catch (_) {}
          }
          let channelTitle = "";
          let channelId = "";
          try {
            const rows =
              (meta.contentMetadata && meta.contentMetadata.metadataRows) ||
              (meta.metadata && meta.metadata.metadataRows) ||
              [];
            if (Array.isArray(rows) && rows[0]) {
              const parts =
                rows[0].metadataParts ||
                rows[0].metadataPartGroups ||
                [];
              const first = Array.isArray(parts) ? parts[0] : null;
              const textSrc =
                (first && first.text) ||
                (first && first.avatarViewModel) ||
                first;
              channelTitle = runsText(textSrc) || "";
            }
          } catch (_) {}

          // Duration badges on lockup image overlays (several YT layout variants)
          let durationSeconds = 0;
          let durationText = "";
          try {
            const img = lvm.contentImage || lvm.image || {};
            const primary =
              (img.collectionThumbnailViewModel &&
                img.collectionThumbnailViewModel.primaryThumbnail) ||
              img;
            const tvm =
              (primary && primary.thumbnailViewModel) ||
              (img && img.thumbnailViewModel) ||
              primary ||
              {};
            const overlays =
              tvm.overlays ||
              (img.thumbnailViewModel && img.thumbnailViewModel.overlays) ||
              img.overlays ||
              [];
            for (const ov of overlays) {
              if (!ov || typeof ov !== "object") continue;
              // Classic time status
              if (ov.thumbnailOverlayTimeStatusRenderer) {
                const t = runsText(ov.thumbnailOverlayTimeStatusRenderer.text);
                const sec = parseDurationText(t);
                if (sec > 0) {
                  durationSeconds = sec;
                  durationText = t;
                  break;
                }
              }
              const badge =
                ov.thumbnailOverlayBadgeViewModel ||
                ov.thumbnailBadgesViewModel ||
                ov.thumbnailBadgeViewModel ||
                null;
              if (!badge) continue;
              const badges =
                badge.thumbnailBadges ||
                badge.badges ||
                (badge.thumbnailBadgeViewModel ? [badge] : [badge]);
              for (const b of Array.isArray(badges) ? badges : [badges]) {
                const tvmBadge =
                  (b && b.thumbnailBadgeViewModel) ||
                  (b && b.badgeViewModel) ||
                  b;
                const t =
                  runsText(
                    tvmBadge &&
                      (tvmBadge.text || tvmBadge.badgeText || tvmBadge.label)
                  ) ||
                  (typeof (tvmBadge && tvmBadge.text) === "string"
                    ? tvmBadge.text
                    : "") ||
                  "";
                const sec = parseDurationText(t) || digDurationInObject(b, 0);
                if (sec > 0) {
                  durationSeconds = sec;
                  durationText = t;
                  break;
                }
              }
              if (durationSeconds) break;
            }
            if (!durationSeconds) {
              // Only dig image/badge subtrees — never whole lockup (avoids "1 minute ago")
              durationSeconds =
                digDurationInObject(img, 0) || digDurationInObject(tvm, 0);
            }
          } catch (_) {}

          const percentWatched = extractWatchProgress(lvm, 0);

          let thumbnail = "";
          try {
            const sources =
              (lvm.contentImage &&
                lvm.contentImage.thumbnailViewModel &&
                lvm.contentImage.thumbnailViewModel.image &&
                lvm.contentImage.thumbnailViewModel.image.sources) ||
              (lvm.contentImage &&
                lvm.contentImage.collectionThumbnailViewModel &&
                lvm.contentImage.collectionThumbnailViewModel.primaryThumbnail &&
                lvm.contentImage.collectionThumbnailViewModel.primaryThumbnail
                  .thumbnailViewModel &&
                lvm.contentImage.collectionThumbnailViewModel.primaryThumbnail
                  .thumbnailViewModel.image &&
                lvm.contentImage.collectionThumbnailViewModel.primaryThumbnail
                  .thumbnailViewModel.image.sources) ||
              (lvm.contentImage && lvm.contentImage.sources) ||
              [];
            if (Array.isArray(sources) && sources[0] && sources[0].url) {
              thumbnail = sources[0].url;
            }
          } catch (_) {}
          if (!thumbnail) {
            thumbnail = "https://i.ytimg.com/vi/" + contentId + "/hqdefault.jpg";
          }

          const isShort =
            durationSeconds > 0 &&
            durationSeconds <= 60 &&
            /short/i.test(JSON.stringify(lvm).slice(0, 2000));

          out.push({
            videoId: contentId,
            title: String(title || contentId).trim(),
            channelId,
            channelTitle: (channelTitle || "").trim(),
            durationSeconds,
            durationText,
            percentWatched: percentWatched,
            thumbnail,
            sectionLabel: nextSection || sectionDate || "",
            isShort: !!isShort,
            isLive: false,
            url: "https://www.youtube.com/watch?v=" + contentId,
          });
        }
      } catch (_) {}
    }

    for (const k of Object.keys(obj)) {
      if (k === "videoRenderer" || k === "compactVideoRenderer" || k === "gridVideoRenderer") {
        continue;
      }
      walkCollect(obj[k], out, nextSection);
    }
  }

  function findContinuationToken(obj, found) {
    if (!obj || typeof obj !== "object" || found.token) return;
    if (Array.isArray(obj)) {
      for (const item of obj) findContinuationToken(item, found);
      return;
    }
    if (obj.continuationItemRenderer) {
      try {
        const c =
          obj.continuationItemRenderer.continuationEndpoint &&
          obj.continuationItemRenderer.continuationEndpoint.continuationCommand &&
          obj.continuationItemRenderer.continuationEndpoint.continuationCommand.token;
        if (c) found.token = c;
      } catch (_) {}
      try {
        const c2 =
          obj.continuationItemRenderer.continuationEndpoint &&
          obj.continuationItemRenderer.continuationEndpoint.command &&
          obj.continuationItemRenderer.continuationEndpoint.command.token;
        if (c2) found.token = c2;
      } catch (_) {}
    }
    if (obj.continuationCommand && obj.continuationCommand.token) {
      found.token = obj.continuationCommand.token;
    }
    for (const k of Object.keys(obj)) {
      if (found.token) return;
      findContinuationToken(obj[k], found);
    }
  }

  /**
   * Map YouTube history section labels to approximate timestamps.
   * Returns ms epoch, or null if unparseable (kept with unknown date).
   */
  function sectionLabelToMs(label, nowMs) {
    const raw = String(label || "").trim();
    if (!raw) return null;
    const lower = raw.toLowerCase();
    const startOfDay = (d) => {
      const x = new Date(d);
      x.setHours(0, 0, 0, 0);
      return x.getTime();
    };
    const now = nowMs || Date.now();

    if (/^today$|^今日$|^本日$/i.test(raw) || lower === "today") {
      return startOfDay(now);
    }
    if (/^yesterday$|^昨日$/i.test(raw) || lower === "yesterday") {
      return startOfDay(now - 86400000);
    }

    // "Monday" / "Mon", "Tuesday" / "Tue", ... (last occurrence)
    const days = [
      "sunday",
      "monday",
      "tuesday",
      "wednesday",
      "thursday",
      "friday",
      "saturday",
    ];
    const dayShort = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"];
    let di = days.indexOf(lower);
    if (di < 0) di = dayShort.indexOf(lower.slice(0, 3));
    if (di >= 0) {
      const d = new Date(now);
      const cur = d.getDay();
      let diff = (cur - di + 7) % 7;
      if (diff === 0) diff = 7; // previous week if same weekday
      return startOfDay(now - diff * 86400000);
    }

    // Absolute-ish dates: "Mar 15", "March 15, 2026", "15 Mar 2026", "2026/03/15"
    const parsed = Date.parse(raw);
    if (!Number.isNaN(parsed)) return startOfDay(parsed);

    // Japanese: 3月15日 / 2026年3月15日
    const jm = raw.match(/(?:(\d{4})\s*年\s*)?(\d{1,2})\s*月\s*(\d{1,2})\s*日/);
    if (jm) {
      const y = jm[1] ? parseInt(jm[1], 10) : new Date(now).getFullYear();
      const mo = parseInt(jm[2], 10) - 1;
      const day = parseInt(jm[3], 10);
      const d = new Date(y, mo, day);
      if (!Number.isNaN(d.getTime())) {
        // If date is in the future (no year, month not yet this year), assume previous year
        if (!jm[1] && d.getTime() > now + 86400000) {
          d.setFullYear(d.getFullYear() - 1);
        }
        return startOfDay(d.getTime());
      }
    }

    return null;
  }

  function dedupeVideos(list) {
    const seen = new Set();
    const out = [];
    for (const v of list) {
      if (!v || !v.videoId || seen.has(v.videoId)) continue;
      seen.add(v.videoId);
      out.push(v);
    }
    return out;
  }

  async function fetchHistoryHtml() {
    const r = await fetch("https://www.youtube.com/feed/history", {
      credentials: "include",
      headers: {
        Accept: "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
      },
      cache: "no-store",
    });
    if (!r.ok) {
      throw new Error("history_http_" + r.status);
    }
    const html = await r.text();
    return html;
  }

  async function browseHistoryContinuation(apiKey, client, token) {
    const url =
      "https://www.youtube.com/youtubei/v1/browse?key=" +
      encodeURIComponent(apiKey) +
      "&prettyPrint=false";
    const body = {
      context: {
        client: {
          clientName: (client && client.clientName) || "WEB",
          clientVersion: (client && client.clientVersion) || "2.20240101.00.00",
          hl: (client && client.hl) || "en",
          gl: (client && client.gl) || "US",
        },
      },
      continuation: token,
    };
    const r = await fetch(url, {
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        "X-YouTube-Client-Name": "1",
        "X-YouTube-Client-Version": body.context.client.clientVersion,
      },
      body: JSON.stringify(body),
      cache: "no-store",
    });
    if (!r.ok) throw new Error("innertube_http_" + r.status);
    return r.json();
  }

  function detailsFromPlayerJson(j) {
    if (!j || typeof j !== "object") return null;
    const details = j.videoDetails || {};
    const micro =
      (j.microformat && j.microformat.playerMicroformatRenderer) || {};
    const length =
      parseInt(details.lengthSeconds, 10) ||
      parseInt(micro.lengthSeconds, 10) ||
      0;
    let language = "";
    try {
      const tracks =
        (j.captions &&
          j.captions.playerCaptionsTracklistRenderer &&
          j.captions.playerCaptionsTracklistRenderer.captionTracks) ||
        [];
      for (const t of tracks) {
        const code = String((t && t.languageCode) || "").toLowerCase();
        if (code.startsWith("ja")) {
          language = "ja";
          break;
        }
        if (!language && code) language = code.split("-")[0];
      }
    } catch (_) {}
    if (!language && hasJapaneseScript(details.title || "")) language = "ja";
    if (!(length > 0) && !details.title && !details.channelId) return null;
    return {
      durationSeconds: length > 0 ? length : 0,
      title: details.title || "",
      channelId: details.channelId || "",
      channelTitle: details.author || "",
      isLive: !!(details.isLive || details.isLiveContent),
      language,
    };
  }

  /**
   * Resolve true media length via Innertube player (fixes missing history durations
   * that previously fell back to a fake 60s → 1 minute logs).
   */
  async function fetchPlayerDetails(videoId, apiKey, client) {
    const id = String(videoId || "").trim();
    if (!id || !apiKey) return null;
    const url =
      "https://www.youtube.com/youtubei/v1/player?key=" +
      encodeURIComponent(apiKey) +
      "&prettyPrint=false";
    const clientVersion =
      (client && client.clientVersion) || "2.20240101.00.00";
    const body = {
      context: {
        client: {
          clientName: (client && client.clientName) || "WEB",
          clientVersion,
          hl: (client && client.hl) || "en",
          gl: (client && client.gl) || "US",
        },
      },
      videoId: id,
      contentCheckOk: true,
      racyCheckOk: true,
    };
    try {
      const r = await fetch(url, {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          "X-YouTube-Client-Name": "1",
          "X-YouTube-Client-Version": clientVersion,
          Origin: "https://www.youtube.com",
          Referer: "https://www.youtube.com/",
        },
        body: JSON.stringify(body),
        cache: "no-store",
      });
      if (!r.ok) return null;
      const j = await r.json();
      return detailsFromPlayerJson(j);
    } catch (_) {
      return null;
    }
  }

  /**
   * Fallback when Innertube player omits lengthSeconds: scrape watch page
   * ytInitialPlayerResponse / lengthSeconds (uses signed-in cookies).
   */
  async function fetchDurationFromWatchPage(videoId) {
    const id = String(videoId || "").trim();
    if (!id) return null;
    try {
      const r = await fetch(
        "https://www.youtube.com/watch?v=" + encodeURIComponent(id) + "&bpctr=9999999999&has_verified=1",
        {
          credentials: "include",
          headers: {
            Accept: "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9,ja;q=0.8",
          },
          cache: "no-store",
        }
      );
      if (!r.ok) return null;
      const html = await r.text();
      const player = extractJsonAssignment(html, "ytInitialPlayerResponse");
      const fromPlayer = detailsFromPlayerJson(player);
      if (fromPlayer && fromPlayer.durationSeconds > 0) return fromPlayer;

      let length = 0;
      const ls = html.match(/"lengthSeconds":\s*"(\d+)"/);
      if (ls) length = parseInt(ls[1], 10) || 0;
      if (!(length > 0)) {
        const ms = html.match(/"approxDurationMs":\s*"(\d+)"/);
        if (ms) length = Math.round(parseInt(ms[1], 10) / 1000) || 0;
      }
      if (!(length > 0)) return fromPlayer;

      let title = (fromPlayer && fromPlayer.title) || "";
      let channelId = (fromPlayer && fromPlayer.channelId) || "";
      let channelTitle = (fromPlayer && fromPlayer.channelTitle) || "";
      if (!title) {
        const tm = html.match(/"title":\s*"((?:\\.|[^"\\])*)"/);
        if (tm) {
          try {
            title = JSON.parse('"' + tm[1] + '"');
          } catch (_) {
            title = tm[1];
          }
        }
      }
      if (!channelId) {
        const cm = html.match(/"channelId":\s*"(UC[\w-]{22})"/);
        if (cm) channelId = cm[1];
      }
      if (!channelTitle) {
        const am = html.match(/"ownerChannelName":\s*"((?:\\.|[^"\\])*)"/);
        if (am) {
          try {
            channelTitle = JSON.parse('"' + am[1] + '"');
          } catch (_) {
            channelTitle = am[1];
          }
        }
      }
      let language = (fromPlayer && fromPlayer.language) || "";
      if (!language && hasJapaneseScript(title)) language = "ja";
      return {
        durationSeconds: length,
        title: title || "",
        channelId: channelId || "",
        channelTitle: channelTitle || "",
        isLive: !!(fromPlayer && fromPlayer.isLive),
        language,
      };
    } catch (_) {
      return null;
    }
  }

  function normalizeLangCode(code) {
    if (!code) return "";
    let c = String(code).trim().toLowerCase().replace(/_/g, "-");
    if (c === "jp") c = "ja";
    return c.split("-")[0] || "";
  }

  async function loadVideoMetaCache() {
    try {
      const data = await storageGet({ [VIDEO_META_CACHE_KEY]: {} });
      const raw = data[VIDEO_META_CACHE_KEY] || {};
      const now = Date.now();
      const out = {};
      for (const id of Object.keys(raw)) {
        const e = raw[id];
        if (!e || typeof e !== "object") continue;
        if (e.at && now - Number(e.at) > VIDEO_META_CACHE_TTL_MS) continue;
        out[id] = e;
      }
      return out;
    } catch (_) {
      return {};
    }
  }

  async function saveVideoMetaCache(cache) {
    try {
      const keys = Object.keys(cache || {});
      if (keys.length > VIDEO_META_CACHE_MAX) {
        keys
          .sort((a, b) => (Number(cache[a].at) || 0) - (Number(cache[b].at) || 0))
          .slice(0, keys.length - VIDEO_META_CACHE_MAX)
          .forEach((k) => delete cache[k]);
      }
      await storageSet({ [VIDEO_META_CACHE_KEY]: cache });
    } catch (_) {}
  }

  function applyMetaCacheToVideo(v, cache) {
    if (!v || !v.videoId || !cache) return false;
    const e = cache[v.videoId];
    if (!e) return false;
    let used = false;
    if (!(Number(v.durationSeconds) > 0) && Number(e.durationSeconds) > 0) {
      v.durationSeconds = Number(e.durationSeconds);
      v.durationEnriched = true;
      used = true;
    }
    if (!normalizeLangCode(v.language) && e.language) {
      v.language = normalizeLangCode(e.language);
      used = true;
    }
    if (e.title && (!v.title || v.title === v.videoId)) v.title = e.title;
    if (e.channelId && !v.channelId) v.channelId = e.channelId;
    if (e.channelTitle && !v.channelTitle) v.channelTitle = e.channelTitle;
    return used;
  }

  function writeMetaCacheEntry(cache, videoId, d) {
    if (!cache || !videoId || !d) return;
    const prev = cache[videoId] || {};
    cache[videoId] = {
      durationSeconds:
        Number(d.durationSeconds) > 0
          ? Number(d.durationSeconds)
          : Number(prev.durationSeconds) || 0,
      language: normalizeLangCode(d.language) || prev.language || "",
      title: d.title || prev.title || "",
      channelId: d.channelId || prev.channelId || "",
      channelTitle: d.channelTitle || prev.channelTitle || "",
      at: Date.now(),
    };
  }

  /**
   * @param {{ allowWatchPage?: boolean }} opts
   */
  async function resolveVideoDetails(videoId, apiKey, client, opts) {
    const allowWatchPage = !opts || opts.allowWatchPage !== false;
    let d = null;
    if (apiKey) {
      d = await fetchPlayerDetails(videoId, apiKey, client);
      // Player with duration is enough; language may still be empty
      if (d && d.durationSeconds > 0) return d;
    }
    if (!allowWatchPage) return d;
    const page = await fetchDurationFromWatchPage(videoId);
    if (page && page.durationSeconds > 0) {
      if (d) {
        return {
          durationSeconds: page.durationSeconds,
          title: page.title || d.title || "",
          channelId: page.channelId || d.channelId || "",
          channelTitle: page.channelTitle || d.channelTitle || "",
          isLive: !!(page.isLive || d.isLive),
          language: page.language || d.language || "",
        };
      }
      return page;
    }
    return d || page;
  }

  function videoNeedsEnrich(v, preferJa) {
    if (!v || !v.videoId) return false;
    if (!(Number(v.durationSeconds) > 0)) return true;
    if (!preferJa) return false;
    const lang = normalizeLangCode(v.language);
    if (lang === "ja" || lang === "en" || (lang && lang !== "ja")) return false;
    // JP title is enough evidence for history filter — skip slow caption lookup
    if (hasJapaneseScript(v.title)) return false;
    // Latin-only title + prefer JA: need player captions to detect JA content
    return true;
  }

  function applyDetailsToVideo(v, d) {
    if (!v || !d) return { filled: false, language: false };
    let filled = false;
    let language = false;
    if (d.durationSeconds > 0 && !(Number(v.durationSeconds) > 0)) {
      v.durationSeconds = d.durationSeconds;
      v.durationText = v.durationText || "";
      v.durationEnriched = true;
      filled = true;
    }
    if (d.title && (!v.title || v.title === v.videoId)) v.title = d.title;
    if (d.channelId && !v.channelId) v.channelId = d.channelId;
    if (d.channelTitle && !v.channelTitle) v.channelTitle = d.channelTitle;
    if (d.language) {
      const next = normalizeLangCode(d.language);
      if (next) {
        v.language = next;
        language = true;
      }
    }
    if (d.isLive) v.isLive = true;
    if (!v.thumbnail) {
      v.thumbnail = "https://i.ytimg.com/vi/" + v.videoId + "/hqdefault.jpg";
    }
    return { filled, language };
  }

  /**
   * Fast enrich: local meta cache → Innertube player (parallel) → optional watch-page
   * only for still-missing duration. Skips caption fetch when title already has JA.
   */
  async function enrichVideosMissingDuration(videos, apiKey, client, maxFetch, opts) {
    const preferJa = !opts || opts.preferJapanese !== false;
    const playerLimit = Math.max(0, Math.min(80, Number(maxFetch) || 40));
    const watchPageLimit = Math.max(
      0,
      Math.min(20, Number(opts && opts.watchPageLimit) || 12)
    );
    const cache = await loadVideoMetaCache();
    let cacheHits = 0;
    for (const v of videos) {
      if (applyMetaCacheToVideo(v, cache)) cacheHits++;
    }

    const need = videos.filter((v) => videoNeedsEnrich(v, preferJa));
    let attempted = 0;
    let filled = 0;
    let languages = 0;
    let watchPages = 0;

    async function runPool(list, limit, concurrency, allowWatchPage) {
      let i = 0;
      let n = 0;
      async function worker() {
        while (i < list.length && n < limit) {
          const idx = i++;
          const v = list[idx];
          if (!v) continue;
          n++;
          attempted++;
          const d = await resolveVideoDetails(v.videoId, apiKey, client, {
            allowWatchPage,
          });
          if (allowWatchPage) watchPages++;
          if (!d) continue;
          const r = applyDetailsToVideo(v, d);
          if (r.filled) filled++;
          if (r.language) languages++;
          writeMetaCacheEntry(cache, v.videoId, {
            durationSeconds: v.durationSeconds,
            language: v.language,
            title: v.title,
            channelId: v.channelId,
            channelTitle: v.channelTitle,
          });
        }
      }
      if (!list.length || limit <= 0) return;
      const workers = [];
      const c = Math.max(1, Math.min(concurrency, list.length));
      for (let w = 0; w < c; w++) workers.push(worker());
      await Promise.all(workers);
    }

    // Phase 1: player only (fast JSON), high concurrency
    if (need.length) {
      await runPool(need, playerLimit, 6, false);
    }

    // Phase 2: watch-page only where duration still missing (expensive HTML)
    const stillNeedDuration = videos.filter(
      (v) => v && v.videoId && !(Number(v.durationSeconds) > 0)
    );
    if (stillNeedDuration.length && watchPageLimit > 0) {
      await runPool(stillNeedDuration, watchPageLimit, 3, true);
    }

    await saveVideoMetaCache(cache);

    return {
      fetched: attempted,
      filled,
      languages,
      cacheHits,
      watchPages,
      remaining: videos.filter((v) => v && !(Number(v.durationSeconds) > 0)).length,
    };
  }

  function looksLoggedOut(html, initialData) {
    const h = String(html || "");
    if (/feed\/history/.test(h) && /Sign in to see your history|履歴を表示するにはログイン/i.test(h)) {
      // still might have partial data
    }
    if (initialData && typeof initialData === "object") {
      const alerts = JSON.stringify(initialData).slice(0, 5000);
      if (/Sign in to see your history|ログインして履歴/i.test(alerts) && !/"videoId"/.test(JSON.stringify(initialData).slice(0, 2000))) {
        return true;
      }
    }
    // No ytInitialData and consent/sign-in wall
    if (!initialData && /ServiceLogin|accounts\.google\.com\/ServiceLogin/i.test(h)) {
      return true;
    }
    return false;
  }

  function parseLinesToTokens(text) {
    return String(text || "")
      .split(/[\n,]+/)
      .map((s) => s.trim())
      .filter(Boolean);
  }

  function normAccountToken(value) {
    let v = String(value || "").trim();
    if (!v) return "";
    try {
      if (/%[0-9A-Fa-f]{2}/.test(v)) v = decodeURIComponent(v);
    } catch (_) {}
    if (v.startsWith("UC") && v.length >= 22) return v;
    const fold = (s) =>
      s
        .split("")
        .map((ch) => ("A" <= ch && ch <= "Z" ? ch.toLowerCase() : ch))
        .join("");
    if (v.startsWith("@")) return "@" + fold(v.slice(1));
    if (v.indexOf("/") < 0 && v.indexOf(" ") < 0) return "@" + fold(v);
    return v;
  }

  function accountTokenSet() {
    const parts = Array.prototype.slice.call(arguments);
    const out = new Set();
    for (const p of parts) {
      const t = normAccountToken(p);
      if (!t) continue;
      out.add(t);
      if (t.startsWith("@")) out.add(t.slice(1));
    }
    return out;
  }

  function viewerAllowedLocal(cfg, viewerChannelId, viewerHandle) {
    const allowed = parseLinesToTokens(cfg && cfg.allowedViewers);
    if (!allowed.length) return { ok: true, reason: "ok" };
    const present = accountTokenSet(viewerChannelId, viewerHandle);
    if (!present.size) return { ok: false, reason: "viewer_unknown" };
    const allowSet = new Set();
    for (const a of allowed) {
      const t = normAccountToken(a);
      if (!t) continue;
      allowSet.add(t);
      if (t.startsWith("@")) allowSet.add(t.slice(1));
    }
    for (const p of present) {
      if (allowSet.has(p)) return { ok: true, reason: "ok" };
    }
    return { ok: false, reason: "viewer_not_allowlisted" };
  }

  function channelFilterReason(cfg, channelId, channelTitle) {
    const mode = (cfg && cfg.channelMode) || "all";
    const block = parseLinesToTokens(cfg && cfg.channelBlocklist).map(normAccountToken);
    const allow = parseLinesToTokens(cfg && cfg.channelAllowlist).map(normAccountToken);
    const present = accountTokenSet(channelId, channelTitle && channelTitle.startsWith("@") ? channelTitle : "");
    // Also match bare channel title as weak handle
    if (channelTitle && channelTitle.startsWith("@")) {
      present.add(normAccountToken(channelTitle));
    }
    for (const b of block) {
      if (!b) continue;
      if (present.has(b) || (channelId && b === channelId)) {
        return "channel_blocked";
      }
    }
    if (mode === "allowlist") {
      if (!allow.length) return "channel_allowlist_empty";
      const allowSet = new Set(allow);
      for (const a of allow) {
        if (a.startsWith("@")) allowSet.add(a.slice(1));
      }
      let hit = false;
      for (const p of present) {
        if (allowSet.has(p)) {
          hit = true;
          break;
        }
      }
      if (!hit && channelId && allowSet.has(channelId)) hit = true;
      if (!hit) return "channel_not_allowlisted";
    }
    return null;
  }

  function videoBlockReason(cfg, videoId) {
    const block = parseLinesToTokens(cfg && cfg.videoBlocklist);
    if (block.indexOf(videoId) >= 0) return "video_blocked";
    return null;
  }

  async function checkServerKnownIds(serverUrl, videoIds) {
    const base = String(serverUrl || "http://127.0.0.1:8000").replace(/\/$/, "");
    if (!videoIds.length) return { known: {}, unknown: [] };
    // Chunk to stay under API max 500
    const known = {};
    const unknown = [];
    const chunkSize = 400;
    for (let i = 0; i < videoIds.length; i += chunkSize) {
      const chunk = videoIds.slice(i, i + chunkSize);
      try {
        const r = await fetch(base + "/api/youtube/check-ids", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ video_ids: chunk }),
        });
        if (!r.ok) {
          // Fallback: treat as unknown so user can still try logging
          for (const id of chunk) unknown.push(id);
          continue;
        }
        const body = await r.json();
        const k = (body && body.known) || {};
        for (const id of Object.keys(k)) known[id] = k[id];
        const u = (body && body.unknown) || [];
        for (const id of u) unknown.push(id);
        // Any missing from response
        for (const id of chunk) {
          if (!(id in known) && unknown.indexOf(id) < 0) unknown.push(id);
        }
      } catch (_) {
        for (const id of chunk) unknown.push(id);
      }
    }
    return { known, unknown };
  }

  function decodeMaybe(s) {
    let v = String(s || "");
    try {
      if (/%[0-9A-Fa-f]{2}/.test(v)) v = decodeURIComponent(v);
    } catch (_) {}
    return v;
  }

  function normalizeHandle(raw) {
    let h = decodeMaybe(raw).trim();
    if (!h) return "";
    if (h.startsWith("/@")) h = h.slice(1);
    if (!h.startsWith("@")) h = "@" + h.replace(/^\/+/, "");
    // strip path junk
    h = h.split(/[/?#]/)[0];
    return h.length > 1 ? h : "";
  }

  /**
   * Extract signed-in *viewer* identity from a YouTube HTML document.
   *
   * CRITICAL: history/feed HTML is full of uploader handles (canonicalBaseUrl,
   * userUrl on every video). Never take the first @handle match — that is
   * almost always a video channel (e.g. @osho_taigu), not you.
   *
   * Safe sources only:
   *  - ytcfg CHANNEL_ID / DELEGATED_CHANNEL_ID
   *  - account switcher payloads (activeAccountHeaderRenderer / selected accountItem)
   */
  function detectViewerFromHistoryHtml(html) {
    const h = String(html || "");
    let channelId =
      extractBetween(h, /"CHANNEL_ID"\s*:\s*"(UC[\w-]{22})"/) ||
      extractBetween(h, /'CHANNEL_ID'\s*:\s*'(UC[\w-]{22})'/) ||
      extractBetween(h, /ytcfg\.set\(\s*["']CHANNEL_ID["']\s*,\s*["'](UC[\w-]{22})["']/) ||
      extractBetween(h, /"DELEGATED_CHANNEL_ID"\s*:\s*"(UC[\w-]{22})"/) ||
      "";

    // Account menu only — never generic "channelId" / "pageId" (those are uploaders)
    if (!channelId) {
      const acct = h.match(
        /"activeAccountHeaderRenderer"\s*:\s*\{[\s\S]{0,1200}?"channelId"\s*:\s*"(UC[\w-]{22})"/
      );
      if (acct) channelId = acct[1];
    }
    if (!channelId) {
      const acct2 = h.match(
        /"accountItem"\s*:\s*\{[\s\S]{0,800}?"channelId"\s*:\s*"(UC[\w-]{22})"[\s\S]{0,400}?"isSelected"\s*:\s*true/
      );
      if (acct2) channelId = acct2[1];
    }

    // Handle ONLY from account-switcher structures — never bare userUrl/canonicalBaseUrl
    let handle = "";
    const acctHandle = h.match(
      /"activeAccountHeaderRenderer"\s*:\s*\{[\s\S]{0,1500}?"canonicalBaseUrl"\s*:\s*"\/(@[^"?#]+)"/
    );
    if (acctHandle) handle = normalizeHandle(acctHandle[1]);
    if (!handle) {
      const acctHandle2 = h.match(
        /"accountItem"\s*:\s*\{[\s\S]{0,1000}?"canonicalBaseUrl"\s*:\s*"\/(@[^"?#]+)"[\s\S]{0,400}?"isSelected"\s*:\s*true/
      );
      if (acctHandle2) handle = normalizeHandle(acctHandle2[1]);
    }
    if (!handle) {
      // ytcfg sometimes embeds the signed-in channel URL (not video owners)
      const cfgUrl = extractBetween(h, /"CHANNEL_URL"\s*:\s*"([^"]+)"/);
      if (cfgUrl) {
        const m = String(cfgUrl).match(/\/@([^/?#"]+)/);
        if (m) handle = normalizeHandle(m[1]);
      }
    }

    const loggedIn =
      !!(channelId || handle) ||
      /"LOGGED_IN"\s*:\s*true/.test(h) ||
      /"LOGGED_IN"\s*,\s*true/.test(h) ||
      /ytcfg\.set\(\s*["']LOGGED_IN["']\s*,\s*true/.test(h);

    const confidence = channelId ? "high" : handle ? "medium" : loggedIn ? "logged-in-only" : "none";

    return {
      viewerChannelId: channelId || "",
      viewerHandle: handle || "",
      loggedIn: !!loggedIn,
      confidence,
      source:
        channelId || handle
          ? "history-html"
          : loggedIn
            ? "history-html-logged-in"
            : "",
    };
  }

  function tabsQuery(q) {
    if (!api.tabs || !api.tabs.query) return Promise.resolve([]);
    try {
      const result = api.tabs.query(q);
      if (result && typeof result.then === "function") return result;
      return new Promise((resolve) => api.tabs.query(q, resolve));
    } catch (_) {
      return Promise.resolve([]);
    }
  }

  function tabsSendMessage(tabId, msg) {
    if (!api.tabs || !api.tabs.sendMessage) {
      return Promise.resolve({ _error: "no_tabs" });
    }
    try {
      const result = api.tabs.sendMessage(tabId, msg);
      if (result && typeof result.then === "function") {
        return result.catch((e) => ({ _error: String(e && e.message ? e.message : e) }));
      }
      return new Promise((resolve) => {
        api.tabs.sendMessage(tabId, msg, (res) => {
          const err = api.runtime && api.runtime.lastError;
          if (err) resolve({ _error: err.message });
          else resolve(res);
        });
      });
    } catch (e) {
      return Promise.resolve({ _error: String(e) });
    }
  }

  async function detectViewerFromOpenTabs() {
    let tabs = await tabsQuery({
      url: ["*://*.youtube.com/*", "*://youtube.com/*", "*://m.youtube.com/*"],
    });
    if (!tabs || !tabs.length) return null;
    // Prefer non-history watch/home tabs first (richer ytcfg), but try all
    tabs = tabs.slice().sort((a, b) => {
      const score = (t) => {
        const u = String((t && t.url) || "");
        if (/\/watch/.test(u)) return 0;
        if (/feed\/history/.test(u)) return 2;
        return 1;
      };
      return score(a) - score(b);
    });
    for (const tab of tabs) {
      if (!tab || !tab.id) continue;
      const res = await tabsSendMessage(tab.id, { type: "GET_PAGE_STATUS" });
      if (!res || res._error || !res.ok) continue;
      const channelId = String(res.viewerChannelId || "").trim();
      const handle = normalizeHandle(res.viewerHandle || "");
      if (!channelId && !handle) continue;
      return {
        viewerChannelId: /^UC[\w-]{22}$/.test(channelId) ? channelId : "",
        viewerHandle: handle,
        loggedIn: res.loggedIn !== false,
        source: "open-tab",
      };
    }
    return null;
  }

  async function rememberViewer(viewer) {
    if (!viewer) return;
    const channelId = String(viewer.viewerChannelId || "").trim();
    const handle = normalizeHandle(viewer.viewerHandle || "");
    if (!channelId && !handle) return;
    try {
      await storageSet({
        lastKnownViewer: {
          viewerChannelId: channelId,
          viewerHandle: handle,
          at: Date.now(),
          source: viewer.source || "",
        },
      });
    } catch (_) {}
  }

  async function loadCachedViewer() {
    try {
      const stored = await storageGet({ lastKnownViewer: null });
      const v = stored && stored.lastKnownViewer;
      if (!v || typeof v !== "object") return null;
      const channelId = String(v.viewerChannelId || "").trim();
      const handle = normalizeHandle(v.viewerHandle || "");
      if (!channelId && !handle) return null;
      return {
        viewerChannelId: channelId,
        viewerHandle: handle,
        loggedIn: true,
        source: "cache",
      };
    } catch (_) {
      return null;
    }
  }

  function viewerFromAllowlistTokens(cfg) {
    const tokens = parseLinesToTokens(cfg && cfg.allowedViewers);
    let channelId = "";
    let handle = "";
    for (const raw of tokens) {
      const t = normAccountToken(raw);
      if (!t) continue;
      if (!channelId && t.startsWith("UC") && t.length >= 22) channelId = t;
      else if (!handle && (t.startsWith("@") || !t.startsWith("UC"))) {
        handle = t.startsWith("@") ? t : "@" + t;
      }
    }
    if (!channelId && !handle) return null;
    return {
      viewerChannelId: channelId,
      viewerHandle: handle,
      loggedIn: true,
      source: "allowlist-fallback",
    };
  }

  function listToMultiline(list) {
    if (!Array.isArray(list)) return "";
    return list
      .map((x) => String(x || "").trim())
      .filter(Boolean)
      .join("\n");
  }

  /**
   * Pull non-secret YouTube filters from the tracker server and merge into
   * extension storage when local fields are empty (or force=true).
   */
  async function pullServerYoutubeConfig(opts) {
    const force = !!(opts && opts.force);
    const stored = await storageGet({
      serverUrl: "http://127.0.0.1:8000",
      allowedViewers: "",
      channelAllowlist: "",
      channelBlocklist: "",
      threshold: 0.9,
      minWatchedSeconds: 300,
    });
    const base = String(stored.serverUrl || "http://127.0.0.1:8000").replace(/\/$/, "");
    let body;
    try {
      const r = await fetch(base + "/api/youtube/extension-config", {
        method: "GET",
        cache: "no-store",
      });
      if (!r.ok) return { ok: false, error: "http_" + r.status };
      body = await r.json();
    } catch (e) {
      return { ok: false, error: String(e && e.message ? e.message : e) };
    }

    const patch = {};
    const serverViewers = listToMultiline(body.viewer_allowlist);
    const serverAllow = listToMultiline(body.channel_allowlist);
    const serverBlock = listToMultiline(body.channel_blocklist);

    if (serverViewers && (force || !String(stored.allowedViewers || "").trim())) {
      patch.allowedViewers = serverViewers;
    }
    if (serverAllow && (force || !String(stored.channelAllowlist || "").trim())) {
      patch.channelAllowlist = serverAllow;
    }
    if (serverBlock && (force || !String(stored.channelBlocklist || "").trim())) {
      patch.channelBlocklist = serverBlock;
    }
    // Only fill numeric defaults when never customized (keep local overrides)
    if (
      force ||
      stored.threshold == null ||
      stored.threshold === "" ||
      Number(stored.threshold) === 0.9
    ) {
      if (body.completion_threshold != null) {
        const t = Number(body.completion_threshold);
        if (Number.isFinite(t) && t > 0 && t <= 1) patch.threshold = t;
      }
    }
    if (
      force ||
      stored.minWatchedSeconds == null ||
      stored.minWatchedSeconds === "" ||
      Number(stored.minWatchedSeconds) === 300
    ) {
      if (body.min_watched_seconds != null) {
        const m = Number(body.min_watched_seconds);
        if (Number.isFinite(m) && m >= 0) patch.minWatchedSeconds = m;
      }
    }

    if (Object.keys(patch).length) {
      await storageSet(patch);
    }
    return {
      ok: true,
      patched: patch,
      server: body,
      applied: Object.keys(patch),
    };
  }

  function identityAllowed(cfg, viewer) {
    if (!viewer) return false;
    const check = viewerAllowedLocal(
      cfg,
      viewer.viewerChannelId || "",
      viewer.viewerHandle || ""
    );
    return check.ok;
  }

  /**
   * Resolve signed-in YouTube viewer without requiring the active tab to be YouTube.
   *
   * Order: history HTML (safe fields only) → open YT tabs → cache → allowlist
   * (when logged in). If a candidate fails the local viewer allowlist, discard it
   * and try the next source — never treat a history *video* channel as you.
   */
  async function resolveViewerIdentity(opts) {
    const html = (opts && opts.html) || "";
    let cfg = opts && opts.cfg;
    if (!cfg) {
      cfg = await storageGet({ allowedViewers: "" });
    }

    const allowedConfigured = parseLinesToTokens(cfg && cfg.allowedViewers).length > 0;
    const candidates = [];

    if (html) {
      candidates.push(detectViewerFromHistoryHtml(html));
    }

    const fromTab = await detectViewerFromOpenTabs();
    if (fromTab) candidates.push(fromTab);

    const cached = await loadCachedViewer();
    if (cached) candidates.push(cached);

    let loggedInFlag = !!(opts && opts.historyLooksLoggedIn);
    for (const c of candidates) {
      if (c && c.loggedIn) loggedInFlag = true;
      if (c && (c.viewerChannelId || c.viewerHandle)) loggedInFlag = true;
    }
    // History HTML may report LOGGED_IN without identity
    if (html) {
      const htmlViewer = candidates[0];
      if (htmlViewer && htmlViewer.loggedIn) loggedInFlag = true;
    }

    let viewer = {
      viewerChannelId: "",
      viewerHandle: "",
      loggedIn: loggedInFlag,
      source: "",
    };

    for (const c of candidates) {
      if (!c || (!c.viewerChannelId && !c.viewerHandle)) continue;
      // Skip identities that fail allowlist (wrong channel scraped from a video)
      if (allowedConfigured && !identityAllowed(cfg, c)) {
        console.info(
          "[immersion-tracker] ignoring non-allowlisted viewer candidate",
          c.viewerHandle || c.viewerChannelId,
          c.source
        );
        continue;
      }
      viewer = {
        viewerChannelId: c.viewerChannelId || "",
        viewerHandle: c.viewerHandle || "",
        loggedIn: true,
        source: c.source || "",
      };
      break;
    }

    // Logged in but no trusted identity → use configured allowlist for payloads
    if (!(viewer.viewerChannelId || viewer.viewerHandle) && loggedInFlag) {
      const fallback = viewerFromAllowlistTokens(cfg);
      if (fallback) viewer = fallback;
    }

    // Only cache high-trust identities (not allowlist-fallback alone without detection)
    if (
      (viewer.viewerChannelId || viewer.viewerHandle) &&
      viewer.source &&
      viewer.source !== "allowlist-fallback"
    ) {
      await rememberViewer(viewer);
    }

    return {
      viewerChannelId: viewer.viewerChannelId || "",
      viewerHandle: viewer.viewerHandle || "",
      loggedIn: !!loggedInFlag || !!(viewer.viewerChannelId || viewer.viewerHandle),
      source: viewer.source || "",
    };
  }

  /**
   * Scan YouTube account history for untracked videos within lookbackDays.
   */
  async function scanWatchHistory(opts) {
    const lookbackDays = Math.max(
      1,
      Math.min(90, Number(opts && opts.lookbackDays) || 7)
    );
    const applyFilters = opts && opts.applyFilters !== false;

    // Auto-fill empty viewer/channel lists from server config (no YouTube tab needed)
    try {
      await pullServerYoutubeConfig({ force: false });
    } catch (_) {}

    const cfg = await storageGet({
      serverUrl: "http://127.0.0.1:8000",
      webhookSecret: "",
      enabled: true,
      allowedViewers: "",
      channelMode: "all",
      channelAllowlist: "",
      channelBlocklist: "",
      videoBlocklist: "",
      preferJapanese: true,
      languageUnknownPolicy: "log",
      blockShorts: true,
      blockLive: true,
      minDurationSeconds: 60,
      minWatchedSeconds: 300,
      threshold: 0.9,
    });

    // Immersion settings: full-watch history logs use media length as watched time.
    // Ready list requires duration ≥ min watched floor (default 5 min) so amount
    // matches live tracking. Shorter / unknown-duration items go to "unfinished".
    const minWatched = Number(cfg.minWatchedSeconds);
    const minReadyDuration =
      Number.isFinite(minWatched) && minWatched > 0 ? minWatched : 300;
    const minContentDuration = Number(cfg.minDurationSeconds);
    const thr = Number(cfg.threshold);
    const completionThreshold =
      Number.isFinite(thr) && thr > 0 && thr <= 1 ? thr : 0.9;

    let html;
    try {
      html = await fetchHistoryHtml();
    } catch (e) {
      return {
        ok: false,
        error: String(e && e.message ? e.message : e),
        hint: "Could not open YouTube history. Stay signed into youtube.com in this browser.",
      };
    }

    const initialData = extractJsonAssignment(html, "ytInitialData");
    if (looksLoggedOut(html, initialData)) {
      return {
        ok: false,
        error: "not_signed_in",
        hint: "Sign into your immersion YouTube account in this browser, open youtube.com/feed/history once, then try again.",
      };
    }
    if (!initialData) {
      return {
        ok: false,
        error: "no_history_data",
        hint: "Could not parse history page. Open https://www.youtube.com/feed/history in a tab and retry.",
      };
    }

    // Works from any tab: history HTML, open YT tabs, cache, or allowlist fallback
    const viewer = await resolveViewerIdentity({
      html,
      cfg,
      historyLooksLoggedIn: true,
    });
    const viewerCheck = viewerAllowedLocal(
      cfg,
      viewer.viewerChannelId,
      viewer.viewerHandle
    );
    if (!viewerCheck.ok) {
      return {
        ok: false,
        error: viewerCheck.reason,
        viewer,
        hint:
          viewerCheck.reason === "viewer_unknown"
            ? "Could not detect which YouTube account is signed in. Set Settings → Who can log (or server viewer_allowlist), or open youtube.com once so the extension can cache your account."
            : "Signed-in account is not on the viewer allowlist. Switch account or update Settings → Who can log.",
      };
    }

    const apiKey =
      extractBetween(html, /"INNERTUBE_API_KEY":"([^"]+)"/) ||
      extractBetween(html, /INNERTUBE_API_KEY","([^"]+)"/);
    const clientVersion =
      extractBetween(html, /"INNERTUBE_CLIENT_VERSION":"([^"]+)"/) ||
      extractBetween(html, /INNERTUBE_CLIENT_VERSION","([^"]+)"/) ||
      "2.20240101.00.00";
    const client = {
      clientName: "WEB",
      clientVersion,
      hl: "en",
      gl: "US",
    };

    // Cap browse pages by lookback (fewer pages = much faster)
    const maxPagesForLookback =
      lookbackDays <= 1 ? 3 : lookbackDays <= 3 ? 5 : lookbackDays <= 7 ? 8 : HISTORY_MAX_PAGES;

    const collected = [];
    walkCollect(initialData, collected, "");
    let pages = 1;
    const cont = { token: "" };
    findContinuationToken(initialData, cont);

    while (
      cont.token &&
      pages < maxPagesForLookback &&
      collected.length < HISTORY_MAX_VIDEOS
    ) {
      try {
        if (!apiKey) break;
        const next = await browseHistoryContinuation(apiKey, client, cont.token);
        walkCollect(next, collected, "");
        cont.token = "";
        findContinuationToken(next, cont);
        pages++;
      } catch (e) {
        console.warn("[immersion-tracker] history continuation failed", e);
        break;
      }
    }

    const videos = dedupeVideos(collected);
    const now = Date.now();
    const cutoff = now - lookbackDays * 86400000;

    // Attach watchedAtMs from section labels; stop when clearly older than window
    // (YouTube lists newest first, so once we pass the window we can soft-stop)
    let pastWindow = false;
    const timed = [];
    for (const v of videos) {
      const ms = sectionLabelToMs(v.sectionLabel, now);
      v.watchedAtMs = ms;
      v.watchedAt = ms ? new Date(ms).toISOString() : null;
      if (ms != null && ms < cutoff) {
        pastWindow = true;
        // Keep only if within window; skip older
        continue;
      }
      // Unknown date: keep only while we haven't gone past the window in order
      if (ms == null && pastWindow) continue;
      if (ms == null) {
        // Assume recent if we haven't left the window yet
        v.watchedAtMs = now;
        v.watchedAt = new Date(now).toISOString();
        v.dateUnknown = true;
      }
      if (!v.thumbnail && v.videoId) {
        v.thumbnail = "https://i.ytimg.com/vi/" + v.videoId + "/hqdefault.jpg";
      }
      timed.push(v);
      if (timed.length >= HISTORY_MAX_VIDEOS) break;
    }

    const loggedMap = await loadLoggedIds();
    const rejectedMap = await loadHistoryRejected();
    const localEntries = await loadLog();
    /** @type {Map<string, any>} */
    const localById = new Map();
    for (const e of localEntries) {
      if (e && e.videoId) localById.set(e.videoId, e);
    }
    // Merge peak progress / duration from live tracking on this browser
    for (const v of timed) {
      const local = localById.get(v.videoId);
      if (!local) continue;
      if (!(Number(v.durationSeconds) > 0) && Number(local.durationSeconds) > 0) {
        v.durationSeconds = Number(local.durationSeconds);
        v.durationEnriched = true;
      }
      let localPct = null;
      if (local.maxRatio != null && Number(local.maxRatio) > 0) {
        localPct = Math.min(100, Math.round(Number(local.maxRatio) * 100));
      } else if (
        Number(local.watchedSeconds) > 0 &&
        Number(local.durationSeconds || v.durationSeconds) > 0
      ) {
        localPct = Math.min(
          100,
          Math.round(
            (Number(local.watchedSeconds) /
              Number(local.durationSeconds || v.durationSeconds)) *
              100
          )
        );
      }
      if (localPct != null) {
        const histPct =
          v.percentWatched != null && Number.isFinite(Number(v.percentWatched))
            ? Number(v.percentWatched)
            : null;
        if (histPct == null || localPct > histPct) {
          v.percentWatched = localPct;
          v.progressSource = "local";
        } else if (histPct != null) {
          v.progressSource = v.progressSource || "history";
        }
      } else if (v.percentWatched != null) {
        v.progressSource = v.progressSource || "history";
      }
    }
    const pendingLocal = new Set(
      localEntries
        .filter(
          (e) =>
            e &&
            e.videoId &&
            (e.status === "pending" ||
              e.status === "error" ||
              e.status === "ready" ||
              e.status === "accepted" ||
              e.status === "duplicate")
        )
        .map((e) => e.videoId)
    );

    const serverCheck = await checkServerKnownIds(
      cfg.serverUrl,
      timed.map((v) => v.videoId)
    );
    const serverKnown = serverCheck.known || {};

    // Mark any server-known as logged locally for future scans (batch)
    {
      const toMark = Object.keys(serverKnown).filter((vid) => !loggedMap[vid]);
      if (toMark.length) {
        const map = await loadLoggedIds();
        for (const vid of toMark) map[vid] = true;
        const keys = Object.keys(map);
        if (keys.length > MAX_LOGGED_IDS) {
          const drop = keys.slice(0, keys.length - MAX_LOGGED_IDS);
          for (const k of drop) delete map[k];
        }
        await storageSet({ [LOGGED_IDS_KEY]: map });
        Object.assign(loggedMap, Object.fromEntries(toMark.map((v) => [v, true])));
      }
    }

    const candidates = [];
    const unfinished = [];
    const skipped = {
      alreadyLogged: 0,
      rejected: 0,
      filters: 0,
      language: 0,
      noDuration: 0,
      shortOfMinWatch: 0,
    };

    // Pre-filter (no network) so we only enrich videos that could appear in the list
    /** @type {any[]} */
    const toEnrich = [];
    for (const v of timed) {
      if (loggedMap[v.videoId] || serverKnown[v.videoId] || pendingLocal.has(v.videoId)) {
        skipped.alreadyLogged++;
        continue;
      }
      if (rejectedMap[v.videoId]) {
        skipped.rejected++;
        continue;
      }
      if (applyFilters) {
        if (cfg.blockShorts !== false && v.isShort) {
          skipped.filters++;
          continue;
        }
        if (cfg.blockLive !== false && v.isLive) {
          skipped.filters++;
          continue;
        }
        const vb = videoBlockReason(cfg, v.videoId);
        if (vb) {
          skipped.filters++;
          continue;
        }
        const cb = channelFilterReason(cfg, v.channelId, v.channelTitle);
        if (cb) {
          skipped.filters++;
          continue;
        }
      }
      toEnrich.push(v);
    }

    // Enrich only survivors (cache + player; watch-page only if duration still missing)
    let enrichInfo = {
      fetched: 0,
      filled: 0,
      languages: 0,
      cacheHits: 0,
      watchPages: 0,
      remaining: 0,
    };
    try {
      const enrichCap = Math.min(50, Math.max(12, toEnrich.length));
      enrichInfo = await enrichVideosMissingDuration(toEnrich, apiKey, client, enrichCap, {
        preferJapanese: cfg.preferJapanese !== false && applyFilters,
        watchPageLimit: Math.min(12, enrichCap),
      });
    } catch (e) {
      console.warn("[immersion-tracker] duration enrich failed", e);
    }

    /**
     * History bulk review is stricter than live tracking:
     * Japanese only requires positive evidence (captions/audio ja OR Japanese in title).
     * Caption "en" always wins over a weak title guess. Unknown with no JA title is hidden
     * so English history doesn't flood Ready (live still respects languageUnknownPolicy).
     */
    function languageFilterReason(v) {
      if (cfg.preferJapanese === false) return null;
      const lang = normalizeLangCode(v.language);
      const titleJa = hasJapaneseScript(v.title);
      // Explicit non-Japanese from player/captions — filter even if title has a JP char
      if (lang === "en") return "language: en";
      if (lang && lang !== "ja") return "language: " + lang;
      if (lang === "ja") return null;
      if (titleJa) return null;
      // No language + no Japanese in title
      if (cfg.languageUnknownPolicy === "skip") return "language: unknown";
      // History: still hide unknowns without JA evidence (avoids EN noise in bulk review)
      return "language: unknown";
    }

    // toEnrich already passed logged/rejected/shorts/live/channel filters
    for (const v of toEnrich) {
      let filterReason = null;
      if (applyFilters) {
        // Hard min content length (settings minDurationSeconds) — still hide junk
        if (
          Number.isFinite(minContentDuration) &&
          minContentDuration > 0 &&
          v.durationSeconds > 0 &&
          v.durationSeconds < minContentDuration
        ) {
          filterReason = "below_min_duration";
        }
        if (!filterReason) {
          const lr = languageFilterReason(v);
          if (lr) {
            filterReason = lr;
            skipped.language++;
          }
        }
      }

      if (filterReason) {
        skipped.filters++;
        continue;
      }

      const durationSeconds = Number(v.durationSeconds) || 0;
      const percentWatched =
        v.percentWatched != null && Number.isFinite(Number(v.percentWatched))
          ? Math.min(100, Math.max(0, Number(v.percentWatched)))
          : null;
      const progressKnown = percentWatched != null;
      const progressRatio = progressKnown ? percentWatched / 100 : null;
      const estimatedWatched =
        progressKnown && durationSeconds > 0
          ? durationSeconds * progressRatio
          : 0;

      // Ready only when we have completion evidence (history bar or local peak).
      // "Appeared in history" alone is NOT finished — unknown progress → Unfinished.
      let unfinishedReason = "";
      if (!(durationSeconds > 0)) {
        unfinishedReason = "duration_unknown";
        skipped.noDuration++;
      } else if (!progressKnown) {
        unfinishedReason = "progress_unknown";
        skipped.shortOfMinWatch++;
      } else if (progressRatio < completionThreshold) {
        unfinishedReason = "partial_progress";
        skipped.shortOfMinWatch++;
      } else if (estimatedWatched < minReadyDuration) {
        unfinishedReason = "below_min_watched";
        skipped.shortOfMinWatch++;
      }

      const bucket = unfinishedReason ? "unfinished" : "ready";

      const row = {
        videoId: v.videoId,
        title: v.title,
        channelId: v.channelId || "",
        channelTitle: v.channelTitle || "",
        durationSeconds,
        durationText: v.durationText || "",
        percentWatched,
        progressSource: v.progressSource || (progressKnown ? "history" : ""),
        watchedSeconds:
          progressKnown && estimatedWatched > 0
            ? Math.round(estimatedWatched)
            : 0,
        thumbnail:
          v.thumbnail ||
          (v.videoId
            ? "https://i.ytimg.com/vi/" + v.videoId + "/hqdefault.jpg"
            : ""),
        sectionLabel: v.sectionLabel || "",
        watchedAt: v.watchedAt,
        dateUnknown: !!v.dateUnknown,
        url: v.url,
        isShort: !!v.isShort,
        isLive: !!v.isLive,
        language: normalizeLangCode(v.language) || (hasJapaneseScript(v.title) ? "ja" : ""),
        bucket,
        unfinishedReason,
        decision: "pending",
      };

      if (bucket === "ready") candidates.push(row);
      else unfinished.push(row);
    }

    return {
      ok: true,
      lookbackDays,
      pages,
      scanned: timed.length,
      rawFound: videos.length,
      candidates,
      unfinished,
      settings: {
        minWatchedSeconds: minReadyDuration,
        minDurationSeconds: Number.isFinite(minContentDuration)
          ? minContentDuration
          : 60,
        threshold: completionThreshold,
        preferJapanese: cfg.preferJapanese !== false,
      },
      enrich: enrichInfo,
      skipped,
      viewer,
      cutoffIso: new Date(cutoff).toISOString(),
    };
  }

  /**
   * Batch-queue approved history videos to the tracker.
   * Each payload uses import_source: "history" (server skips min-watch floor).
   */
  async function batchLogHistory(items, opts) {
    const list = Array.isArray(items) ? items : [];
    if (!list.length) return { ok: false, error: "no_items" };

    const cfg = await storageGet({
      serverUrl: "http://127.0.0.1:8000",
      webhookSecret: "",
      enabled: true,
      threshold: 0.9,
    });
    if (cfg.enabled === false) {
      return { ok: false, error: "extension_disabled" };
    }

    // Resolve viewer for payloads (any tab; allowlist / cache / open YT tabs)
    let viewerChannelId = (opts && opts.viewerChannelId) || "";
    let viewerHandle = (opts && opts.viewerHandle) || "";
    let apiKey = "";
    let client = {
      clientName: "WEB",
      clientVersion: "2.20240101.00.00",
      hl: "en",
      gl: "US",
    };
    try {
      let html = "";
      try {
        html = await fetchHistoryHtml();
      } catch (_) {}
      if (html) {
        apiKey =
          extractBetween(html, /"INNERTUBE_API_KEY":"([^"]+)"/) ||
          extractBetween(html, /INNERTUBE_API_KEY","([^"]+)"/) ||
          "";
        const clientVersion =
          extractBetween(html, /"INNERTUBE_CLIENT_VERSION":"([^"]+)"/) ||
          extractBetween(html, /INNERTUBE_CLIENT_VERSION","([^"]+)"/) ||
          client.clientVersion;
        client.clientVersion = clientVersion;
      }
      if (!viewerChannelId && !viewerHandle) {
        const cfgLocal = await storageGet({ allowedViewers: "" });
        const v = await resolveViewerIdentity({
          html,
          cfg: cfgLocal,
          historyLooksLoggedIn: !!html,
        });
        viewerChannelId = v.viewerChannelId || "";
        viewerHandle = v.viewerHandle || "";
      }
    } catch (_) {}

    const results = [];
    for (const item of list) {
      const videoId = String((item && item.videoId) || "").trim();
      if (!videoId) {
        results.push({ videoId: "", ok: false, error: "no_video_id" });
        continue;
      }
      let duration = Number(item.durationSeconds) || 0;
      let title = (item.title || videoId).trim();
      let channelId = item.channelId || "";
      let channelTitle = item.channelTitle || "";

      // Never invent 60s — fetch real length so Tadoku amount is correct
      if (!(duration > 0)) {
        const d = await resolveVideoDetails(videoId, apiKey, client);
        if (d && d.durationSeconds > 0) {
          duration = d.durationSeconds;
          if (d.title) title = d.title;
          if (d.channelId) channelId = d.channelId;
          if (d.channelTitle) channelTitle = d.channelTitle;
        }
      }
      if (!(duration > 0)) {
        results.push({
          videoId,
          ok: false,
          error: "duration_unknown",
          reason: "duration_unknown",
        });
        continue;
      }

      const finishedAt =
        (item.watchedAt && String(item.watchedAt)) || new Date().toISOString();
      // Approve = user confirms a full immersion watch (progress bars are for UI bucketing only)
      const payload = {
        video_id: videoId,
        title,
        channel_id: channelId,
        channel_title: channelTitle,
        duration_seconds: duration,
        watched_seconds: duration,
        ratio: 1.0,
        url: item.url || "https://www.youtube.com/watch?v=" + videoId,
        finished_at: finishedAt,
        viewer_channel_id: viewerChannelId,
        viewer_handle: viewerHandle,
        import_source: "history",
      };

      try {
        const out = await enqueueComplete(payload, cfg);
        const accepted =
          !!(out.body && out.body.accepted) ||
          (out.entry && out.entry.status === "accepted");
        const reason =
          (out.body && out.body.reason) ||
          (out.entry && (out.entry.serverReason || out.entry.status)) ||
          out.error ||
          "";
        if (accepted || reason === "duplicate" || (out.entry && isTerminalOk(out.entry.status))) {
          await markVideoLogged(videoId);
        }
        results.push({
          videoId,
          ok: !!(accepted || reason === "duplicate" || (out.entry && isTerminalOk(out.entry.status))),
          accepted: !!accepted,
          reason,
          logId: (out.body && out.body.log_id) || (out.entry && out.entry.logId) || null,
          already: !!out.already,
        });
      } catch (e) {
        results.push({
          videoId,
          ok: false,
          error: String(e && e.message ? e.message : e),
        });
      }
    }

    const logged = results.filter((r) => r.ok && r.accepted).length;
    const dupes = results.filter((r) => r.reason === "duplicate" || r.already).length;
    const failed = results.filter((r) => !r.ok).length;
    return {
      ok: failed === 0,
      logged,
      duplicates: dupes,
      failed,
      results,
    };
  }

  // --- messaging ---

  api.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    if (!msg || !msg.type) return false;

    const run = async () => {
      switch (msg.type) {
        case "YOUTUBE_PROGRESS":
          return upsertProgress(msg.patch || msg.payload || {});

        case "YOUTUBE_COMPLETE": {
          const stored = await storageGet({
            serverUrl: "http://127.0.0.1:8000",
            webhookSecret: "",
            threshold: 0.9,
            enabled: true,
          });
          const cfg = Object.assign({}, stored, msg.config || {}, {
            forceRedeliver: !!(msg.force || msg.forceRedeliver || (msg.config && msg.config.force)),
          });
          const out = await enqueueComplete(msg.payload, cfg);
          // Shape matches previous content-script expectation
          return {
            ok: !!(out.ok || (out.entry && isTerminalOk(out.entry.status))),
            status: out.status,
            body: out.body || {
              accepted: out.entry && out.entry.status === "accepted",
              reason:
                (out.entry && (out.entry.serverReason || out.entry.status)) ||
                out.error,
              log_id: out.entry && out.entry.logId,
            },
            entry: out.entry,
            error: out.error,
            already: out.already,
          };
        }

        case "LOCAL_LOG_LIST":
          return listLocalLog(msg.opts || {});

        case "LOCAL_LOG_STATUS":
          return getLocalStatusForVideo(msg.videoId);

        case "LOCAL_LOG_RETRY":
          return retryLocal(msg.key);

        case "LOCAL_LOG_RETRY_ALL":
          return retryAllPending();

        case "LOCAL_LOG_FLUSH":
          return flushPending();

        case "LOCAL_LOG_CLEAR_DONE":
          return clearLocalDone();

        case "LOCAL_LOG_DISMISS":
          return dismissLocal(msg.key);

        case "LOCAL_LOG_RESET_VIDEO":
          return resetLocalVideo(msg.videoId);

        case "HISTORY_SCAN":
          return scanWatchHistory(msg.opts || {});

        case "HISTORY_REJECT":
          return markHistoryRejected(msg.videoIds || msg.videoId);

        case "HISTORY_UNREJECT":
          return unrejectHistory(msg.videoIds || msg.videoId);

        case "HISTORY_BATCH_LOG":
          return batchLogHistory(msg.items || [], msg.opts || {});

        case "DETECT_VIEWER":
          return (async () => {
            let html = "";
            try {
              html = await fetchHistoryHtml();
            } catch (_) {}
            const viewer = await resolveViewerIdentity({
              html,
              historyLooksLoggedIn: !!(html && !looksLoggedOut(html, extractJsonAssignment(html, "ytInitialData"))),
            });
            return {
              ok: !!(viewer.viewerChannelId || viewer.viewerHandle),
              ...viewer,
            };
          })();

        case "PULL_SERVER_YOUTUBE_CONFIG":
          return pullServerYoutubeConfig(msg.opts || {});

        case "CACHE_VIEWER":
          await rememberViewer(msg.viewer || msg);
          return { ok: true };

        default:
          return { ok: false, error: "unknown_type" };
      }
    };

    run()
      .then(sendResponse)
      .catch((e) => sendResponse({ ok: false, error: String(e) }));
    return true;
  });

  // Periodic retry of pending/error
  setInterval(() => {
    scheduleFlush(0);
  }, RETRY_MS);

  // Kick once after load
  scheduleFlush(1500);

  console.info("[immersion-tracker] background ready (local queue)");
})();
