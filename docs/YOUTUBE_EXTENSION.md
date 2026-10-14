# YouTube extension setup & test

Logs only when **≥ 90%** of a video is watched **and** at least **5 minutes** of watch progress (both configurable), after local filters pass. Each video is logged **once ever** (rewatches and next-day replays are duplicates).

**Local durable queue (v1.6+):** the extension stores peak progress and completion payloads in browser storage. Reloading the add-on does not drop a finished watch; **History** shows local pending/error/synced rows, auto-retries failed POSTs, and **Queue this tab now** can recover a missed finish.

**UI (v1.7+):** compact toolbar popup = live **This tab** + most recent log. **Settings** (gear) and **History** (clock) open as full pages from the popup. Channel/video allow·block still works from **This tab**.

**Log from history (v1.9+):** when a watch was not logged live (another device, closed tab, etc.), open **Log from history** → scan your signed-in YouTube watch history for a lookback window (default **7 days**) → approve/reject each untracked video → batch log. Rejected ids are remembered so they do not reappear. Logs send `import_source: "history"` so the server skips the auto **min watch time** floor (you already reviewed them); completion threshold, once-ever dedupe, and channel/viewer filters still apply.

**Default filters (v1.5+):** Japanese-only (skip English), skip Shorts & Live, min **60s**, any uploader unless blocked.

Works on **Firefox**, **Chrome**, **Edge**, **Brave**, and multiple PCs (all point at one Immersion Tracker server).

**Toolbar icon:** LiT wave monogram (teal/dark, not YouTube). After upgrading, pin again or disable/enable the extension if the browser cached an old icon.

## 1. Start Immersion Tracker

```powershell
cd C:\path\to\immersion-tracker
.\scripts\docker\start.ps1
# Health: http://127.0.0.1:8000/api/health
```

Note `WEBHOOK_SECRET` from `.env` (default in Compose: `changeme` if unset).

Optional pack for other machines:

```powershell
.\scripts\pack-extension.ps1
# → dist\immersion-tracker-youtube.zip / .xpi
```

## 2. Install

### Firefox

1. Open: `about:debugging#/runtime/this-firefox`
2. **Load Temporary Add-on…**
3. Select `extension\manifest.json` or `dist\immersion-tracker-youtube.xpi`
4. Pin **Immersion Tracker YouTube**

> Temporary add-ons vanish when Firefox fully restarts — reload after restart.

### Chrome / Edge / Brave

1. `chrome://extensions` (or `edge://extensions`)
2. **Developer mode** on
3. **Load unpacked** → `extension\` folder
4. Pin the extension

## 3. Configure settings

Open the toolbar popup → **gear** (or right‑click extension → Options / Manage → Extension options).

| Setting | This PC | Other PC (LAN) |
|---------|---------|----------------|
| Server URL | `http://127.0.0.1:8000` when the tracker runs on this PC | The tracker’s Tailscale or LAN URL. Do not use this PC’s localhost if the app runs on another machine. |
| Webhook secret | same as `.env` `WEBHOOK_SECRET` | same |
| Threshold | `90%` | `90%` |
| Min watch time | `300` s (5 min) | same |
| Enabled | checked | checked |
| Japanese only | on (skip English) | same |
| Skip Shorts / Live | on | same |
| Channel mode | Any (or allowlist) | same |

**Save all** → **Test server** → Server OK. Popup shows live watch status; **History** (clock icon) shows the full activity list.

If Server URL is still `http://127.0.0.1:8000` and that tracker is not running, the extension can adopt a machine-local URL from `extension/deployed-server.local.json` (gitignored):

```json
{ "serverUrl": "https://your-tracker.example" }
```

Reload the extension, open Settings, and click **Save all** so Firefox can allow that host. The public repo does not contain the deployed hostname.

### This tab preview

While a watch page is open, the top panel shows progress, language chips, and skip reason (if any). Quick actions:

| Button | Effect |
|--------|--------|
| **Allow channel** | Add uploader to allowlist; remove from blocklist |
| **Block channel** | Block this uploader (toggle unblocks) |
| **Only allowlisted + add** | Switch to allowlist-only mode and add this channel |
| **Block video** | Never auto-log this video id |
| Checkboxes | Japanese only / Skip Shorts / Skip Live — save immediately |

Allow the host-permission prompt when using a non-localhost Server URL. On the host, allow Windows Firewall TCP **8000** for LAN clients.

## 4. Live test

1. Open a ≥5 minute YouTube video in that browser profile.
2. Watch to the end (≥ 90% **and** ≥5 min of actual progress).
3. F12 Console: `[immersion-tracker] report result` with `ok: true`.
4. Check API:

   ```powershell
   curl "http://127.0.0.1:8000/api/logs?source=youtube"
   ```

YouTube defaults to Tadoku **`auto`** → status **ready** (exportable / auto-submit per your Tadoku config).

## 4b. Log from history

Use **Log from history** when live tab tracking missed a watch (another device, closed tab, TV app, etc.). YouTube does not expose “percent watched” for those sessions; the extension scans `youtube.com/feed/history` for the Google account signed into **this** browser.

