# Steam playtime → Immersion Tracker

Polls the Steam Web API for **lifetime playtime** per owned game, logs **minute deltas** as immersion entries (`source=steam`, default `content_type=game`).

```
Steam GetOwnedGames → poll_steam (watermark per appid) → SQLite logs → sheet sync
```

Default poll interval: **600s** (registry / `steam.poll_seconds`).

---

## Prerequisites

1. Immersion Tracker running (Docker): http://127.0.0.1:8000/api/health  
2. A Steam **Web API key**  
3. Your **SteamID64** (not custom URL name)

---

## 1. API key

1. Sign in at https://steamcommunity.com/dev/apikey  
2. Register a domain (any value is fine for personal use, e.g. `localhost`)  
3. Copy the key  

**Docker (recommended):** put credentials in `config/settings.yaml` (mounted into the container):

```yaml
steam:
  enabled: true
  api_key: "your_key_here"
  steam_id: "76561198XXXXXXXX"
```

**Local / process env** (also supported by `resolve_credentials`):

```env
STEAM_API_KEY=your_key_here
STEAM_ID=76561198XXXXXXXX
```

To use env vars inside Docker, add them under `immersion-tracker.environment` in `docker-compose.yml` (they are not wired by default).
---

## 2. SteamID64

- Profile → edit profile / share profile → URL like  
  `https://steamcommunity.com/profiles/76561198XXXXXXXX`  
- Or use a converter (search “steamid64 finder”) if you only have a custom vanity URL.

Privacy: **Game details** on your profile must be **Public**, or GetOwnedGames returns empty / private.

---

## 3. Configure

Edit `config/settings.yaml`:

```yaml
steam:
  enabled: true
  api_key: "YOUR_KEY"            # or env STEAM_API_KEY (host/local)
  steam_id: "76561198XXXXXXXX"   # or env STEAM_ID
  poll_seconds: 600
  app_allowlist: [1234560]       # strongly recommended — empty = all owned games
  app_blocklist: []
  name_allowlist: []             # optional case-insensitive name substrings
  name_blocklist: ["dota", "counter-strike"]
  min_delta_minutes: 1.0
  content_type: game
  unit: minutes
  activity: reading              # VN-like; override via catalog if needed
  tadoku_default: never
  bootstrap: false               # first sight = baseline only (no huge historical log)
```

**Allowlist tip:** find appids on the store URL  
`https://store.steampowered.com/app/<appid>/…`

| Setting | Meaning |
|---------|---------|
| `bootstrap: false` | First poll stores current `playtime_forever` only; later increases become logs |
| `bootstrap: true` | First sight may log full lifetime minutes (≥ `min_delta_minutes`) |
| `min_delta_minutes` | Hold watermark until cumulative delta reaches this floor, then log once |
| `app_allowlist` | If non-empty, only these appids are tracked |

After edit / env change:

```powershell
cd C:\path\to\immersion-tracker
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\docker\rebuild.ps1
```

---

## 4. Verify

```powershell
# Logs created from Steam
curl "http://127.0.0.1:8000/api/logs?source=steam"
```

Each log:

- `source_ref` ≈ `steam:{appid}:{playtime_forever}`  
- `series_key` ≈ `steam:{appid}`  
- `amount` = minutes played since last watermark  

Watermarks live in sheet sync state keys: `steam:playtime:{appid}`.

---

## 5. Troubleshooting

| Issue | Fix |
|-------|-----|
| Poll message `disabled` | `steam.enabled: true` |
| `missing credentials` | Set `STEAM_API_KEY` + `STEAM_ID` (or yaml `api_key` / `steam_id`) |
| HTTP / empty games | Profile game details public? Key valid? SteamID64 correct? |
| Huge first log | Keep `bootstrap: false` |
| Noisy English titles | Use `app_allowlist` and/or `name_blocklist` |
| Small sessions ignored | Lower `min_delta_minutes` (watermark is held until the cumulative delta clears the floor) |

Steam only exposes **lifetime totals** (and optional 2-week); the tracker infers session size from the delta between polls. Gaps longer than one session still produce one log for the full gap.
