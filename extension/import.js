/* global
  loadSettingsIntoCache, applyConfigToForm, updateDashboardLinks,
  runtimeSend, wireNavButtons, setStatus, setServerChip, storageGet, storageSet,
  openHistoryPage, openSettingsPage, openImportPage, cachedSettings
*/

/** @type {Array<any>} */
let readyCandidates = [];
/** @type {Array<any>} */
let unfinishedCandidates = [];
let activeTab = "ready"; // "ready" | "unfinished"
let lastViewer = { viewerChannelId: "", viewerHandle: "" };
let lastSettings = {
  minWatchedSeconds: 300,
  threshold: 0.9,
  preferJapanese: true,
};
let lastScanMetaHtml = "";
let scanning = false;
let logging = false;
let persistTimer = null;
let sectionCollapsed = false;

const SCAN_CACHE_KEY = "historyScanCache";
const SCAN_CACHE_TTL_MS = 7 * 86400000;
const COLLAPSED_KEY = "historyImportCollapsed";

function importUiPresent() {
  return !!document.getElementById("scanHistory");
}

/** Popup (and any host with data-import-compact) — ready-only compact UI. */
function isCompactImport() {
  if (document.body && document.body.classList.contains("popup")) return true;
  const sec = document.getElementById("secLogHistory");
  return !!(sec && sec.getAttribute("data-import-compact") === "1");
}

function allCandidates() {
  return readyCandidates.concat(unfinishedCandidates);
}

function activeList() {
  // Compact popup only lists ready-to-log videos
  if (isCompactImport()) return readyCandidates;
  return activeTab === "unfinished" ? unfinishedCandidates : readyCandidates;
}

function updateSectionHint() {
  const hint = document.getElementById("importSectionHint");
  if (!hint) return;
  if (isCompactImport()) {
    const n = readyCandidates.length;
    const u = unfinishedCandidates.length;
    if (n || u) {
      hint.textContent =
        n + " ready" + (u ? " · " + u + " unfinished" : "") + (sectionCollapsed ? " · collapsed" : "");
    } else {
      hint.textContent = sectionCollapsed ? "collapsed" : "ready only";
    }
  }
}

function applySectionCollapsed(collapsed) {
  sectionCollapsed = !!collapsed;
  const sec = document.getElementById("secLogHistory");
  const body = document.getElementById("logHistoryBody");
  const btn = document.getElementById("toggleLogHistory");
  if (sec) sec.classList.toggle("is-collapsed", sectionCollapsed);
  if (body) body.hidden = sectionCollapsed;
  if (btn) {
    btn.setAttribute("aria-expanded", sectionCollapsed ? "false" : "true");
    const chev = btn.querySelector(".collapse-chevron");
    if (chev) chev.textContent = sectionCollapsed ? "▸" : "▾";
  }
  updateSectionHint();
}

async function persistSectionCollapsed() {
  try {
    await storageSet({ [COLLAPSED_KEY]: sectionCollapsed });
  } catch (_) {}
}

function setImportStatus(text, kind) {
  const el =
    document.getElementById("importStatus") || document.getElementById("status");
  if (!el) {
    setStatus(text, kind);
    return;
  }
  el.textContent = text || "";
  el.classList.remove("ok", "err");
  if (kind === "ok" || kind === "err") el.classList.add(kind);
}

function fmtDuration(sec) {
  const s = Math.max(0, Math.floor(Number(sec) || 0));
  if (!s) return "?—?";
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const r = s % 60;
  if (h > 0) {
    return h + ":" + String(m).padStart(2, "0") + ":" + String(r).padStart(2, "0");
  }
  return m + ":" + String(r).padStart(2, "0");
}

function fmtWhen(iso, sectionLabel, dateUnknown) {
  if (sectionLabel) {
    if (dateUnknown) return sectionLabel + " (date approx.)";
    return sectionLabel;
  }
  if (!iso) return "recent";
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "recent";
    return d.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
  } catch (_) {
    return "recent";
  }
}

function decisionCounts(list) {
  let approve = 0;
  let reject = 0;
  let pending = 0;
  for (const c of list) {
    if (c.decision === "approve") approve++;
    else if (c.decision === "reject") reject++;
    else pending++;
  }
  return { approve, reject, pending };
}