1. Open the extension popup — **Log from history** is embedded in the popup (lookback, scan, Ready/Unfinished list). The full Activity page also has an **Activity | From history** tab for a larger review surface.
2. On youtube.com in **this** browser, switch to the immersion account once (the other Google account can stay signed in). Auto then reads that account’s history without changing the tab again. Settings → **History import account** stays on Auto.
3. Choose lookback (**7 days** default) → **Scan history** — works from any tab (no need to leave youtube.com open). Lookback, filter checkbox, and last scan (with approve/reject decisions) are **cached** in this browser across refresh.
4. Approve immersion videos, reject junk / English / accidents.
5. **Log approved** (optionally **Save rejects** first).

Notes:

- Uses `https://www.youtube.com/feed/history` with your browser session cookies (no Google API key).
- Viewer identity comes from the history page that was fetched (display name or channel id). A missing identity is not filled in from the allowlist, so English history is not labeled as the Japanese account.
- Empty local allowlists are auto-filled from `GET /api/youtube/extension-config` (server `viewer_allowlist` / channel lists).
- Already-logged videos (server + local) and previously rejected ids are hidden.
- **Ready to log** tab: **known** progress ≥ completion threshold (history resume bar or live tracking on this browser) **and** estimated watched time ≥ min-watch (default **5 minutes**). Merely appearing in YouTube history is not treated as finished. Channel / Shorts / Live / Japanese filters still apply when enabled. **Approve** always logs a full watch (100% of media length).
- **Unfinished / short** tab: partial progress, **no progress data**, under min-watch, or duration unknown (still approvable — finished watches often lack a history %).
- Each row shows **duration** and **% watched** when available, with a small progress bar.
- Missing durations + caption language use a local meta cache, then Innertube player (parallel), then a limited watch-page scrape only when duration is still missing. Already-logged / filtered videos are not enriched.
- **Japanese only** on history requires positive evidence: caption/audio `ja` **or** Japanese script in the title. Caption `en` is always skipped. Unknown language with a Latin-only title is hidden from history candidates (stricter than live “still log unknowns”).
- Thumbnails show next to each title.
- Approved history items skip the server min-watch floor; once-ever dedupe and channel/viewer rules still apply.
- Server endpoint for bulk dedupe preview: `POST /api/youtube/check-ids` with `{ "video_ids": ["…"] }`.

## 5. Webhook-only test (no browser)

```powershell
curl -X POST http://127.0.0.1:8000/api/webhooks/youtube `
  -H "Content-Type: application/json" `
  -H "X-Webhook-Secret: <your-secret>" `
  -d "{\"video_id\":\"dQw4w9WgXcQ\",\"title\":\"Test Video\",\"channel_id\":\"UCtest\",\"channel_title\":\"Test Channel\",\"duration_seconds\":600,\"watched_seconds\":540,\"ratio\":0.9}"
```

Expect `accepted: true` and a new log. A second POST with the same `video_id` returns `duplicate`.

## Which YouTube *account* is tracked?

Live tab tracking follows the account that YouTube tab is using. **Log from history** reads the YouTube account this browser is already signed in as (`youtube.com/feed/history` with no `authuser`). That is the account YouTube last switched to, including watches from a phone or another computer. Both Google accounts can stay signed in. The scan does not change the YouTube tab.

History HTML identifies that account by its display name (`USER_ACCOUNT_NAME`), not by a channel id. The display name matches an allowlist handle at a hyphen: `ルシド` matches `@ルシド-q4w`. The webhook sends the allowlist handle. If the signed-in account is not on the viewer list, the scan then tries the other signed-in accounts by `authuser` index. Pin **History import account** only when Auto picks the wrong one.

### Viewer allowlist

**Settings** → **Only log when signed in as**
Paste `@handle` and/or `UC…` channel id (one per line). Empty = the account currently active in the tab.

1. Sign the immersion account into this browser (the other account can stay active)
2. Settings → **List accounts**
3. Leave **History import account** on **Auto — the account YouTube is using**, or pin a session
4. **Add to viewer list** if the handle is not already there

A dedicated browser profile still works if you only want one account.

**Server** (enforced for every PC), `config/settings.yaml`:

```yaml
youtube:
  viewer_allowlist:
    - "@YourHandle"
    - "UCxxxxxxxxxxxxxxxxxxxxxx"
```

Then rebuild/restart the container. If this list is non-empty, watches without a matching viewer id are rejected (`viewer_not_allowlisted` / `viewer_unknown_with_allowlist`).

> `channel_allowlist` / `channel_blocklist` filter **uploaders** (who made the video), not who is watching.

## Optional: uploader channel allow/block (server)

```yaml
youtube:
  channel_allowlist:
    - "UCxxxxxxxx"   # only these uploaders
  channel_blocklist: []
```

Then `.\scripts\docker\rebuild.ps1`.

### Extension content filters (local)

| Setting | Default | Notes |
|---------|---------|--------|
| Japanese only | on | Skips detected `en` (and non-`ja`) via captions/audio tracks |
| Language unknown | still log | Title with Japanese characters counts as `ja` |
| Skip Shorts | on | `/shorts/` URLs |
| Skip Live | on | Live / live-content flags from player |
| Min duration | 60s | 0 disables |
| Uploader allow/block | empty / any | Allowlist mode optional; blocklist always applies |
| Video blocklist | empty | Per-video ids |

Server `channel_allowlist` / `channel_blocklist` still apply as a multi-PC safety net.
