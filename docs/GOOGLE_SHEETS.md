# Google Sheets + Docker — how it actually works

## Short answer

| Question | Answer |
|----------|--------|
| Is the sheet a file on my PC that Docker mounts? | **No.** |
| Where does the sheet live? | **Google Drive (cloud)** — a normal Google Spreadsheet you open in the browser. |
| How does Docker read/write it? | Over the **internet**, via **Google Sheets API**. |
| Auth options | **(A)** Service account JSON key, or **(B)** Your Google user via **OAuth** (if org blocks SA keys). |
| What is mounted into Docker? | Credential files under `./data` → `/app/data`, plus `./config`. |
| Did we ship an empty sheet you can open? | **No pre-made sheet.** Use your Drive sheet or create one. |
| Can I use a local Excel file instead? | Not as the Google Sheets integration. Use the **API / queue UI**, or `export-local-csv.ps1` for local CSVs. |

### Pull vs push (why relink used to “stick” then revert)

| Direction | Cadence | Role |
|-----------|---------|------|
| **Pull** (sheet → DB) | Often (~20s) | Browser edits on **Logs (All)** / Catalog |
| **Push** (DB → sheet) | When dirty (~3 min) | Ingest, queue, **catalog link / relink** |

Local UI/API edits (catalog aliases, relink titles, queue approve) **mark the sheet dirty** and win over stale sheet rows until the next successful push. After push, sheet edits apply again as usual.

---

## Org policy: `iam.disableServiceAccountKeyCreation`

If Google says you **cannot create service account keys**, that is an **organization policy**. You will **not** get a SA JSON download on that org project.

### Option 1 — OAuth as yourself (recommended for locked orgs)

Service account **keys** are blocked; **OAuth Desktop clients** usually are not.

1. Cloud Console → enable **Sheets API** + **Drive API**  
2. **APIs & Services → OAuth consent screen**  
   - Configure app (External for personal Gmail, or Internal for Workspace)  
   - If status is **Testing**, add **yourself** under Test users  
3. **Credentials → Create credentials → OAuth client ID**  
   - Type: **Desktop app**  
   - Download JSON → save as:

   ```
   data/google-oauth-client.json
   ```

4. On your PC (browser login):

   ```powershell
   cd C:\path\to\immersion-tracker
   .\scripts\docker\sheets-oauth-setup.ps1
   ```

   Or:

   ```powershell
   .\.venv\Scripts\python scripts\google_oauth_login.py
   ```

5. That writes `data/google-oauth-token.json` (refresh token).  
6. Set `sheets.enabled: true`, rebuild, `sheets-sync.ps1`.  

Sign in with the Google account that **already can edit** your spreadsheet.  
You do **not** share the sheet with `…iam.gserviceaccount.com` in this mode.

### Option 2 — Free personal GCP project (outside the org)

1. Use a personal Gmail → https://console.cloud.google.com/  
2. Create a **new project** not under the company org  
3. Enable Sheets + Drive APIs  
4. Create a service account + **JSON key** (allowed on personal projects)  
5. Share your sheet with that SA email as Editor  
6. Save key as `data/google-service-account.json`  

### Option 3 — Ask org admin

Someone with **Organization Policy Administrator** can remove or exempt:

- Constraint: `iam.disableServiceAccountKeyCreation`  

Only do this if company policy allows.

```
┌─────────────────┐     HTTPS API      ┌──────────────────────┐
│ Your browser    │ ◄────────────────► │ Google Sheets        │
│ sheets.google…  │                    │ (cloud document)     │
└─────────────────┘                    └──────────▲───────────┘
                                                  │
                                          Sheets API
                                                  │
┌─────────────────┐   mount key only   ┌──────────┴───────────┐
│ PC: data/       │ ─────────────────► │ Docker container     │
│  sa.json        │                    │ immersion-tracker    │
│  immersion.db   │ ◄─── volume ─────► │ SQLite + sync jobs   │
└─────────────────┘                    └──────────────────────┘
```

**Source of truth** for the app is still **SQLite** (`data/immersion.db` on your PC via Docker volume).  
Sheets is a **dashboard + manual entry UI** that syncs with that DB.

---

## One-time setup

### 1. Service account key (on your PC)

