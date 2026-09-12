# AnkiConnect → Immersion Tracker

Auto-log **Anki review time** as **study minutes** via [AnkiConnect](https://foosoft.net/projects/anki-connect/).

```
Anki (desktop) + AnkiConnect add-on
        │  HTTP POST :8765
        ▼
immersion-tracker poll (scheduler or POST /api/anki/sync)
        │  watermark: anki:last_review_id
        ▼
SQLite study log (source=anki) → Sheets / Tadoku rules
```

**Where to look for logs:** http://127.0.0.1:8000/logs ,  
`http://127.0.0.1:8000/api/logs?source=anki` , or the Google Sheet.

---

## Prerequisites

1. **Anki desktop** running on the host (not only AnkiMobile / AnkiWeb).
2. **AnkiConnect** add-on installed (code **2055492159**).
3. Immersion Tracker running (Docker or local): http://127.0.0.1:8000/api/health  

---

## 1. Install AnkiConnect

1. Open Anki → **Tools → Add-ons → Get Add-ons…**
2. Paste code: **`2055492159`**
3. Restart Anki **and open a profile** (deck browser must be visible — the launcher alone is not enough).
4. Confirm the API responds on the host:

```powershell
# From the Windows host (Anki must be open on a profile)
Invoke-RestMethod -Method POST -Uri http://127.0.0.1:8765 `
  -ContentType 'application/json' `
  -Body '{"action":"version","version":6}'
# → 6 (or similar)
```

### Anki 25.09.x / launcher builds — “AnkiConnect broken after update”

Symptoms: immersion-tracker shows `AnkiConnect unreachable` / connection refused; nothing is **LISTENING** on port **8765** even though Anki is “running”.

Common causes:

1. **Profile not loaded** — process exists but you’re still on the profile chooser / empty window.
2. **Addon load crash** — older AnkiConnect version parsers fail if the version string ever looks like `25.09.4 (d52ca669)` (hash suffix → `ValueError` → addon never starts the HTTP server).
3. **Stale `meta.json`** — `max_point_version: 45` (2.1-era) while Anki 25.09 uses point versions like `250904`; other modern add-ons already use `2509xx`.

**Repair (Windows):**

```powershell
cd C:\path\to\immersion-tracker
.\scripts\fix-ankiconnect.ps1
```

That rewrites a safe version parse, bumps `max_point_version` for 25.x, sets CORS for Docker (`host.docker.internal`), restarts Anki, and probes `:8765`.

Then:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/anki/status
# expect connected=true
```

If it still fails: Anki → **Tools → Add-ons** → check for red error text mentioning AnkiConnect, or **View Add-on Errors**.

---

## 2. Allow Docker → AnkiConnect

Immersion Tracker in Docker reaches the host Anki process at  
`http://host.docker.internal:8765` (default `anki.connect_url`).

AnkiConnect binds to `127.0.0.1` by default. On **Docker Desktop (Windows/macOS)**  
`host.docker.internal` usually reaches that listener. If polls fail from the container:

### CORS / origin list (recommended)

AnkiConnect can reject some clients unless origins are allowed. Open  
**Tools → Add-ons → AnkiConnect → Config** and ensure something like:

```json
{
  "apiKey": null,
  "webBindAddress": "127.0.0.1",
  "webBindPort": 8765,
  "webCorsOriginList": [
    "http://localhost",
    "http://127.0.0.1",
    "*"
  ]
}
```

- `"*"` is the simplest for local lab use (any origin).
- For a tighter setup, list only what you need; server-side `httpx` from Docker  
  often works without browser CORS, but keeping `webCorsOriginList` open avoids  
  surprising denials from tools and the first-permission prompt.

Restart Anki after saving config.

### Linux Docker note

If the container cannot reach Anki on the host, either:

- Bind AnkiConnect to `0.0.0.0` (`webBindAddress`) and firewall carefully, or  
- Run the tracker on the host network / use the host gateway IP, or  
- Set `anki.connect_url` to a reachable address.

---

## 3. Enable in settings

Edit `config/settings.yaml`:

```yaml
anki:
  enabled: true
  connect_url: "http://host.docker.internal:8765"  # host Anki from Docker
  # connect_url: "http://127.0.0.1:8765"           # tracker on same host as Anki
  poll_seconds: 300
  deck_allowlist: []          # empty = all decks
  # deck_allowlist: ["Japanese*", "Core 2k/6k"]  # exact or prefix*
  deck_blocklist: []          # applied after allowlist
  min_delta_minutes: 0.5      # ignore tiny review batches
  content_type: study
  unit: minutes
  activity: study
  tadoku_default: never       # study usually not pushed to Tadoku
  title: Anki
  series_key: anki
  timeout_seconds: 10
```

Rebuild / restart so the container picks up config + code:

```powershell
cd C:\path\to\immersion-tracker
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\docker\rebuild.ps1
```

---

## 4. Verify

```powershell
# Status (Anki must be running with AnkiConnect)
Invoke-RestMethod http://127.0.0.1:8000/api/anki/status

# Manual poll (also runs on the scheduler when enabled)
Invoke-RestMethod -Method POST http://127.0.0.1:8000/api/anki/sync
```

**First successful poll bootstraps:** it stores the latest review id and **does not**  
log historical reviews. Only reviews after that baseline create study logs.

Expected flow:

| Step | Result |
|------|--------|
| `enabled: false` | Status says disabled; scheduler skips Anki |
| Anki closed / wrong URL | `ok: false`, connection error |
| First contact | `bootstrapped`, watermark set, **0** logs |
| New reviews ≥ `min_delta_minutes` | One aggregated **study** log (minutes) |

---

## Behaviour details

| Topic | Behaviour |
|-------|-----------|
| Watermark | State key `anki:last_review_id` (Anki review id = epoch ms) |
| Bootstrap | State key `anki:bootstrapped`; history not logged |
| Batching | One log per poll that clears `min_delta_minutes` |
| Amount | Sum of review durations (ms) → minutes |
| Below min delta | Watermark **held** so short sessions accumulate across polls |
| Deck filter | Allowlist: exact name or `prefix*`. Blocklist after |
| Dedup | `source_ref` = `anki:{prev_watermark}:{max_id}` |
| Scheduler | Registry job `anki_poll` every `poll_seconds` (≥ 60s) |

---

## Troubleshooting

| Symptom | Check |
|---------|--------|
| `AnkiConnect unreachable` | Anki open? Add-on installed? `connect_url` correct? |
| Works on host, not Docker | Use `host.docker.internal:8765`; rebuild; CORS config |
| No logs after reviewing | Wait for poll or `POST /api/anki/sync`; sessions under `min_delta_minutes` are held until enough time accumulates |
| Wrong decks | Adjust `deck_allowlist` / `deck_blocklist` |
| Want history logged | Not supported on purpose — bootstrap skips past reviews |

API surface:

- `GET /api/anki/status`
- `POST /api/anki/sync`
- `GET /api/integrations` (lists poll integrations including Anki)