function updateTabChrome() {
  const readyBtn = document.getElementById("tabReady");
  const unfinishedBtn = document.getElementById("tabUnfinished");
  if (readyBtn) {
    readyBtn.classList.toggle("active", activeTab === "ready");
    readyBtn.setAttribute("aria-selected", activeTab === "ready" ? "true" : "false");
  }
  if (unfinishedBtn) {
    unfinishedBtn.classList.toggle("active", activeTab === "unfinished");
    unfinishedBtn.setAttribute(
      "aria-selected",
      activeTab === "unfinished" ? "true" : "false"
    );
  }
  const rc = document.getElementById("readyCount");
  if (rc) rc.textContent = String(readyCandidates.length);
  const uc = document.getElementById("unfinishedCount");
  if (uc) uc.textContent = String(unfinishedCandidates.length);

  const minW = lastSettings.minWatchedSeconds || 300;
  const thrPct = Math.round((lastSettings.threshold || 0.9) * 100);
  const hint = document.getElementById("tabHint");
  if (hint) {
    if (isCompactImport()) {
      hint.textContent = "";
      hint.hidden = true;
    } else if (activeTab === "ready") {
      hint.hidden = false;
      hint.textContent =
        "Only videos with known progress ≥ " +
        thrPct +
        "% and ≥ " +
        Math.round(minW / 60) +
        " min watched (history bar or live tracking). Appearing in history alone is not enough. Approve still logs a full watch.";
    } else {
      hint.hidden = false;
      hint.textContent =
        "Partial progress, no progress data, shorter than " +
        Math.round(minW / 60) +
        " min, or duration unknown. Finished watches often lack a history % — Approve here if you completed them.";
    }
  }

  const reviewCount = document.getElementById("reviewCount");
  if (reviewCount) {
    const n = allCandidates().length;
    reviewCount.textContent =
      n +
      " total · " +
      readyCandidates.length +
      " ready · " +
      unfinishedCandidates.length +
      " unfinished";
  }
  updateSectionHint();
}

function updateSummary() {
  updateTabChrome();
  const list = activeList();
  const { approve, reject, pending } = decisionCounts(list);
  const sum = document.getElementById("decisionSummary");
  if (sum) {
    if (isCompactImport()) {
      sum.textContent =
        readyCandidates.length +
        " ready" +
        (approve ? " · " + approve + "✓" : "") +
        (unfinishedCandidates.length
          ? " · " + unfinishedCandidates.length + " unfinished on full page"
          : "");
    } else {
      sum.textContent =
        approve + " approve · " + reject + " reject · " + pending + " undecided (this tab)";
    }
  }
  // Compact: only log ready approvals; full page can log both buckets
  const approvePool = isCompactImport()
    ? decisionCounts(readyCandidates).approve
    : decisionCounts(allCandidates()).approve;
  const rejectPool = isCompactImport()
    ? 0
    : decisionCounts(allCandidates()).reject;
  const batch = document.getElementById("batchLog");
  if (batch) batch.disabled = logging || approvePool === 0;
  const rej = document.getElementById("saveRejects");
  if (rej) rej.disabled = logging || rejectPool === 0;
}

function findCandidate(videoId) {
  return (
    readyCandidates.find((x) => x.videoId === videoId) ||
    unfinishedCandidates.find((x) => x.videoId === videoId)
  );
}

function schedulePersistScan() {
  if (persistTimer) clearTimeout(persistTimer);
  persistTimer = setTimeout(() => {
    persistTimer = null;
    persistScanCache().catch(() => {});
  }, 400);
}

function setDecision(videoId, decision) {
  const c = findCandidate(videoId);
  if (!c) return;
  c.decision = decision;
  const items = document.querySelectorAll("li.import-item");
  let li = null;
  for (const el of items) {
    if (el.getAttribute("data-vid") === videoId) {
      li = el;
      break;
    }
  }
  if (li) {
    li.dataset.decision = decision;
    li.classList.remove("dec-approve", "dec-reject", "dec-pending");
    li.classList.add(
      decision === "approve"
        ? "dec-approve"
        : decision === "reject"
          ? "dec-reject"
          : "dec-pending"
    );
    const group = li.querySelector(".import-decision");
    if (group) {
      group.querySelectorAll("button").forEach((btn) => {
        btn.classList.toggle("active", btn.dataset.decision === decision);
      });
    }
  }
  updateSummary();
  schedulePersistScan();
}

