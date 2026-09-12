# Spotify podcasts → Immersion Tracker

Auto-log finished Spotify **podcast episodes** as listening minutes (Tadoku-friendly).

```
Spotify app plays episode
        │
        ▼
recently-played API  ──poll every N min──►  immersion-tracker
        │                                         │
        └──── OAuth refresh token ────────────────┘
                                              Logs / Queue / sheet sync
```

**Where to look for logs:** http://127.0.0.1:8000/queue ,  
http://127.0.0.1:8000/api/logs?source=spotify , or the Google Sheet.

---

## How it works

1. Scheduler calls `poll_spotify` (registry: `spotify`, default every **300s**).
2. Refresh OAuth access token from `token_file` (refresh_token grant).
3. `GET /v1/me/player/recently-played?limit=50` (plus optional currently-playing when ≥99% done).
4. Keep items that are **episodes** (type/show/context). With `podcasts_only: true` (default), music tracks are ignored.
5. Optional **show allowlist / blocklist** (show id or name substring).
6. Each episode id is logged **once ever**:
   - `source` = `spotify`
   - `source_ref` = `spotify:episode:{id}`
   - `series_key` = `spotify:show:{show_id}`
   - `amount` = `duration_ms / 60000` minutes
   - `title` = episode name (notes include show name)

Spotify’s public API does not expose a dedicated “recently played podcasts” endpoint. This integration uses recently-played (and finished currently-playing when available). Coverage depends on Spotify returning episode objects in those responses for your account/client.

---

## Prerequisites

1. Immersion Tracker running (Docker): http://127.0.0.1:8000/api/health  
2. Spotify Developer app: https://developer.spotify.com/dashboard  
3. Redirect URI registered exactly:

   `http://127.0.0.1:8766/callback`

---

## 1. One-time OAuth

On your PC (needs a browser), from the repo root:

```powershell
cd C:\path\to\immersion-tracker
.\.venv\Scripts\activate   # if you use a venv
pip install -r requirements.txt

$env:SPOTIFY_CLIENT_ID = "your_client_id"
$env:SPOTIFY_CLIENT_SECRET = "your_client_secret"
python scripts\spotify_oauth_setup.py
```

Or pass flags:

```powershell
python scripts\spotify_oauth_setup.py --client-id YOUR_ID --client-secret YOUR_SECRET
```

Scopes requested:

- `user-read-recently-played`
- `user-read-playback-state`
- `user-read-currently-playing`

Token JSON is written to **`data/spotify-oauth-token.json`**:

```json
{
  "refresh_token": "...",
  "access_token": "...",
  "expires_at": 1710000000
}
```

The poller refreshes `access_token` / `expires_at` in place. Do not commit this file.

---

## 2. Config

`config/settings.yaml` (see also `config/settings.example.yaml`):

```yaml
spotify:
  enabled: true
  client_id: ""                    # or env SPOTIFY_CLIENT_ID
  client_secret: ""                # or env SPOTIFY_CLIENT_SECRET
  token_file: "/app/data/spotify-oauth-token.json"
  poll_seconds: 300
  show_allowlist: []               # e.g. ["showIdHere", "Nihongo"]
  show_blocklist: []
  podcasts_only: true
  content_type: podcast
  unit: minutes
  activity: listening
  tadoku_default: pending          # auto | pending | never
  market: US
```

| Field | Meaning |
|-------|---------|
| `show_allowlist` | Empty = all podcast shows. Non-empty = only matching **show ids** or **name substrings** (case-insensitive). |
| `show_blocklist` | Always drop matching shows. |
| `podcasts_only` | `true` (default): skip music tracks. `false`: also log tracks as `spotify:track:{id}`. |
| `token_file` | Inside Docker use `/app/data/...` (host `./data` is mounted there). |

Credentials: yaml `client_id` / `client_secret`, or environment variables `SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET`.

---

## 3. Rebuild Docker

After enabling Spotify or changing code that ships in the image:

```powershell
cd C:\path\to\immersion-tracker
.\scripts\docker\rebuild.ps1
```

Confirm:

- App: http://127.0.0.1:8000  
- Logs UI / queue: play a podcast episode on Spotify, wait one poll cycle (~5 min), check source `spotify`.

---

## Deduping & Tadoku

- Unique on `(source, source_ref)` → one log per episode id forever (replays do not create a second row).
- Tadoku mode comes from catalog override → content_type default → `spotify.tadoku_default`.
- Amount is full episode duration in minutes (recently-played has no partial-progress ratio).

---

## Troubleshooting

| Symptom | Check |
|---------|--------|
| No logs | `spotify.enabled: true`, token file exists under `data/`, client id/secret set, episode actually finished in Spotify. |
| Auth errors | Re-run `python scripts/spotify_oauth_setup.py`; confirm redirect URI; refresh token not revoked. |
| Music logged | Set `podcasts_only: true`. |
| Wrong shows | Use `show_allowlist` with show id (from Spotify URI `spotify:show:…`) or a unique name substring. |
| Only some podcasts | Spotify may omit some episode history from recently-played; keep the app online and poll interval modest (e.g. 300s). |

Token path resolution tries, in order: configured path, `data/<filename>`, `/app/data/<filename>`.

---

## Files

| Path | Role |
|------|------|
| `app/ingest/spotify.py` | Token refresh, poll, status |
| `scripts/spotify_oauth_setup.py` | One-time browser OAuth |
| `app/ingest/registry.py` | Schedules `poll_spotify` when enabled |
| `config/settings.example.yaml` | Sample `spotify:` block |
