/* Settings page — advanced filters, connection, viewer allowlist. */

function setDetectPanel(state, title, detail) {
  const panel = document.getElementById("secViewer");
  if (!panel) return;
  panel.classList.remove("ok", "warn", "err");
  panel.classList.add("settings-block", "detect-panel");
  if (state) panel.classList.add(state);
  const det = document.getElementById("detected");
  const detD = document.getElementById("detectDetail");
  if (det) det.textContent = title;
  if (detD) detD.textContent = detail || "";
}

function setUseEnabled(on) {
  const btn = document.getElementById("useDetected");
  if (btn) btn.disabled = !on;
}

async function detectViewer() {
  lastDetected = { handle: "", channelId: "" };
  setUseEnabled(false);

  setDetectPanel(
    "warn",
    "Checking…",
    "Resolving signed-in account (history session, open YouTube tabs, or cache)."
  );
  setStatus("Detecting account…");

  const btn = document.getElementById("detect");
  if (btn) btn.disabled = true;
  try {
    // Background resolves without requiring this tab to be YouTube
    const res = await runtimeSend({ type: "DETECT_VIEWER" });
    const handle = ((res && res.viewerHandle) || "").trim();
    const channelId = ((res && res.viewerChannelId) || "").trim();

    if (handle || channelId) {
      lastDetected = { handle, channelId };
      const lines = [];
      if (handle) lines.push("Handle: " + handle);
      if (channelId) lines.push("Channel id: " + channelId);
      if (res && res.source) lines.push("Source: " + res.source);
      lines.push("", "Click “Add to viewer list” to restrict logging to this account.");
      setDetectPanel("ok", handle || channelId, lines.join("\n"));
      setUseEnabled(true);
      setStatus("Detected: " + (handle || channelId), "ok");
      return;
    }

    // Fallback: open YouTube tabs (content script may have richer DOM)
    if (api && api.tabs) {
      const tabs = await findYoutubeTabs();
      let lastErr = "";
      for (const tab of tabs) {
        if (!tab.id) continue;
        const page = await tabsSendMessage(tab.id, { type: "GET_PAGE_STATUS" });
        if (!page || page._error) {
          lastErr = (page && page._error) || "no response";
          continue;
        }
        const h = (page.viewerHandle || "").trim();
        const c = (page.viewerChannelId || "").trim();
        if (!h && !c) {
          lastErr = "signed-in channel not found yet on this tab";
          continue;
        }
        lastDetected = { handle: h, channelId: c };
        setDetectPanel(
          "ok",
          h || c,
          [h && "Handle: " + h, c && "Channel id: " + c, "Source: open-tab"]
            .filter(Boolean)
            .join("\n")
        );
        setUseEnabled(true);
        setStatus("Detected: " + (h || c), "ok");
        return;
      }
      if (tabs.length && lastErr) {
        setDetectPanel(
          "err",
          "Could not read signed-in account",
          "Detail: " + lastErr + "\n\nReload a YouTube tab, or type @handle manually / Pull from server."
        );
        setStatus("Detect failed — try Pull from server", "err");
        return;
      }
    }

    setDetectPanel(
      "err",
      "Could not detect account",
      "Sign into YouTube in this browser (any tab is fine), or set the viewer list manually / Pull from server."
    );
    setStatus("Detect failed — type handle or pull server config", "err");
  } finally {
    if (btn) btn.disabled = false;
  }
}

/**
 * Fill empty viewer / channel lists from tracker server config.
 * force=true overwrites local lists with server values.
 */
async function pullServerAllowlists(opts) {
  const force = !!(opts && opts.force);
  setStatus(force ? "Pulling server lists (overwrite)…" : "Pulling server lists…");
  const res = await runtimeSend({
    type: "PULL_SERVER_YOUTUBE_CONFIG",
    opts: { force },
  });
  if (!res || !res.ok) {
    setStatus("Pull failed: " + ((res && res.error) || "unknown"), "err");
    return false;
  }
  const merged = await loadSettingsIntoCache();
  applyConfigToForm(merged);
  const applied = (res.applied && res.applied.length) || 0;
  if (!applied) {
    setStatus("Server config loaded; local lists already set (use force to overwrite).", "ok");
  } else {
    setStatus("Updated from server: " + res.applied.join(", "), "ok");
  }
  return true;
}

async function useDetectedInAllowlist() {
  const parts = [];
  if (lastDetected.handle) parts.push(lastDetected.handle);
  if (lastDetected.channelId) parts.push(lastDetected.channelId);
  if (!parts.length) {
    setStatus("Nothing detected to use", "err");
    return;
  }
  addToListField("allowedViewers", parts);
  try {
    await persistSettings();
    setStatus("Viewer list updated.", "ok");
  } catch (e) {
    setStatus("Save failed: " + e, "err");
  }
}

