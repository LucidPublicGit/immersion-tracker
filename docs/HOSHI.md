# Hoshi Reader (Boox) + Immersion Tracker

Two different jobs:

| Job | How |
|-----|-----|
| **Set up** the Boox / Hoshi / tracker config | **ADB** — `scripts/boox-hoshi-setup.ps1` |
| **Log characters read** automatically | **Google Drive poll** (default) — Hoshi already syncs stats there |

ADB is great for install/permissions/launch. It **cannot** complete Hoshi’s Google OAuth or flip private in-app toggles. Stock release Hoshi also **cannot** expose `statistics.json` over ADB without a debug build or root.

```
Setup (once)                         Daily use
────────────                         ─────────
PC ──ADB──► Boox                     Boox Hoshi ──autosync──► Drive
  install Hoshi                            │
  grant perms                              │ poll every N min
  open app                                 ▼
  enable tracker config              immersion-tracker → logs
```

---

## 1. Device setup via ADB

Plug in the Boox (USB debugging on, authorize this PC).

```powershell
cd C:\path\to\immersion-tracker

# Status only
.\scripts\boox-hoshi-setup.ps1 -StatusOnly

# Full prep: ensure adb, detect device, grant perms, open Hoshi
.\scripts\boox-hoshi-setup.ps1 -OpenApp

# Also download+install latest Hoshi APK from GitHub
.\scripts\boox-hoshi-setup.ps1 -InstallHoshi -OpenApp

# Turn on tracker config (Drive progress source)
.\scripts\boox-hoshi-setup.ps1 -EnableTracker -Source drive
```

What ADB **does** automate:

- Find / install `platform-tools` (`adb`)
- Detect serial / model (your Go7 shows as online)
- Install or update Hoshi APK from GitHub releases (`-InstallHoshi`)
- Grant installable permissions (`INTERNET`, `WAKE_LOCK`, …)
- Stay-on-while-plugged (helps first sync)
- Launch Hoshi
- Patch `config/settings.yaml` (`-EnableTracker`)

What you still do **on the device UI**:

1. Hoshi → **Sync / Google Drive** → connect account  
2. Enable **autosync** (progress + statistics)  
3. Read a little with **Wi‑Fi on** so Drive gets `ttu-reader-data/`  
4. If tracker uses a **service account**, share that Drive folder with the SA email  

---

## 2. Progress auto-logging (Drive)

After Hoshi is syncing to Drive:

```yaml
# config/settings.yaml
hoshi:
  enabled: true
  source: drive              # recommended on stock release Hoshi
  root_folder_name: "ttu-reader-data"
  poll_seconds: 300
  bootstrap: true
```

```powershell
.\scripts\docker\rebuild.ps1   # or restart container

Invoke-RestMethod http://127.0.0.1:8000/api/hoshi/status
Invoke-RestMethod -Method POST http://127.0.0.1:8000/api/hoshi/sync
```

### Auth

| Credential mode | Requirement |
|-----------------|-------------|
| OAuth (same Google account as Hoshi) | Token under `data/google-oauth-token.json` |
| Service account (Sheets SA) | Share **`ttu-reader-data`** with the SA email |

### Deltas

Hoshi stores per-day stats (`dateKey` = `YYYY-MM-DD`, `charactersRead`).  
Tracker logs **positive deltas** only (`source=hoshi`, `unit=characters`).

---

## 3. Optional: ADB progress reads

Only works if you can read app private storage:

- Debug Hoshi (`moe.antimony.hoshi.debug`), or  
- Root / open firmware  

```yaml
hoshi:
  source: adb   # or auto (ADB then Drive)
```

Host USB poller (Docker Desktop cannot see USB):

```powershell
.\scripts\hoshi_adb_poll.ps1
```

Verified on **Boox Go7 + release Hoshi 1.3.1**: `run-as` blocked, `/data/data/...` denied — use **Drive** for logging.

---

## API

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/hoshi/status` | Config + last poll |
| `POST` | `/api/hoshi/sync` | Run Drive/ADB poll now |
| `POST` | `/api/hoshi/ingest-stats` | Host script push (ADB poller) |

---

## Scripts

| Script | Role |
|--------|------|
| `scripts/boox-hoshi-setup.ps1` | **ADB setup** (this is what “use ADB” means for onboarding) |
| `scripts/install-platform-tools.ps1` | Install `adb` into `tools/platform-tools/` |
| `scripts/hoshi_adb_poll.ps1` | Optional ADB stats pull → API |
