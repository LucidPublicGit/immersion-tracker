# Plex / Tautulli → Immersion Tracker

Auto-log finished watches (default **≥ 90%** or `watched`) into SQLite (+ optional Sheets).

```
Plex plays media → Tautulli (or Plex webhook) → POST /api/webhooks/tautulli
                                              → Immersion Tracker
                                              → Queue / logs
```

**Recommended:** [Tautulli](https://tautulli.com/) — clearer “watched” events than raw Plex.

**Where to look:** http://127.0.0.1:8000/queue · `/api/logs?source=plex` · not `/docs` alone.

---

## Prerequisites

1. Immersion Tracker running: http://127.0.0.1:8000/api/health  
2. Same machine as Plex **or** tracker reachable on LAN  
3. `WEBHOOK_SECRET` in project `.env` (created by `.\setup.ps1`; also `data/extension-connect.txt`)

---

## Guided setup

```powershell
.\scripts\setup-wizard.ps1 -Plex
# or interactive: .\scripts\setup-wizard.ps1
```

```bash
./scripts/setup-wizard.sh --plex
```

Writes `data/plex-tautulli-connect.txt` with the webhook URL (includes your secret).

---

## 1. Start Tautulli (optional bundled)

Bundled Tautulli is **opt-in** (compose profile `plex`):

```powershell
.\setup.ps1 -WithPlex
# or:
docker compose --profile plex up -d
```

UI: http://127.0.0.1:8181 — first run: link your Plex server.

From the Tautulli container:

- Plex: `http://host.docker.internal:32400`  
- Tracker webhook: `http://immersion-tracker:8000/api/webhooks/tautulli?secret=<WEBHOOK_SECRET>`

You can also use a Tautulli install on the host (not Docker).

---

## 2. Align library names

Edit `config/settings.yaml` (wizard can set via `-PlexLibraries "Anime=anime,TV Shows=show"`):

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

**Keys** must match your Plex **library names** exactly (case-sensitive).

After edit:

```powershell
.\scripts\docker\rebuild.ps1
```

---

## 3. Tautulli notification agent

1. Tautulli → **Settings → Notification Agents → Add**  
2. Agent: **Webhook**  
3. Configuration:

| Field | Value |
|-------|--------|
| Webhook URL (Docker Tautulli → tracker) | `http://immersion-tracker:8000/api/webhooks/tautulli?secret=<from .env>` |
| Webhook URL (host Tautulli) | `http://127.0.0.1:8000/api/webhooks/tautulli?secret=<from .env>` |
| Method | POST |

**Put the secret in the URL** as `?secret=` (same as `.env` → `WEBHOOK_SECRET`).  
Tautulli’s webhook agent often has **no header field**. Missing secret → **401**.

4. **Triggers:** enable **Watched**.

5. **Watched → JSON body** (empty body cannot create a log):

```json
{
  "action": "watched",
  "rating_key": "{rating_key}",
  "title": "{title}",
  "grandparent_title": "{show_name}",
  "library_name": "{library_name}",
  "media_type": "{media_type}",
  "duration_ms": "{stream_duration_ms}",
  "progress_percent": "{progress_percent}",
  "watched": true
}
```

(Exact Tautulli placeholders can vary by version — match their notification docs if a field is blank.)

---

## 4. Test

1. Finish an episode in a mapped library (≥ threshold / watched).  
2. Queue UI or:

```powershell
curl "http://127.0.0.1:8000/api/logs?source=plex"
```

Tadoku: items often land **pending** → Approve on http://127.0.0.1:8000/queue.

---

## Normalized Plex body (direct API)

`POST /api/webhooks/plex` with header `X-Webhook-Secret: <secret>` (or `?secret=`):

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

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| 401 | `?secret=` ≠ `.env` `WEBHOOK_SECRET` |
| No log | Watched trigger off; empty JSON body; library name not in `library_map` |
| Tautulli cannot reach tracker | Use `immersion-tracker:8000` on Docker network, or host.docker.internal |
| Wrong content type | Fix `plex.library_map` keys to exact Plex names |
