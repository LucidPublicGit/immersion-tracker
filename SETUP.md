# Immersion Tracker — setup

**Goal:** tracker running on your machine with as few decisions as possible.  
Cloud (Sheets), Plex, Steam, etc. are **optional** and can wait.

---

## Minimum path (do this first)

### 0. Install Docker once

- Windows/macOS: [Docker Desktop](https://docs.docker.com/desktop/) → install → start → wait until **Running**
- Linux: Docker Engine + Compose plugin

### 1. Clone and setup

**Windows (PowerShell):**

```powershell
git clone https://github.com/LucidPublicGit/immersion-tracker.git
cd immersion-tracker
.\setup.ps1
```

**Linux / macOS:**

```bash
git clone https://github.com/LucidPublicGit/immersion-tracker.git
cd immersion-tracker
chmod +x setup.sh && ./setup.sh
```

What setup does:

- creates `config/settings.yaml` and `.env` if missing
- generates a real `WEBHOOK_SECRET` (not `changeme`)
- starts **only** `immersion-tracker` (not Tautulli)
- waits for http://127.0.0.1:8000/api/health
- writes `data/extension-connect.txt` (URL + secret for the browser extension)
- opens the queue UI in your browser

**Checkpoint:** http://127.0.0.1:8000/api/health → `"status":"ok"`.

You can log manually with zero integrations:

```powershell
curl -X POST http://127.0.0.1:8000/api/logs -H "Content-Type: application/json" -d "{\"content_type\":\"book\",\"title\":\"Test book\",\"amount\":5,\"unit\":\"pages\"}"
```

Daily commands:

| Task | Windows | Docker CLI |
|------|---------|------------|
| Start | `.\scripts\docker\start.ps1` | `docker compose up -d immersion-tracker` |
| Stop | `.\scripts\docker\stop.ps1` | `docker compose down` |
| Logs | `.\scripts\docker\logs.ps1` | `docker compose logs -f immersion-tracker` |
| Status | `.\scripts\docker\status.ps1` | — |
| Port flake (Desktop) | `.\scripts\docker\ensure-up.ps1` | — |

---

## Optional: YouTube extension

1. Server must be up (health OK).
2. Install extension **only** in the browser profile signed into your immersion YouTube account.
3. **Firefox:** `about:debugging#/runtime/this-firefox` → **Load Temporary Add-on** → `extension/manifest.json`  
   **Chrome/Edge:** `chrome://extensions` → Developer mode → **Load unpacked** → `extension/`
4. Popup → gear → paste **Server URL** + **Webhook secret** from `data/extension-connect.txt` → **Test server**.
5. Watch a short video past ~90% (and default min watch time) → log appears.

> Firefox temporary add-ons unload on full browser restart — reload `manifest.json` after restart.

Pack for another PC: `.\scripts\pack-extension.ps1` → `dist/`.

---

## Optional: Google Sheets

Sheets live in **Google’s cloud**, not as a local Excel file. Skip entirely if local SQLite + UI is enough.

**Fast path (service account keys allowed on your GCP project):**

1. Enable Sheets API + Drive API  
2. Service account JSON → `data/google-service-account.json`  
3. `.\scripts\docker\sheets-init.ps1`  
4. Share the sheet with the service account `client_email` as Editor if the script did not  

**If org blocks SA keys** (`iam.disableServiceAccountKeyCreation`): use OAuth instead —  
`.\scripts\docker\sheets-oauth-setup.ps1` after placing a Desktop OAuth client JSON at  
`data/google-oauth-client.json`. Details: [docs/GOOGLE_SHEETS.md](docs/GOOGLE_SHEETS.md).

Tabs expected: `Logs`, `Manual Entry`, `Catalog`, `Tadoku Queue`, `Metrics` (init script can create).

Sync anytime: `.\scripts\docker\sheets-sync.ps1`

---

## Optional: Tadoku queue

1. http://127.0.0.1:8000/queue  
2. Approve / skip pending  
3. Process READY → files under `data/tadoku_export/`  
4. No automatic submit to tadoku.app unless you wire a session later in the UI  

Modes (`auto` / `pending` / `never`) come from `config/settings.yaml` rules + catalog overrides.

---

## Optional: Plex / Tautulli

Bundled Tautulli is **off by default**.

```powershell
.\setup.ps1 -WithPlex
# or later:
docker compose --profile plex up -d
```

Tautulli UI: http://127.0.0.1:8181  

Webhook agent:

- URL: `http://host.docker.internal:8000/api/webhooks/tautulli` (Tautulli in Docker on same host)  
  or `http://127.0.0.1:8000/api/webhooks/tautulli` if Tautulli runs on the host  
- Header: `X-Webhook-Secret: <same as WEBHOOK_SECRET>`  
- Align `plex.library_map` in `config/settings.yaml` with your libraries → rebuild  

---

## Optional: other integrations

Steam, Spotify, Anki, mpv, asbplayer, Hoshi, GSM — each has a short doc under `docs/` and flags in `config/settings.example.yaml`.  

Interactive secrets helper (Windows): `.\scripts\setup-integrations.ps1`

---

## Without Docker

Python **3.12–3.13** (3.14 may fail on pinned deps):

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\activate
pip install -U pip
pip install -r requirements.txt
mkdir data -ErrorAction SilentlyContinue
if (-not (Test-Path config\settings.yaml)) { copy config\settings.example.yaml config\settings.yaml }
$env:DATABASE_URL = "sqlite:///./data/immersion.db"
$env:CONFIG_PATH = "config/settings.yaml"
$env:WEBHOOK_SECRET = "pick-a-long-random-string"
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

```bash
python3.13 -m venv .venv && source .venv/bin/activate
pip install -U pip && pip install -r requirements.txt
mkdir -p data
cp -n config/settings.example.yaml config/settings.yaml
export DATABASE_URL="sqlite:///./data/immersion.db"
export CONFIG_PATH="config/settings.yaml"
export WEBHOOK_SECRET="pick-a-long-random-string"
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

---

## Checklist

- [ ] Docker running  
- [ ] `.\setup.ps1` / `./setup.sh` → health OK  
- [ ] (Optional) Extension + `data/extension-connect.txt` → Test server OK  
- [ ] (Optional) Sheets / Plex / other docs  

---

## If something fails

| Symptom | Fix |
|---------|-----|
| Setup says Docker not running | Start Docker Desktop; wait until Running |
| Health fails | `.\scripts\docker\logs.ps1` |
| Browser can’t reach :8000 but container healthy | `.\scripts\docker\ensure-up.ps1` |
| Extension Test server fails | Server up? URL `http://127.0.0.1:8000`? Secret = `.env` / `extension-connect.txt`? |
| Extension no log | Watch ≥ ~90% + min seconds; F12 console; reload temp add-on after Firefox restart |
| Webhook 401 | Secret mismatch |
| `sheets_disabled` | `sheets.enabled: true` + restart; finish Sheets section above |

More detail: [README.md](README.md) · [docs/GOOGLE_SHEETS.md](docs/GOOGLE_SHEETS.md) · [extension/README.md](extension/README.md)