1. [Google Cloud Console](https://console.cloud.google.com/) → project  
2. Enable **Google Sheets API** and **Google Drive API**  
3. **IAM → Service accounts → Create**  
4. **Keys → Add key → JSON**  
5. Save as:

   ```
   immersion-tracker/data/google-service-account.json
   ```

   This path is gitignored-friendly (under `data/`). Docker sees it as:

   ```
   /app/data/google-service-account.json
   ```

### 2. Create the spreadsheet

**Easy path (script):**

```powershell
cd C:\path\to\immersion-tracker
.\scripts\docker\sheets-init.ps1
```

That will:

- Create a Google Spreadsheet with tabs: Logs, Manual Entry, Catalog, Tadoku Queue, Metrics, Rules  
- Print a URL you open in the browser  
- Write `data/google-sheet-info.txt`  
- Patch `config/settings.yaml` (`sheets.enabled: true`, spreadsheet id, key path)  
- Restart Docker and run a sync  

When prompted, enter **your Gmail** so you can open/edit the sheet (service accounts own files you otherwise never see in “My Drive”).

**Manual path:**

1. Create a blank spreadsheet in your Google account  
2. Share it with the **service account email** (`client_email` inside the JSON) as **Editor**  
3. Copy the ID from the URL:  
   `https://docs.google.com/spreadsheets/d/<THIS_ID>/edit`  
4. Edit `config/settings.yaml`:

   ```yaml
   sheets:
     enabled: true
     spreadsheet_id: "THIS_ID"
     service_account_file: "/app/data/google-service-account.json"
   ```

5. Restart: `.\scripts\docker\rebuild.ps1` or `.\scripts\docker\start.ps1`  
6. Sync: `.\scripts\docker\sheets-sync.ps1`  
   (Missing tabs are created automatically on first sync/use.)

### 3. Day-to-day (bidirectional edits)

**Single source of truth on the sheet:** **Logs (All)**.  
Type tabs, Tadoku Queue, and Metrics are **live formulas** (`FILTER` / `COUNTIF`) over that tab — the browser updates them immediately when Logs changes. The app does **not** copy the same rows into those tabs.

Sync order: **pull sheet → DB, then push DB → Logs (All) / Catalog** (views are formulas, installed once).

| Tab | Editable? | Notes |
|-----|-----------|--------|
| **Logs (All)** | **Yes** | Canonical log table. Edit any column; keep `id` to update. Clear title+amount (or action/delete) to remove. New row with no id + title+amount → creates a log. **Edit `tadoku_mode` / `tadoku_status` here** (Queue is a view). |
| **Tadoku Queue** | **View** (formula) | Live `FILTER` of pending/ready/failed from Logs (All), with computed `tadoku_title`. Not a second copy — no app rewrite wait. |
| **Manual Entry** | **Yes** | New logs only; leave `imported` blank until sync marks TRUE. |
| **Catalog** | **Yes** | Series overrides (`tadoku_override`: `auto` / `pending` / `never`). Sheet-authoritative; re-pulled before rewrite. |
| **Logs · Anime / VN / …** | **View** (formula) | Live `FILTER` by `content_type`. Updates the moment Logs (All) does. |
| **Metrics** | **View** (formula) | `COUNTIF` / `SUMIF` over Logs (All). |
| **Enums** | **View** | Reference lists for dropdowns. |

| Action | How |
|--------|-----|
| Force sync now | `.\scripts\docker\sheets-sync.ps1` or `POST /api/sync/sheets` |
| Auto pull (user edits) | Scheduler every `sheets.poll_manual_seconds` (default ~20s) — sheet → DB, mostly reads |
| Auto push (DB → Logs) | Scheduler every `sheets.push_sync_seconds` when dirty; hash-skips unchanged **Logs (All)** / Catalog |
| Tadoku batch submit | Scheduler every `scheduler.tadoku_process_seconds` (default 300s) |
| Local CSV backup | `.\scripts\docker\export-local-csv.ps1` |

**Seamless views:** With `sheets.formula_views: true` (default), filtering by type or queue status is done by Google Sheets itself. You only wait on the app for **SQLite ingest** (Manual/Logs edits → DB, or Plex/YouTube → Logs). Set `formula_views: false` to restore the old row-copy dumps if you need them.

**Sync design (quota-friendly):** User edits polled often. App writes focus on **Logs (All)** + Catalog. Formula tabs are installed once and left alone.

---

## Config reference

`config/settings.yaml` (host file, mounted into the container):

```yaml
sheets:
  enabled: true
  spreadsheet_id: "1abc..."
  service_account_file: "/app/data/google-service-account.json"
```

Docker Compose already mounts:

```yaml
volumes:
  - ./data:/app/data      # DB + service account JSON + exports
  - ./config:/app/config  # settings.yaml
```

You edit **`config/settings.yaml` on the host**; the container reads the same file.

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `sheets_disabled` | `sheets.enabled: true` and non-empty `spreadsheet_id` |
| Permission / 403 | Share the spreadsheet with the **service account email** as Editor |
| Can’t find sheet in Drive | Sheet owned by SA — use URL from `data/google-sheet-info.txt` or share with your Gmail |
| Key not found in container | File must be at `data/google-service-account.json` on host |
| Manual rows not importing | `imported` must be empty/false; content_type, title, amount required |

---

## Privacy note

The service account key can read/write only spreadsheets it owns or that were shared with it. Treat `data/google-service-account.json` like a password; do not commit it to git.