async function load() {
  const merged = await loadSettingsIntoCache();
  applyConfigToForm(merged);
  updateDashboardLinks();
  const base = baseUrlFromForm();
  setServerChip("warn", "…");
  try {
    const health = await fetch(base + "/api/health", { method: "GET" });
    if (health.ok) {
      setServerChip("ok", "online");
      // Auto-fill empty viewer/channel allowlists from server
      const pull = await runtimeSend({
        type: "PULL_SERVER_YOUTUBE_CONFIG",
        opts: { force: false },
      });
      if (pull && pull.ok && pull.applied && pull.applied.length) {
        const again = await loadSettingsIntoCache();
        applyConfigToForm(again);
        setStatus("Auto-filled from server: " + pull.applied.join(", "), "ok");
      }
    } else setServerChip("err", "HTTP " + health.status);
  } catch (_) {
    setServerChip("err", "offline");
  }
}

function flushSettingsOnHide() {
  if (settingsSaveTimer) {
    clearTimeout(settingsSaveTimer);
    settingsSaveTimer = null;
  }
  persistSettings().catch((e) =>
    console.warn("[immersion-tracker] flush settings failed", e)
  );
}
window.addEventListener("pagehide", flushSettingsOnHide);
window.addEventListener("blur", flushSettingsOnHide);

document.getElementById("thresholdRange").addEventListener("input", (e) => {
  syncThresholdUi(e.target.value);
  schedulePersistSettings();
});
document.getElementById("thresholdPct").addEventListener("input", (e) => {
  syncThresholdUi(e.target.value);
  schedulePersistSettings();
});
document.getElementById("serverUrl").addEventListener("change", () => {
  updateDashboardLinks();
  schedulePersistSettings();
});
document.getElementById("serverUrl").addEventListener("input", schedulePersistSettings);

const secretInput = document.getElementById("webhookSecret");
if (secretInput) {
  secretInput.addEventListener("input", () => {
    secretDirty = true;
    schedulePersistSettings();
  });
  secretInput.addEventListener("change", () => {
    secretDirty = true;
    schedulePersistSettings();
  });
}
const clearSecretBtn = document.getElementById("clearSecret");
if (clearSecretBtn) {
  clearSecretBtn.addEventListener("click", async () => {
    secretDirty = true;
    document.getElementById("webhookSecret").value = "";
    try {
      await persistSettings({ clearSecret: true });
      setStatus("Webhook secret cleared from this browser.", "ok");
    } catch (e) {
      setStatus("Could not clear secret: " + e, "err");
    }
  });
}

const AUTO_SAVE_IDS = [
  "enabled",
  "allowedViewers",
  "channelAllowlist",
  "channelBlocklist",
  "videoBlocklist",
  "preferJapanese",
  "languageUnknownPolicy",
  "blockShorts",
  "blockLive",
  "minDurationSeconds",
  "minWatchedSeconds",
  "channelModeAll",
  "channelModeAllowlist",
];
for (const id of AUTO_SAVE_IDS) {
  const el = document.getElementById(id);
  if (!el) continue;
  el.addEventListener("change", schedulePersistSettings);
  if (el.tagName === "TEXTAREA" || el.type === "text" || el.type === "number") {
    el.addEventListener("input", schedulePersistSettings);
  }
}

document.getElementById("save").addEventListener("click", async () => {
  try {
    const data = await persistSettings();
    const granted = await requestHostIfNeeded(data.serverUrl);
    if (!granted) {
      setStatus(
        "Saved locally, but host permission denied. Allow the prompt for LAN servers.",
        "err"
      );
    } else {
      setStatus(
        data.webhookSecret
          ? "Saved locally (secret kept). Reload-safe."
          : "Saved locally. Set webhook secret to match .env.",
        "ok"
      );
    }
    if (!document.getElementById("webhookSecret").value && data.webhookSecret) {
      secretDirty = false;
    }
    updateSecretUi();
  } catch (e) {
    setStatus("Save failed: " + e, "err");
  }
});

document.getElementById("test").addEventListener("click", async () => {
  setStatus("Testing…");
  const base = baseUrlFromForm();
  setServerChip("warn", "…");
  try {
    const health = await fetch(base + "/api/health", { method: "GET" });
    if (health.ok) {
      setServerChip("ok", "online");
      await pullServerAllowlists({ force: false });
      setStatus("Server OK. Allowlists synced if empty.", "ok");
    } else {
      setServerChip("err", "HTTP " + health.status);
      setStatus("Cannot reach server.", "err");
    }
  } catch (_) {
    setServerChip("err", "offline");
    setStatus("Cannot reach server.", "err");
  }
});

document.getElementById("detect").addEventListener("click", () => detectViewer());
document.getElementById("useDetected").addEventListener("click", () => useDetectedInAllowlist());
const pullServerBtn = document.getElementById("pullServerConfig");
if (pullServerBtn) {
  pullServerBtn.addEventListener("click", () => pullServerAllowlists({ force: true }));
}

wireNavButtons();
load();
