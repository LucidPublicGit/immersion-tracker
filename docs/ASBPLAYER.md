# asbplayer → Immersion Tracker

Log finished local video watches from [asbplayer](https://github.com/killergerbah/asbplayer) (browser media player + subs for language learners) into Immersion Tracker.

asbplayer has **no stable server-side stats API**. Use the same webhook pattern as YouTube: POST a finished-watch JSON payload when a file ends (or when you decide it counts).

## Architecture

```
asbplayer (browser) → userscript / curl → POST /api/webhooks/asbplayer
                                       → Immersion Tracker
                                       → Logs (source=asbplayer)
```

**Where to look for logs:** http://127.0.0.1:8000/queue ,  
http://127.0.0.1:8000/api/logs?source=asbplayer , or the Google Sheet.

---

## Config

`config/settings.yaml`:

```yaml
asbplayer:
  enabled: true              # informational / tadoku-related; webhook always ingests
  completion_threshold: 0.90 # must reach this watch ratio
  min_watched_seconds: 60    # and this much progress (seconds)
  content_type: anime
  unit: minutes
  activity: listening
  tadoku_default: pending    # auto | pending | never
```

| Setting | Default | Meaning |
|---------|---------|---------|
| `completion_threshold` | `0.90` | Reject if `ratio` (or watched/duration) is lower |
| `min_watched_seconds` | `60` | Reject short / end-seek clips under this progress |
| `content_type` | `anime` | Default type; override per event with `content_type` |
| `tadoku_default` | `pending` | Source-level Tadoku mode when catalog/type defaults are empty |
| `enabled` | `true` | Does **not** block ingest; keep for docs / future tadoku gates |

Each media file is logged **once ever** (`source_ref = asbplayer:{media_id}`). Rewatches are duplicates.

**Amount** = full `duration_seconds / 60` minutes (original runtime, Tadoku-friendly for speed-watching).

**series_key** = `asb:{slug(series_title or title)}` (catalog-editable).

---

## Webhook payload

`POST /api/webhooks/asbplayer`  
Auth: same as other webhooks (`?secret=` or header; see `WEBHOOK_SECRET`).

### JSON body

| Field | Required | Notes |
|-------|----------|--------|
| `media_id` | one of media_id / path | Stable id for dedupe (file basename, hash, etc.) |
| `path` | one of media_id / path | Full path; used as id if `media_id` omitted |
| `title` | yes | Display title (episode / file name) |
| `duration_seconds` | for success | Media length; amount = duration/60 |
| `watched_seconds` | recommended | Progress toward thresholds |
| `ratio` | optional | 0–1; else `watched_seconds / duration_seconds` |
| `series_title` | optional | Show name → `series_key` slug |
| `url` | optional | Stored in notes |
| `finished_at` | optional | ISO-8601 timestamp |
| `content_type` | optional | Override yaml default (e.g. `show`) |

### Success response

```json
{
  "accepted": true,
  "reason": "logged",
  "log_id": 42,
  "log": { "title": "...", "amount": 24.0, "unit": "minutes", ... }
}
```

### Rejected (still HTTP 200 typically)

| reason | Cause |
|--------|--------|
| `below_threshold:0.500<0.9` | Ratio under config threshold |
| `below_min_watched:40.0<60` | Not enough watched seconds |
| `duplicate` | Same `media_id` already logged |
| `missing_duration` | No positive `duration_seconds` |

---

## curl example

```powershell
# Health
curl http://127.0.0.1:8000/api/health

# Log a finished watch (secret from .env WEBHOOK_SECRET; default often changeme)
curl -X POST "http://127.0.0.1:8000/api/webhooks/asbplayer?secret=changeme" `
  -H "Content-Type: application/json" `
  -d '{
    "media_id": "frieren-s01e01.mkv",
    "title": "Frieren S01E01",
    "series_title": "Frieren",
    "duration_seconds": 1440,
    "watched_seconds": 1400,
    "ratio": 0.97,
    "finished_at": "2026-07-15T21:00:00+00:00"
  }'
```

List logs:

```powershell
curl "http://127.0.0.1:8000/api/logs?source=asbplayer"
```

---

## Companion userscript

A minimal Tampermonkey / Violentmonkey script lives at:

[`scripts/asbplayer/immersion-tracker.user.js`](../scripts/asbplayer/immersion-tracker.user.js)

1. Install [Violentmonkey](https://violentmonkey.github.io/) or Tampermonkey.
2. Create a new script → paste the file contents (or open the file and install).
3. Edit `SERVER` and `SECRET` at the top of the script.
4. Open asbplayer (or any page with a long HTML5 `<video>`) and watch to the end (≥ threshold).

The script listens for `ended` / high `timeupdate` progress on `<video>` elements and POSTs once per `src` (session dedupe). It is intentionally small; refine selectors if your asbplayer build uses a different player shell.

**asbplayer extension note:** if you run asbplayer as a browser extension on local files, grant the userscript access to the relevant host/file URLs, or call the webhook from a custom bookmarklet using the same JSON shape as the curl example.

### Bookmarklet (one-shot current video)

```javascript
javascript:(async()=>{
  const v=document.querySelector('video');
  if(!v||!v.duration){alert('No video');return;}
  const src=v.currentSrc||v.src||location.href;
  const body={
    media_id:src.split('/').pop()||src,
    path:src,
    title:document.title||src,
    duration_seconds:v.duration,
    watched_seconds:v.currentTime,
    ratio:v.duration?v.currentTime/v.duration:0
  };
  const r=await fetch('http://127.0.0.1:8000/api/webhooks/asbplayer?secret=changeme',{
    method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)
  });
  alert(await r.text());
})();
```

---

## Dedupe & catalog

- **source:** `asbplayer`
- **source_ref:** `asbplayer:{media_id}` (or path when media_id omitted)
- **series_key:** `asb:frieren`-style slug from `series_title` or `title`
- Rename / merge series in Catalog UI like other sources

---

## Related

- YouTube (same threshold + webhook pattern): [YOUTUBE_EXTENSION.md](YOUTUBE_EXTENSION.md)
- Plex/Tautulli (watched webhook): [PLEX.md](PLEX.md)
