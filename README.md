# Immersion Tracker

> **Status / expectations**
>
> This is a **vibe-coded** personal project that was cleaned up enough to share. I am **not** aiming for polished architecture or production code quality. It works for me; it might work for you.
>
> I **probably will not** maintain this for other users (no roadmap, no guaranteed fixes, no support SLA). Issues and PRs may sit forever. Fork it if you need it to evolve.
>
> Use at your own risk. Back up your data.

Self-hosted Japanese immersion logger. It records books, visual novels, games, anime, YouTube, and more into a local database, optionally mirrors them to **Google Sheets**, and maintains a **Tadoku.app** queue (what is pending, ready, pushed, or skipped).

| Feature | How it works |
|---------|----------------|
| Manual logs | API, Queue UI, or Google Sheet “Manual Entry” tab |
| YouTube | Browser extension logs when **≥90%** watched **and** ≥5 min progress; each video once ever |
| Plex / Tautulli | Webhooks when progress ≥90% or marked watched |
| Hoshi (Boox) | ADB pull of `statistics.json` (host script for USB) or Drive poll → character deltas ([docs/HOSHI.md](docs/HOSHI.md)) |
| GameSentenceMiner | Local SQLite line counts → VN/game characters ([GSM](config/settings.example.yaml)) |
| Steam | Playtime deltas for allowlisted apps ([docs/STEAM.md](docs/STEAM.md)) |
| AnkiConnect | Review time → study minutes ([docs/ANKI.md](docs/ANKI.md)) |
| Spotify | Recently played podcasts (allowlisted shows) ([docs/SPOTIFY.md](docs/SPOTIFY.md)) |
| mpv | Watch history / lua webhook → anime minutes ([docs/MPV.md](docs/MPV.md)) |
| asbplayer | Webhook / userscript when video finishes ([docs/ASBPLAYER.md](docs/ASBPLAYER.md)) |
| Tadoku queue | Hybrid rules: auto-export, review-then-push, or never |
| Google Sheets | Optional dashboard + manual entry + catalog overrides |
| Deploy | Docker Compose (or run FastAPI locally) |

**Stack:** Python 3.12+ (3.13 recommended), FastAPI, SQLite, optional gspread.

---

## Table of contents

