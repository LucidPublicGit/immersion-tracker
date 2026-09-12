/* global
  loadSettingsIntoCache, applyConfigToForm, updateDashboardLinks,
  refreshServerAndHistory, refreshPageStatus, syncThresholdUi, thresholdFromStorage,
  cachedSettings, wireNavButtons, onToggleChannel, onToggleVideo, forceQueueThisTab,
  retryAllPending, runtimeSend, openSettingsPage, openHistoryPage
*/

window.__activityRenderOpts = {
  limit: 1,
  emptyMsg: "No activity yet. Watch past the threshold to log.",
};

let watchPollTimer = null;

async function load() {
  const merged = await loadSettingsIntoCache();
  applyConfigToForm(merged);
  syncThresholdUi(thresholdFromStorage(merged.threshold));
  updateDashboardLinks();
  refreshServerAndHistory();
  refreshPageStatus();
  if (watchPollTimer) clearInterval(watchPollTimer);
  watchPollTimer = setInterval(refreshPageStatus, 2000);
  // Restore lookback/filters + last history scan into the embedded Log from history section
  if (window.__immersionImport && typeof window.__immersionImport.load === "function") {
    await window.__immersionImport.load();
  }
}

document.getElementById("toggleChannel").addEventListener("click", () => onToggleChannel());
document.getElementById("toggleVideo").addEventListener("click", () => onToggleVideo());

const forceQueueBtn = document.getElementById("forceQueueTab");
if (forceQueueBtn) {
  forceQueueBtn.addEventListener("click", () => forceQueueThisTab());
}

document.getElementById("refreshHistory").addEventListener("click", () => {
  runtimeSend({ type: "LOCAL_LOG_FLUSH" }).finally(() => {
    refreshServerAndHistory();
    refreshPageStatus();
  });
});

const queueBannerRetry = document.getElementById("queueBannerRetry");
if (queueBannerRetry) {
  queueBannerRetry.addEventListener("click", () => retryAllPending());
}

wireNavButtons();

const openSettingsBottom = document.getElementById("openSettingsBottom");
if (openSettingsBottom) {
  openSettingsBottom.addEventListener("click", () => openSettingsPage());
}
const openHistoryBottom = document.getElementById("openHistoryBottom");
if (openHistoryBottom) {
  openHistoryBottom.addEventListener("click", () => openHistoryPage());
}

load();
