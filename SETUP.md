# Immersion Tracker — setup

**Goal:** tracker running fast, then optional sources that feed **Tadoku**.

| Path | Command |
|------|---------|
| Core only | `.\setup.ps1` / `./setup.sh` |
| Core + features (prompt or forced) | `.\setup.ps1 -Wizard` / `./setup.sh --wizard` |
| Features only | `.\scripts\setup-wizard.ps1` / `./scripts/setup-wizard.sh` |
| Core without wizard prompt | `.\setup.ps1 -NoWizard` / `./setup.sh --no-wizard` |

**Nested flow:** `setup` starts Docker only; the wizard uses `-SkipCore` / `--skip-core` so it does not loop.  
Everything after core is **optional**.

---

## Minimum path (core)

### 0. Install Docker once

- Windows/macOS: [Docker Desktop](https://docs.docker.com/desktop/) → **Running**
- Linux: Docker Engine + Compose plugin

### 1. Clone and setup

```powershell
git clone https://github.com/LucidPublicGit/immersion-tracker.git
cd immersion-tracker
.\setup.ps1
```

```bash
git clone https://github.com/LucidPublicGit/immersion-tracker.git
cd immersion-tracker
chmod +x setup.sh scripts/setup-wizard.sh
./setup.sh
```

What core setup does:

- `config/settings.yaml` + `.env` (creates if missing)
- random `WEBHOOK_SECRET`
- starts **immersion-tracker** only (not Tautulli)
- health check + `data/extension-connect.txt`
- opens Queue UI
- **prompts for the feature wizard** (Tadoku / Plex / GSM / Hoshi / …)

**Checkpoint:** http://127.0.0.1:8000/api/health → `"status":"ok"`.

Manual log smoke test:

```powershell
curl -X POST http://127.0.0.1:8000/api/logs -H "Content-Type: application/json" -d "{\"content_type\":\"book\",\"title\":\"Test book\",\"amount\":5,\"unit\":\"pages\"}"
```

| Daily | Windows | Docker CLI |
|-------|---------|------------|
| Start | `.\scripts\docker\start.ps1` | `docker compose up -d immersion-tracker` |
| Stop | `.\scripts\docker\stop.ps1` | `docker compose down` |
| Logs | `.\scripts\docker\logs.ps1` | `docker compose logs -f` |
| Status | `.\scripts\docker\status.ps1` | — |
| Port flake | `.\scripts\docker\ensure-up.ps1` | — |

---

## Feature wizard (recommended)

The wizard **does not assume** Docker, Python, GSM, Plex, Hoshi, or a browser extension
are already installed. It checks each dependency, prints install links when something is
missing, and can still write `.env` / cheat sheets in **config-only** mode.

When Docker is not ready, the end screen prints the exact next commands to run later.

```powershell
.\scripts\setup-wizard.ps1
.\scripts\setup-wizard.ps1 -Tadoku -Plex -Gsm
.\scripts\setup-wizard.ps1 -All -Yes -NoPause
.\scripts\setup-wizard.ps1 -Plex -PlexLibraries "Anime=anime,TV Shows=show"
.\scripts\setup-wizard.ps1 -Timezone America/Los_Angeles -GsmDataDir "$env:APPDATA\GameSentenceMiner"
```

```bash
./scripts/setup-wizard.sh
./scripts/setup-wizard.sh --tadoku --plex --gsm
./scripts/setup-wizard.sh --all --yes --no-pause
./scripts/setup-wizard.sh --plex-libraries 'Anime=anime,TV Shows=show'
./scripts/setup-wizard.sh --timezone America/Los_Angeles --gsm-data-dir "$HOME/..."
```

### Suggested combinations

| You care about | Enable in wizard |
|----------------|------------------|
| Contest submit | **Tadoku** (always if using tadoku.app) |
| Anime on Plex | Tadoku + **Plex** |
| VN / games via GSM | Tadoku + **GSM** |
| Boox reading | Tadoku + **Hoshi** |
| YouTube | **YouTube** (+ Tadoku if contest) |

---

## Tadoku.app (manual steps if not using wizard)

1. Join/create contest on https://tadoku.app  
2. http://127.0.0.1:8000/queue → **Save login** (email/username + password)  
3. List registrations:

   ```powershell
   .\scripts\docker\tadoku-list-registrations.ps1
   ```

4. Put `registration_id` (and optional `contest_id` / `name`) under `tadoku.contest` in `config/settings.yaml`  
5. Restart: `.\scripts\docker\rebuild.ps1`  
6. Daily: Queue → **Approve (+ submit)** or Process READY  

Detail: [docs/TADOKU.md](docs/TADOKU.md)

---

## Plex / Tautulli

```powershell
.\setup.ps1 -WithPlex
# or wizard -Plex path / docker compose --profile plex up -d
```

- Tautulli UI: http://127.0.0.1:8181  
- Webhook URL is written to `data/plex-tautulli-connect.txt` by the wizard (includes `?secret=` from `.env`)  
- **Watched** trigger + JSON body required (see [docs/PLEX.md](docs/PLEX.md))  
- `config/settings.yaml` → `plex.library_map` keys = exact Plex library names  

---

## GameSentenceMiner (GSM)

1. Install/run [GSM](https://github.com/GameSentenceMiner/GameSentenceMiner) so `gsm.db` exists (Windows default: `%APPDATA%\GameSentenceMiner`)  
2. Wizard sets `GSM_DATA_DIR` in `.env` (Docker mounts it at `/gsm`)  
3. `gsm.enabled: true` in settings  
4. Queue → GSM tools → Approve to Tadoku  

---

## Hoshi / Boox

1. Device: Hoshi → Google Drive sync + autosync/statistics  
2. Drive folder `ttu-reader-data` visible on PC  
3. Tracker reads Drive (OAuth same account, or share folder with Sheets SA)  
4. `hoshi.enabled: true`, `source: drive`  
5. `POST /api/hoshi/sync`  

Windows ADB helpers: `.\scripts\boox-hoshi-setup.ps1`  
Detail: [docs/HOSHI.md](docs/HOSHI.md)

---

## YouTube extension

1. Load `extension/` (Firefox temporary add-on or Chrome unpacked)  
2. Paste Server URL + secret from `data/extension-connect.txt` → **Test server**  
3. Watch ≥ ~90% in the immersion account profile  

---

## Google Sheets (optional)

Not required for Tadoku. SQLite is source of truth.

- SA keys OK: `data/google-service-account.json` → `.\scripts\docker\sheets-init.ps1`  
- SA keys blocked: OAuth Desktop client → `.\scripts\docker\sheets-oauth-setup.ps1`  

[docs/GOOGLE_SHEETS.md](docs/GOOGLE_SHEETS.md)

---

## Other integrations

Steam, Spotify, Anki, mpv, asbplayer — `docs/*` + `.\scripts\setup-integrations.ps1`

---

## Without Docker

Python **3.12–3.13**:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
mkdir data -ErrorAction SilentlyContinue
copy config\settings.example.yaml config\settings.yaml
$env:DATABASE_URL = "sqlite:///./data/immersion.db"
$env:CONFIG_PATH = "config/settings.yaml"
$env:WEBHOOK_SECRET = "pick-a-long-random-string"
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Then run `.\scripts\setup-wizard.ps1` for guided feature steps (Docker-specific pieces will need manual equivalents).

---

## Checklist

- [ ] `.\setup.ps1` / `./setup.sh` → health OK  
- [ ] Wizard: **Tadoku** login + `registration_id`  
- [ ] Wizard: **Plex** and/or **GSM** and/or **Hoshi** as needed  
- [ ] Queue shows new logs → Approve submits  

---

## If something fails

| Symptom | Fix |
|---------|-----|
| Docker not running | Start Docker Desktop |
| Health fails | `.\scripts\docker\logs.ps1` |
| Host port dead, container healthy | `.\scripts\docker\ensure-up.ps1` |
| Tadoku list empty / 401 | Queue → Save login again; cookie in `data/tadoku_session.cookie` |
| Plex webhook 401 | URL must include `?secret=` matching `.env` |
| GSM not found | Set `GSM_DATA_DIR` to folder containing `gsm.db` |
| Hoshi sync empty | Drive folder + Google auth; `docs/HOSHI.md` |

More: [README.md](README.md) · [docs/TADOKU.md](docs/TADOKU.md) · [docs/PLEX.md](docs/PLEX.md) · [docs/HOSHI.md](docs/HOSHI.md)
