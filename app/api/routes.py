from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.api.deps import verify_webhook_secret
from app.api.schemas import (
    BatchIds,
    CatalogCreate,
    CatalogLinkBody,
    CatalogOut,
    CatalogUpdate,
    EnrichBody,
    LogCreate,
    LogOut,
    LogUpdate,
    MetricsOut,
    ProgressFixupBody,
    ProgressItemOut,
    ProgressListOut,
    TadokuCookieIn,
    TadokuCredentialsIn,
    TadokuPullOut,
    TimelineDay,
    TimelineOut,
    YouTubeVideoIdsIn,
)
from app.db.models import CatalogItem, LogEntry, TadokuStatus, utcnow
from app.db.session import get_db
from app.ingest.plex import PlexWatchEvent, from_tautulli_webhook, ingest_plex_watch
from app.ingest.service import (
    DuplicateLogError,
    LogUpdateError,
    create_log,
    delete_log,
    update_log,
)
from app.ingest.youtube import (
    YouTubeWatchEvent,
    find_existing_youtube_log,
    ingest_youtube_watch,
)
from app.media.catalog_resolve import (
    add_alias_to_catalog,
    format_aliases,
    parse_aliases,
    relink_logs_to_catalog,
)
from app.sheets.sync import full_sync
from app.tadoku import queue as tadoku_queue

router = APIRouter()


@router.get("/health")
def health():
    return {"status": "ok", "service": "immersion-tracker"}


def _log_out(entry) -> LogOut:
    from app.media.title_format import tadoku_title

    data = LogOut.model_validate(entry)
    data.tadoku_title = tadoku_title(
        entry.title, season=entry.season, episode=entry.episode
    )
    return data


@router.post("/logs", response_model=LogOut, status_code=201)
def post_log(body: LogCreate, db: Session = Depends(get_db)):
    try:
        entry = create_log(
            db,
            content_type=body.content_type,
            title=body.title,
            source=body.source,
            amount=body.amount,
            unit=body.unit,
            activity=body.activity,
            series_key=body.series_key,
            source_ref=body.source_ref,
            language=body.language,
            notes=body.notes,
            tags=body.tags,
            timestamp=body.timestamp,
            tadoku_mode_override=body.tadoku_mode,
            season=body.season,
            episode=body.episode,
        )
    except DuplicateLogError as e:
        raise HTTPException(status_code=409, detail={"message": "duplicate", "id": e.existing.id})
    return _log_out(entry)