1. [How it works](#how-it-works)
2. [Prerequisites](#prerequisites)
3. [Setup with Docker (recommended)](#setup-with-docker-recommended)
4. [Setup without Docker](#setup-without-docker)
5. [Important URLs](#important-urls)
6. [Configuration](#configuration)
7. [YouTube extension](#youtube-extension)
8. [Plex / Tautulli](#plex--tautulli)
9. [Manual logging](#manual-logging)
10. [Tadoku queue](#tadoku-queue)
11. [Google Sheets](#google-sheets)
12. [API reference](#api-reference)
13. [Data & files](#data--files)
14. [Tests](#tests)
15. [Troubleshooting](#troubleshooting)
16. [Roadmap / limits](#roadmap--limits)

---

## How it works

```
YouTube extension ──┐
Plex / Tautulli ────┤
Hoshi ADB / Drive ──┤
GSM (local SQLite) ─┼──► FastAPI ──► SQLite (source of truth)
Steam / Anki / Spotify / mpv / asbplayer
Manual API / Sheet ─┘       ├──► Tadoku queue (pending / ready / pushed)
                            ├──► data/tadoku_export/*.json  (export “push”)
                            └──► Google Sheets (optional sync)
```

1. A **log entry** is created (manual or auto).
2. **Rules** decide Tadoku mode: `auto`, `pending`, or `never`.
3. Status becomes `ready`, `pending`, or `skipped`.
4. You approve pending items if needed, then **process** ready items.
5. “Push” currently writes JSON exports under `data/tadoku_export/` (tadoku.app has no public third-party submit API yet). Use those for manual contest entry or plug in a real client later.

SQLite is the source of truth. Sheets is a human-friendly view and input surface, not the primary database.

---

## Prerequisites

- **Docker Desktop** (or Docker Engine + Compose), **or** Python **3.12–3.13**
- **Firefox 121+** (recommended) or Chrome / Edge (for the YouTube extension)
- Optional: Plex or Tautulli on the same LAN
- Optional: Google Cloud service account for Sheets

> **Note:** Python 3.14 may fail to install pinned deps (pydantic). Prefer 3.13.

---

## Setup with Docker (recommended)

### One-shot setup (Windows)

```powershell
cd C:\path	o\immersion-tracker
.\scripts\docker\setup.ps1
```

Creates `config/settings.yaml` + `.env` if missing, builds, starts, waits for health.

### Helper scripts

| Script | Purpose |
|--------|---------|
| `.\scripts\docker\setup.ps1` | First-time setup + build + start |
| `.\scripts\docker\start.ps1` | Start stack |
| `.\scripts\docker\stop.ps1` | Stop stack (keeps `data/` + `config/`) |
| `.\scripts\docker\rebuild.ps1` | Rebuild image + recreate container |
| `.\scripts\docker\logs.ps1` | Follow logs |
| `.\scripts\docker\status.ps1` | Compose status + health + metrics |
| `.\scripts\docker\shell.ps1` | Shell inside container |
| `.\scripts\docker\sheets-init.ps1` | Create Google Sheet + wire config |
| `.\scripts\docker\sheets-sync.ps1` | Force sheet sync now |
| `.\scripts\docker\export-local-csv.ps1` | Dump logs/queue to `data/local-exports/` (no Google) |

### Manual Docker commands

```powershell
cd C:\path	o\immersion-tracker
copy config\settings.example.yaml config\settings.yaml   # if needed
copy .env.example .env                                   # set WEBHOOK_SECRET
docker compose up --build -d
curl http://127.0.0.1:8000/api/health
docker compose down
```

**Volumes (host folders, not anonymous Docker volumes):**

| Host path | Container | Purpose |
|-----------|-----------|---------|
| `./data` | `/app/data` | SQLite DB, Tadoku exports, **optional** Google service-account JSON |
| `./config` | `/app/config` | `settings.yaml` you edit on the PC |

Default port: **8000**.

### Google Sheets — important (not a local Excel file)

We did **not** ship a spreadsheet file on disk. **Google Sheets lives in Google’s cloud.** You open it in the browser like any Drive doc.

Docker does **not** “open a sheet from your Documents folder.” It talks to **Google’s API** using a **service account key** you drop in `data/google-service-account.json` (that file *is* on your PC and is mounted into the container).

```
Browser  ←→  Google Sheet (cloud)
                ↑
         Sheets API (HTTPS)
                ↑
Docker  ←  mounts only the JSON key + config from ./data and ./config
```

Full walkthrough: **[docs/GOOGLE_SHEETS.md](docs/GOOGLE_SHEETS.md)**

Quick path:

```powershell
# 1. Save GCP service account JSON as:
#    data\google-service-account.json
.\scripts\docker\sheets-init.ps1   # creates sheet, patches settings, syncs
.\scripts\docker\sheets-sync.ps1   # force sync anytime
```

Without Google, use the API, `/queue` UI, or `export-local-csv.ps1`.

---

## Setup without Docker

Use **Python 3.13** if available:

```powershell
cd C:\path	o\immersion-tracker

py -3.13 -m venv .venv
.\.venv\Scripts\activate
python -m pip install -U pip
pip install -r requirements.txt

# Create data dir + settings if missing
mkdir data -ErrorAction SilentlyContinue
if (-not (Test-Path config\settings.yaml)) {
  copy config\settings.example.yaml config\settings.yaml
}

$env:DATABASE_URL = "sqlite:///./data/immersion.db"
$env:CONFIG_PATH = "config/settings.yaml"
$env:WEBHOOK_SECRET = "pick-a-long-random-string"

uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Linux / macOS:

```bash
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL="sqlite:///./data/immersion.db"
export CONFIG_PATH="config/settings.yaml"
export WEBHOOK_SECRET="pick-a-long-random-string"
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

---

## Important URLs

| URL | What |
|-----|------|
| http://localhost:8000/ | Home |
| http://localhost:8000/docs | Interactive OpenAPI (Swagger) |
| http://localhost:8000/queue | **Tadoku queue UI** (approve / skip / process) |
| http://localhost:8000/api/health | Health check |
| http://localhost:8000/api/metrics | Totals & breakdowns |
| http://localhost:8000/api/logs | List logs |
| http://localhost:8000/api/queue | Queue as JSON |
| http://localhost:8000/api/sheet-template | Column headers for Sheets tabs |

---

## Configuration

Primary file: **`config/settings.yaml`**  
Template: **`config/settings.example.yaml`**

### Environment variables

| Variable | Default (Docker) | Meaning |
|----------|------------------|---------|
| `DATABASE_URL` | `sqlite:////app/data/immersion.db` | SQLAlchemy DB URL |
| `CONFIG_PATH` | `/app/config/settings.yaml` | Path to YAML settings |
| `WEBHOOK_SECRET` | `changeme` in compose | Required header for webhooks if set |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | empty | Full service-account JSON string (Sheets) |

If `WEBHOOK_SECRET` is **empty**, webhooks are open (dev only). In production always set a secret.

### YouTube (`youtube:`)

```yaml
youtube:
  completion_threshold: 0.90   # 0.0–1.0; only log at/above this ratio
  min_watched_seconds: 300     # also require this much watch progress (0 = ratio only)
  channel_allowlist: []        # empty = all channels; e.g. ["UCxxxx", "@SomeHandle"]
  channel_blocklist: []        # always reject these channel ids
  tadoku_default: auto         # default Tadoku mode for YT if type default missing
```

### Plex (`plex:`)

```yaml
plex:
  watch_threshold: 0.90
  library_map:
    Anime: anime
    Movies: show
    TV Shows: show
  tadoku_default: pending
```

Map your Plex **library names** → internal content types (`anime`, `show`, etc.).

### Content types & Tadoku defaults

```yaml
content_type_defaults:
  book:
    activity: reading      # reading | listening | study | ...
    unit: pages            # pages | comic_pages | characters | minutes | ...
    tadoku_mode: pending   # auto | pending | never
  youtube:
    activity: listening
    unit: minutes
    tadoku_mode: auto
  # ... see settings.example.yaml for full list
```

Built-in types: `book`, `manga`, `visual_novel`, `game`, `anime`, `show`, `youtube`, `podcast`, `study`.

### Tadoku score estimates

Approximate contest score using official-style JP multipliers (pages, minutes, characters, etc.). Configured under `tadoku_scores:` — used for **local estimates**, not submitted automatically to tadoku.app.

### Sheets (`sheets:`)

```yaml
sheets:
  enabled: false
  spreadsheet_id: ""
  service_account_file: ""   # e.g. /app/data/sa.json inside Docker
  tabs:
    logs: Logs
    manual: Manual Entry
    catalog: Catalog
    queue: Tadoku Queue
    metrics: Metrics
```

### Scheduler

```yaml
sheets:
  poll_manual_seconds: 20   # sheet→DB user-edit poll (reads; cheap)
  push_sync_seconds: 180    # DB→Logs (All) when dirty; hash-skipped if unchanged
  formula_views: true       # type tabs / Queue / Metrics = live FILTER over Logs
scheduler:
  enabled: true
  sheet_sync_seconds: 180       # fallback push interval
  tadoku_process_seconds: 300   # batch tadoku submit (independent of sheets)
```

**Logs (All)** is the only log table the app writes. Type tabs, Tadoku Queue, and Metrics are Google **formulas** (not row copies), so they update in the browser as soon as Logs changes. Edit `tadoku_mode` / `tadoku_status` on **Logs (All)**. Sheet **pull** runs often so browser edits land in SQLite; **push** is slower and hash-skips unchanged data.

---

## YouTube extension

More detail (Firefox-focused): **[`extension/README.md`](extension/README.md)**

YouTube’s public APIs do **not** expose “percent of this video I watched.” This project ships a **Manifest V3** WebExtension that:

1. Runs a content script on `youtube.com` / `m.youtube.com`
2. Measures the HTML5 player (`currentTime / duration`)
3. When progress reaches your threshold (default **90%**), POSTs once to Immersion Tracker

Works in:

| Browser | Minimum | Install style |
|---------|---------|----------------|
| **Firefox** | **121+** | Temporary add-on via `about:debugging` (see below) |
| Chrome / Edge / Brave | recent Chromium | Load unpacked |

### Why 90%?

- Avoids logging videos you opened and abandoned  
- Large seek-to-end jumps without prior progress are dampened (scrubbing to 99% without watching usually won’t fire)  
- Threshold % and min watch time are configurable in the extension and should stay in line with server `youtube.completion_threshold` (0.90) and `youtube.min_watched_seconds` (300)

### Install on Firefox (recommended)

1. Start Immersion Tracker so `http://127.0.0.1:8000/api/health` works.
2. In Firefox, open:

   ```
   about:debugging#/runtime/this-firefox
   ```

3. Click **Load Temporary Add-on…**
4. Select **`extension/manifest.json`** in this repo  
   (`C:\path	o\immersion-tracker\extension\manifest.json`)
5. You should see **Immersion Tracker YouTube** listed and enabled.
6. Open the extension panel (puzzle piece → pin the add-on) and set:

   | Setting | What to put |
   |---------|-------------|
   | **Server URL** | `http://127.0.0.1:8000` |
   | **Webhook secret** | Same as `WEBHOOK_SECRET` (Docker Compose default is `changeme` if you never changed `.env`) |
   | **Threshold** | `0.9` |
   | **Enabled** | checked |

7. Click **Save**, then **Test server** — you want `Server OK` with a health JSON body.
8. Open a YouTube video, watch to ≥90% (or let it finish after watching most of it).
9. Confirm a log:

   ```powershell
   curl "http://127.0.0.1:8000/api/logs?source=youtube"
   ```

   Or open http://127.0.0.1:8000/queue

#### Firefox notes

| Topic | Detail |
|-------|--------|
| **Temporary add-on** | Removed when Firefox **fully restarts**. After restart: `about:debugging` → Load Temporary Add-on again (same `manifest.json`). Your saved settings usually persist under the fixed Gecko id. |
| **Permanent install** | Release Firefox blocks unsigned permanent add-ons. Options: re-load temporary each session; use **Developer Edition/Nightly** + `xpinstall.signatures.required=false` + an `.xpi`; or get the extension signed on AMO (unlisted). |
| **Private windows** | Add-on details → allow **Run in Private Windows** if you watch YouTube there. |
| **Version** | Manifest requires Firefox **121+** (MV3 service worker background). |
| **Gecko id** | `immersion-tracker-youtube@local.dev` (in `manifest.json`) |

Optional: zip as `.xpi` for temporary load:

```powershell
cd C:\path	o\immersion-tracker\extension
Compress-Archive -Path manifest.json,*.js,*.html -DestinationPath ..\immersion-tracker-youtube.zip -Force
Rename-Item ..\immersion-tracker-youtube.zip ..\immersion-tracker-youtube.xpi -Force
# Then Load Temporary Add-on → pick the .xpi
```

### Install on Chrome / Edge

1. `chrome://extensions` or `edge://extensions`
2. **Developer mode** on
3. **Load unpacked** → select the `extension/` **folder**
4. Configure popup the same way as Firefox (Server URL, secret, threshold, Test server)

### Settings reference

| Setting | Default | Description |
|---------|---------|-------------|
| Server URL | `http://127.0.0.1:8000` | Base URL of Immersion Tracker |
| Webhook secret | _(empty)_ | Sent as `X-Webhook-Secret`; required if the server has `WEBHOOK_SECRET` set |
| Threshold | `0.9` | 0–1 fraction of duration that must be watched |
| Enabled | on | Disable to pause logging without removing the add-on |

Settings use **`storage.local`** (no Firefox Account required).

#### Server not on this PC

`localhost` / `127.0.0.1` are already allowed. For e.g. `http://192.168.1.50:8000`:

1. Enter that URL → **Save** (browser may prompt for optional host permission).
2. If fetch still fails, add the origin to `host_permissions` in `extension/manifest.json`, e.g. `"http://192.168.1.50:8000/*"`, then reload the extension.

### Behavior (what the extension does)

```
YouTube tab (content.js)
  → every ~2s read video progress
  → when ratio ≥ threshold
  → message background.js
  → POST /api/webhooks/youtube
  → SQLite log (+ Tadoku queue)
```

- **Dedupe on server:** same `video_id` **once ever** (not once per day)  
- **Amount logged:** full video duration in **minutes** (good for Tadoku if you watch at >1×)  
- **Content type:** `youtube` → default Tadoku mode **`auto`** → status **`ready`**  
- **Series key:** `yt:{channel_id}` when the channel can be detected  

### Example webhook payload

```json
{
  "video_id": "dQw4w9WgXcQ",
  "title": "Video title",
  "channel_id": "UCxxxx",
  "channel_title": "Channel",
  "duration_seconds": 600,
  "watched_seconds": 540,
  "ratio": 0.9,
  "url": "https://www.youtube.com/watch?v=...",
  "finished_at": "2026-07-11T20:00:00+00:00"
}
```

### Debug the extension

1. Popup → **Test server** must succeed first.
2. On a YouTube tab press **F12** → Console. You should see:

   ```
   [immersion-tracker] YouTube content script loaded (Firefox/Chromium)
   [immersion-tracker] report result { ok: true, status: 201, ... }
   ```

3. Firefox: `about:debugging` → inspect the extension’s **background** script for fetch errors.
4. Server rejected? Check `reason` in the response body (`below_threshold`, `duplicate`, `channel_blocked`, …).

### Test the webhook without the extension

```powershell
curl -X POST http://127.0.0.1:8000/api/webhooks/youtube `
  -H "Content-Type: application/json" `
  -H "X-Webhook-Secret: changeme" `
  -d "{\"video_id\":\"test1\",\"title\":\"CI practice\",\"channel_id\":\"UCtest\",\"duration_seconds\":600,\"watched_seconds\":540,\"ratio\":0.9}"
```

### Extension file layout

```
extension/
  manifest.json     # MV3 + Firefox gecko id
  browser-api.js    # Chrome/Firefox API helper
  content.js        # Progress detection on YouTube
  background.js     # POST to Immersion Tracker
  popup.html/js     # Settings + Test server
  README.md         # Extension-only guide
```

---

## Plex / Tautulli

### Endpoints

| Endpoint | Use |
|----------|-----|
| `POST /api/webhooks/plex` | Normalized JSON or Tautulli-like body |
| `POST /api/webhooks/tautulli` | Tautulli webhook payload |

Header (if secret set):

```http
X-Webhook-Secret: your-secret
```

### Tautulli setup (typical)

1. Tautulli → Settings → Notification Agents → webhook.
2. URL: `http://<host-running-tracker>:8000/api/webhooks/tautulli`
3. Trigger on **watched** (and optionally high progress).
4. Add header `X-Webhook-Secret` if you use one.
5. Ensure the host can reach the tracker (same LAN / reverse proxy).

### Normalized Plex body example

```json
{
  "rating_key": "12345",
  "title": "Episode title",
  "grandparent_title": "Show Name",
  "library_name": "Anime",
  "media_type": "episode",
  "duration_ms": 1440000,
  "progress_percent": 95,
  "watched": true
}
```

Accepted when `watched` is true **or** progress ≥ `plex.watch_threshold`.  
Default Tadoku mode for Plex-mapped anime/shows: **`pending`** (review before export).

---

## Manual logging

### API

```powershell
curl -X POST http://localhost:8000/api/logs `
  -H "Content-Type: application/json" `
  -d "{\"content_type\":\"book\",\"title\":\"こころ\",\"amount\":12,\"unit\":\"pages\",\"series_key\":\"book:kokoro\"}"
```

Fields:

| Field | Required | Notes |
|-------|----------|--------|
| `content_type` | yes | e.g. `book`, `anime`, `visual_novel` |
| `title` | yes | Display title |
| `amount` | yes | Number of pages / minutes / etc. |
| `unit` | no | Defaults from content type |
| `activity` | no | Defaults from content type |
| `series_key` | no | Links to catalog + overrides |
| `source` | no | Default `manual` |
| `tadoku_mode` | no | Force `auto` / `pending` / `never` for this row |

### Google Sheet “Manual Entry”

Columns (also listed at `/api/sheet-template`):

```
content_type | title | amount | unit | series_key | activity | notes | imported
```

Leave `imported` empty; after sync the server sets it to `TRUE`.

### Catalog overrides

Catalog items can force Tadoku behavior per series:

```powershell
curl -X POST http://localhost:8000/api/catalog `
  -H "Content-Type: application/json" `
  -d "{\"series_key\":\"yt:UCxxxx\",\"display_title\":\"My JP Channel\",\"content_type\":\"youtube\",\"tadoku_override\":\"never\"}"
```

Or edit the **Catalog** sheet (`tadoku_override` = `auto` | `pending` | `never`) when Sheets sync is enabled.

---

## Tadoku queue

Target: **[tadoku.app](https://tadoku.app)** immersion contest logs (not the Eroge-Abyss desktop VN app).

### Rule resolution (highest wins)

1. **Catalog** `tadoku_override` for `series_key`
2. **Content type** default (`content_type_defaults.*.tadoku_mode`)
3. **Source** default (YouTube / Plex yaml)
4. Fallback: `pending`

### Modes → status

| Mode | Initial status | Meaning |
|------|----------------|---------|
| `auto` | `ready` | Eligible to process/export without manual approve |
| `pending` | `pending` | You review first |
| `never` | `skipped` | Do not send to Tadoku |

Other statuses: `pushed`, `failed`.

### Workflow

1. Open **http://localhost:8000/queue**
2. **Approve** pending items you want to count toward Tadoku  
3. **Skip** items that should not  
4. Click **Process READY (export)** (or wait for the scheduler)

CLI equivalents:

```http
POST /api/logs/{id}/approve
POST /api/logs/{id}/skip
POST /api/tadoku/process
GET  /api/queue
```

### What “push” does today

Each processed entry becomes a JSON file:

```
data/tadoku_export/export-<id>.json
```

Example fields: activity, language, amount, unit, title, score estimate, local log id.

There is **no official public tadoku.app submit API** for third-party apps. Export is intentional. To automate real submits later, replace or extend `app/tadoku/client.py`.

Contest tips (from Tadoku’s own rules spirit): prefer **regular** updates, not one huge dump at contest end; only reading/listening usually count in official contests.

---

## Google Sheets

**See [docs/GOOGLE_SHEETS.md](docs/GOOGLE_SHEETS.md)** for architecture, setup, and FAQ.

### Mental model

| Item | Where it lives |
|------|----------------|
| Spreadsheet you edit | **Google Drive (cloud)** — browser URL |
| Service account key | **Your PC** `data/google-service-account.json` → Docker `/app/data/...` |
| Log database | **Your PC** `data/immersion.db` (SQLite, mounted) |
| Empty starter sheet in the repo? | **No** — create with `sheets-init.ps1` or manually in Drive |

### Fast setup

```powershell
# After placing data\google-service-account.json
.\scripts\docker\sheets-init.ps1
# Open the printed docs.google.com URL in your browser
.\scripts\docker\sheets-sync.ps1
```

Or configure by hand in `config/settings.yaml`:

```yaml
sheets:
  enabled: true
  spreadsheet_id: "YOUR_ID"
  service_account_file: "/app/data/google-service-account.json"
```

Tabs: Logs, Manual Entry, Catalog, Tadoku Queue, Metrics (auto-created if missing).  
Headers: `GET /api/sheet-template`  
Sync: scheduler, or `POST /api/sync/sheets`, or `.\scripts\docker\sheets-sync.ps1`

**Manual Entry columns:** `content_type, title, amount, unit, series_key, activity, notes, imported`  
Leave `imported` blank; after sync it becomes `TRUE`.

---

## API reference

Base path: `/api` (OpenAPI: `/docs`).

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Liveness |
| GET | `/metrics` | Aggregates |
| GET | `/logs` | List (`tadoku_status`, `content_type`, `source`, `limit`) |
| GET | `/logs/{id}` | One log |
| POST | `/logs` | Create manual log |
| POST | `/logs/{id}/approve` | Pending → ready |
| POST | `/logs/{id}/skip` | Skip Tadoku |
| GET | `/queue` | Tadoku queue items |
| POST | `/tadoku/process` | Export all ready |
| POST | `/webhooks/youtube` | Extension / YT complete |
| POST | `/webhooks/plex` | Plex payload |
| POST | `/webhooks/tautulli` | Tautulli payload |
| GET/POST | `/catalog` | List / create catalog |
| PATCH | `/catalog/{series_key}` | Update override |
| POST | `/sync/sheets` | Force sheet sync |
| GET | `/sheet-template` | Sheet column names |

Webhook auth: header `X-Webhook-Secret` must match `WEBHOOK_SECRET` when secret is non-empty.

---

## Data & files

```
immersion-tracker/
├── app/                 # FastAPI application
├── config/
│   ├── settings.yaml          # Your config (edit this)
│   └── settings.example.yaml  # Template
├── data/
│   ├── immersion.db           # SQLite (created at runtime)
│   └── tadoku_export/         # Exported Tadoku payloads
├── extension/           # Firefox + Chromium MV3 YouTube logger
├── tests/
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
└── README.md
```

**Backup:** copy `data/immersion.db` and `config/settings.yaml`.

---

## Tests

```powershell
cd C:\path	o\immersion-tracker
.\.venv\Scripts\activate   # if using local venv
python -m pytest -q
```

Coverage focuses on:

- YouTube threshold / dedupe / blocklist
- Plex threshold / mapping
- Tadoku rules, approve, process/export
- Metrics
- **Tadoku upstream contracts** (`tests/test_tadoku_upstream.py`) — live GET-only
  checks of contest leaderboard page + public immersion API shape. Fails if
  tadoku.app moves paths (e.g. bare `/contests/{id}` 404). Skips if offline.
  Optional auth-gated probes need `data/tadoku_session.cookie` or
  `IMMERSION_TADOKU_UPSTREAM_COOKIE`.
- **Runtime path monitor** (while Docker/app is running): every
  `scheduler.tadoku_upstream_check_hours` (default **12h**, plus once on boot)
  two GET canaries (leaderboard HTML + API). Failures log `ERROR`; status at
  `GET /api/tadoku/upstream` and `data/tadoku_upstream_status.json`.

Smoke script:

```powershell
$env:PYTHONPATH = (Get-Location).Path
python scripts\smoke.py
```

---

## Troubleshooting

| Problem | What to try |
|---------|-------------|
| Extension does nothing | Confirm server URL, Enabled, threshold; F12 on youtube.com for `[immersion-tracker]` logs; reload tab after installing |
| Firefox extension vanished | Temporary add-ons die on restart → `about:debugging` → Load Temporary Add-on again |
| Firefox won’t load add-on | Need Firefox **121+**; select `extension/manifest.json` (not a parent folder zip of the whole repo) |
| `401` on webhooks | Set popup **Webhook secret** = `WEBHOOK_SECRET` (Compose default `changeme` if unset) |
| Extension cannot reach server | Use `http://127.0.0.1:8000`; popup **Test server**; for LAN IP grant host permission or edit `host_permissions` |
| Below threshold rejections | Server requires ≥ `youtube.completion_threshold` (default 0.90) **and** ≥ `youtube.min_watched_seconds` (default 300). Seeking to the end without watching enough may not count |
| Duplicate YouTube log | Same `video_id` was already logged (once ever). Rewatches do not count again |
| Plex events ignored | Progress under threshold and not `watched`; check `library_name` mapping |
| Sheets disabled | `sheets.enabled: false` or missing credentials / spreadsheet share |
| Python install fails | Use Python 3.13, not 3.14 |
| Port in use | Change `"8000:8000"` in `docker-compose.yml` |
| DB location | Docker: `data/immersion.db` on host via volume |

Logs (Docker):

```powershell
docker compose logs -f immersion-tracker
```

---

## Roadmap / limits

**Working now**

- Manual + YouTube (90%) + Plex/Tautulli ingest  
- Hoshi (Boox) + GameSentenceMiner  
- Steam playtime deltas, AnkiConnect study time, Spotify podcasts  
- mpv history/webhook + asbplayer webhook  
- Rule-based Tadoku queue + live submit (when credentials set)  
- Optional Google Sheets sync  
- Queue / Progress / Reading UI  

**Not automatic yet**

- Mobile YouTube app (extension is desktop **Firefox/Chromium** only)  
- Commercial streamers (Netflix / Crunchyroll / etc. — no reliable API)  
- Kindle / Audible progress  


**Security**

- Do not expose port 8000 to the public internet without auth/TLS.  
- Always set a strong `WEBHOOK_SECRET`.  
- Treat service-account JSON and `.env` as secrets (they are gitignored patterns; keep keys out of git).

---

## Quick checklist

- [ ] `docker compose up --build -d` (or local uvicorn)
- [ ] `GET /api/health` returns ok
- [ ] Set `WEBHOOK_SECRET` and match it in the extension / Tautulli
- [ ] Firefox: `about:debugging` → load `extension/manifest.json`; popup **Test server** OK; finish a JP video to ≥90%
- [ ] Optional: wire Plex/Tautulli webhook
- [ ] Optional: enable Sheets + share spreadsheet with service account
- [ ] Use `/queue` to approve pending anime/etc. and process READY exports
- [ ] Copy `data/tadoku_export/` entries into tadoku.app as needed

Happy immersion.
