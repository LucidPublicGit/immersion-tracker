# Immersion Tracker — full setup (proper order)

Do these **in order**. Skip optional sections if you don’t need them yet.

After you create or connect a sheet (Phase 2), put its ID in `config/settings.yaml`
(`sheets.spreadsheet_id`). Do not commit real spreadsheet IDs or credentials.

---

## Phase 0 — Prerequisites (once)

### 0.1 Software

| Need | Why |
|------|-----|
| **Docker Desktop** | Run the server |
| **Firefox 121+** (or Chrome) | YouTube extension |
| Optional: **Python 3.13** | Local tests / sheet-create scripts only |

Install Docker Desktop, start it, wait until it says **running**.

### 0.2 Open a terminal in the project

```powershell
cd C:\path	o\immersion-tracker
```

---

## Phase 1 — First Docker start (server only)

### 1.1 Run setup

```powershell
.\scripts\docker\setup.ps1
```

This will:

- Ensure `config\settings.yaml` and `.env` exist  
- Create `data\`  
- Build and start the container  
- Check http://127.0.0.1:8000/api/health  

### 1.2 Set a webhook secret

Edit **`.env`** in the project root:

```env
WEBHOOK_SECRET=pick-a-long-random-string-you-will-reuse
```

Restart so the container picks it up:

```powershell
.\scripts\docker\rebuild.ps1
```

### 1.3 Verify the API

Browser or terminal:

- Health: http://127.0.0.1:8000/api/health  
- Docs: http://127.0.0.1:8000/docs  
- Queue UI: http://127.0.0.1:8000/queue  

```powershell
.\scripts\docker\status.ps1
```

**Checkpoint:** health returns `"status":"ok"`.  
You can log manually even without Sheets/YouTube:

```powershell
curl -X POST http://127.0.0.1:8000/api/logs -H "Content-Type: application/json" -d "{\"content_type\":\"book\",\"title\":\"Test book\",\"amount\":5,\"unit\":\"pages\"}"
```

---

## Phase 2 — Google Sheets (your existing sheet)

Sheets live in **Google’s cloud**. Auth is either a **service account key** or **OAuth as you**.

**If you see `iam.disableServiceAccountKeyCreation`:** you cannot download a service account JSON on that org project. Use **Path B (OAuth)** below (or a personal GCP project).

Set `sheets.spreadsheet_id` in `config/settings.yaml` to the ID from your
sheet URL (`…/spreadsheets/d/<ID>/edit`).

### 2.0 Create tabs on the sheet (both paths)

| Tab name | Purpose |
|----------|---------|
| `Logs` | Auto-filled from the server |
| `Manual Entry` | You type new logs here |
| `Catalog` | Series + Tadoku overrides |
| `Tadoku Queue` | Pending / ready / pushed |
| `Metrics` | Totals |

**Manual Entry** header row:

```text
content_type	title	amount	unit	series_key	activity	notes	imported
```

---

### Path A — Service account key (only if org allows keys)

1. Enable Sheets API + Drive API  
2. Service account → Keys → JSON → save as `data\google-service-account.json`  
3. Share sheet with `client_email` as **Editor**  
4. `sheets.enabled: true` in `config\settings.yaml`  
5. `.\scripts\docker\rebuild.ps1` then `.\scripts\docker\sheets-sync.ps1`  

---

### Path B — OAuth as your Google user (**use this when SA keys are blocked**)

OAuth **Desktop client** secrets are different from service account keys and usually still allowed.

1. https://console.cloud.google.com/apis/library — enable **Sheets API** + **Drive API**  
2. **OAuth consent screen** — configure; if app is **Testing**, add **your email** as a test user  
3. **Credentials → Create credentials → OAuth client ID**  
   - Application type: **Desktop app**  
   - Download JSON → save as:

   ```
   C:\path	o\immersion-tracker\data\google-oauth-client.json
   ```

4. Run (opens browser; sign in with the account that owns/edits the sheet):

   ```powershell
   cd C:\path	o\immersion-tracker
   .\scripts\docker\sheets-oauth-setup.ps1
   ```

   This writes `data\google-oauth-token.json` and restarts Docker.

5. Confirm `config\settings.yaml` has:

   ```yaml
   sheets:
     enabled: true
     spreadsheet_id: "YOUR_SPREADSHEET_ID"
     oauth_token_file: "/app/data/google-oauth-token.json"
   ```

6. Sync:

   ```powershell
   .\scripts\docker\sheets-sync.ps1
   ```

You do **not** need to share the sheet with the  
service account email when using OAuth as yourself.

**Checkpoint:** sync returns `"ok": true` (not `sheets_disabled`). Sheet **Logs** updates.

### 2.x Test manual entry via the sheet

1. **Manual Entry** row: `book` / `テスト本` / `3` / `pages` / … leave `imported` blank  
2. `.\scripts\docker\sheets-sync.ps1`  
3. `imported` → `TRUE`; log appears in API / **Logs** tab

---

## Phase 3 — YouTube extension (Firefox / Chrome / multi-PC)

YouTube does **not** expose watch % via API. The browser extension logs only when **≥ 90%** is watched (default).

Install the extension **only in the browser profile signed into your immersion YouTube account**. Other accounts → other profile, no extension.

### 3.1 Server must be up

```powershell
.\scripts\docker\status.ps1
# Health: http://127.0.0.1:8000/api/health
```

Optional package for other PCs:

```powershell
.\scripts\pack-extension.ps1
# → dist\immersion-tracker-youtube.zip  and  .xpi
```

### 3.2 Firefox (this PC)

1. Open: `about:debugging#/runtime/this-firefox`
2. **Load Temporary Add-on…**
3. Select `C:\path	o\immersion-tracker\extension\manifest.json`  
   (or `dist\immersion-tracker-youtube.xpi` after packing)