@router.get("/logs", response_model=list[LogOut])
def list_logs(
    db: Session = Depends(get_db),
    status: Optional[str] = Query(None, alias="tadoku_status"),
    content_type: Optional[str] = None,
    source: Optional[str] = None,
    series_key: Optional[str] = None,
    q: Optional[str] = Query(
        None,
        description="Case-insensitive search across title, series_key, notes, tags",
    ),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    query = db.query(LogEntry)
    if status:
        query = query.filter(LogEntry.tadoku_status == status)
    if content_type:
        query = query.filter(LogEntry.content_type == content_type)
    if source:
        query = query.filter(LogEntry.source == source)
    if series_key:
        query = query.filter(LogEntry.series_key == series_key)
    if q and q.strip():
        like = f"%{q.strip()}%"
        query = query.filter(
            or_(
                LogEntry.title.ilike(like),
                LogEntry.series_key.ilike(like),
                LogEntry.notes.ilike(like),
                LogEntry.tags.ilike(like),
            )
        )
    rows = (
        query.order_by(LogEntry.timestamp.desc(), LogEntry.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [_log_out(e) for e in rows]


@router.get("/logs/{log_id}", response_model=LogOut)
def get_log(log_id: int, db: Session = Depends(get_db)):
    entry = db.get(LogEntry, log_id)
    if not entry:
        raise HTTPException(404, "log not found")
    return _log_out(entry)


@router.patch("/logs/{log_id}", response_model=LogOut)
def patch_log(log_id: int, body: LogUpdate, db: Session = Depends(get_db)):
    """
    Edit a log (title, amount, tadoku status/mode, etc.).

    SQLite is source of truth; marks Google Sheets dirty for the next push.
    Changing tadoku_status away from pushed clears remote_id so re-submit works.
    """
    entry = db.get(LogEntry, log_id)
    if not entry:
        raise HTTPException(404, "log not found")
    fields = body.model_dump(exclude_unset=True)
    try:
        entry = update_log(db, entry, fields)
    except LogUpdateError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return _log_out(entry)


@router.delete("/logs/{log_id}")
def remove_log(log_id: int, db: Session = Depends(get_db)):
    entry = db.get(LogEntry, log_id)
    if not entry:
        raise HTTPException(404, "log not found")
    delete_log(db, entry)
    return {"ok": True, "id": log_id}


@router.post("/logs/undo-last")
def undo_last_log(db: Session = Depends(get_db)):
    """Delete the most recently created log (highest id). Hard delete."""
    entry = db.query(LogEntry).order_by(LogEntry.id.desc()).first()
    if not entry:
        raise HTTPException(404, "no logs to undo")
    deleted = {
        "id": entry.id,
        "title": entry.title,
        "content_type": entry.content_type,
        "amount": entry.amount,
        "unit": entry.unit,
        "source": entry.source,
        "tadoku_status": entry.tadoku_status,
    }
    delete_log(db, entry)
    return {"ok": True, "deleted": deleted}


@router.get("/backup")
def backup_database(background_tasks: BackgroundTasks):
    """Download a consistent SQLite snapshot (source of truth)."""
    import sqlite3
    import tempfile

    from app.core.config import get_settings

    settings = get_settings()
    src = settings.sqlite_file_path()
    if src is None:
        raise HTTPException(400, "backup only supported for sqlite database_url")
    if not src.is_file():
        raise HTTPException(404, f"database file not found: {src}")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    tmp = tempfile.NamedTemporaryFile(
        prefix=f"immersion-backup-{stamp}-",
        suffix=".db",
        delete=False,
    )
    tmp_path = Path(tmp.name)
    tmp.close()
    try:
        with sqlite3.connect(str(src)) as conn:
            conn.execute("PRAGMA busy_timeout=5000")
            with sqlite3.connect(str(tmp_path)) as dest:
                conn.backup(dest)
    except sqlite3.Error as e:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise HTTPException(500, f"sqlite backup failed: {e}") from e

    def _cleanup() -> None:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass

    background_tasks.add_task(_cleanup)
    return FileResponse(
        path=str(tmp_path),
        filename=f"immersion-{stamp}.db",
        media_type="application/octet-stream",
        headers={"X-Backup-Source": src.name},
    )


@router.get("/queue", response_model=list[LogOut])
def get_queue(
    db: Session = Depends(get_db),
    status: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
    include_pushed: bool = Query(
        False,
        description="Include already-submitted (pushed) logs (debug only; queue UI never uses this)",
    ),
):
    return [
        _log_out(e)
        for e in tadoku_queue.list_queue(
            db, status=status, limit=limit, include_pushed=include_pushed
        )
    ]


@router.get("/tadoku/recent", response_model=list[LogOut])
def get_recent_tadoku_logs(
    db: Session = Depends(get_db),
    limit: int = Query(30, ge=1, le=100),
):
    """
    Recently submitted (pushed) logs from the local database only.
    Ordered by timestamp desc (immersion / Tadoku log time). Does not query tadoku.app.
    """
    return [_log_out(e) for e in tadoku_queue.list_recent_pushed(db, limit=limit)]


@router.post("/logs/batch/approve")
def approve_logs_batch(body: BatchIds, db: Session = Depends(get_db)):
    """Approve (+ submit) many log ids (e.g. whole series group)."""
    return tadoku_queue.approve_many(db, body.ids)


@router.post("/logs/batch/skip")
def skip_logs_batch(body: BatchIds, db: Session = Depends(get_db)):
    return tadoku_queue.skip_many(db, body.ids)


@router.post("/logs/{log_id}/approve", response_model=LogOut)
def approve_log(log_id: int, db: Session = Depends(get_db)):
    entry = tadoku_queue.approve(db, log_id)
    if not entry:
        raise HTTPException(404, "log not found")
    return _log_out(entry)


@router.post("/logs/{log_id}/skip", response_model=LogOut)
def skip_log(log_id: int, db: Session = Depends(get_db)):
    entry = tadoku_queue.skip(db, log_id)
    if not entry:
        raise HTTPException(404, "log not found")
    return _log_out(entry)


@router.post("/tadoku/process")
def process_tadoku(db: Session = Depends(get_db)):
    return tadoku_queue.process_ready(db)


@router.get("/tadoku/settings")
def tadoku_settings(
    check_session: bool = Query(
        False,
        description="Force a live cookie probe (otherwise cached ~5m when ok)",
    ),
):
    """Safe view of contest defaults + session health (no password/cookie secrets)."""
    from app.core.config import get_settings
    from app.tadoku.session import session_public_dict
    from app.tadoku.upstream import manual_log_url
    from app.workers.scheduler import tadoku_process_schedule, tadoku_upstream_schedule

    t = get_settings().yaml_config.tadoku
    session = session_public_dict(force_check=check_session)
    return {
        "live_submit": t.live_submit,
        "auto_submit_on_approve": t.auto_submit_on_approve,
        "api_base": t.api_base,
        "language_code": t.language_code,
        "contest": t.contest.model_dump() if t.contest else {},
        **session,
        "registration_id_set": bool(t.contest and t.contest.registration_id),
        "manual_log_url": manual_log_url(),
        "auto_process": tadoku_process_schedule(),
        "upstream_monitor": tadoku_upstream_schedule(),
    }


@router.get("/tadoku/upstream")
def tadoku_upstream_status():
    """
    Last minimal tadoku.app path canary result (leaderboard HTML + API).

    Scheduler runs this infrequently (default every 12h). See also POST to force.
    """
    from app.workers.scheduler import tadoku_upstream_schedule

    return tadoku_upstream_schedule()


@router.post("/tadoku/upstream/check")
def tadoku_upstream_check_now():
    """Force a minimal GET-only upstream path check now (does not POST logs)."""
    from app.tadoku.upstream_monitor import run_minimal_probes
    from app.workers.scheduler import tadoku_upstream_schedule

    report = run_minimal_probes()
    return {
        "ok": report.ok,
        "report": report.to_dict(),
        "schedule": tadoku_upstream_schedule(),
    }


@router.post("/tadoku/credentials")
def tadoku_credentials_set(body: TadokuCredentialsIn):
    """
    Save Tadoku username/password (password encrypted at rest).

    Blank password keeps the previously saved password.
    Changing credentials invalidates the stored session cookie.
    Never returns the password.
    """
    from app.tadoku.credentials import (
        TadokuCredentialsError,
        credentials_public_dict,
        load_credentials,
        save_credentials,
    )
    from app.tadoku.session import invalidate_saved_session, session_public_dict

    old_user, old_pass = load_credentials()
    try:
        save_credentials(
            body.username,
            body.password,
            preserve_password_if_blank=True,
        )
    except TadokuCredentialsError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    new_user, new_pass = load_credentials()
    # Invalidate session when account or password actually changes
    if (new_user != old_user) or (body.password and body.password != old_pass):
        invalidate_saved_session()

    return {
        "ok": True,
        **credentials_public_dict(),
        **session_public_dict(force_check=False),
    }


@router.delete("/tadoku/credentials")
def tadoku_credentials_clear():
    """Clear saved username, password, and session cookie together."""
    from app.tadoku.credentials import clear_credentials, credentials_public_dict
    from app.tadoku.session import invalidate_saved_session, session_public_dict

    removed = clear_credentials()
    invalidate_saved_session()
    return {
        "ok": True,
        "removed_credentials": removed,
        **credentials_public_dict(),
        **session_public_dict(force_check=False),
    }


@router.post("/tadoku/auth/refresh")
def tadoku_auth_refresh():
    """
    Force browser login with saved credentials and persist a new session cookie.

    Does not overwrite the previous cookie until login succeeds.
    Returns {authenticated: true} without secrets.
    """
    from app.tadoku.auth import TadokuAuthenticationError
    from app.tadoku.session import refresh_login

    try:
        result = refresh_login()
    except TadokuAuthenticationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(
            status_code=502,
            detail="Tadoku login failed; check network and credentials",
        ) from e

    return {
        "authenticated": bool(result.get("authenticated")),
        "session_status": result.get("session_status"),
        "session_detail": result.get("session_detail"),
        "tadoku_username": result.get("tadoku_username"),
        "tadoku_credentials_configured": result.get("tadoku_credentials_configured"),
    }


@router.post("/tadoku/session")
def tadoku_session_set(body: TadokuCookieIn):
    """
    Legacy: save a browser Cookie header manually.

    Prefer POST /api/tadoku/credentials + POST /api/tadoku/auth/refresh.
    """
    from app.tadoku.session import check_session, save_cookie, session_public_dict

    try:
        path = save_cookie(body.cookie)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    health = check_session(force=True)
    return {
        "ok": health.status == "ok",
        "saved_to": str(path),
        **session_public_dict(force_check=False),
    }


@router.delete("/tadoku/session")
def tadoku_session_clear():
    """Remove runtime cookie file (credentials kept; next sync can re-login)."""
    from app.tadoku.session import check_session, clear_cookie_file, session_public_dict

    removed = clear_cookie_file()
    check_session(force=True)
    return {"ok": True, "removed_file": removed, **session_public_dict(force_check=False)}


@router.get("/contest/momentum")
def contest_momentum(force: bool = Query(False, description="Bypass TTL and re-fetch Tadoku")):
    """
    Contest race board payload: standings, daily growth, velocity & acceleration.

    Locally caches leaderboard + per-user activity under data/contest_cache/.
    """
    from app.tadoku.contest_cache import get_contest_momentum

    try:
        return get_contest_momentum(force=force)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"tadoku fetch failed: {e}") from e


@router.post("/contest/refresh")
def contest_refresh():
    """Force-refresh contest cache from tadoku.app."""
    from app.tadoku.contest_cache import get_contest_momentum

    try:
        snap = get_contest_momentum(force=True)
        return {
            "ok": True,
            "fetched_at": snap.get("fetched_at"),
            "users": len(snap.get("users") or []),
            "cache": snap.get("cache"),
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"tadoku fetch failed: {e}") from e


@router.post("/webhooks/youtube")
def webhook_youtube(
    body: YouTubeWatchEvent,
    db: Session = Depends(get_db),
    _: None = Depends(verify_webhook_secret),
):
    result = ingest_youtube_watch(db, body)
    status = 201 if result.accepted else 200
    return JSONResponse(status_code=status, content=result.model_dump())


@router.post("/youtube/check-ids")
def youtube_check_ids(
    body: YouTubeVideoIdsIn,
    db: Session = Depends(get_db),
):
    """
    Return which of the given video_ids already have a YouTube log (once-ever).
    Used by the extension history-import review list.
    """
    known: dict[str, int] = {}
    unknown: list[str] = []
    seen: set[str] = set()
    for raw in body.video_ids:
        vid = (raw or "").strip()
        if not vid or vid in seen:
            continue
        seen.add(vid)
        existing = find_existing_youtube_log(db, vid)
        if existing:
            known[vid] = existing.id
        else:
            unknown.append(vid)
    return {"known": known, "unknown": unknown, "checked": len(seen)}


@router.get("/youtube/extension-config")
def youtube_extension_config():
    """
    Non-secret YouTube filter defaults for the browser extension.
    Used to auto-populate viewer/channel allowlists so history scan works
    without requiring a youtube.com tab for Detect.
    """
    from app.core.config import get_settings

    yt = get_settings().yaml_config.youtube
    return {
        "viewer_allowlist": list(yt.viewer_allowlist or []),
        "channel_allowlist": list(yt.channel_allowlist or []),
        "channel_blocklist": list(yt.channel_blocklist or []),
        "completion_threshold": float(yt.completion_threshold),
        "min_watched_seconds": float(yt.min_watched_seconds),
        "tadoku_default": yt.tadoku_default,
    }


@router.get("/hoshi/status")
def hoshi_status_route(db: Session = Depends(get_db)):
    """Hoshi poller config + last run + ADB probe (when source=adb)."""
    from app.ingest.hoshi import hoshi_status

    return hoshi_status(db)


@router.post("/hoshi/sync")
def hoshi_sync(
    dry_run: bool = Query(False, description="Compute deltas without writing logs"),
    source: Optional[str] = Query(
        None,
        description="Override hoshi.source for this run: adb | drive",
    ),
    db: Session = Depends(get_db),
):
    """
    Poll Hoshi statistics (ADB device or Google Drive) and log character deltas.
    Same work as the scheduled job.
    """
    from app.ingest.hoshi import poll_hoshi

    result = poll_hoshi(db, dry_run=dry_run, source=source)
    # 200 = ran cleanly (possibly zero deltas); 503 = disabled / device / Drive failure
    status = 200 if result.ok else 503
    return JSONResponse(status_code=status, content=result.to_dict())


@router.post("/hoshi/ingest-stats")
def hoshi_ingest_stats(
    body: dict,
    dry_run: bool = Query(False),
    db: Session = Depends(get_db),
):
    """
    Push pre-fetched Hoshi statistics (host ADB script → API).

    Body::

        {
          "books": [
            {
              "folder_id": "MyBook",
              "title": "My Book",
              "statistics": [ { "dateKey": "2026-07-24", "charactersRead": 1200, ... } ]
            }
          ]
        }
    """
    from app.ingest.hoshi import ingest_stats_payload

    books = body.get("books") if isinstance(body, dict) else None
    if not isinstance(books, list):
        raise HTTPException(400, "body.books must be a list")
    result = ingest_stats_payload(db, books, dry_run=dry_run)
    status = 200 if result.ok else 503
    return JSONResponse(status_code=status, content=result.to_dict())


@router.get("/hoshi/reading")
def hoshi_reading_dashboard(db: Session = Depends(get_db)):
    """Per-book pending character buckets + session fragments."""
    from app.ingest.hoshi_buckets import reading_dashboard

    return reading_dashboard(db)


@router.post("/hoshi/buckets/{bucket_id}/submit")
def hoshi_submit_bucket(bucket_id: int, db: Session = Depends(get_db)):
    """Manually force-create a log from the Hoshi buffer (no Tadoku push)."""
    from app.ingest.hoshi_buckets import submit_bucket, bucket_to_dict
    from app.db.models import HoshiBookBucket

    entry = submit_bucket(db, bucket_id, force=True)
    if entry is None:
        raise HTTPException(400, "nothing pending to submit (or bucket missing)")
    bucket = db.get(HoshiBookBucket, bucket_id)
    return {
        "ok": True,
        "log_id": entry.id,
        "amount": entry.amount,
        "bucket": bucket_to_dict(db, bucket) if bucket else None,
    }


@router.post("/hoshi/buckets/{bucket_id}/log-to-tadoku")
def hoshi_log_bucket_to_tadoku(bucket_id: int, db: Session = Depends(get_db)):
    """
    Manual force log to Tadoku: all chars since last Tadoku push for this book.

    Ignores min character threshold. Creates a log from any buffer, then pushes
    every not-yet-pushed Hoshi log for the book to tadoku.app.
    """
    from app.ingest.hoshi_buckets import log_bucket_to_tadoku
    from app.db.models import HoshiBookBucket

    if db.get(HoshiBookBucket, bucket_id) is None:
        raise HTTPException(404, "bucket not found")
    result = log_bucket_to_tadoku(db, bucket_id)
    if (
        result.get("pushed", 0) == 0
        and result.get("failed", 0) == 0
        and not result.get("created_log_ids")
        and float(result.get("chars_logged") or 0) <= 0
    ):
        # Nothing to send
        return JSONResponse(
            status_code=400,
            content={**result, "reason": result.get("reason") or "nothing to log to Tadoku"},
        )
    status = 200 if result.get("failed", 0) == 0 else 207
    return JSONResponse(status_code=status, content=result)


@router.post("/hoshi/buckets/{bucket_id}/discard")
def hoshi_discard_bucket(bucket_id: int, db: Session = Depends(get_db)):
    """Discard pending session fragments without creating a log."""
    from app.ingest.hoshi_buckets import discard_bucket, bucket_to_dict
    from app.db.models import HoshiBookBucket

    ok = discard_bucket(db, bucket_id)
    if not ok:
        raise HTTPException(404, "bucket not found")
    bucket = db.get(HoshiBookBucket, bucket_id)
    return {"ok": True, "bucket": bucket_to_dict(db, bucket) if bucket else None}


@router.post("/hoshi/submit-all-ready")
def hoshi_submit_all_ready(db: Session = Depends(get_db)):
    """Force log every book with missing Tadoku chars (same as Log to Tadoku)."""
    from app.ingest.hoshi_buckets import log_all_to_tadoku

    return log_all_to_tadoku(db)


@router.post("/hoshi/log-all-to-tadoku")
def hoshi_log_all_to_tadoku(db: Session = Depends(get_db)):
    """Alias: force log all books' missing chars to Tadoku."""
    from app.ingest.hoshi_buckets import log_all_to_tadoku

    return log_all_to_tadoku(db)


@router.patch("/hoshi/settings")
def hoshi_patch_settings(body: dict, db: Session = Depends(get_db)):
    """
    Runtime reading prefs (UI): log_mode, global min_submit_characters, idle minutes.

    Stored in SQLite (overrides settings.yaml until changed again).
    """
    from app.ingest.hoshi_buckets import set_reading_prefs

    try:
        prefs = set_reading_prefs(
            db,
            log_mode=body.get("log_mode"),
            min_submit_characters=body.get("min_submit_characters"),
            auto_submit_idle_minutes=body.get("auto_submit_idle_minutes"),
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True, **prefs}


@router.patch("/hoshi/buckets/{bucket_id}")
def hoshi_patch_bucket(bucket_id: int, body: dict, db: Session = Depends(get_db)):
    """
    Per-book settings. Body:
      - min_submit_characters: int (override)
      - clear_min_submit: true → use global threshold
    """
    from app.ingest.hoshi_buckets import update_bucket_settings, bucket_to_dict

    clear = bool(body.get("clear_min_submit"))
    raw_min = body.get("min_submit_characters")
    min_submit = None if clear or raw_min is None else int(raw_min)
    bucket = update_bucket_settings(
        db,
        bucket_id,
        min_submit_characters=None if clear else min_submit,
        clear_min_submit=clear,
        title=body.get("title"),
    )
    if not bucket:
        raise HTTPException(404, "bucket not found")
    return {"ok": True, "bucket": bucket_to_dict(db, bucket)}


# ----- GameSentenceMiner (GSM) → Tadoku character export -----


@router.get("/gsm/status")
def gsm_status_route(db: Session = Depends(get_db)):
    """
    Detect GSM database path, schema, cursor, and auto-export prefs.

    Never modifies GSM data. Clear messaging when GSM is missing/disabled.
    """
    from app.ingest.gsm import get_prefs, get_status

    data = get_status(db).to_dict()
    data["prefs"] = get_prefs(db)
    return data


@router.get("/gsm/preview")
def gsm_preview_route(
    deduplicate: Optional[bool] = Query(
        None, description="Override saved dedupe pref; omit to use saved setting"
    ),
    strip_punctuation: Optional[bool] = Query(
        None,
        description="Override saved punctuation-strip pref; omit to use saved setting",
    ),
    collapse_repeated_blocks: Optional[bool] = Query(
        None,
        description="Collapse within-line block repeats (mail hook spam); omit = saved",
    ),
    require_japanese: Optional[bool] = Query(
        None,
        description="Skip lines with almost no Japanese; omit = saved",
    ),
    db: Session = Depends(get_db),
):
    """
    GSM-equivalent Tadoku preview: per-game character totals since GSM watermark.

    Read-only on the GSM database.
    """
    from app.ingest.gsm import (
        build_preview,
        get_collapse_repeated_blocks,
        get_deduplicate,
        get_require_japanese,
        get_status,
        get_strip_punctuation,
    )

    dedupe = get_deduplicate(db) if deduplicate is None else bool(deduplicate)
    strip = (
        get_strip_punctuation(db)
        if strip_punctuation is None
        else bool(strip_punctuation)
    )
    collapse = (
        get_collapse_repeated_blocks(db)
        if collapse_repeated_blocks is None
        else bool(collapse_repeated_blocks)
    )
    require_jp = (
        get_require_japanese(db)
        if require_japanese is None
        else bool(require_japanese)
    )
    preview = build_preview(
        deduplicate=dedupe,
        strip_punctuation=strip,
        collapse_repeated_blocks=collapse,
        require_japanese=require_jp,
        db=db,
    )
    st = get_status(db)
    if isinstance(preview.get("status"), dict):
        preview["status"] = st.to_dict()
    return preview


@router.patch("/gsm/settings")
def gsm_patch_settings(body: dict, db: Session = Depends(get_db)):
    """
    Runtime GSM auto-export prefs (UI).

    Body fields (all optional)::

        log_mode: manual | auto
        min_submit_characters: int
        auto_submit_idle_minutes: float
        deduplicate: bool
        strip_punctuation: bool
        collapse_repeated_blocks: bool
        require_japanese: bool
    """
    from app.ingest.gsm import set_prefs

    try:
        prefs = set_prefs(
            db,
            log_mode=body.get("log_mode"),
            min_submit_characters=body.get("min_submit_characters"),
            auto_submit_idle_minutes=body.get("auto_submit_idle_minutes"),
            deduplicate=body.get("deduplicate"),
            strip_punctuation=body.get("strip_punctuation"),
            collapse_repeated_blocks=body.get("collapse_repeated_blocks"),
            require_japanese=body.get("require_japanese"),
            auto_log_at_time_enabled=body.get("auto_log_at_time_enabled"),
            auto_log_at_hour=body.get("auto_log_at_hour"),
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True, **prefs}


@router.post("/gsm/queue")
def gsm_queue_route(body: dict | None = None, db: Session = Depends(get_db)):
    """
    Create immersion LogEntry rows from the current GSM Tadoku preview.

    Body (all optional)::

        {
          "deduplicate": null,
          "strip_punctuation": null,
          "collapse_repeated_blocks": null,
          "require_japanese": null,
          "submit": false,
          "include_history_if_no_cursor": false,
          "only_auto_ready": false,
          "game_keys": null
        }

    Does not delete GSM lines. GSM cursor advances only after the created batch
    is fully pushed/skipped (when gsm.advance_cursor is true).
    """
    from app.ingest.gsm import GsmError, queue_from_preview

    body = body or {}
    dedupe = body.get("deduplicate")
    strip = body.get("strip_punctuation")
    collapse = body.get("collapse_repeated_blocks")
    require_jp = body.get("require_japanese")
    try:
        result = queue_from_preview(
            db,
            deduplicate=None if dedupe is None else bool(dedupe),
            strip_punctuation=None if strip is None else bool(strip),
            collapse_repeated_blocks=None if collapse is None else bool(collapse),
            require_japanese=None if require_jp is None else bool(require_jp),
            submit=bool(body.get("submit", False)),
            include_history_if_no_cursor=bool(
                body.get("include_history_if_no_cursor", False)
            ),
            game_keys=body.get("game_keys"),
            only_auto_ready=bool(body.get("only_auto_ready", False)),
            min_characters=body.get("min_characters"),
        )
    except GsmError as exc:
        raise HTTPException(400, str(exc)) from exc
    status = 200 if result.get("ok") else 400
    return JSONResponse(status_code=status, content=result)


@router.post("/gsm/auto-export")
def gsm_auto_export_route(db: Session = Depends(get_db)):
    """Run the same auto-export job as the scheduler (min chars + idle)."""
    from app.ingest.gsm import process_auto_export

    return process_auto_export(db)


@router.post("/gsm/mark-synced")
def gsm_mark_synced_route(db: Session = Depends(get_db)):
    """
    Set GSM's tadoku_incremental cursor to now without posting to Tadoku.

    Skips all current lines for future Tadoku counts (same idea as GSM first-run
    cursor init). Never deletes game lines.
    """
    from app.ingest.gsm import GsmError, mark_synced_now

    try:
        result = mark_synced_now(db)
    except GsmError as exc:
        raise HTTPException(400, str(exc)) from exc
    return result


@router.post("/gsm/skip-game")
def gsm_skip_game_route(body: dict | None = None, db: Session = Depends(get_db)):
    """
    Zero Ready-to-log for one game (fast-forward / accidental capture).

    Body: ``{"game_key": "..."}``. Immersion-local only — other games unchanged.
    Never deletes GSM lines or moves the global watermark.
    """
    from app.ingest.gsm import GsmError, mark_game_synced

    body = body or {}
    try:
        return mark_game_synced(db, str(body.get("game_key") or ""))
    except GsmError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/gsm/complete-export")
def gsm_complete_export_route(db: Session = Depends(get_db)):
    """
    Manually retry finishing a GSM export batch and syncing the watermark.

    Raises the immersion-local floor (so the panel resets) and best-effort
    writes GSM's tadoku_incremental row when the host file is writable.
    """
    from app.ingest.gsm import finish_pending_export_work

    return finish_pending_export_work(db)


@router.post("/webhooks/plex")
def webhook_plex(
    body: dict,
    db: Session = Depends(get_db),
    _: None = Depends(verify_webhook_secret),
):
    # Accept either normalized PlexWatchEvent or raw tautulli dict
    try:
        event = PlexWatchEvent.model_validate(body)
    except Exception:
        event = from_tautulli_webhook(body)
    result = ingest_plex_watch(db, event)
    status = 201 if result.accepted else 200
    return JSONResponse(status_code=status, content=result.model_dump())


@router.post("/webhooks/tautulli")
def webhook_tautulli(
    body: dict,
    db: Session = Depends(get_db),
    _: None = Depends(verify_webhook_secret),
):
    event = from_tautulli_webhook(body)
    result = ingest_plex_watch(db, event)
    status = 201 if result.accepted else 200
    return JSONResponse(status_code=status, content=result.model_dump())


@router.get("/catalog", response_model=list[CatalogOut])
def list_catalog(db: Session = Depends(get_db)):
    return db.query(CatalogItem).order_by(CatalogItem.series_key).all()


@router.post("/catalog", response_model=CatalogOut, status_code=201)
def create_catalog(body: CatalogCreate, db: Session = Depends(get_db)):
    from app.tadoku.rules import resolve_activity_unit

    existing = (
        db.query(CatalogItem)
        .filter(CatalogItem.series_key == body.series_key)
        .one_or_none()
    )
    if existing:
        raise HTTPException(409, "series_key exists")
    aliases = body.aliases
    if aliases:
        aliases = format_aliases(parse_aliases(aliases))
    unit = body.default_unit
    if not unit:
        _, unit = resolve_activity_unit(body.content_type)
    item = CatalogItem(
        series_key=body.series_key,
        display_title=body.display_title,
        content_type=body.content_type,
        aliases=aliases or None,
        tadoku_override=body.tadoku_override,
        default_unit=unit,
        notes=body.notes,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    try:
        from app.sheets.state import mark_sheets_dirty

        mark_sheets_dirty(db)
    except Exception:  # noqa: BLE001
        pass
    return item


@router.patch("/catalog/{series_key}", response_model=CatalogOut)
def update_catalog(
    series_key: str,
    body: CatalogUpdate,
    db: Session = Depends(get_db),
    relink_logs: bool = Query(
        False,
        description="Also retarget existing logs that match aliases / old auto keys",
    ),
):
    item = (
        db.query(CatalogItem)
        .filter(CatalogItem.series_key == series_key)
        .one_or_none()
    )
    if not item:
        raise HTTPException(404, "not found")
    data = body.model_dump(exclude_unset=True)
    if "aliases" in data and data["aliases"] is not None:
        data["aliases"] = format_aliases(parse_aliases(data["aliases"])) or None
    for k, v in data.items():
        setattr(item, k, v)
    item.updated_at = utcnow()
    db.commit()
    db.refresh(item)
    try:
        from app.sheets.state import mark_sheets_dirty

        mark_sheets_dirty(db)
    except Exception:  # noqa: BLE001
        pass
    if relink_logs:
        relink_logs_to_catalog(db, item)
        db.refresh(item)
    return item


@router.post("/catalog/link")
def link_catalog_alias(body: CatalogLinkBody, db: Session = Depends(get_db)):
    """
    Create or update a catalog row and attach a Plex title as an alias.

    Use this to:
      - Link Plex English name → your manual series_key
      - Set display_title so future (and optionally past) logs show your name
    """
    from app.tadoku.rules import resolve_activity_unit

    item = (
        db.query(CatalogItem)
        .filter(CatalogItem.series_key == body.series_key)
        .one_or_none()
    )
    created = False
    if not item:
        _, unit = resolve_activity_unit(body.content_type)
        item = CatalogItem(
            series_key=body.series_key,
            display_title=body.display_title,
            content_type=body.content_type,
            tadoku_override=body.tadoku_override,
            default_unit=unit,
        )
        db.add(item)
        created = True
    else:
        if body.display_title:
            item.display_title = body.display_title
        if body.content_type:
            item.content_type = body.content_type
        if body.tadoku_override is not None:
            item.tadoku_override = body.tadoku_override or None

    if body.alias:
        add_alias_to_catalog(item, body.alias)
    if body.aliases:
        for a in parse_aliases(body.aliases):
            add_alias_to_catalog(item, a)

    item.updated_at = utcnow()
    db.commit()
    db.refresh(item)
    try:
        from app.sheets.state import mark_sheets_dirty

        mark_sheets_dirty(db)
    except Exception:  # noqa: BLE001
        pass

    relink_result = {"updated": 0}
    if body.relink_logs:
        extra_titles = []
        if body.alias:
            extra_titles.append(body.alias)
        extra_titles.extend(parse_aliases(body.aliases or ""))
        relink_result = relink_logs_to_catalog(db, item, also_titles=extra_titles)
        db.refresh(item)

    return {
        "ok": True,
        "created": created,
        "catalog": CatalogOut.model_validate(item).model_dump(),
        "relink": relink_result,
    }


@router.post("/catalog/{series_key}/relink")
def relink_catalog(series_key: str, db: Session = Depends(get_db)):
    """Retarget existing logs to this catalog display_title + series_key via aliases."""
    item = (
        db.query(CatalogItem)
        .filter(CatalogItem.series_key == series_key)
        .one_or_none()
    )
    if not item:
        raise HTTPException(404, "not found")
    result = relink_logs_to_catalog(db, item)
    return {"ok": True, "series_key": series_key, **result}


@router.post("/sync/sheets")
def sync_sheets(db: Session = Depends(get_db)):
    return full_sync(db)


@router.get("/sheet-template")
def sheet_template():
    """Column headers + enum dropdown values + per-type log tab names."""
    from app.sheets import enums as E

    return {
        "headers": {
            "Logs (All)": E.LOG_HEADERS,
            "Logs · <Type>": E.LOG_HEADERS,
            "Manual Entry": E.MANUAL_HEADERS,
            "Catalog": E.CATALOG_HEADERS,
            "Tadoku Queue": E.QUEUE_HEADERS,
        },
        "dropdowns": {
            "content_type": E.content_types(),
            "activity": E.ACTIVITIES,
            "unit": E.UNITS,
            "tadoku_mode": E.TADOKU_MODES,
            "tadoku_override": ["auto", "pending", "never"],
            "tadoku_status": E.TADOKU_STATUSES,
            "source": E.SOURCES,
            "imported": E.IMPORTED_FLAGS,
        },
        "type_tabs": E.all_type_tab_titles(),
        "note": "Sync applies data-validation dropdowns automatically. Open Logs · Anime etc. for filtered views.",
    }


@router.get("/metrics", response_model=MetricsOut)
def metrics(db: Session = Depends(get_db)):
    total = db.query(func.count(LogEntry.id)).scalar() or 0
    minutes = (
        db.query(func.coalesce(func.sum(LogEntry.amount), 0.0))
        .filter(LogEntry.unit.in_(("minutes", "minutes_high_density")))
        .scalar()
        or 0.0
    )
    score = (
        db.query(func.coalesce(func.sum(LogEntry.tadoku_score_estimate), 0.0)).scalar() or 0.0
    )
    pending = (
        db.query(func.count(LogEntry.id))
        .filter(LogEntry.tadoku_status == TadokuStatus.PENDING.value)
        .scalar()
        or 0
    )
    ready = (
        db.query(func.count(LogEntry.id))
        .filter(LogEntry.tadoku_status == TadokuStatus.READY.value)
        .scalar()
        or 0
    )
    pushed = (
        db.query(func.count(LogEntry.id))
        .filter(LogEntry.tadoku_status == TadokuStatus.PUSHED.value)
        .scalar()
        or 0
    )
    type_rows = (
        db.query(
            LogEntry.content_type,
            func.count(LogEntry.id),
            func.coalesce(func.sum(LogEntry.amount), 0.0),
        )
        .group_by(LogEntry.content_type)
        .all()
    )
    by_ct = {
        ct: {"count": float(cnt), "amount": float(amt)} for ct, cnt, amt in type_rows
    }
    unit_rows = (
        db.query(
            LogEntry.unit,
            func.coalesce(func.sum(LogEntry.amount), 0.0),
        )
        .group_by(LogEntry.unit)
        .all()
    )
    by_unit = {unit: float(amt) for unit, amt in unit_rows if unit}
    activity_rows = (
        db.query(
            LogEntry.activity,
            LogEntry.unit,
            func.coalesce(func.sum(LogEntry.amount), 0.0),
        )
        .group_by(LogEntry.activity, LogEntry.unit)
        .all()
    )
    by_activity: dict[str, dict[str, float]] = {}
    for activity, unit, amt in activity_rows:
        if not activity or not unit:
            continue
        bucket = by_activity.setdefault(activity, {})
        bucket[unit] = float(amt)
    return MetricsOut(
        total_logs=total,
        total_minutes=float(minutes),
        total_hours=round(float(minutes) / 60.0, 2),
        tadoku_score_estimate=float(score),
        tadoku_pending=pending,
        tadoku_ready=ready,
        tadoku_pushed=pushed,
        by_content_type=by_ct,
        by_unit=by_unit,
        by_activity=by_activity,
    )


@router.get("/metrics/timeline", response_model=TimelineOut)
def metrics_timeline(
    db: Session = Depends(get_db),
    year: Optional[int] = Query(
        None,
        ge=2000,
        le=2100,
        description="Calendar year (default: current UTC year)",
    ),
):
    """Daily immersion totals for a calendar year (for home charts)."""
    y = year or datetime.now(timezone.utc).year
    start = datetime(y, 1, 1, tzinfo=timezone.utc)
    end = datetime(y + 1, 1, 1, tzinfo=timezone.utc)

    # Group by calendar date + unit; pivot in Python (small personal log volume).
    day_expr = func.date(LogEntry.timestamp)
    rows = (
        db.query(
            day_expr,
            LogEntry.unit,
            func.coalesce(func.sum(LogEntry.amount), 0.0),
            func.count(LogEntry.id),
            func.coalesce(func.sum(LogEntry.tadoku_score_estimate), 0.0),
        )
        .filter(LogEntry.timestamp >= start, LogEntry.timestamp < end)
        .group_by(day_expr, LogEntry.unit)
        .all()
    )

    by_date: dict[str, TimelineDay] = {}
    for day, unit, amount, count, day_score in rows:
        if day is None:
            continue
        key = str(day)[:10]
        slot = by_date.get(key)
        if slot is None:
            slot = TimelineDay(date=key)
            by_date[key] = slot
        amt = float(amount or 0.0)
        unit_l = (unit or "").strip().lower()
        if unit_l in ("minutes", "minutes_high_density", "minute"):
            slot.hours += amt / 60.0
        elif unit_l in ("characters", "character", "chars"):
            slot.characters += amt
        elif unit_l in ("pages", "two_column_pages", "page"):
            slot.pages += amt
        elif unit_l in ("comic_pages", "comic page", "comic_page"):
            slot.comic_pages += amt
        elif unit_l in ("sentences", "sentence"):
            slot.sentences += amt
        slot.logs += int(count or 0)
        slot.score += float(day_score or 0.0)

    days = sorted(by_date.values(), key=lambda d: d.date)
    for d in days:
        d.hours = round(d.hours, 3)
        d.characters = round(d.characters, 2)
        d.pages = round(d.pages, 2)
        d.comic_pages = round(d.comic_pages, 2)
        d.sentences = round(d.sentences, 2)
        d.score = round(d.score, 4)

    totals = {
        "hours": round(sum(d.hours for d in days), 3),
        "characters": round(sum(d.characters for d in days), 2),
        "pages": round(sum(d.pages for d in days), 2),
        "comic_pages": round(sum(d.comic_pages for d in days), 2),
        "sentences": round(sum(d.sentences for d in days), 2),
        "score": round(sum(d.score for d in days), 4),
        "logs": float(sum(d.logs for d in days)),
    }
    return TimelineOut(year=y, days=days, totals=totals)


# ── Content progress (per-work view + Tadoku pull + metadata cache) ──────────


def _progress_snapshot(db: Session, *, auto_finish: bool = False) -> ProgressListOut:
    """
    One aggregate pass → items + type/status counts.

    auto_finish: True after write paths (pull/enrich/fixup) so unlocked
    active@100% works become finished. GET always uses auto_finish=False.
    """
    from app.media.progress import aggregate_progress, counts_from_progress_rows

    items = aggregate_progress(db, auto_finish=auto_finish)
    content_types, status_counts = counts_from_progress_rows(items)
    return ProgressListOut(
        items=[ProgressItemOut.model_validate(i) for i in items],
        total=len(items),
        content_types=content_types,
        status_counts=status_counts,
    )


@router.get("/progress", response_model=ProgressListOut)
def list_progress(
    db: Session = Depends(get_db),
    content_type: Optional[str] = None,
    q: Optional[str] = None,
    status: Optional[str] = Query(
        None,
        description="Filter: active | unfinished | finished | dropped | ignored (omit for all)",
    ),
):
    """
    Aggregate local logs by series/work for the Progress page.
    Metadata (covers, totals) comes from the local media_metadata cache only.

    Pure read: does not auto-finish works or mutate catalog.
    content_types / status_counts are always library-wide; items may be filtered.
    """
    from app.media.catalog_resolve import normalize_title
    from app.media.progress import (
        _normalize_status,
        aggregate_progress,
        counts_from_progress_rows,
    )

    # Single full pass for global counts, then filter items in memory when needed.
    full = aggregate_progress(db, auto_finish=False)
    content_types, status_counts = counts_from_progress_rows(full)

    items = full
    if content_type:
        ct = content_type.strip().lower()
        items = [i for i in items if (i.get("content_type") or "") == ct]
    if status and status.strip().lower() not in ("", "all"):
        want = _normalize_status(status)
        if status.strip().lower() == "unfinished":
            want = "active"
        items = [
            i for i in items if _normalize_status(i.get("progress_status")) == want
        ]
    if q and q.strip():
        needle = normalize_title(q)
        items = [
            i
            for i in items
            if needle
            in normalize_title(
                f"{i.get('title') or ''} {i.get('series_key') or ''} "
                f"{i.get('content_type') or ''}"
            )
        ]

    return ProgressListOut(
        items=[ProgressItemOut.model_validate(i) for i in items],
        total=len(items),
        content_types=content_types,
        status_counts=status_counts,
    )


@router.post("/progress/pull-tadoku", response_model=TadokuPullOut)
def progress_pull_tadoku(
    db: Session = Depends(get_db),
    user_id: Optional[str] = Query(
        None,
        description="Tadoku user UUID; auto-discovered from local exports when omitted",
    ),
    dry_run: bool = Query(False, description="Count missing logs without writing"),
    enrich: bool = Query(
        True,
        description="After import, auto-fetch missing covers/totals (jiten) and include in response",
    ),
    enrich_limit: int = Query(50, ge=1, le=200),
    q: Optional[str] = Query(
        None,
        description="Only import remote logs matching this title (per-work resync)",
    ),
    series_key: Optional[str] = Query(
        None,
        description="Progress series_key — resolves title filter from catalog/logs",
    ),
):
    """
    Fetch Tadoku logs for the user and import any that are not already in SQLite.

    Optional ``q`` / ``series_key`` scopes the import to one work (Resync from Tadoku).

    Returns a fresh progress snapshot so the UI can update in place. When
    enrich=true (default), also fills missing media metadata before returning.
    """
    from app.tadoku.pull import pull_missing_logs

    result = pull_missing_logs(
        db,
        user_id=user_id,
        dry_run=dry_run,
        title_query=q,
        series_key=series_key,
    )
    enrich_keys = [series_key] if series_key and result.get("ok") else None
    if result.get("ok") and enrich and not dry_run:
        _run_enrich(
            db,
            series_keys=enrich_keys,
            force=False,
            limit=enrich_limit if not enrich_keys else min(enrich_limit, 5),
            only_missing=True,
        )
    if result.get("ok"):
        result["progress"] = _progress_snapshot(db, auto_finish=True)
    return TadokuPullOut.model_validate(result)


def _run_enrich(
    db: Session,
    *,
    series_keys: Optional[list[str]],
    force: bool,
    limit: int,
    only_missing: bool = True,
    retry_none: bool = False,
) -> dict:
    from app.media.metadata_cache import ensure_metadata, metadata_to_dict
    from app.media.progress import aggregate_progress

    items = aggregate_progress(db, auto_finish=False)
    by_key = {i["series_key"]: i for i in items}

    keys = series_keys
    if not keys:
        # Prefer never-looked-up / no cover / no totals first
        ranked = sorted(
            items,
            key=lambda r: (
                0 if not r.get("has_metadata") else 1,
                0 if not r.get("has_cover") else 1,
                0 if r.get("total_units") is None else 1,
                r.get("last_logged") or "",
            ),
        )
        keys = [r["series_key"] for r in ranked]

    done = 0
    skipped = 0
    results: list[dict] = []
    errors: list[str] = []
    hit = 0

    for key in keys:
        if done >= limit:
            skipped += 1
            continue
        info = by_key.get(key)
        if not info:
            skipped += 1
            continue
        ct = (info.get("content_type") or "").strip().lower()
        # Skip youtube / study unless explicitly requested
        if ct in ("youtube", "study") and not series_keys:
            skipped += 1
            continue
        if only_missing and not force and info.get("has_metadata") and info.get("has_cover"):
            skipped += 1
            continue
        use_force = force or (
            retry_none
            and not info.get("has_metadata")
        )
        try:
            row = ensure_metadata(
                db,
                series_key=key,
                title=info.get("title") or key,
                content_type=ct,
                force=use_force,
            )
            results.append(metadata_to_dict(row))
            done += 1
            if row.source and row.source != "none":
                hit += 1
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{key}: {type(exc).__name__}: {exc}")

    return {
        "ok": True,
        "enriched": done,
        "matched": hit,
        "skipped": skipped,
        "errors": errors[:20],
        "items": results,
        "progress": _progress_snapshot(db, auto_finish=True),
    }


@router.post("/progress/enrich")
def progress_enrich(
    body: EnrichBody,
    db: Session = Depends(get_db),
):
    """
    Resolve media metadata for works missing a local cache entry.

    Cascade is type-aware (jiten/Jikan/AniList/VNDB/Open Library/TMDB).
    Cached positives are not re-fetched unless force=true. source=none retries
    after none_retry_days (or immediately with retry_none/force).
    """
    return _run_enrich(
        db,
        series_keys=body.series_keys,
        force=body.force,
        limit=body.limit,
        only_missing=body.only_missing,
        retry_none=body.retry_none,
    )


@router.post("/progress/{series_key:path}/enrich")
def progress_enrich_one(
    series_key: str,
    db: Session = Depends(get_db),
    force: bool = Query(False),
):
    """Enrich a single series_key (force re-lookup when force=true)."""
    from app.media.metadata_cache import ensure_metadata, metadata_to_dict
    from app.media.progress import aggregate_progress

    items = aggregate_progress(db)
    info = next((i for i in items if i["series_key"] == series_key), None)
    title = (info or {}).get("title") or series_key
    ct = (info or {}).get("content_type") or "anime"
    row = ensure_metadata(
        db,
        series_key=series_key,
        title=title,
        content_type=ct,
        force=force,
    )
    return {"ok": True, "item": metadata_to_dict(row)}


@router.post("/progress/fixup")
def progress_fixup(body: ProgressFixupBody, db: Session = Depends(get_db)):
    """
    Bulk Progress fixups: set category, rename, merge/group works, refetch covers.

    Always returns a fresh progress snapshot so the UI updates in place.
    """
    from app.media import progress_fixup as fixup

    action = (body.action or "").strip().lower()
    keys = list(body.series_keys or [])
    try:
        if action == "set_type":
            if not keys:
                raise HTTPException(400, "series_keys required")
            if not body.content_type:
                raise HTTPException(400, "content_type required for set_type")
            result = fixup.set_content_type(
                db,
                keys,
                body.content_type,
                # Always re-lookup cover/totals for the new type (manga≠show providers)
                refetch_meta=body.refetch_meta if body.refetch_meta is not None else True,
            )
        elif action in ("set_status", "status"):
            if not keys:
                raise HTTPException(400, "series_keys required")
            if not body.progress_status:
                raise HTTPException(
                    400,
                    "progress_status required (active|finished|dropped|ignored)",
                )
            result = fixup.set_progress_status(db, keys, body.progress_status)
        elif action == "rename":
            if not keys:
                raise HTTPException(400, "series_keys required")
            if not body.title:
                raise HTTPException(400, "title required for rename")
            result = fixup.rename_works(
                db,
                keys,
                body.title,
                also_parse_episodes=body.parse_episodes,
            )
        elif action == "merge":
            if not keys:
                raise HTTPException(400, "series_keys required")
            if not body.title:
                raise HTTPException(400, "title required for merge")
            result = fixup.merge_works(
                db,
                keys,
                target_series_key=body.target_series_key,
                title=body.title,
                content_type=body.content_type or "anime",
                parse_episodes=body.parse_episodes,
                refetch_meta=body.refetch_meta,
            )
        elif action in ("refetch_cover", "refetch_meta", "cover"):
            if not keys:
                raise HTTPException(400, "series_keys required")
            result = fixup.refetch_covers(
                db,
                keys,
                title_override=body.title,
            )
        elif action in ("recover_notes", "recover", "unmerge_notes"):
            # series_keys optional filter; empty = scan all logs with Tadoku import notes
            result = fixup.recover_tadoku_notes(
                db,
                series_keys=keys or None,
                dry_run=False,
            )
            # After recovery, auto-fetch covers for recovered targets
            if result.get("ok") and body.refetch_meta:
                targets = list((result.get("by_target") or {}).keys())
                if targets:
                    cover = fixup.refetch_covers(db, targets[:20])
                    result["covers"] = cover.get("results")
        elif action in ("normalize_library", "normalize", "heal_library"):
            # Collapse volume/episode fragments, reclassify study tools
            result = fixup.normalize_library(db, dry_run=False)
        elif action in ("set_metadata", "manual_meta", "import_url"):
            if not keys:
                raise HTTPException(400, "series_keys required (one work)")
            from app.media.manual_meta import apply_manual_metadata

            result = apply_manual_metadata(
                db,
                keys[0],
                content_type=body.content_type or "",
                title=body.title,
                import_url=body.import_url,
                cover_url=body.cover_url,
                total_units=body.total_units,
                total_units_label=body.total_units_label,
                total_characters=body.total_characters,
                total_minutes=body.total_minutes,
                external_url=body.external_url,
                season_totals=body.season_totals,
            )
        else:
            raise HTTPException(
                400,
                "action must be set_type | set_status | rename | merge | "
                "refetch_cover | recover_notes | normalize_library | set_metadata",
            )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e

    result["progress"] = _progress_snapshot(db, auto_finish=True)
    return result
