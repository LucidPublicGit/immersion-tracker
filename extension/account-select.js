/**
 * Pick which signed-in YouTube account history import should read.
 * Does not change the account active in a YouTube tab.
 *
 * Loaded before background.js on Firefox. Chromium's service worker
 * importScripts this file from background.js.
 */
(function (root, factory) {
  const api = factory();
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
  Object.assign(root, api);
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
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
    const out = new Set();
    for (let i = 0; i < arguments.length; i++) {
      const t = normAccountToken(arguments[i]);
      if (!t) continue;
      out.add(t);
      if (t.startsWith("@")) out.add(t.slice(1));
    }
    return out;
  }

  function allowSetFromTokens(tokens) {
    const allow = new Set();
    const list = Array.isArray(tokens) ? tokens : [];
    for (const raw of list) {
      const t = normAccountToken(raw);
      if (!t) continue;
      allow.add(t);
      if (t.startsWith("@")) allow.add(t.slice(1));
    }
    return allow;
  }

  function foldAccount(value) {
    return String(value || "")
      .split("")
      .map((ch) => ("A" <= ch && ch <= "Z" ? ch.toLowerCase() : ch))
      .join("");
  }

  function handleBody(token) {
    const t = normAccountToken(token);
    if (!t || t.startsWith("UC")) return "";
    return t.startsWith("@") ? t.slice(1) : t;
  }

  /**
   * YouTube history HTML in 2026 has no channel id. The signed-in identity is
   * USER_ACCOUNT_NAME (a display name). Match that to an allowlist handle only
   * at a hyphen or underscore boundary: ルシド → @ルシド-q4w.
   * One-character names never match.
   */
  function nameMatchesAllowToken(name, allowToken) {
    const raw = String(name || "")
      .trim()
      .replace(/^@+/, "");
    if (raw.length < 2) return false;
    const body = handleBody(allowToken);
    if (!body) return false;
    const n = foldAccount(raw);
    const h = foldAccount(body);
    if (h === n) return true;
    return h.startsWith(n + "-") || h.startsWith(n + "_");
  }

  function accountNames(account) {
    if (!account) return [];
    return [account.name, account.accountName, account.displayName, account.handle, account.viewerHandle]
      .map((v) => String(v || "").trim())
      .filter(Boolean);
  }

  function accountMatchesAllow(account, allowTokens) {
    const allow = allowSetFromTokens(allowTokens);
    if (!allow.size) return true;
    const present = accountTokenSet(
      account && account.handle,
      account && account.viewerHandle,
      account && account.channelId,
      account && account.viewerChannelId
    );
    for (const token of present) {
      if (allow.has(token)) return true;
    }
    const list = Array.isArray(allowTokens) ? allowTokens : [];
    for (const raw of list) {
      for (const name of accountNames(account)) {
        if (nameMatchesAllowToken(name, raw)) return true;
      }
    }
    return false;
  }

  /**
   * Handle to send the server. The live allowlist is an exact token match,
   * so a display name must be replaced with the allowlist handle it matched.
   */
  function matchedAllowHandle(account, allowTokens) {
    const list = Array.isArray(allowTokens) ? allowTokens : [];
    const own = normAccountToken(
      (account && (account.handle || account.viewerHandle)) || ""
    );
    if (!list.length) return own.startsWith("@") ? own : "";
    if (!accountMatchesAllow(account, list)) return "";
    const present = accountTokenSet(
      account && account.handle,
      account && account.viewerHandle,
      account && account.channelId,
      account && account.viewerChannelId
    );
    for (const raw of list) {
      const t = normAccountToken(raw);
      if (!t.startsWith("@")) continue;
      if (present.has(t) || present.has(t.slice(1))) return t;
    }
    const hits = [];
    for (const raw of list) {
      const t = normAccountToken(raw);
      if (!t.startsWith("@")) continue;
      for (const name of accountNames(account)) {
        if (nameMatchesAllowToken(name, t) && hits.indexOf(t) < 0) hits.push(t);
      }
    }
    if (hits.length === 1) return hits[0];
    if (hits.length > 1) {
      hits.sort((a, b) => b.length - a.length);
      return hits[0];
    }
    return "";
  }

  /** Signed-in display name from a history document. Not an uploader handle. */
  function parseHistoryAccountName(html) {
    const h = String(html || "");
    const m = h.match(/"USER_ACCOUNT_NAME"\s*:\s*"((?:\\.|[^"\\])*)"/);
    if (!m || !m[1]) return "";
    let name = m[1];
    try {
      name = JSON.parse('"' + m[1] + '"');
    } catch (_) {}
    name = String(name || "").trim();
    if (!name || name.length > 80) return "";
    if (name.indexOf("/") >= 0) return "";
    return name;
  }

  /**
   * @param {Array<{authUser?: number, handle?: string, channelId?: string, selected?: boolean}>} accounts
   * @param {string[]} allowTokens empty = the account YouTube marks selected, else the first
   * @returns {object|null}
   */
  function pickHistoryAccount(accounts, allowTokens) {
    const list = Array.isArray(accounts) ? accounts.filter(Boolean) : [];
    if (!list.length) return null;
    const allow = allowSetFromTokens(allowTokens);
    if (!allow.size) {
      for (const account of list) {
        if (account.selected) return account;
      }
      return list[0];
    }
    for (const account of list) {
      if (accountMatchesAllow(account, allowTokens)) return account;
    }
    return null;
  }

  /** Empty / auto → null. 0 is a real account index. */
  function authUserIndex(value) {
    if (value === 0) return 0;
    if (value == null) return null;
    const s = String(value).trim().toLowerCase();
    if (!s || s === "auto") return null;
    if (!/^\d+$/.test(s)) return null;
    const n = Number(s);
    if (n > 20) return null;
    return n;
  }

  function textOf(node) {
    if (!node) return "";
    if (typeof node === "string") return node;
    if (typeof node.simpleText === "string") return node.simpleText;
    if (Array.isArray(node.runs)) {
      return node.runs.map((run) => (run && run.text) || "").join("");
    }
    return "";
  }

  function parseAccountItem(item) {
    const handleRaw = textOf(item && item.channelHandle).trim();
    let handle = handleRaw;
    if (handle && handle.charAt(0) !== "@") handle = "@" + handle.replace(/^\/+/, "");
    handle = handle.split(/[/?#]/)[0];
    let channelId = "";
    const browse =
      item &&
      item.navigationEndpoint &&
      item.navigationEndpoint.browseEndpoint;
    const browseId = browse && browse.browseId ? String(browse.browseId) : "";
    if (browseId.startsWith("UC") && browseId.length >= 24) channelId = browseId;
    if (!channelId && item && item.channelId) {
      const cid = String(item.channelId);
      if (cid.startsWith("UC") && cid.length >= 24) channelId = cid;
    }
    return {
      handle: handle.length > 1 ? handle : "",
      channelId,
      email: textOf(item && item.accountByline).trim(),
      name: textOf(item && item.accountName).trim(),
      selected: !!(item && item.isSelected),
    };
  }

  function extractAccountItems(node, out) {
    if (!node || typeof node !== "object") return;
    if (node.accountItemRenderer && typeof node.accountItemRenderer === "object") {
      out.push(parseAccountItem(node.accountItemRenderer));
    }
    if (Array.isArray(node)) {
      for (const child of node) extractAccountItems(child, out);
      return;
    }
    for (const key of Object.keys(node)) {
      if (key === "accountItemRenderer") continue;
      extractAccountItems(node[key], out);
    }
  }

  function parseAccountSwitcherPayload(text) {
    const raw = String(text || "")
      .replace(/^\)\]\}'\s*/, "")
      .trim();
    if (!raw) return [];
    let data = null;
    if (raw.charAt(0) === "{" || raw.charAt(0) === "[") {
      try {
        data = JSON.parse(raw);
      } catch (_) {
        data = null;
      }
    }
    if (!data) {
      const start = raw.indexOf("{");
      const end = raw.lastIndexOf("}");
      if (start >= 0 && end > start) {
        try {
          data = JSON.parse(raw.slice(start, end + 1));
        } catch (_) {
          data = null;
        }
      }
    }
    if (!data) return [];
    const items = [];
    extractAccountItems(data, items);
    return items.map((item, index) => Object.assign({ authUser: index }, item));
  }

  return {
    normAccountToken,
    accountMatchesAllow,
    nameMatchesAllowToken,
    matchedAllowHandle,
    parseHistoryAccountName,
    pickHistoryAccount,
    authUserIndex,
    parseAccountSwitcherPayload,
  };
});
