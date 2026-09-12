# Plex / Tautulli → Immersion Tracker

Auto-log finished watches (default **≥ 90%** or `watched`) into SQLite + Google Sheets.

## Architecture

```
Plex plays media → Tautulli (or Plex webhook) → POST /api/webhooks/tautulli
                                              → Immersion Tracker
                                              → Logs / Logs · Anime / sheet sync
```

**Recommended:** [Tautulli](https://tautulli.com/) — clearer “watched” events than raw Plex.

**Where to look for logs:** `/docs` is only the API reference — it does not list watches.  
Use http://127.0.0.1:8000/queue , http://127.0.0.1:8000/api/logs?source=plex , or the Google Sheet.

---

## Prerequisites

1. Immersion Tracker running (Docker): http://127.0.0.1:8000/api/health  
2. Same machine as Plex **or** tracker reachable on LAN (`http://YOUR_PC_IP:8000`)  
3. `WEBHOOK_SECRET` in project `.env` (default often `changeme`)

---

## 1. Align library names

Edit `config/settings.yaml`:

```yaml
plex:
  watch_threshold: 0.90
  library_map:
    Anime: anime         # Plex library name → content_type
    JDrama: show
    Movies: show
    TV Shows: show
  tadoku_default: pending
```

**Keys** must match your Plex/Tautulli **library names** exactly (case-sensitive).

Tautulli can run in Docker next to the tracker (`docker compose up -d tautulli` → http://127.0.0.1:8181).
From the Tautulli container, reach Plex at `http://host.docker.internal:32400` and the
tracker webhook at `http://immersion-tracker:8000/api/webhooks/tautulli?secret=changeme`.

After edit:

```powershell
cd C:\path\to\immersion-tracker
.\scripts\docker\rebuild.ps1
```

---

## 2. Tautulli notification agent

1. Open Tautulli → **Settings → Notification Agents → Add**  
2. Agent: **Webhook**  
3. Configuration:

| Field | Value |
|-------|--------|
| Webhook URL (Docker Tautulli) | `http://immersion-tracker:8000/api/webhooks/tautulli?secret=changeme` |
| Webhook URL (host) | `http://127.0.0.1:8000/api/webhooks/tautulli?secret=changeme` |
| Method | POST |

**Secret must be in the URL** as `?secret=` (same as `.env` → `WEBHOOK_SECRET`, default `changeme`).  
Tautulli’s webhook agent often has **no header field**. Missing secret → **401** and nothing is logged.

4. **Triggers:** enable **Watched**.

5. **Watched → JSON body** (empty body cannot create a log):

```json
{"action":"watched","rating_key":"{rating_key}","title":"{title}","grandparent_title":"{show_name}","library_name":"{library_name}","media_type":"{media_type}","duration":"{duration}","progress_percent":"{progress_percent}","season_num":"{season_num}","episode_num":"{episode_num}","watched":true}
```

Or auto-fix Tautulli’s DB (URL + body) — already applied on this machine if you used our setup scripts:

```powershell
python scripts\fix_tautulli_webhook.py data\tautulli\tautulli.db changeme
docker restart tautulli
```

6. Save. Finish an episode past Tautulli’s watched threshold (not a short scrub under ~2 minutes if Tautulli ignores it for history — **Watched** notify can still fire near the end).

### Payload

Normalized body also accepted at `POST /api/webhooks/plex?secret=changeme`:

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

---

## 3. Aliases (display name + link to manual)

Plex uses the library title (often English). Catalog **aliases** map that name to your preferred
`series_key` and **display_title** (e.g. JP short name), so Plex and manual logs group together.

| Field | Purpose |
|-------|---------|
| `series_key` | Stable id shared with Manual Entry (e.g. `anime:tensura`) |
| `display_title` | How the log appears in queue / sheet / Tadoku |
| `aliases` | Pipe-separated Plex names: `That Time I Got… \| Tensei the Slime` |
| `tadoku_override` | Optional `auto` / `pending` / `never` for this series |

**UI:** http://127.0.0.1:8000/catalog  
**Sheet:** Catalog tab → `aliases` column  
**API:** `POST /api/catalog/link` or `PATCH /api/catalog/{series_key}?relink_logs=true`

Example:

```powershell
curl -X POST http://127.0.0.1:8000/api/catalog/link `
  -H "Content-Type: application/json" `
  -d "{\"series_key\":\"anime:tensura\",\"display_title\":\"転スラ\",\"content_type\":\"anime\",\"alias\":\"That Time I Got Reincarnated as a Slime\",\"tadoku_override\":\"auto\",\"relink_logs\":true}"
```

`relink_logs` rewrites **existing** logs that match the alias / old auto keys:

- `title` → `display_title`, `series_key` → catalog key
- if `tadoku_override` is set: applies mode/status to **pipeline** logs (`pending` / `ready` / `failed`)
- never reopens **`pushed`** (already submitted) or user **`skipped`** logs (unless override is `never`)

---

## 4. Verify

```powershell
# After watching something to completion:
curl "http://127.0.0.1:8000/api/logs?source=plex"
# Queue UI (not /docs):
# http://127.0.0.1:8000/queue
```

Check **Logs · Anime** (or Show) on your Google Sheet after the next sync.

Plex/anime logs default Tadoku mode **`pending`** → approve on http://127.0.0.1:8000/queue before export.
Set catalog **`tadoku_override=auto`** (and relink) if you want a series to skip the approve step.

---

## 5. Troubleshooting

| Issue | Fix |
|-------|-----|
| Nothing logged | Trigger = Watched? JSON body filled? `?secret=` on URL? |
| 401 Unauthorized | Secret missing/wrong — use `?secret=changeme` or header `X-Webhook-Secret` |
| Looking at `/docs` | That’s Swagger only — use `/api/logs?source=plex` or `/queue` |
| Connection refused from Tautulli on another machine | Use host LAN IP; Windows Firewall allow port 8000 |
| Wrong content_type | Fix `plex.library_map` keys to match library names |
| Docker Tautulli → tracker | URL host must be `immersion-tracker` not `127.0.0.1` |

---

## Manual test (no Plex)

```powershell
curl -X POST "http://127.0.0.1:8000/api/webhooks/plex?secret=changeme" `
  -H "Content-Type: application/json" `
  -d "{\"rating_key\":\"test-rk-1\",\"title\":\"E01\",\"grandparent_title\":\"Test Anime\",\"library_name\":\"Anime\",\"media_type\":\"episode\",\"duration_ms\":1440000,\"progress_percent\":95,\"watched\":true}"
```
