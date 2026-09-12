/* global
  loadSettingsIntoCache, applyConfigToForm, updateDashboardLinks,
  refreshServerAndHistory, runtimeSend, retryAllPending, clearHistoryList,
  wireNavButtons
*/

window.__activityRenderOpts = {
  limit: 40,
  emptyMsg: null,
};

let activityRefreshTimer = null;

function pageTabFromHash() {
  const h = String(location.hash || "")
    .replace(/^#/, "")
    .toLowerCase();
  if (
    h === "from-history" ||
    h === "import" ||
    h === "history-import" ||
    h === "log-from-history"
  ) {
    return "import";
  }
  return "activity";
}

function setPageTab(tab, opts) {
  const name = tab === "import" ? "import" : "activity";
  const activityBtn = document.getElementById("pageTabActivity");
  const importBtn = document.getElementById("pageTabImport");
  const panelActivity = document.getElementById("panelActivity");
  const panelImport = document.getElementById("panelImport");
  const brand = document.getElementById("pageBrandSub");

  if (activityBtn) {
    activityBtn.classList.toggle("active", name === "activity");
    activityBtn.setAttribute("aria-selected", name === "activity" ? "true" : "false");
  }
  if (importBtn) {
    importBtn.classList.toggle("active", name === "import");
    importBtn.setAttribute("aria-selected", name === "import" ? "true" : "false");
  }
  if (panelActivity) panelActivity.hidden = name !== "activity";
  if (panelImport) panelImport.hidden = name !== "import";
  if (brand) {
    brand.textContent = name === "import" ? "From history" : "Activity";
  }
  document.title =
    name === "import"
      ? "Lucid Immersion — From history"
      : "Lucid Immersion — Activity";

  if (!opts || opts.updateHash !== false) {
    const want = name === "import" ? "#from-history" : "#activity";
    if (location.hash !== want) {
      try {
        history.replaceState(null, "", want);
      } catch (_) {
        location.hash = want;
      }
    }
  }

  // Activity list auto-refresh only while that tab is visible
  if (name === "activity") {
    if (!activityRefreshTimer) {
      activityRefreshTimer = setInterval(() => {
        refreshServerAndHistory();
      }, 8000);
    }
    refreshServerAndHistory();
  } else if (activityRefreshTimer) {
    clearInterval(activityRefreshTimer);
    activityRefreshTimer = null;
  }
}

async function load() {
  const merged = await loadSettingsIntoCache();
  applyConfigToForm(merged);
  updateDashboardLinks();

  if (window.__immersionImport && typeof window.__immersionImport.load === "function") {
    await window.__immersionImport.load();
  }

  setPageTab(pageTabFromHash(), { updateHash: false });
  if (pageTabFromHash() === "activity") {
    await refreshServerAndHistory();
  }
}

document.getElementById("refreshHistory").addEventListener("click", () => {
  runtimeSend({ type: "LOCAL_LOG_FLUSH" }).finally(() => {
    refreshServerAndHistory();
  });
});
document.getElementById("clearHistory").addEventListener("click", () => clearHistoryList());
document.getElementById("retryAllPending").addEventListener("click", () => retryAllPending());
const queueBannerRetry = document.getElementById("queueBannerRetry");
if (queueBannerRetry) {
  queueBannerRetry.addEventListener("click", () => retryAllPending());
}

const pageTabActivity = document.getElementById("pageTabActivity");
if (pageTabActivity) {
  pageTabActivity.addEventListener("click", () => setPageTab("activity"));
}
const pageTabImport = document.getElementById("pageTabImport");
if (pageTabImport) {
  pageTabImport.addEventListener("click", () => setPageTab("import"));
}

window.addEventListener("hashchange", () => {
  setPageTab(pageTabFromHash(), { updateHash: false });
});

wireNavButtons();
load();