function setActiveTab(tab) {
  activeTab = tab === "unfinished" ? "unfinished" : "ready";
  renderList();
  schedulePersistScan();
}

function renderList() {
  const ul = document.getElementById("importList");
  const card = document.getElementById("reviewCard");
  if (!ul) return;
  const compact = isCompactImport();
  // Compact: show card whenever we have a scan (even 0 ready) so empty state is clear
  const total = compact ? readyCandidates.length : allCandidates().length;
  const hasScan =
    readyCandidates.length > 0 ||
    unfinishedCandidates.length > 0 ||
    !!lastScanMetaHtml;
  if (card) {
    if (compact) card.hidden = !hasScan && !scanning && total === 0;
    else card.hidden = total === 0 && !scanning && !hasScan;
  }

  updateTabChrome();
  const list = activeList();

  if (!list.length) {
    if (compact) {
      ul.innerHTML =
        unfinishedCandidates.length > 0
          ? '<li class="empty">No ready videos. ' +
            unfinishedCandidates.length +
            ' unfinished — use <strong>Full page</strong>.</li>'
          : '<li class="empty">No ready videos. Scan history or open Full page.</li>';
    } else {
      ul.innerHTML =
        activeTab === "unfinished"
          ? '<li class="empty">No unfinished / short videos in this window.</li>'
          : '<li class="empty">No ready videos. Check the Unfinished tab, lengthen lookback, or relax filters.</li>';
    }
    updateSummary();
    return;
  }

  if (card) card.hidden = false;
  ul.innerHTML = "";
  for (const c of list) {
    const li = document.createElement("li");
    li.className = "import-item dec-" + (c.decision || "pending");
    li.dataset.vid = c.videoId;
    li.dataset.decision = c.decision || "pending";

    const thumbWrap = document.createElement("a");
    thumbWrap.className = "import-thumb-link";
    thumbWrap.href = c.url || "https://www.youtube.com/watch?v=" + c.videoId;
    thumbWrap.target = "_blank";
    thumbWrap.rel = "noopener";
    thumbWrap.title = "Open on YouTube";
    const img = document.createElement("img");
    img.className = "import-thumb";
    img.alt = "";
    img.loading = "lazy";
    img.src =
      c.thumbnail ||
      "https://i.ytimg.com/vi/" + c.videoId + "/hqdefault.jpg";
    img.addEventListener("error", () => {
      if (img.dataset.fallback) return;
      img.dataset.fallback = "1";
      img.src = "https://i.ytimg.com/vi/" + c.videoId + "/mqdefault.jpg";
    });
    thumbWrap.appendChild(img);

    const main = document.createElement("div");
    main.className = "import-main";

    const title = document.createElement("a");
    title.className = "import-title";
    title.href = c.url || "https://www.youtube.com/watch?v=" + c.videoId;
    title.target = "_blank";
    title.rel = "noopener";
    title.textContent = c.title || c.videoId;

    const meta = document.createElement("div");
    meta.className = "import-meta-line";
    const bits = [];
    if (c.channelTitle) bits.push(c.channelTitle);
    bits.push(c.durationSeconds ? fmtDuration(c.durationSeconds) : "duration unknown");
    const pct =
      c.percentWatched != null && Number.isFinite(Number(c.percentWatched))
        ? Math.round(Number(c.percentWatched))
        : null;
    if (pct != null && Number.isFinite(pct)) {
      bits.push(pct + "% watched");
    }
    bits.push(fmtWhen(c.watchedAt, c.sectionLabel, c.dateUnknown));
    if (c.language) bits.push(c.language);
    if (c.unfinishedReason === "below_min_watched") {
      bits.push("< " + Math.round((lastSettings.minWatchedSeconds || 300) / 60) + " min");
    } else if (c.unfinishedReason === "duration_unknown") {
      bits.push("needs duration lookup");
    } else if (c.unfinishedReason === "partial_progress") {
      bits.push("under threshold");
    } else if (c.unfinishedReason === "progress_unknown") {
      bits.push("progress unknown");
    }
    meta.textContent = bits.join(" · ");

    main.appendChild(title);
    main.appendChild(meta);

    if (pct != null && Number.isFinite(pct)) {
      const bar = document.createElement("div");
      bar.className = "import-progress";
      bar.title = pct + "% watched";
      const fill = document.createElement("div");
      fill.className = "import-progress-fill";
      fill.style.width = Math.min(100, Math.max(0, pct)) + "%";
      if (pct >= Math.round((lastSettings.threshold || 0.9) * 100)) {
        fill.classList.add("met");
      }
      bar.appendChild(fill);
      main.appendChild(bar);
    }

    const actions = document.createElement("div");
    actions.className = "import-decision";
    const decisions = compact
      ? [
          ["approve", "✓"],
          ["pending", "·"],
          ["reject", "✕"],
        ]
      : [
          ["approve", "Approve"],
          ["reject", "Reject"],
          ["pending", "Skip"],
        ];
    for (const [dec, label] of decisions) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className =
        "mini secondary" + (c.decision === dec ? " active" : "");
      btn.dataset.decision = dec;
      btn.title =
        dec === "approve" ? "Approve" : dec === "reject" ? "Reject" : "Skip";
      btn.textContent = label;
      btn.addEventListener("click", () => setDecision(c.videoId, dec));
      actions.appendChild(btn);
    }

    li.appendChild(thumbWrap);
    li.appendChild(main);
    li.appendChild(actions);
    ul.appendChild(li);
  }
  updateSummary();
}

