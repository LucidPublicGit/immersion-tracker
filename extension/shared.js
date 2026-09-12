/* global browser, chrome */
/* Shared helpers for popup, settings, and history pages. */

const api =
  typeof browser !== "undefined" ? browser : typeof chrome !== "undefined" ? chrome : null;

/**
 * All settings persist in browser.storage.local (device-local only).
 * Safe for webhook secrets: never uses storage.sync (cloud / account sync).
 */
const defaults = {
  serverUrl: "http://127.0.0.1:8000",
  webhookSecret: "",
  threshold: 0.9,
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
  /** Min content seconds of watch progress required (with ≥ threshold %). Default 5 min. */
  minWatchedSeconds: 300,
  historyClearedAt: "",
  historyClearedMaxId: 0,
  /** Default lookback window for Log from history (days). */
  historyLookbackDays: 7,
  /** Whether From history scan applies extension content filters. */
  historyApplyFilters: true,
  /** Popup: Log from history section collapsed (default true = collapsed). */
  historyImportCollapsed: true,
  uiSections: {
    watch: true,
    history: true,
    viewer: false,
    channels: true,
    content: true,
    connection: true,
  },
};

/** In-memory mirror of storage.local so blank password fields never wipe the secret. */
var cachedSettings = Object.assign({}, defaults);

var lastDetected = { handle: "", channelId: "" };
var lastWatch = null;
var lastLogsCache = [];
var lastLocalEntries = [];
var lastLocalMeta = { pendingCount: 0, errorCount: 0 };
var historyClearedAt = "";
var historyClearedMaxId = 0;
var secretDirty = false;
var settingsSaveTimer = null;
var applyingForm = false;

/** Optional hooks set by each page. */
const pageHooks = {
  /** @type {null | ((key: string) => void)} */
  onRetryLocal: null,
  /** @type {null | ((text: string, kind?: string) => void)} */
  setStatus: null,
};

