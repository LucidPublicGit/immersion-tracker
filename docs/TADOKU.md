# Tadoku.app integration

## Saved contest (Manual log default)

Configured in `config/settings.yaml` under `tadoku.contest`:

```yaml
tadoku:
  live_submit: true
  auto_submit_on_approve: true   # Approve = submit to tadoku.app
  language_code: jpn
  contest:
    name: "My Year Contest"
    contest_id: "00000000-0000-0000-0000-000000000001"
    registration_id: ""   # REQUIRED for live submit — see below
```

This matches the contest dropdown on https://tadoku.app/logs/new.

View current settings (no secrets):

```text
GET http://127.0.0.1:8000/api/tadoku/settings
```

---

## Tests never live-submit

The pytest suite **cannot** POST to tadoku.app, even if `.env` has a real
`TADOKU_COOKIE` and `live_submit: true`:

- `tests/conftest.py` clears cookies, sets `IMMERSION_TADOKU_DRY_RUN=1`, and
  forces every `TadokuClient` into dry-run with a temp export dir
- `TadokuClient` hard-blocks live HTTP when `PYTEST_CURRENT_TEST` is set or
  `IMMERSION_TADOKU_DRY_RUN` is truthy (`1` / `true` / `yes` / `on`)

Use `IMMERSION_TADOKU_DRY_RUN=1` in any other script (e.g. smoke) that should
not hit the live API.

### Upstream contract checks (GET-only)

`tests/test_tadoku_upstream.py` hits **public** tadoku.app pages and immersion
API routes this app depends on (contest meta/summary/leaderboard/activity,
manual log page, leaderboard HTML). Failures mean tadoku changed a path or
payload shape — fix `app/tadoku/upstream.py` / config, not by disabling the test.

```powershell
python -m pytest tests/test_tadoku_upstream.py -q
# full suite (includes upstream probes):
python -m pytest -q
```

- Offline / DNS failure → **skip** (not fail)
- Wrong contest id, 404 leaderboard page, missing JSON keys → **fail**
- Auth-gated routes (`configuration-options`, `ongoing-registrations`) run only
  when a session cookie is present (`data/tadoku_session.cookie` or
  `IMMERSION_TADOKU_UPSTREAM_COOKIE`); otherwise they **skip with a warning**

### Runtime monitor (infrequent, while the app is up)

The Docker/app scheduler runs a **minimal** subset (2 GETs only) on an interval:

1. Contest leaderboard HTML (`/contests/{id}/leaderboard/1`)  
2. Contest leaderboard API (`…/leaderboard?page=0&page_size=1`)

Defaults (`config/settings.yaml` → `scheduler`):

```yaml
scheduler:
  tadoku_upstream_check: true
  tadoku_upstream_check_hours: 12   # also runs once shortly after boot
```

- Failures → `logger.error` in container logs (`tadoku upstream monitor FAIL …`)
- Last result → `data/tadoku_upstream_status.json`
- Status API: `GET /api/tadoku/upstream` (also nested under `/api/tadoku/settings` as `upstream_monitor`)
- Force now: `POST /api/tadoku/upstream/check`

This is intentional lighter than full pytest: path/API breakage without hourly traffic.

---

## Two ways logs reach tadoku.app

### A) `tadoku_mode = auto` (no Approve click)

1. Catalog `tadoku_override=auto`, or set `tadoku_mode=auto` on Logs / Queue  
2. Tracker promotes status to **`ready`** (even if the sheet still says `pending`)  
3. After sheet sync (and every ~5 minutes) **`process_ready`** POSTs to tadoku.app  

### B) Approve → submit (`tadoku_mode = pending`)

When `auto_submit_on_approve: true`:

1. You click **Approve (+ submit)** on http://127.0.0.1:8000/queue  
2. Tracker marks the item ready  
3. Immediately **POST**s to tadoku.app  
   `POST https://tadoku.app/api/internal/immersion/logs`  
   with your **contest registration** + activity/amount/description  

**Requirements for live submit:**

| Need | Where |
|------|--------|
| Tadoku username + password | Queue UI **Save login**, or env `TADOKU_USERNAME` / `TADOKU_PASSWORD` |
| Your registration UUID for that contest | `tadoku.contest.registration_id` |

Without credentials (or a legacy cookie), Approve will fail live submit (status
`failed`) and still write a local export under `data/tadoku_export/`.

---

## 1. Tadoku login (username / password)