async function refreshServerChip() {
  try {
    const base = (cachedSettings.serverUrl || "http://127.0.0.1:8000").replace(/\/$/, "");
    const r = await fetch(base + "/api/health");
    if (r.ok) setServerChip("ok", "Server OK");
    else setServerChip("err", "Server " + r.status);
  } catch (_) {
    setServerChip("err", "Offline");
  }
}

function readLookbackDays() {
  return parseInt(
    (document.getElementById("lookbackDays") || {}).value || "7",
    10
  );
}

function readApplyFilters() {
  return !!(document.getElementById("applyFilters") || {}).checked;
}

async function persistImportSettings() {
  try {
    await storageSet({
      historyLookbackDays: readLookbackDays(),
      historyApplyFilters: readApplyFilters(),
    });
  } catch (_) {}
}

async function persistScanCache() {
  const payload = {
    at: Date.now(),
    lookbackDays: readLookbackDays(),
    applyFilters: readApplyFilters(),
    activeTab,
    viewer: lastViewer,
    settings: lastSettings,
    metaHtml: lastScanMetaHtml,
    candidates: readyCandidates,
    unfinished: unfinishedCandidates,
  };
  try {
    await storageSet({ [SCAN_CACHE_KEY]: payload });
  } catch (_) {}
}

function applyScanResult(res, opts) {
  const fromCache = !!(opts && opts.fromCache);
  lastViewer = res.viewer || lastViewer;
  if (res.settings) {
    lastSettings = Object.assign({}, lastSettings, res.settings);
  }

  readyCandidates = (res.candidates || []).map((c) =>
    Object.assign({}, c, {
      decision: c.decision || "pending",
      bucket: "ready",
    })
  );
  unfinishedCandidates = (res.unfinished || []).map((c) =>
    Object.assign({}, c, {
      decision: c.decision || "pending",
      bucket: "unfinished",
    })
  );

  if (opts && opts.activeTab) {
    activeTab = opts.activeTab === "unfinished" ? "unfinished" : "ready";
  } else {
    activeTab = readyCandidates.length
      ? "ready"
      : unfinishedCandidates.length
        ? "unfinished"
        : "ready";
  }

  const sk = res.skipped || {};
  const viewerLabel =
    (res.viewer && (res.viewer.viewerHandle || res.viewer.viewerChannelId)) ||
    "signed-in account";
  const minW = (res.settings && res.settings.minWatchedSeconds) || 300;
  const meta = document.getElementById("scanMeta");
  if (meta) {
    meta.hidden = false;
    if (fromCache && res.metaHtml) {
      meta.innerHTML = res.metaHtml;
      lastScanMetaHtml = res.metaHtml;
    } else {
      lastScanMetaHtml =
        "Account: <strong>" +
        escapeHtml(viewerLabel) +
        "</strong> · lookback " +
        (res.lookbackDays != null ? res.lookbackDays : readLookbackDays()) +
        "d · scanned " +
        (res.scanned != null ? res.scanned : "?") +
        " (" +
        (res.rawFound != null ? res.rawFound : "?") +
        " raw / " +
        (res.pages != null ? res.pages : "?") +
        " page" +
        (res.pages === 1 ? "" : "s") +
        ") · ready " +
        readyCandidates.length +
        " · unfinished " +
        unfinishedCandidates.length +
        " · min-watch " +
        Math.round(minW / 60) +
        "m · skipped logged " +
        (sk.alreadyLogged || 0) +
        ", rejected " +
        (sk.rejected || 0) +
        ", filtered " +
        (sk.filters || 0) +
        (sk.language ? " (lang " + sk.language + ")" : "") +
        (res.enrich
          ? " · durations filled " +
            (res.enrich.filled != null ? res.enrich.filled : res.enrich.fetched || 0) +
            (res.enrich.cacheHits ? ", cache " + res.enrich.cacheHits : "") +
            (res.enrich.languages ? ", lang " + res.enrich.languages : "") +
            (res.enrich.watchPages ? ", pages " + res.enrich.watchPages : "") +
            (res.enrich.remaining
              ? " (" + res.enrich.remaining + " still unknown)"
              : "")
          : "") +
        (fromCache ? " · <em>restored from last scan</em>" : "");
      meta.innerHTML = lastScanMetaHtml;
    }
  }

  const total = readyCandidates.length + unfinishedCandidates.length;
  if (isCompactImport()) {
    setImportStatus(
      fromCache
        ? readyCandidates.length
          ? readyCandidates.length +
            " ready restored" +
            (unfinishedCandidates.length
              ? " · " + unfinishedCandidates.length + " unfinished on Full page"
              : "")
          : unfinishedCandidates.length
            ? "0 ready · " + unfinishedCandidates.length + " unfinished on Full page"
            : "Last scan empty — re-scan if needed"
        : readyCandidates.length
          ? readyCandidates.length +
            " ready to log" +
            (unfinishedCandidates.length
              ? " · " + unfinishedCandidates.length + " unfinished on Full page"
              : "")
          : unfinishedCandidates.length
            ? "0 ready · open Full page for " + unfinishedCandidates.length + " unfinished"
            : "No new videos in this window",
      readyCandidates.length && !fromCache ? "ok" : ""
    );
  } else {
    setImportStatus(
      fromCache
        ? total
          ? "Restored last scan (" +
            readyCandidates.length +
            " ready · " +
            unfinishedCandidates.length +
            " unfinished). Re-scan to refresh."
          : "Restored last scan — no candidates. Re-scan if needed."
        : total
          ? "Found " +
            readyCandidates.length +
            " ready · " +
            unfinishedCandidates.length +
            " unfinished. Review and log."
          : "No new videos to log in this window.",
      total && !fromCache ? "ok" : ""
    );
  }
  renderList();
}

