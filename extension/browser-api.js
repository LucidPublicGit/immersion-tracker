/**
 * Tiny Chrome / Firefox API shim.
 * Firefox exposes `browser` (Promise-based) and often `chrome` (callbacks).
 * Prefer `browser` when present; fall back to `chrome`.
 */
(function (global) {
  const api = typeof global.browser !== "undefined" ? global.browser : global.chrome;
  if (!api) {
    console.error("[immersion-tracker] No WebExtension API (browser/chrome) found");
  }
  global.ImmersionExt = api;
  /** Prefer local storage — works offline and without Firefox Account sync. */
  global.ImmersionStorage = api && api.storage ? api.storage.local : null;
})(typeof globalThis !== "undefined" ? globalThis : this);