function runtimeSend(message) {
  if (!api || !api.runtime || !api.runtime.sendMessage) {
    return Promise.resolve({ ok: false, error: "no_runtime" });
  }
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

function storageArea() {
  if (!api || !api.storage || !api.storage.local) return null;
  return api.storage.local;
}

function storageGet(keys) {
  const area = storageArea();
  if (!area) {
    return Promise.resolve(typeof keys === "object" && !Array.isArray(keys) ? keys : defaults);
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
  if (!area) return Promise.reject(new Error("no storage.local"));
  try {
    const result = area.set(data);
    if (result && typeof result.then === "function") {
      return result.then(() => {
        Object.assign(cachedSettings, data);
        return undefined;
      });
    }
    return new Promise((resolve, reject) => {
      area.set(data, () => {
        const err = api.runtime && api.runtime.lastError;
        if (err) reject(new Error(err.message));
        else {
          Object.assign(cachedSettings, data);
          resolve();
        }
      });
    });
  } catch (e) {
    return Promise.reject(e);
  }
}

async function migrateSyncToLocal() {
  if (!api || !api.storage || !api.storage.sync || !api.storage.local) return;
  try {
    const local = await new Promise((resolve) => {
      try {
        const r = api.storage.local.get(null);
        if (r && typeof r.then === "function") r.then(resolve);
        else api.storage.local.get(null, resolve);
      } catch (_) {
        resolve({});
      }
    });
    const sync = await new Promise((resolve) => {
      try {
        const r = api.storage.sync.get(null);
        if (r && typeof r.then === "function") r.then(resolve);
        else api.storage.sync.get(null, resolve);
      } catch (_) {
        resolve({});
      }
    });
    if (!sync || typeof sync !== "object") return;
    const patch = {};
    for (const key of Object.keys(defaults)) {
      const localEmpty =
        local[key] === undefined ||
        local[key] === null ||
        local[key] === "" ||
        (key === "webhookSecret" && !local[key]);
      if (localEmpty && sync[key] !== undefined && sync[key] !== null && sync[key] !== "") {
        patch[key] = sync[key];
      }
    }
    if (Object.keys(patch).length) {
      await storageSet(patch);
      console.info("[immersion-tracker] migrated settings from sync → local", Object.keys(patch));
    }
  } catch (e) {
    console.warn("[immersion-tracker] sync→local migrate skipped", e);
  }
}

function openExtensionPage(page) {
  // getURL must receive a path without hash; re-attach fragment afterward
  let path = String(page || "");
  let hash = "";
  const hi = path.indexOf("#");
  if (hi >= 0) {
    hash = path.slice(hi);
    path = path.slice(0, hi);
  }
  const base =
    api && api.runtime && api.runtime.getURL ? api.runtime.getURL(path) : path;
  const url = base + hash;
  if (api && api.tabs && api.tabs.create) {
    try {
      const r = api.tabs.create({ url });
      if (r && typeof r.then === "function") return r;
      return new Promise((resolve) => api.tabs.create({ url }, resolve));
    } catch (e) {
      window.open(url, "_blank");
      return Promise.resolve();
    }
  }
  window.open(url, "_blank");
  return Promise.resolve();
}

function openSettingsPage() {
  if (api && api.runtime && api.runtime.openOptionsPage) {
    try {
      const r = api.runtime.openOptionsPage();
      if (r && typeof r.then === "function") {
        return r.catch(() => openExtensionPage("settings.html"));
      }
      return new Promise((resolve) => {
        api.runtime.openOptionsPage(() => {
          if (api.runtime.lastError) openExtensionPage("settings.html").then(resolve);
          else resolve();
        });
      });
    } catch (_) {
      return openExtensionPage("settings.html");
    }
  }
  return openExtensionPage("settings.html");
}

function openHistoryPage() {
  return openExtensionPage("history.html#activity");
}

/** From history is a tab on the Activity page (not a separate window). */
function openImportPage() {
  return openExtensionPage("history.html#from-history");
}

function setStatus(text, kind) {
  if (pageHooks.setStatus) {
    pageHooks.setStatus(text, kind);
    return;
  }
  const el = document.getElementById("status");
  if (!el) return;
  el.textContent = text || "";
  el.classList.remove("ok", "err");
  if (kind === "ok" || kind === "err") el.classList.add(kind);
}

function setServerChip(state, text) {
  const el = document.getElementById("serverChip");
  if (!el) return;
  el.classList.remove("ok", "err", "warn");
  el.classList.add(state || "warn");
  el.textContent = text;
}

function baseUrlFromSettings() {
  return (cachedSettings.serverUrl || defaults.serverUrl).replace(/\/$/, "");
}

function baseUrlFromForm() {
  const el = document.getElementById("serverUrl");
  if (el && el.value != null) {
    return (el.value.trim() || defaults.serverUrl).replace(/\/$/, "");
  }
  return baseUrlFromSettings();
}

function thresholdFromStorage(t) {
  const n = typeof t === "number" ? t : parseFloat(t);
  if (!Number.isFinite(n)) return 90;
  if (n > 1) return Math.round(Math.min(100, Math.max(50, n)));
  return Math.round(Math.min(100, Math.max(50, n * 100)));
}

function thresholdToStorage(pct) {
  const n = parseInt(pct, 10);
  if (!Number.isFinite(n)) return 0.9;
  return Math.min(1, Math.max(0.5, n / 100));
}

function syncThresholdUi(pct) {
  const p = Math.min(100, Math.max(50, parseInt(pct, 10) || 90));
  const range = document.getElementById("thresholdRange");
  const num = document.getElementById("thresholdPct");
  const live = document.getElementById("thresholdLive");
  const thrLabel = document.getElementById("watchThrLabel");
  if (range) range.value = String(p);
  if (num) num.value = String(p);
  if (live) live.textContent = p + "%";
  if (thrLabel) thrLabel.textContent = "log at " + p + "%";
}

function formatMinutes(amount) {
  if (amount == null || !Number.isFinite(Number(amount))) return "—";
  const n = Number(amount);
  if (n < 1) return Math.round(n * 60) + "s";
  return Math.round(n * 10) / 10 + " min";
}

function formatWhen(iso) {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return String(iso);
    return d.toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch (_) {
    return String(iso);
  }
}

function parseLines(raw) {
  return String(raw || "")
    .split(/[\n,]+/)
    .map((s) => s.trim())
    .filter(Boolean);
}

function joinLines(items) {
  return Array.from(new Set(items.map((s) => String(s).trim()).filter(Boolean))).join("\n");
}

function normToken(value) {
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

function addTokensToList(raw, values) {
  const set = new Set(parseLines(raw).map(normToken));
  for (const v of values) {
    const t = normToken(v);
    if (t) set.add(t);
  }
  return joinLines(Array.from(set));
}

function removeTokensFromList(raw, values) {
  const remove = new Set(values.map(normToken).filter(Boolean));
  const kept = parseLines(raw).filter((line) => {
    const t = normToken(line);
    if (remove.has(t)) return false;
    if (t.startsWith("@") && remove.has(t.slice(1))) return false;
    if (!t.startsWith("@") && remove.has("@" + t)) return false;
    return true;
  });
  return joinLines(kept);
}

function addToListField(fieldId, values) {
  const el = document.getElementById(fieldId);
  if (!el) return;
  el.value = addTokensToList(el.value, values);
}

function removeFromListField(fieldId, values) {
  const el = document.getElementById(fieldId);
  if (!el) return;
  el.value = removeTokensFromList(el.value, values);
}

function addVideoId(fieldId, videoId) {
  if (!videoId) return;
  const el = document.getElementById(fieldId);
  if (!el) return;
  const set = new Set(parseLines(el.value));
  set.add(String(videoId).trim());
  el.value = joinLines(Array.from(set));
}

function removeVideoId(fieldId, videoId) {
  if (!videoId) return;
  const el = document.getElementById(fieldId);
  if (!el) return;
  const id = String(videoId).trim();
  el.value = joinLines(parseLines(el.value).filter((v) => v !== id));
}

function channelModeValue() {
  const allow = document.getElementById("channelModeAllowlist");
  if (allow) return allow.checked ? "allowlist" : "all";
  return cachedSettings.channelMode === "allowlist" ? "allowlist" : "all";
}

function setChannelMode(mode) {
  const all = document.getElementById("channelModeAll");
  const allow = document.getElementById("channelModeAllowlist");
  if (all) all.checked = mode !== "allowlist";
  if (allow) allow.checked = mode === "allowlist";
}

function updateSecretUi() {
  const hint = document.getElementById("webhookSecretHint");
  const input = document.getElementById("webhookSecret");
  const has = !!(cachedSettings.webhookSecret && String(cachedSettings.webhookSecret).length);
  if (hint) {
    if (has) {
      hint.innerHTML =
        "Saved in <strong>this browser</strong> (storage.local). Leave the field blank to keep it — it will not be cleared on Save or reload.";
      hint.classList.add("ok-hint");
    } else {
      hint.textContent =
        "Paste WEBHOOK_SECRET from immersion-tracker .env once. It is stored only on this device.";
      hint.classList.remove("ok-hint");
    }
  }
  if (input) {
    input.placeholder = has
      ? "•••• saved — type only to change"
      : "same as WEBHOOK_SECRET in .env";
    input.setAttribute("autocomplete", "off");
    input.setAttribute("data-lpignore", "true");
    input.setAttribute("data-1p-ignore", "true");
  }
  const chip = document.getElementById("secretChip");
  if (chip) {
    chip.textContent = has ? "secret saved" : "no secret";
    chip.className = "secret-chip " + (has ? "ok" : "warn");
  }
}

function updateDashboardLinks() {
  const base = baseUrlFromForm();
  const home = document.getElementById("linkHome");
  const queue = document.getElementById("linkQueue");
  const logs = document.getElementById("linkLogs");
  if (home) home.href = base + "/";
  if (queue) queue.href = base + "/queue";
  if (logs) logs.href = base + "/api/logs?source=youtube&limit=20";
}

/**
 * Read form → settings object.
 * When form fields are missing (compact popup), falls back to cachedSettings.
 */
function readFormConfig(opts) {
  const hasForm = !!document.getElementById("serverUrl");
  if (!hasForm) {
    return Object.assign({}, defaults, cachedSettings, {
      historyClearedAt: historyClearedAt || cachedSettings.historyClearedAt || "",
      historyClearedMaxId: historyClearedMaxId || cachedSettings.historyClearedMaxId || 0,
    });
  }

  const pctEl = document.getElementById("thresholdPct");
  const pct = pctEl ? parseInt(pctEl.value, 10) : thresholdFromStorage(cachedSettings.threshold);
  const minEl = document.getElementById("minDurationSeconds");
  const minDur = minEl ? parseInt(minEl.value, 10) : Number(cachedSettings.minDurationSeconds);
  const minWatchEl = document.getElementById("minWatchedSeconds");
  const minWatch = minWatchEl
    ? parseInt(minWatchEl.value, 10)
    : Number(cachedSettings.minWatchedSeconds);
  const secretEl = document.getElementById("webhookSecret");
  const fieldSecret = secretEl ? secretEl.value : "";
  let webhookSecret = cachedSettings.webhookSecret || "";
  if (opts && opts.clearSecret) {
    webhookSecret = "";
  } else if (secretDirty) {
    webhookSecret = fieldSecret;
  } else if (fieldSecret) {
    webhookSecret = fieldSecret;
  }

  const enabledEl = document.getElementById("enabled");
  const allowedEl = document.getElementById("allowedViewers");
  const allowEl = document.getElementById("channelAllowlist");
  const blockEl = document.getElementById("channelBlocklist");
  const videoEl = document.getElementById("videoBlocklist");
  const preferEl = document.getElementById("preferJapanese");
  const langEl = document.getElementById("languageUnknownPolicy");
  const shortsEl = document.getElementById("blockShorts");
  const liveEl = document.getElementById("blockLive");
  const serverEl = document.getElementById("serverUrl");

  return {
    serverUrl: serverEl
      ? serverEl.value.trim() || defaults.serverUrl
      : cachedSettings.serverUrl || defaults.serverUrl,
    webhookSecret,
    threshold: thresholdToStorage(pct),
    enabled: enabledEl ? enabledEl.checked : cachedSettings.enabled !== false,
    allowedViewers: allowedEl ? allowedEl.value.trim() : cachedSettings.allowedViewers || "",
    channelMode: channelModeValue(),
    channelAllowlist: allowEl ? allowEl.value.trim() : cachedSettings.channelAllowlist || "",
    channelBlocklist: blockEl ? blockEl.value.trim() : cachedSettings.channelBlocklist || "",
    videoBlocklist: videoEl ? videoEl.value.trim() : cachedSettings.videoBlocklist || "",
    preferJapanese: preferEl ? preferEl.checked : cachedSettings.preferJapanese !== false,
    languageUnknownPolicy: langEl
      ? langEl.value || "log"
      : cachedSettings.languageUnknownPolicy || "log",
    blockShorts: shortsEl ? shortsEl.checked : cachedSettings.blockShorts !== false,
    blockLive: liveEl ? liveEl.checked : cachedSettings.blockLive !== false,
    minDurationSeconds: Number.isFinite(minDur) ? Math.max(0, minDur) : 60,
    minWatchedSeconds: Number.isFinite(minWatch) ? Math.max(0, minWatch) : 300,
    historyClearedAt: historyClearedAt || "",
    historyClearedMaxId: historyClearedMaxId || 0,
    uiSections: cachedSettings.uiSections || defaults.uiSections,
  };
}

function applyConfigToForm(cfg) {
  applyingForm = true;
  try {
    const serverEl = document.getElementById("serverUrl");
    if (serverEl) serverEl.value = cfg.serverUrl || defaults.serverUrl;
    const sec = cfg.webhookSecret || "";
    const secretEl = document.getElementById("webhookSecret");
    if (secretEl) {
      secretEl.value = sec;
      secretDirty = false;
    }
    syncThresholdUi(thresholdFromStorage(cfg.threshold));
    const enabledEl = document.getElementById("enabled");
    if (enabledEl) enabledEl.checked = cfg.enabled !== false;
    const allowedEl = document.getElementById("allowedViewers");
    if (allowedEl) allowedEl.value = cfg.allowedViewers || "";
    setChannelMode(cfg.channelMode === "allowlist" ? "allowlist" : "all");
    const allowEl = document.getElementById("channelAllowlist");
    if (allowEl) allowEl.value = cfg.channelAllowlist || "";
    const blockEl = document.getElementById("channelBlocklist");
    if (blockEl) blockEl.value = cfg.channelBlocklist || "";
    const videoEl = document.getElementById("videoBlocklist");
    if (videoEl) videoEl.value = cfg.videoBlocklist || "";
    const preferEl = document.getElementById("preferJapanese");
    if (preferEl) preferEl.checked = cfg.preferJapanese !== false;
    const langEl = document.getElementById("languageUnknownPolicy");
    if (langEl) langEl.value = cfg.languageUnknownPolicy === "skip" ? "skip" : "log";
    const shortsEl = document.getElementById("blockShorts");
    if (shortsEl) shortsEl.checked = cfg.blockShorts !== false;
    const liveEl = document.getElementById("blockLive");
    if (liveEl) liveEl.checked = cfg.blockLive !== false;
    const minEl = document.getElementById("minDurationSeconds");
    if (minEl) {
      const minD =
        cfg.minDurationSeconds != null && cfg.minDurationSeconds !== ""
          ? Number(cfg.minDurationSeconds)
          : 60;
      minEl.value = String(Number.isFinite(minD) ? minD : 60);
    }
    const minWatchEl = document.getElementById("minWatchedSeconds");
    if (minWatchEl) {
      const minW =
        cfg.minWatchedSeconds != null && cfg.minWatchedSeconds !== ""
          ? Number(cfg.minWatchedSeconds)
          : 300;
      minWatchEl.value = String(Number.isFinite(minW) ? minW : 300);
    }
    historyClearedAt = cfg.historyClearedAt || "";
    historyClearedMaxId = Number(cfg.historyClearedMaxId) || 0;
    updateSecretUi();
  } finally {
    setTimeout(() => {
      applyingForm = false;
    }, 0);
  }
}

async function persistSettings(opts) {
  const data = readFormConfig(opts);
  await storageSet(data);
  cachedSettings = Object.assign({}, defaults, cachedSettings, data);
  updateSecretUi();
  syncThresholdUi(thresholdFromStorage(data.threshold));
  updateDashboardLinks();
  return data;
}

function schedulePersistSettings() {
  if (applyingForm) return;
  if (settingsSaveTimer) clearTimeout(settingsSaveTimer);
  settingsSaveTimer = setTimeout(() => {
    settingsSaveTimer = null;
    persistSettings()
      .then(() => {})
      .catch((e) => console.warn("[immersion-tracker] auto-save failed", e));
  }, 350);
}

async function requestHostIfNeeded(serverUrl) {
  if (!api || !api.permissions || !api.permissions.request) return true;
  try {
    const u = new URL(serverUrl);
    if (u.hostname === "localhost" || u.hostname === "127.0.0.1" || u.hostname === "[::1]") {
      return true;
    }
    const origin = u.origin + "/*";
    const result = api.permissions.request({ origins: [origin] });
    if (result && typeof result.then === "function") return result;
    return new Promise((resolve) => {
      api.permissions.request({ origins: [origin] }, resolve);
    });
  } catch (e) {
    console.warn("[immersion-tracker] permission request failed", e);
    return false;
  }
}

function tabsQuery(q) {
  if (!api || !api.tabs || !api.tabs.query) return Promise.resolve([]);
  try {
    const result = api.tabs.query(q);
    if (result && typeof result.then === "function") return result;
    return new Promise((resolve) => api.tabs.query(q, resolve));
  } catch (_) {
    return Promise.resolve([]);
  }
}

function tabsSendMessage(tabId, msg) {
  try {
    const result = api.tabs.sendMessage(tabId, msg);
    if (result && typeof result.then === "function") return result;
    return new Promise((resolve) => {
      api.tabs.sendMessage(tabId, msg, (res) => {
        if (api.runtime.lastError) resolve({ _error: api.runtime.lastError.message });
        else resolve(res);
      });
    });
  } catch (e) {
    return Promise.resolve({ _error: String(e) });
  }
}

function isYoutubeUrl(url) {
  return !!url && /https?:\/\/(www\.|m\.)?youtube\.com\//i.test(url);
}

async function findYoutubeTabs() {
  const active = await tabsQuery({ active: true, currentWindow: true });
  const activeTab = active && active[0];
  if (activeTab && isYoutubeUrl(activeTab.url)) return [activeTab];

  let list = await tabsQuery({
    currentWindow: true,
    url: ["*://*.youtube.com/*", "*://youtube.com/*"],
  });
  if (!list || !list.length) {
    list = await tabsQuery({ url: ["*://*.youtube.com/*", "*://youtube.com/*"] });
  }
  return list || [];
}

function chip(text, cls) {
  const span = document.createElement("span");
  span.className = "chip" + (cls ? " " + cls : "");
  span.textContent = text;
  return span;
}

function setEntityToggle(btn, nameEl, stateEl, opts) {
  const { name, state, kind, title, disabled } = opts;
  btn.className = "entity-toggle " + (kind || "muted");
  btn.disabled = !!disabled;
  btn.title = title || "";
  nameEl.textContent = name || "—";
  stateEl.textContent = state || "";
}

function updateChannelToggle(watch) {
  const btn = document.getElementById("toggleChannel");
  const nameEl = document.getElementById("channelToggleName");
  const stateEl = document.getElementById("channelToggleState");
  if (!btn || !nameEl || !stateEl) return;

  if (!watch || !watch.videoId) {
    setEntityToggle(btn, nameEl, stateEl, {
      name: "—",
      state: "No channel yet",
      kind: "muted",
      disabled: true,
      title: "",
    });
    return;
  }

  const label = watch.channelTitle || watch.channelId || "Unknown channel";
  const hasChannel = !!(watch.channelId || watch.channelTitle);

  if (!hasChannel) {
    setEntityToggle(btn, nameEl, stateEl, {
      name: "Detecting…",
      state: "Channel not loaded yet",
      kind: "muted",
      disabled: true,
      title: "Wait for the page to load the uploader.",
    });
    return;
  }

  if (watch.channelOnBlocklist) {
    setEntityToggle(btn, nameEl, stateEl, {
      name: label,
      state: "BLOCKED · click to allow again",
      kind: "blocked",
      disabled: false,
      title:
        "This uploader is on your blocklist. No videos from them will auto-log. Click to unblock.",
    });
    return;
  }

  if (watch.channelMode === "allowlist" && !watch.channelOnAllowlist) {
    setEntityToggle(btn, nameEl, stateEl, {
      name: label,
      state: "NOT ON ALLOWLIST · click to allow",
      kind: "off",
      disabled: false,
      title:
        "Allowlist-only mode is on and this uploader is not listed. Click to add them to the allowlist.",
    });
    return;
  }

  const modeNote =
    watch.channelMode === "allowlist" ? "on allowlist" : "any-channel mode";
  setEntityToggle(btn, nameEl, stateEl, {
    name: label,
    state: "ALLOWED · click to block (" + modeNote + ")",
    kind: "ok",
    disabled: false,
    title:
      "This uploader can auto-log. Click to block the whole channel (all their videos).",
  });
}

function updateVideoToggle(watch) {
  const btn = document.getElementById("toggleVideo");
  const nameEl = document.getElementById("videoToggleName");
  const stateEl = document.getElementById("videoToggleState");
  if (!btn || !nameEl || !stateEl) return;

  if (!watch || !watch.videoId) {
    setEntityToggle(btn, nameEl, stateEl, {
      name: "—",
      state: "No video yet",
      kind: "muted",
      disabled: true,
      title: "",
    });
    return;
  }

  const title = watch.title || watch.videoId;
  if (watch.videoOnBlocklist) {
    setEntityToggle(btn, nameEl, stateEl, {
      name: title,
      state: "BLOCKED · click to unblock this video",
      kind: "blocked",
      disabled: false,
      title: "Only this video is blocked. Click to allow it again.",
    });
    return;
  }

  setEntityToggle(btn, nameEl, stateEl, {
    name: title,
    state: "CAN LOG · click to block only this video",
    kind: "ok",
    disabled: false,
    title:
      "This video is not blocked. Click to skip only this video (other videos from the channel still log).",
  });
}

function setLogStatus(kind, label, title) {
  const el = document.getElementById("logStatus");
  const glyph = document.getElementById("logStatusGlyph");
  const text = document.getElementById("logStatusLabel");
  if (!el) return;
  el.className = "log-status " + (kind || "idle");
  el.title = title || label || "";
  if (text) text.textContent = label || "";

  const map = {
    will: "✓",
    wait: "✓",
    wont: "×",
    done: "✓",
    pending: "…",
    error: "!",
    idle: "·",
  };
  if (glyph) glyph.textContent = map[kind] || "·";
}

function renderWatch(watch, thrPct) {
  const bar = document.getElementById("watchBar");
  const pctEl = document.getElementById("watchPct");
  const chips = document.getElementById("watchChips");
  if (!bar || !pctEl || !chips) return;

  chips.innerHTML = "";
  lastWatch = watch && watch.videoId ? watch : null;

  if (!watch || !watch.videoId) {
    setLogStatus("idle", "idle", "Open a YouTube watch page in this browser.");
    bar.style.width = "0%";
    pctEl.textContent = "0% watched";
    updateChannelToggle(null);
    updateVideoToggle(null);
    return;
  }

  const ratio = Math.min(1, Math.max(0, Number(watch.maxRatio) || 0));
  const pct = Math.round(ratio * 100);
  bar.style.width = pct + "%";
  pctEl.textContent = pct + "% peak progress (saved locally)";

  if (watch.language) {
    chips.appendChild(
      chip(watch.language, watch.language === "ja" ? "ja" : watch.language === "en" ? "en" : "warn")
    );
  } else {
    chips.appendChild(chip("lang ?", "warn"));
  }
  if (watch.isShorts) chips.appendChild(chip("Shorts", "info"));
  if (watch.isLive) chips.appendChild(chip("Live", "warn"));
  if (watch.channelMode === "allowlist") chips.appendChild(chip("allowlist only", "info"));
  if (watch.localStatus) {
    chips.appendChild(
      chip(
        watch.localStatus,
        watch.localStatus === "accepted" || watch.localStatus === "duplicate"
          ? "ja"
          : watch.localStatus === "error" || watch.localStatus === "rejected"
            ? "en"
            : watch.localStatus === "pending"
              ? "warn"
              : "info"
      )
    );
  }

  const ls = watch.localStatus || "";
  if (ls === "accepted" || ls === "duplicate") {
    setLogStatus(
      "done",
      ls === "duplicate" ? "already logged" : "synced",
      ls === "duplicate"
        ? "This video was already logged (once-ever)."
        : "Saved locally and accepted by Immersion Tracker."
    );
  } else if (ls === "pending" || ls === "ready") {
    setLogStatus(
      "pending",
      "pending sync",
      "Saved locally — waiting for server (auto-retries)."
    );
  } else if (ls === "error") {
    setLogStatus(
      "error",
      "sync error",
      "Saved locally but server delivery failed. Use Retry queue."
    );
  } else if (ls === "rejected") {
    setLogStatus("wont", "rejected", "Server rejected: " + (watch.skipReason || "see Activity"));
  } else if (watch.reported) {
    setLogStatus("pending", "queued", "Queued locally for Immersion Tracker.");
  } else if (watch.skipReason) {
    setLogStatus("wont", "won't log", "Will not log: " + watch.skipReason);
  } else {
    const minW =
      watch.minWatchedSeconds != null
        ? Number(watch.minWatchedSeconds)
        : Number(cachedSettings.minWatchedSeconds) || 300;
    const watched = Number(watch.watchedSeconds) || 0;
    const meetsWatch = !Number.isFinite(minW) || minW <= 0 || watched >= minW;
    if (pct >= thrPct && meetsWatch) {
      setLogStatus(
        "will",
        "will log",
        "Filters OK, past " + thrPct + "% and min watch time — will log automatically."
      );
    } else if (pct >= thrPct && !meetsWatch) {
      const need = Math.ceil(minW - watched);
      setLogStatus(
        "wait",
        "need more watch time",
        "Past " +
          thrPct +
          "% but need ≥" +
          Math.round(minW) +
          "s watched (now " +
          Math.round(watched) +
          "s; ~" +
          need +
          "s more)."
      );
    } else {
      setLogStatus(
        "wait",
        "at " + thrPct + "%",
        "Filters OK — will log at ≥" +
          thrPct +
          "% and ≥" +
          Math.round(minW || 0) +
          "s watched (now " +
          pct +
          "% / " +
          Math.round(watched) +
          "s)."
      );
    }
  }

  updateChannelToggle(watch);
  updateVideoToggle(watch);
}

async function refreshPageStatus() {
  const thrPct =
    thresholdFromStorage(
      document.getElementById("thresholdPct")
        ? parseInt(document.getElementById("thresholdPct").value, 10)
        : cachedSettings.threshold
    ) || 90;
  const tabs = await findYoutubeTabs();
  if (!tabs.length) {
    renderWatch(null, thrPct);
    return;
  }
  for (const tab of tabs) {
    if (!tab.id) continue;
    const res = await tabsSendMessage(tab.id, { type: "GET_PAGE_STATUS" });
    if (res && res.ok && res.watch) {
      renderWatch(res.watch, thrPct);
      return;
    }
  }
  renderWatch(null, thrPct);
}

function logIsVisible(log) {
  if (!log) return false;
  const id = Number(log.id);
  if (historyClearedMaxId > 0 && Number.isFinite(id) && id > 0) {
    if (id <= historyClearedMaxId) return false;
    return true;
  }
  if (!historyClearedAt) return true;
  if (!log.timestamp) return false;
  try {
    const t = new Date(log.timestamp).getTime();
    const cut = new Date(historyClearedAt).getTime();
    if (Number.isNaN(t) || Number.isNaN(cut)) return false;
    return t > cut;
  } catch (_) {
    return false;
  }
}

function updateQueueBanner() {
  const banner = document.getElementById("queueBanner");
  const text = document.getElementById("queueBannerText");
  const delivery = document.getElementById("secDelivery");
  if (!banner || !text) return;
  const p = lastLocalMeta.pendingCount || 0;
  const e = lastLocalMeta.errorCount || 0;
  if (p + e <= 0) {
    banner.classList.remove("show");
    if (delivery) delivery.hidden = true;
    return;
  }
  banner.classList.add("show");
  if (delivery) delivery.hidden = false;
  const parts = [];
  if (p) parts.push(p + " pending sync");
  if (e) parts.push(e + " failed");
  text.textContent = parts.join(" · ") + " — saved locally, will retry";
}

function badgeForLocalStatus(status) {
  const s = status || "watching";
  const map = {
    watching: "watching",
    ready: "pending",
    pending: "pending",
    accepted: "accepted",
    duplicate: "duplicate",
    error: "error",
    rejected: "rejected",
  };
  return map[s] || "pending";
}

function labelForLocalStatus(status) {
  const s = status || "watching";
  const map = {
    watching: "watching",
    ready: "ready",
    pending: "pending",
    accepted: "synced",
    duplicate: "duplicate",
    error: "error",
    rejected: "rejected",
  };
  return map[s] || s;
}

function appendMetaBits(m, bits, badgeClass, badgeText) {
  if (bits.length) {
    m.appendChild(document.createTextNode(bits.filter(Boolean).join(" · ") + " "));
  }
  if (badgeText) {
    const b = document.createElement("span");
    b.className = "badge " + (badgeClass || "pending");
    b.textContent = badgeText;
    m.appendChild(b);
  }
}

function buildActivityRows() {
  const rows = [];
  const localSorted = (lastLocalEntries || []).slice().sort((a, b) => {
    const rank = (s) =>
      s === "error" ? 0 : s === "pending" || s === "ready" ? 1 : s === "watching" ? 3 : 2;
    const d = rank(a.status) - rank(b.status);
    if (d !== 0) return d;
    return String(b.updatedAt || "").localeCompare(String(a.updatedAt || ""));
  });

  for (const e of localSorted) {
    rows.push({ kind: "local", entry: e });
  }

  const localLogIds = new Set(
    localSorted
      .filter((e) => e.logId != null)
      .map((e) => Number(e.logId))
      .filter((n) => Number.isFinite(n))
  );

  const serverVisible = (lastLogsCache || []).filter(logIsVisible);
  for (const log of serverVisible) {
    if (log.id != null && localLogIds.has(Number(log.id))) continue;
    rows.push({ kind: "server", log });
  }
  return rows;
}

function appendActivityRow(ul, row) {
  const li = document.createElement("li");
  if (row.kind === "local") {
    const e = row.entry;
    const t = document.createElement("div");
    t.className = "t";
    t.textContent = e.title || e.videoId || "video";
    const m = document.createElement("div");
    m.className = "m";
    const bits = [];
    bits.push(formatWhen(e.finishedAt || e.updatedAt));
    if (e.maxRatio != null) bits.push(Math.round((Number(e.maxRatio) || 0) * 100) + "%");
    if (e.durationSeconds) bits.push(formatMinutes(e.durationSeconds / 60));
    bits.push("local");
    appendMetaBits(m, bits, badgeForLocalStatus(e.status), labelForLocalStatus(e.status));
    const canRetry =
      !!e.payload &&
      (e.status === "error" ||
        e.status === "pending" ||
        e.status === "ready" ||
        e.status === "duplicate" ||
        e.status === "accepted" ||
        (e.status === "rejected" &&
          (String(e.serverReason || "").startsWith("http_401") ||
            String(e.serverReason || "").startsWith("http_403") ||
            String(e.lastError || "").includes("webhook secret"))));
    if (canRetry) {
      const actions = document.createElement("span");
      actions.className = "row-actions";
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "secondary mini";
      btn.textContent = e.status === "duplicate" ? "Re-check" : "Retry";
      btn.title =
        e.status === "duplicate"
          ? "Server may have deleted the log — POST again"
          : "Retry delivery";
      btn.addEventListener("click", (ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        if (pageHooks.onRetryLocal) pageHooks.onRetryLocal(e.key);
        else retryLocalEntry(e.key);
      });
      actions.appendChild(btn);
      m.appendChild(actions);
    }
    const detail = e.lastError || e.serverReason || "";
    if (detail && (e.status === "error" || e.status === "rejected")) {
      const err = document.createElement("div");
      err.className = "hint";
      err.style.marginTop = "0.15rem";
      err.textContent = detail;
      li.appendChild(t);
      li.appendChild(m);
      li.appendChild(err);
      ul.appendChild(li);
      return;
    }
    li.appendChild(t);
    li.appendChild(m);
  } else {
    const log = row.log;
    const t = document.createElement("div");
    t.className = "t";
    t.textContent = log.title || "#" + log.id;
    const m = document.createElement("div");
    m.className = "m";
    const bits = [];
    bits.push(formatWhen(log.timestamp));
    bits.push(formatMinutes(log.amount));
    bits.push("server");
    const tadoku = log.tadoku_status || "";
    appendMetaBits(
      m,
      bits,
      tadoku === "ready" || tadoku === "pushed" ? "ready" : tadoku ? "pending" : "server",
      tadoku || "on server"
    );
    li.appendChild(t);
    li.appendChild(m);
  }
  ul.appendChild(li);
}

/**
 * @param {{ limit?: number, emptyMsg?: string }} opts
 */
function renderActivity(opts) {
  const ul = document.getElementById("historyList");
  if (!ul) return;
  const limit = opts && opts.limit != null ? opts.limit : 14;
  const emptyMsg = (opts && opts.emptyMsg) || null;
  ul.innerHTML = "";
  updateQueueBanner();

  const rows = buildActivityRows();

  if (!rows.length) {
    const li = document.createElement("li");
    li.className = "empty";
    li.textContent =
      emptyMsg ||
      (historyClearedAt || historyClearedMaxId
        ? "List cleared. New local/server activity will show here."
        : "No activity yet. Watch past the threshold — progress is saved in this browser.");
    ul.appendChild(li);
    return;
  }

  for (const row of rows.slice(0, limit)) {
    appendActivityRow(ul, row);
  }
}

async function loadLocalActivity() {
  const res = await runtimeSend({ type: "LOCAL_LOG_LIST", opts: { limit: 40 } });
  if (res && res.ok) {
    lastLocalEntries = Array.isArray(res.entries) ? res.entries : [];
    lastLocalMeta = {
      pendingCount: Number(res.pendingCount) || 0,
      errorCount: Number(res.errorCount) || 0,
    };
  } else {
    lastLocalEntries = [];
    lastLocalMeta = { pendingCount: 0, errorCount: 0 };
  }
}

async function retryLocalEntry(key) {
  if (!key) return;
  setStatus("Retrying…");
  const res = await runtimeSend({ type: "LOCAL_LOG_RETRY", key });
  await loadLocalActivity();
  renderActivity(window.__activityRenderOpts || {});
  if (res && (res.ok || (res.entry && (res.entry.status === "accepted" || res.entry.status === "duplicate")))) {
    setStatus("Delivered: " + (res.entry && res.entry.title ? res.entry.title : key), "ok");
    refreshServerAndHistory();
  } else {
    setStatus(
      "Still pending: " +
        ((res && res.entry && (res.entry.lastError || res.entry.serverReason)) ||
          (res && res.error) ||
          "unknown"),
      "err"
    );
  }
}

async function retryAllPending() {
  setStatus("Retrying queue…");
  await runtimeSend({ type: "LOCAL_LOG_RETRY_ALL" });
  await loadLocalActivity();
  await refreshServerAndHistory();
  const p = lastLocalMeta.pendingCount || 0;
  const e = lastLocalMeta.errorCount || 0;
  if (p + e === 0) setStatus("Queue clear.", "ok");
  else setStatus(p + e + " still waiting (will auto-retry).", "err");
}

async function refreshServerAndHistory() {
  const base = baseUrlFromForm();
  updateDashboardLinks();
  setServerChip("warn", "…");

  await loadLocalActivity();
  renderActivity(window.__activityRenderOpts || {});

  try {
    const health = await fetch(base + "/api/health", { method: "GET" });
    if (!health.ok) {
      setServerChip("err", "HTTP " + health.status);
      lastLogsCache = [];
      renderActivity(window.__activityRenderOpts || {});
      return;
    }
    setServerChip("ok", "online");
  } catch (e) {
    setServerChip("err", "offline");
    lastLogsCache = [];
    renderActivity(window.__activityRenderOpts || {});
    return;
  }

  try {
    const r = await fetch(base + "/api/logs?source=youtube&limit=50", { method: "GET" });
    if (!r.ok) {
      lastLogsCache = [];
      renderActivity(window.__activityRenderOpts || {});
      return;
    }
    const body = await r.json();
    lastLogsCache = Array.isArray(body) ? body : [];
    renderActivity(window.__activityRenderOpts || {});
  } catch (_) {
    lastLogsCache = [];
    renderActivity(window.__activityRenderOpts || {});
  }
}

async function clearHistoryList() {
  let maxId = historyClearedMaxId || 0;
  for (const log of lastLogsCache) {
    const id = Number(log && log.id);
    if (Number.isFinite(id) && id > maxId) maxId = id;
  }
  if (!lastLogsCache.length) {
    try {
      const r = await fetch(baseUrlFromForm() + "/api/logs?source=youtube&limit=50", {
        method: "GET",
      });
      if (r.ok) {
        const body = await r.json();
        if (Array.isArray(body)) {
          for (const log of body) {
            const id = Number(log && log.id);
            if (Number.isFinite(id) && id > maxId) maxId = id;
          }
          lastLogsCache = body;
        }
      }
    } catch (_) {}
  }

  historyClearedAt = new Date().toISOString();
  historyClearedMaxId = maxId;
  try {
    await storageSet({
      historyClearedAt,
      historyClearedMaxId,
    });
    await runtimeSend({ type: "LOCAL_LOG_CLEAR_DONE" });
    await loadLocalActivity();
    renderActivity(window.__activityRenderOpts || {});
    setStatus("Cleared synced rows from list. Pending queue kept.", "ok");
  } catch (e) {
    setStatus("Could not clear list: " + e, "err");
  }
}

function channelTokensFromWatch(watch) {
  if (!watch) return [];
  if (watch.channelId) return [watch.channelId];
  return [];
}

/** Single channel control: block ↔ allow (works with or without form fields). */
async function onToggleChannel() {
  const watch = lastWatch;
  const tokens = channelTokensFromWatch(watch);
  if (!tokens.length) {
    setStatus("No channel on this video yet — wait a moment.", "err");
    return;
  }

  const hasForm = !!document.getElementById("channelBlocklist");
  if (hasForm) {
    if (watch.channelOnBlocklist) {
      removeFromListField("channelBlocklist", tokens);
      addToListField("channelAllowlist", tokens);
      await persistSettings();
      setStatus("Channel allowed: " + tokens[0], "ok");
    } else if (watch.channelMode === "allowlist" && !watch.channelOnAllowlist) {
      addToListField("channelAllowlist", tokens);
      removeFromListField("channelBlocklist", tokens);
      await persistSettings();
      setStatus("Channel added to allowlist: " + tokens[0], "ok");
    } else {
      addToListField("channelBlocklist", tokens);
      removeFromListField("channelAllowlist", tokens);
      await persistSettings();
      setStatus("Channel blocked: " + tokens[0], "ok");
    }
  } else {
    let allow = cachedSettings.channelAllowlist || "";
    let block = cachedSettings.channelBlocklist || "";
    if (watch.channelOnBlocklist) {
      block = removeTokensFromList(block, tokens);
      allow = addTokensToList(allow, tokens);
      await storageSet({ channelAllowlist: allow, channelBlocklist: block });
      setStatus("Channel allowed: " + tokens[0], "ok");
    } else if (watch.channelMode === "allowlist" && !watch.channelOnAllowlist) {
      allow = addTokensToList(allow, tokens);
      block = removeTokensFromList(block, tokens);
      await storageSet({ channelAllowlist: allow, channelBlocklist: block });
      setStatus("Channel added to allowlist: " + tokens[0], "ok");
    } else {
      block = addTokensToList(block, tokens);
      allow = removeTokensFromList(allow, tokens);
      await storageSet({ channelAllowlist: allow, channelBlocklist: block });
      setStatus("Channel blocked: " + tokens[0], "ok");
    }
  }
  refreshPageStatus();
}

async function onToggleVideo() {
  const watch = lastWatch;
  if (!watch || !watch.videoId) {
    setStatus("No video id.", "err");
    return;
  }
  const hasForm = !!document.getElementById("videoBlocklist");
  if (hasForm) {
    if (watch.videoOnBlocklist) {
      removeVideoId("videoBlocklist", watch.videoId);
      await persistSettings();
      setStatus("Video unblocked: " + watch.videoId, "ok");
    } else {
      addVideoId("videoBlocklist", watch.videoId);
      await persistSettings();
      setStatus("Video blocked: " + watch.videoId, "ok");
    }
  } else {
    let list = cachedSettings.videoBlocklist || "";
    const id = String(watch.videoId).trim();
    if (watch.videoOnBlocklist) {
      list = joinLines(parseLines(list).filter((v) => v !== id));
      await storageSet({ videoBlocklist: list });
      setStatus("Video unblocked: " + watch.videoId, "ok");
    } else {
      const set = new Set(parseLines(list));
      set.add(id);
      await storageSet({ videoBlocklist: joinLines(Array.from(set)) });
      setStatus("Video blocked: " + watch.videoId, "ok");
    }
  }
  refreshPageStatus();
}

async function forceQueueThisTab() {
  setStatus("Queueing this tab…");
  const tabs = await findYoutubeTabs();
  if (!tabs.length || !tabs[0].id) {
    setStatus("Open a YouTube watch tab first.", "err");
    return;
  }
  const res = await tabsSendMessage(tabs[0].id, {
    type: "FORCE_QUEUE",
    opts: { forceComplete: true },
  });
  if (res && res._error) {
    setStatus("Tab not ready — reload the YouTube page, then try again.", "err");
    return;
  }
  if (res && res.ok === false && res.error === "filtered") {
    setStatus("Blocked by filters: " + (res.skip || "filtered"), "err");
    return;
  }
  if (res && (res.ok || (res.entry && res.entry.status))) {
    setStatus(
      "Queued: " +
        ((res.entry && res.entry.title) ||
          (res.body && res.body.reason) ||
          "ok"),
      res.ok === false ? "err" : "ok"
    );
  } else {
    setStatus(
      "Queue failed: " + ((res && (res.error || res._error)) || "unknown"),
      "err"
    );
  }
  await refreshServerAndHistory();
  await refreshPageStatus();
}

async function loadSettingsIntoCache() {
  try {
    await migrateSyncToLocal();
  } catch (_) {}
  const cfg = await storageGet(defaults);
  const merged = Object.assign({}, defaults, cfg);
  if (cfg && cfg.uiSections && typeof cfg.uiSections === "object") {
    merged.uiSections = Object.assign({}, defaults.uiSections, cfg.uiSections);
  }
  cachedSettings = Object.assign({}, merged);
  historyClearedAt = merged.historyClearedAt || "";
  historyClearedMaxId = Number(merged.historyClearedMaxId) || 0;
  return merged;
}

function wireNavButtons() {
  const openSettings = document.getElementById("openSettings");
  if (openSettings) {
    openSettings.addEventListener("click", (e) => {
      e.preventDefault();
      openSettingsPage();
    });
  }
  const openHistory = document.getElementById("openHistory");
  if (openHistory) {
    openHistory.addEventListener("click", (e) => {
      e.preventDefault();
      openHistoryPage();
    });
  }
  const openImport = document.getElementById("openImport");
  if (openImport) {
    openImport.addEventListener("click", (e) => {
      e.preventDefault();
      openImportPage();
    });
  }
  const openSettingsLink = document.getElementById("linkSettings");
  if (openSettingsLink) {
    openSettingsLink.addEventListener("click", (e) => {
      e.preventDefault();
      openSettingsPage();
    });
  }
  const openHistoryLink = document.getElementById("linkHistory");
  if (openHistoryLink) {
    openHistoryLink.addEventListener("click", (e) => {
      e.preventDefault();
      openHistoryPage();
    });
  }
  const openImportLink = document.getElementById("linkImport");
  if (openImportLink) {
    openImportLink.addEventListener("click", (e) => {
      e.preventDefault();
      openImportPage();
    });
  }
}