async function scan() {
  if (scanning) return;
  scanning = true;
  const btn = document.getElementById("scanHistory");
  if (btn) btn.disabled = true;
  setImportStatus("Scanning YouTube history…", "");
  const meta = document.getElementById("scanMeta");
  if (meta) {
    meta.hidden = false;
    meta.textContent = "Fetching feed/history (signed-in session)…";
  }

  const lookbackDays = readLookbackDays();
  const applyFilters = readApplyFilters();
  await persistImportSettings();

  try {
    const res = await runtimeSend({
      type: "HISTORY_SCAN",
      opts: { lookbackDays, applyFilters },
    });

    if (!res || !res.ok) {
      const err = (res && res.error) || "scan_failed";
      const hint = (res && res.hint) || "";
      setImportStatus((hint || err) + (hint ? " (" + err + ")" : ""), "err");
      if (meta) {
        meta.textContent = hint || String(err);
      }
      readyCandidates = [];
      unfinishedCandidates = [];
      renderList();
      return;
    }

    applyScanResult(res, { fromCache: false });
    await persistScanCache();
  } catch (e) {
    setImportStatus(String(e), "err");
  } finally {
    scanning = false;
    if (btn) btn.disabled = false;
  }
}

function escapeHtml(s) {
  return String(s || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

async function batchLog() {
  if (logging) return;
  // Compact popup only logs from the ready list
  const pool = isCompactImport() ? readyCandidates : allCandidates();
  const approved = pool.filter((c) => c.decision === "approve");
  if (!approved.length) {
    setImportStatus("Approve at least one video first.", "err");
    return;
  }

  logging = true;
  updateSummary();
  setImportStatus("Logging " + approved.length + " video(s)…", "");

  const rejected = isCompactImport()
    ? readyCandidates.filter((c) => c.decision === "reject")
    : allCandidates().filter((c) => c.decision === "reject");
  if (rejected.length) {
    await runtimeSend({
      type: "HISTORY_REJECT",
      videoIds: rejected.map((c) => c.videoId),
    });
  }

  try {
    const res = await runtimeSend({
      type: "HISTORY_BATCH_LOG",
      items: approved,
      opts: {
        viewerChannelId: lastViewer.viewerChannelId || "",
        viewerHandle: lastViewer.viewerHandle || "",
      },
    });

    if (!res) {
      setImportStatus("No response from extension background.", "err");
      return;
    }

    const logged = res.logged || 0;
    const dupes = res.duplicates || 0;
    const failed = res.failed || 0;
    const parts = [];
    if (logged) parts.push(logged + " logged");
    if (dupes) parts.push(dupes + " already known");
    if (failed) parts.push(failed + " failed");
    if (rejected.length) parts.push(rejected.length + " rejected saved");

    setImportStatus(parts.join(" · ") || "Done", failed ? "err" : "ok");

    const doneIds = new Set(
      (res.results || [])
        .filter((r) => r.ok || r.reason === "duplicate")
        .map((r) => r.videoId)
    );
    for (const r of rejected) doneIds.add(r.videoId);
    readyCandidates = readyCandidates.filter((c) => !doneIds.has(c.videoId));
    unfinishedCandidates = unfinishedCandidates.filter((c) => !doneIds.has(c.videoId));
    renderList();
    await persistScanCache();

    if (failed && res.results) {
      const firstFail = res.results.find((r) => !r.ok);
      if (firstFail) {
        console.warn("[immersion-tracker] import failures", res.results);
        setImportStatus(
          (parts.join(" · ") || "Partial") +
            " — e.g. " +
            (firstFail.videoId || "") +
            ": " +
            (firstFail.reason || firstFail.error || "error"),
          "err"
        );
      }
    }
  } catch (e) {
    setImportStatus(String(e), "err");
  } finally {
    logging = false;
    updateSummary();
  }
}

async function saveRejectsOnly() {
  const rejected = allCandidates().filter((c) => c.decision === "reject");
  if (!rejected.length) return;
  await runtimeSend({
    type: "HISTORY_REJECT",
    videoIds: rejected.map((c) => c.videoId),
  });
  const ids = new Set(rejected.map((c) => c.videoId));
  readyCandidates = readyCandidates.filter((c) => !ids.has(c.videoId));
  unfinishedCandidates = unfinishedCandidates.filter((c) => !ids.has(c.videoId));
  setImportStatus("Saved " + rejected.length + " reject(s). Hidden on future scans.", "ok");
  renderList();
  await persistScanCache();
}

async function restoreScanCache() {
  try {
    const stored = await storageGet({ [SCAN_CACHE_KEY]: null });
    const cache = stored[SCAN_CACHE_KEY];
    if (!cache || typeof cache !== "object") return false;
    if (cache.at && Date.now() - Number(cache.at) > SCAN_CACHE_TTL_MS) return false;
    const hasRows =
      (Array.isArray(cache.candidates) && cache.candidates.length) ||
      (Array.isArray(cache.unfinished) && cache.unfinished.length) ||
      cache.metaHtml;
    if (!hasRows) return false;
    applyScanResult(
      {
        ok: true,
        viewer: cache.viewer,
        settings: cache.settings,
        candidates: cache.candidates || [],
        unfinished: cache.unfinished || [],
        skipped: {},
        lookbackDays: cache.lookbackDays,
        metaHtml: cache.metaHtml,
      },
      { fromCache: true, activeTab: cache.activeTab }
    );
    return true;
  } catch (_) {
    return false;
  }
}

async function loadImportUi() {
  if (!importUiPresent()) return;

  const merged = await loadSettingsIntoCache();
  // Don't wipe activity status when both panels share the page
  if (document.getElementById("importStatus")) {
    /* settings already in cache */
  } else {
    applyConfigToForm(merged);
    updateDashboardLinks();
  }
  lastSettings.minWatchedSeconds = Number(merged.minWatchedSeconds) || 300;
  lastSettings.threshold = Number(merged.threshold) || 0.9;
  lastSettings.preferJapanese = merged.preferJapanese !== false;
  await refreshServerChip();

  try {
    const stored = await storageGet({
      historyLookbackDays: 7,
      historyApplyFilters: true,
      [COLLAPSED_KEY]: true,
    });
    const days = Number(stored.historyLookbackDays) || 7;
    const sel = document.getElementById("lookbackDays");
    if (sel) {
      const opt = Array.from(sel.options).find((o) => Number(o.value) === days);
      if (opt) sel.value = String(days);
    }
    const af = document.getElementById("applyFilters");
    if (af) {
      af.checked = stored.historyApplyFilters !== false;
    }
    if (isCompactImport()) {
      applySectionCollapsed(stored[COLLAPSED_KEY] === true);
    }
  } catch (_) {}

  await restoreScanCache();
  updateSectionHint();
}

function wireImportUi() {
  if (!importUiPresent()) return;

  const scanBtn = document.getElementById("scanHistory");
  if (scanBtn) scanBtn.addEventListener("click", () => scan());
  const batchBtn = document.getElementById("batchLog");
  if (batchBtn) batchBtn.addEventListener("click", () => batchLog());
  const saveRej = document.getElementById("saveRejects");
  if (saveRej) saveRej.addEventListener("click", () => saveRejectsOnly());
  const approveAll = document.getElementById("approveAll");
  if (approveAll) {
    approveAll.addEventListener("click", () => {
      for (const c of activeList()) c.decision = "approve";
      renderList();
      schedulePersistScan();
    });
  }
  const rejectAll = document.getElementById("rejectAll");
  if (rejectAll) {
    rejectAll.addEventListener("click", () => {
      for (const c of activeList()) c.decision = "reject";
      renderList();
      schedulePersistScan();
    });
  }
  const reset = document.getElementById("resetDecisions");
  if (reset) {
    reset.addEventListener("click", () => {
      for (const c of activeList()) c.decision = "pending";
      renderList();
      schedulePersistScan();
    });
  }
  const tabReady = document.getElementById("tabReady");
  if (tabReady) tabReady.addEventListener("click", () => setActiveTab("ready"));
  const tabUnf = document.getElementById("tabUnfinished");
  if (tabUnf) tabUnf.addEventListener("click", () => setActiveTab("unfinished"));
  const openYt = document.getElementById("openYtHistory");
  if (openYt) {
    openYt.addEventListener("click", () => {
      const url = "https://www.youtube.com/feed/history";
      if (typeof browser !== "undefined" && browser.tabs && browser.tabs.create) {
        browser.tabs.create({ url });
      } else if (typeof chrome !== "undefined" && chrome.tabs && chrome.tabs.create) {
        chrome.tabs.create({ url });
      } else {
        window.open(url, "_blank");
      }
    });
  }

  const lookback = document.getElementById("lookbackDays");
  if (lookback) {
    lookback.addEventListener("change", () => {
      persistImportSettings();
    });
  }
  const applyFilters = document.getElementById("applyFilters");
  if (applyFilters) {
    applyFilters.addEventListener("change", () => {
      persistImportSettings();
    });
  }

  const toggle = document.getElementById("toggleLogHistory");
  if (toggle) {
    toggle.addEventListener("click", (e) => {
      e.preventDefault();
      applySectionCollapsed(!sectionCollapsed);
      persistSectionCollapsed();
    });
  }
  const openFull = document.getElementById("openImportFull");
  if (openFull) {
    openFull.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      if (typeof openImportPage === "function") openImportPage();
      else if (typeof openHistoryPage === "function") openHistoryPage();
    });
  }
}

// Wire controls when present. Host pages (popup.js / history.js) call load().
wireImportUi();
window.__immersionImport = {
  load: loadImportUi,
  isPresent: importUiPresent,
};
