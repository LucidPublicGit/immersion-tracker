const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
const extension = path.join(__dirname, "..", "extension");

function loadShared(fetch) {
  const context = vm.createContext({ URL, console, fetch });
  vm.runInContext(fs.readFileSync(path.join(extension, "shared.js"), "utf8"), context);
  return context;
}

test("host permission is requested before leaving the click stack", async () => {
  let clicked = true;
  let calls = 0;
  const context = vm.createContext({ URL, console,
    document: { getElementById: () => ({ value: "https://tracker.example" }) },
    browser: { permissions: { request({ origins }) {
      assert.equal(clicked, true);
      assert.equal(origins[0], "https://tracker.example/*");
      calls++;
      return Promise.resolve(true);
    } } },
  });
  vm.runInContext(fs.readFileSync(path.join(extension, "shared.js"), "utf8"), context);
  const result = context.grantConfiguredServer();
  assert.equal(calls, 1);
  clicked = false;
  assert.equal(await result, true);
});

test("Save all requests permission before awaiting storage", async () => {
  const source = fs.readFileSync(path.join(extension, "settings.js"), "utf8");
  const start = source.indexOf('document.getElementById("save").addEventListener');
  const end = source.indexOf('document.getElementById("test").addEventListener', start);
  let handler, status;
  let clicked = true;
  let saved = false;
  const context = vm.createContext({
    document: { getElementById: (id) => id === "save"
      ? { addEventListener: (_, fn) => { handler = fn; } } : { value: "" } },
    readFormConfig: () => ({ serverUrl: "https://tracker.example" }),
    validatedServerUrl: (url) => url,
    requestHostIfNeeded: () => { assert.equal(clicked, true); return Promise.resolve(true); },
    persistSettings: async () => { saved = true; return { webhookSecret: "" }; },
    setStatus: (message, kind) => { status = kind; },
    updateSecretUi: () => {},
  });
  vm.runInContext(source.slice(start, end), context);
  const result = handler();
  clicked = false;
  await result;
  assert.equal(saved, true);
  assert.equal(status, "ok");
});

test("remote plaintext tracker requests fail before transmitting credentials", async () => {
  let calls = 0;
  const context = loadShared(() => { calls++; return Promise.resolve({ ok: true }); });
  for (const url of ["http://192.168.1.10:8000", "http://tracker.example", "ftp://tracker.example", "https://user:secret@tracker.example"]) {
    assert.throws(() => context.trackerFetch(url + "/api/health"));
  }
  assert.equal(calls, 0);
  await context.trackerFetch("https://tracker.example/api/logs?source=youtube&limit=50");
  for (const host of ["localhost", "127.0.0.1", "[::1]"]) {
    await context.trackerFetch(`http://${host}:8000/api/health`);
  }
  assert.equal(calls, 4);
  assert.throws(() => context.validatedServerUrl("https://tracker.example?secret=bad"));
});

test("tracker requests cannot follow redirects to plaintext destinations", async () => {
  let options;
  const context = loadShared((url, value) => { options = value; return Promise.resolve({ ok: true }); });
  await context.trackerFetch("https://tracker.example/api/webhooks/youtube", {
    method: "POST", redirect: "follow", headers: { "X-Webhook-Secret": "test-only" },
  });
  assert.equal(options.redirect, "error");
  assert.equal(options.headers["X-Webhook-Secret"], "test-only");
});

test("restored scan metadata renders markup as text", () => {
  const meta = { hidden: true, textContent: "" };
  Object.defineProperty(meta, "innerHTML", { set() { throw new Error("HTML injection"); } });
  const context = vm.createContext({ console, window: {}, document: { getElementById: () => null } });
  vm.runInContext(fs.readFileSync(path.join(extension, "import.js"), "utf8"), context);
  const attack = '<img src=x onerror="alert(1)">';
  context.document.getElementById = (id) => id === "scanMeta" ? meta : null;
  context.setImportStatus = () => {};
  context.renderList = () => {};
  context.schedulePersistScan = () => {};
  context.applyScanResult({ candidates: [], unfinished: [], metaText: attack }, { fromCache: true });
  assert.equal(meta.textContent, attack);
});