4. Pin **Immersion Tracker YouTube**

> Temporary add-ons are removed when Firefox **fully restarts**. Reload after restart (settings usually stick for the same add-on id).

### 3.3 Chrome / Edge / Brave (this PC)

1. Open `chrome://extensions` (or `edge://extensions`)
2. Enable **Developer mode**
3. **Load unpacked** → select `C:\path	o\immersion-tracker\extension`
4. Pin the extension

Chrome keeps unpacked extensions across restarts (path must stay valid).

### 3.4 Configure settings (every browser)

Open the toolbar popup → **gear icon** (or extension Options). The popup itself is for live watch status + latest log; **Settings**, **Activity**, and **Log from history** (catch-up from YouTube watch history) are separate pages.

| Field | This PC | Other PC on same LAN |
|-------|---------|----------------------|
| Server URL | `http://127.0.0.1:8000` | `http://<host-LAN-IP>:8000` (e.g. `http://192.168.1.10:8000`) |
| Webhook secret | same as `.env` → `WEBHOOK_SECRET` | **same secret** |
| Threshold | `0.9` | `0.9` |
| Track only these accounts | empty *or* `@handle` / `UC…` of immersion account | same |
| Enabled | checked | checked |

**Save** → **Test server** → Server OK.

**Which account is tracked?** Open youtube.com as the immersion account → Settings → **Detect account** → paste into the allowlist (and/or set `youtube.viewer_allowlist` in `config/settings.yaml` for all PCs). Empty allowlist = any account in that browser.

On first save to a non-localhost URL, allow the host permission prompt (or the extension cannot POST to the tracker).

**Windows Firewall** on the host: allow inbound TCP **8000** if other PCs cannot reach the server.

### 3.5 Other PCs

