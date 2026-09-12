# mpv → Immersion Tracker

Auto-log finished local video watches (default **≥ 90%** progress **and** ≥ **60s** watched) from [mpv](https://mpv.io/) into SQLite → Tadoku queue / Google Sheets.

## Architecture

```
mpv plays file
  ├─ scripts/mpv/immersion-tracker.lua
  │    ├─ append JSONL (~~/immersion-tracker.jsonl)
  │    └─ optional POST /api/webhooks/mpv
  │
  └─ Immersion Tracker poll_mpv (scheduler, when mpv.enabled)
       reads history file → create_log(source=mpv)
```

**Where to look for logs:** http://127.0.0.1:8000/queue ,  
http://127.0.0.1:8000/api/logs?source=mpv , or the Google Sheet.

---

## Prerequisites

1. Immersion Tracker running: http://127.0.0.1:8000/api/health  
2. mpv with scripts enabled  
3. Optional: `WEBHOOK_SECRET` / `IMMERSION_WEBHOOK_SECRET` if using live HTTP POSTs

---

## Config (`config/settings.yaml`)

```yaml
mpv:
  enabled: true
  history_path: ""          # empty → try defaults / env (see below)
  poll_seconds: 120
  completion_threshold: 0.90
  min_watched_seconds: 60
  content_type: anime       # default; path markers can force "show"
  unit: minutes
  activity: listening
  tadoku_default: pending
  show_path_markers:
    - jdrama
    - drama
    - live-action
    - shows
```

### History path resolution

When `history_path` is empty, the poller tries (first existing file wins):

1. env `MPV_HISTORY_PATH`
2. `/mpv/watch_history.jsonl`
3. `/mpv/immersion-tracker.jsonl`

Mount a host directory into the container at `/mpv` (or set an absolute path that exists inside the container).

Example Compose volume idea:

```yaml
volumes:
  - D:/mpv-history:/mpv:ro
```

And point the lua script’s `history_path` at `D:/mpv-history/immersion-tracker.jsonl` on the host.

---

## A) File poll (recommended offline path)

### Supported history formats (auto-detected)

**1. JSONL (preferred — written by our lua script)**  
One JSON object per line:

```json
{"path":"D:/Anime/Show/S01E02.mkv","title":"Show S01E02","duration_seconds":1420,"watched_seconds":1400,"ratio":0.98,"finished_at":"2026-07-30T12:00:00+00:00","event":"end-file"}
```

**2. JSON array** of similar objects.

**3. mpv watch_history–style lists** (`path` + `duration`/`position`/`time`, etc.)  
Best-effort. Entries with **only** path + timestamp and **no duration** are skipped (cannot prove completion).

### Rules

| Rule | Behavior |
|------|----------|
| Completion | `ratio ≥ completion_threshold` **and** `watched ≥ min_watched_seconds` |
| Amount | **Full** `duration_seconds / 60` minutes (same as YouTube completed logs) |
| content_type | Default `anime`; if path contains any `show_path_markers` → `show` |
| series_key | Parent folder / title stem (catalog aliases via `resolve_series`) |
| Dedupe | `source_ref = mpv:{sha1(path\|finished_at)}` (unique with `source`) |

Enable poll + rebuild:

```powershell
# set mpv.enabled: true in config/settings.yaml, then:
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\docker\rebuild.ps1
```

---

## B) Webhook ingest

Payload = one JSONL object (same fields). Server entrypoint:

```text
POST /api/webhooks/mpv
Content-Type: application/json
X-Webhook-Secret: <WEBHOOK_SECRET>
```

(Routes are wired separately; the lua script defaults to this URL.)

Handler logic lives in `app.ingest.mpv.ingest_mpv_event`.

---

## C) Lua script

Path: [`scripts/mpv/immersion-tracker.lua`](../scripts/mpv/immersion-tracker.lua)

### Install

Copy or symlink into mpv’s scripts folder:

| OS | Scripts directory |
|----|-------------------|
| Windows | `%APPDATA%\mpv\scripts\immersion-tracker.lua` |
| Linux / macOS | `~/.config/mpv/scripts/immersion-tracker.lua` |

### Behavior

On `end-file`:

- Tracks peak `time-pos` / `duration`
- Logs when reason is **eof** (high ratio) **or** quit/stop with `ratio ≥ completion` and `watched ≥ min_watched`
- Appends JSONL to history file
- Optionally POSTs via `curl` to Immersion Tracker

### Options

`script-opts/immersion-tracker.conf` (next to `mpv.conf`) or env:

| Opt / env | Default | Meaning |
|-----------|---------|---------|
| `history_path` / `MPV_HISTORY_PATH` | `~~/immersion-tracker.jsonl` | JSONL path (`~~` = mpv config dir) |
| `tracker_url` / `IMMERSION_TRACKER_URL` | `http://127.0.0.1:8000/api/webhooks/mpv` | Webhook URL |
| `webhook_secret` / `IMMERSION_WEBHOOK_SECRET` | _(empty)_ | `X-Webhook-Secret` header |
| `completion` | `0.90` | Quit/stop ratio floor |
| `min_watched` | `60` | Minimum watched seconds |
| `enable_http` | `yes` | POST webhook |
| `enable_file` | `yes` | Append JSONL |

Example `script-opts/immersion-tracker.conf`:

```ini
history_path=D:/mpv-history/immersion-tracker.jsonl
tracker_url=http://127.0.0.1:8000/api/webhooks/mpv
webhook_secret=changeme
completion=0.90
min_watched=60
enable_http=yes
enable_file=yes
```

`curl` must be on `PATH` for HTTP mode (Windows 10+ usually has it).

---

## Manual checks

```powershell
# After enabling mpv + mounting history:
# 1) Watch something in mpv to eof
# 2) Confirm JSONL grew
Get-Content $env:APPDATA\mpv\immersion-tracker.jsonl -Tail 3

# 3) Poll / logs
Invoke-RestMethod http://127.0.0.1:8000/api/logs?source=mpv
```

Or open http://127.0.0.1:8000/queue and filter / scan for `source=mpv`.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Poll says “history file not found” | Set `mpv.history_path` or `MPV_HISTORY_PATH`; mount host dir at `/mpv` in Docker |
| Nothing logged after quit early | Need ≥ threshold ratio **and** ≥ min watched seconds |
| Duplicates never appear | By design — same path + finished_at hashes to one `source_ref` |
| HTTP post fails in lua | Install/fix `curl`; check URL + secret; file JSONL still works offline |
| Wrong anime vs show | Adjust `show_path_markers` or folder names |
| Series name wrong | Fix Catalog alias / display title; parent folder is the series heuristic |

---

## Related

- Config model: `app.core.config.MpvConfig`
- Ingest: `app.ingest.mpv`
- Registry poll: `app.ingest.mpv:poll_mpv` (scheduler when `mpv.enabled`)
- Plex (similar completion threshold): [PLEX.md](PLEX.md)
- YouTube (full-duration amount on complete): [YOUTUBE_EXTENSION.md](YOUTUBE_EXTENSION.md)