Tadoku immersion API auth is a **browser session cookie** (`ory_kratos_session` from
Ory Kratos). You no longer need to copy that cookie from DevTools.

### Recommended: Queue UI credentials

1. Open http://127.0.0.1:8000/queue  
2. Enter your **tadoku.app username or email** and **password**  
3. Click **Save login** (password is **encrypted at rest** under `data/`)  
4. Click **Refresh Tadoku login** to verify (optional — sync also logs in on demand)

The app:

- Performs the Tadoku **browser** login flow automatically  
- Stores the resulting session cookie in `data/tadoku_session.cookie`  
- Reuses that cookie until Tadoku returns **401**, then re-logins once  
- **Never** returns the password or session cookie from settings APIs  

| Storage | Contents |
|---------|----------|
| `data/tadoku_credentials.json` | Username + Fernet-encrypted password |
| `data/tadoku_credentials.key` | Local encryption key (gitignored, volume-mounted) |
| `data/tadoku_session.cookie` | Internal `ory_kratos_session` (auto-managed) |

### Env fallbacks (optional)

```env
TADOKU_USERNAME=you@example.com
TADOKU_PASSWORD=your-password
# Legacy only — prefer username/password above:
# TADOKU_COOKIE=ory_kratos_session=...
```

UI-saved credentials take priority over env when both are present.

### Session health

- `GET /api/tadoku/settings` includes `session_status`, `tadoku_username`,
  `tadoku_credentials_configured` (never password / cookie value)
- `GET /api/tadoku/settings?check_session=1` forces a fresh probe
- Live submit **401/403** → mark expired → automatic re-login once on next submit
- Queue UI banner when login or session is missing/expired

```powershell
# Save credentials
curl -X POST http://127.0.0.1:8000/api/tadoku/credentials `
  -H "Content-Type: application/json" `
  -d "{\"username\":\"you@example.com\",\"password\":\"your-password\"}"

# Force a new browser session (does not echo secrets)
curl -X POST http://127.0.0.1:8000/api/tadoku/auth/refresh

# Clear username, password, and session together
curl -X DELETE http://127.0.0.1:8000/api/tadoku/credentials
```

---

## 2. Set `registration_id` (contest selection)

You will **not** see this UUID on the Manual log page.  
The dropdown only shows the **contest name**. The ID is in an API response.

### Easiest: helper script (recommended)

With Tadoku login configured (Queue UI credentials or session cookie):

```powershell
cd C:\path\to\immersion-tracker
.\scripts\docker\tadoku-list-registrations.ps1
```

Example output:

```text
Contest name:     My Year Contest
contest_id:       00000000-0000-0000-0000-000000000001
registration_id:  f32268b5-...   <--- put this in settings.yaml
```

Then:

```yaml
tadoku:
  contest:
    registration_id: "f32268b5-...."
```

```powershell
.\scripts\docker\rebuild.ps1
```

### Browser Network tab (manual)

1. Open https://tadoku.app/logs/new (logged in)  
2. F12 → **Network** → check **Preserve log**  
3. Refresh the page  
4. Filter: `ongoing-registrations`  
5. Click that request → **Response**  
6. Find your contest → copy field **`id`** (that is `registration_id`, not only `contest.id`)

### Two different UUIDs

| Field | What it is | Visible in UI? |
|-------|------------|----------------|
| `contest_id` | The contest itself | In the URL `/contests/{id}/leaderboard/1` (bare `/contests/{id}` 404s) |
| `registration_id` | **Your** signup for that contest | **No** — only in API JSON |

---

## What gets sent

| Our field | Tadoku API |
|-----------|------------|
| listening + minutes | `activity_id: 2`, `duration_seconds: amount*60` |
| reading + pages | `activity_id: 1`, `amount` + `unit_id` (looked up) |
| title + season + episode | `description`: e.g. `KonoSuba S01E02` |
| contest.registration_id | `registration_ids: […]` |
| language | `language_code: jpn` |

Tags: content type + series slug.

---

## Flow

```
Approve → READY → POST tadoku.app/logs → PUSHED (remote id)
                ↘ on error → FAILED + note + local export JSON
```

Still works without live cookie if `live_submit: false` (export-only).

---

## Manual Entry (anime) reminder

| content_type | title | season | episode | amount | unit | series_key | activity |
|--------------|-------|--------|---------|--------|------|------------|----------|
| anime | KonoSuba | 1 | 2 | 24 | minutes | anime:konosuba | listening |