1. Copy `extension\` or extract `dist\immersion-tracker-youtube.zip`
2. Install per Firefox or Chrome steps above
3. Set Server URL to the host LAN IP (or a reverse-proxy HTTPS URL if you expose it that way)
4. Paste the **same** `WEBHOOK_SECRET`
5. **Test server**

### 3.6 Test a real watch

1. Open a short YouTube video in the immersion-account profile  
2. Watch to the end (or past 90%)  
3. F12 Console: `[immersion-tracker] report result` with `ok: true`  
4. Check logs:

   ```powershell
   curl "http://127.0.0.1:8000/api/logs?source=youtube"
   ```

**Checkpoint:** finishing a video creates a log; YouTube defaults to Tadoku **auto/ready**.

Language / channel / length Tadoku rules come later (server-side). Channel allow/block already exists under `youtube:` in `config\settings.yaml`.

---

## Phase 4 — Tadoku queue (contest pipeline)

### 4.1 Understand modes

| Mode | Meaning |
|------|---------|
| `auto` | Goes to **ready** → can export without approve |
| `pending` | You approve first (default for books/anime/Plex) |
| `never` | Skipped |

Rules: catalog override → content type default → source default (`config/settings.yaml`).

### 4.2 Use the queue UI

1. Open http://127.0.0.1:8000/queue  
2. **Approve** or **Skip** pending rows  
3. **Process READY (export)**  

Exports land in:

```
C:\path	o\immersion-tracker\data\tadoku_export\
```

There is **no** automatic submit to tadoku.app yet — copy/export JSON into the contest UI as needed.

**Checkpoint:** you can move items pending → ready → pushed (exported).

---

## Phase 5 — Plex / Tautulli (optional)

Only if you use Plex.

1. Tracker must be reachable from the Plex/Tautulli host (same PC → `http://127.0.0.1:8000`, else LAN IP).  
2. Tautulli → Notification Agents → Webhook:  
   - URL: `http://<tracker-host>:8000/api/webhooks/tautulli`  
   - Header: `X-Webhook-Secret: <same as WEBHOOK_SECRET>`  
   - Trigger: watched / high progress  
3. Align library names in `config\settings.yaml` → `plex.library_map` with your Plex libraries.  
4. Rebuild after config changes:

   ```powershell
   .\scripts\docker\rebuild.ps1
   ```

**Checkpoint:** finishing an anime episode creates a **pending** log.

---

## Phase 6 — Daily use

| Task | How |
|------|-----|
| Start server | `.\scripts\docker\start.ps1` |
| Stop server | `.\scripts\docker\stop.ps1` |
| After code/config change | `.\scripts\docker\rebuild.ps1` |
| Logs | `.\scripts\docker\logs.ps1` |
| Force sheet sync | `.\scripts\docker\sheets-sync.ps1` |
| Local CSV backup (no Google) | `.\scripts\docker\export-local-csv.ps1` |
| YouTube | Watch in Firefox with extension loaded |
| Manual without sheet | `POST /api/logs` or Manual Entry tab |
| Tadoku review | http://127.0.0.1:8000/queue |
| Firefox restart | Reload temporary add-on again |

---

## Quick order checklist

- [ ] **0** Docker Desktop running  
- [ ] **1** `.\scripts\docker\setup.ps1` → health OK  
- [ ] **1** Set `WEBHOOK_SECRET` in `.env` → rebuild  
- [ ] **2** GCP: Sheets + Drive APIs on  
- [ ] **2** Service account JSON → `data\google-service-account.json`  
- [ ] **2** Share sheet with `client_email` as Editor  
- [ ] **2** Create tabs (Logs, Manual Entry, …)  
- [ ] **2** `sheets.enabled: true` in `config\settings.yaml`  
- [ ] **2** Rebuild + `sheets-sync.ps1` → sheet updates  
- [ ] **3** Firefox or Chrome: load `extension\` (see Phase 3)  
- [ ] **3** Popup: URL + secret + Test server  
- [ ] **3** Finish a YouTube video → log appears  
- [ ] **4** Use `/queue` for Tadoku approve/process  
- [ ] **5** (Optional) Plex/Tautulli webhook  

---

## If something fails

| Symptom | Fix |
|---------|-----|
| Health fails | Docker running? `.\scripts\docker\logs.ps1` |
| `sheets_disabled` | `enabled: true` + restart |
| Sheet 403 / permission | Share sheet with **service account email**, not only your Gmail |
| Key not found | File path must be `data\google-service-account.json` on the host |
| Extension Test server fails | Server up? URL `http://127.0.0.1:8000`? Secret match? |
| Extension no log | Watch ≥ 90%; F12 console; reload temporary add-on after Firefox restart |
| Webhook 401 | `X-Webhook-Secret` / popup secret ≠ `.env` `WEBHOOK_SECRET` |

More detail:

- [README.md](README.md) — full reference  
- [docs/GOOGLE_SHEETS.md](docs/GOOGLE_SHEETS.md) — Sheets + Docker model  
- [extension/README.md](extension/README.md) — Firefox extension  
