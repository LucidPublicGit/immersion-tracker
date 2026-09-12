# Immersion Tracker — YouTube browser extension

Logs a YouTube watch to your Immersion Tracker server **only when** you have watched **≥ 90%** of the video **and** at least **5 minutes** of content (both configurable). Each `video_id` is logged **once ever** (not once per day).

**v1.6+ local queue:** peak progress and completions are stored in `browser.storage.local` so reloading the extension does not lose a finished watch. The popup **Activity** list shows local `watching` / `pending` / `error` / `synced` rows plus server logs; failed deliveries auto-retry. Use **Queue this tab now** if a finish was missed.

**UI (v1.7+):** toolbar popup is compact — **This tab** + **latest activity** only. Full **Settings** (gear icon or Options) and **History** open in separate tabs. All options (including **webhook secret**) auto-save to `storage.local` on this device only — not `storage.sync` / cloud.

**Log from history (v1.9+):** first-class catch-up flow. Popup **Log from history** scans YouTube watch history (default last **7 days**) for videos not yet tracked, lets you approve/reject each, then batch-logs approved ones — any device, same immersion Google account.

| Browser | Install |
|---------|---------|
| **Firefox 121+** | Temporary add-on (`about:debugging`) or packaged `.xpi` |
| **Chrome / Edge / Brave** | Load unpacked |

Multi-PC: install on each browser, point **Server URL** at one tracker host, reuse the same **webhook secret**.

---

## Why an extension?

YouTube does not expose “percent watched” for your account via a public API. The extension reads the on-page `<video>` element and reports completion to:

```http
POST {serverUrl}/api/webhooks/youtube
Header: X-Webhook-Secret: <optional>
```

---

## Pack for other PCs

From the repo root:

```powershell
.\scripts\pack-extension.ps1
```

Creates `dist\immersion-tracker-youtube.zip` and `.xpi`. Copy `extension\` or the zip to other machines.

---

## Firefox install

1. Start Immersion Tracker (`http://127.0.0.1:8000`).
2. Open **`about:debugging#/runtime/this-firefox`**
3. **Load Temporary Add-on…**
4. Select **`manifest.json`** in this folder (or the packed `.xpi`)
5. Pin **Immersion Tracker YouTube**
6. Open the popup and set Server URL / webhook secret / threshold
7. **Save** → **Test server**

> Temporary add-ons are **removed when Firefox restarts**. Reload via `about:debugging` after restart (settings usually remain for the same id).

### Persist after restart (optional)

1. Reload temporary each session (simplest).
2. Firefox Developer Edition / Nightly: `xpinstall.signatures.required` = `false`, then install unsigned `.xpi`.
3. Sign via [addons.mozilla.org](https://addons.mozilla.org) (unlisted) for permanent install on release Firefox.

---

## Chrome / Edge / Brave install

1. `chrome://extensions` or `edge://extensions`
2. **Developer mode** on
3. **Load unpacked** → this `extension/` directory
4. Configure popup the same way

---

## Multi-PC

| Machine | Server URL | Secret |
|---------|------------|--------|
| PC running Docker tracker | `http://127.0.0.1:8000` | `.env` → `WEBHOOK_SECRET` |
| Other PC on LAN | `http://<host-LAN-IP>:8000` | **same** secret |

1. Host: tracker listening on `0.0.0.0:8000` (Compose default).
2. Host: allow Windows Firewall inbound **TCP 8000** if needed.
3. Client: install extension → set Server URL + secret → **Test server**.
4. Allow the host-permission prompt for non-localhost URLs.

Install only in the browser profile used for your **immersion** YouTube account.

---

## Settings reference

| Setting | Default | Description |
|---------|---------|-------------|
| Server URL | `http://127.0.0.1:8000` | Base URL of Immersion Tracker |
| Webhook secret | _(empty)_ | `X-Webhook-Secret`; must match server |
| Threshold | `0.9` | Fraction of duration required |
| Min watch time | `300` | Content seconds required (with threshold); `0` = ratio only |
| Enabled | on | Master switch |
| Viewer list | empty | Only these signed-in accounts may log |
| Channel mode | `all` | `all` or `allowlist` |
| Channel allow/block | empty | Uploader filters |
| Video blocklist | empty | Skip specific video ids |
| Japanese only | on | Skip English / non-Japanese when detected |
| Language unknown | `log` | `log` or `skip` when language unknown |
| Skip Shorts / Live | on | Content-type filters |
| Min duration | `60` | Video length seconds; `0` = off |

**This tab** preview: allow/block current channel or video; toggle Japanese/Shorts/Live for the session (saved immediately).

Toolbar uses the **LiT wave** brand icons under `icons/` (not YouTube). Regenerate from `app/web/static/brand/source-app-icon.jpg` via `python scripts/process_brand_icons.py`.

Stored in **`browser.storage.local`**.

---

## How detection works

1. Content script on `youtube.com` / `m.youtube.com` (watch + Shorts).
2. Every ~2s reads main `<video>` `currentTime` / `duration`.
3. Anti-scrub: large seeks to the end without prior progress do not instantly count.
4. When progress ≥ threshold **and** min watch time (default 5 min), POSTs once.
5. Server dedupes by **video id only** (once ever). Extension keeps a durable logged-id set so homepage revisits and next-day rewatches do not re-queue.

### What gets logged

- **Content type:** `youtube`
- **Amount:** full video length in **minutes**
- **Tadoku mode:** default `auto` → `ready` (server config)
- **Series key:** `yt:{channel_id}` when known

---

## Verify

1. **Test server** in the popup → health OK.
2. Play a ≥5 min video past 90% (and ≥5 min watch progress).
3. Console: `[immersion-tracker] report result { ok: true, ... }`
4. `curl http://127.0.0.1:8000/api/logs?source=youtube`

---

## Files

| File | Role |
|------|------|
| `manifest.json` | MV3 (Firefox + Chromium) |
| `browser-api.js` | Shared API helper |
| `content.js` | Watch-progress detector |
| `background.js` | Local queue, webhook POST, history scan/batch log |
| `popup.html` / `popup.js` | This tab, Log from history, latest activity |
| `import.html` / `import.js` | Log from history — scan, review, batch log |
| `history.html` / `history.js` | Full activity list |
| `settings.html` / `settings.js` | Filters, viewer list, connection |
| `icons/` | Toolbar icons |

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Extension gone after Firefox restart | Temporary add-on — load again |
| `Cannot reach server` | Tracker up? URL correct? Firewall for LAN? |
| `401` | Popup secret must match `WEBHOOK_SECRET` |
| Host permission denied | Re-Save and allow prompt, or add origin to `host_permissions` |
| Private window | Enable “Run in Private Windows” on the add-on |
| No log after watch | ≥90% **and** ≥5 min watch; F12 console; reload tab after install |

---

## Privacy

- Runs only on YouTube hosts in the manifest.
- Sends watch metadata only to **your** configured Immersion Tracker URL.
- No third-party analytics.
