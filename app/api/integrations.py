"""
HTTP surface for poll-based and webhook integrations (Steam, Anki, Spotify, mpv, asbplayer).

Kept separate from core log/tadoku routes so each integration stays loosely coupled.
Ingest logic lives under app/ingest/<name>.py — this module only wires HTTP.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, Response
from sqlalchemy.orm import Session

from app.api.deps import verify_webhook_secret
from app.core.config import get_settings
from app.db.session import get_db
from app.ingest.registry import list_poll_status, run_poll
from app.sheets.state import mark_sheets_dirty

router = APIRouter(tags=["integrations"])


@router.get("/integrations")
def integrations_overview():
    """List registered poll integrations and enabled flags."""
    cfg = get_settings().yaml_config
    return {
        "poll": list_poll_status(cfg),
        "webhooks": [
            {"name": "youtube", "path": "/api/webhooks/youtube"},
            {"name": "plex", "path": "/api/webhooks/plex"},
            {"name": "tautulli", "path": "/api/webhooks/tautulli"},
            {"name": "mpv", "path": "/api/webhooks/mpv"},
            {"name": "asbplayer", "path": "/api/webhooks/asbplayer"},
        ],
    }


def _poll_or_404(name: str, db: Session) -> dict[str, Any]:
    try:
        result = run_poll(db, name)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if result.logs_created:
        mark_sheets_dirty(db)
    return result.to_dict()


# ── Steam ───────────────────────────────────────────────────────────────────


@router.get("/steam/status")
def steam_status_route(db: Session = Depends(get_db)):
    from app.ingest.steam import steam_status

    return steam_status(db)


@router.post("/steam/sync")
def steam_sync(
    db: Session = Depends(get_db),
    dry_run: bool = Query(False, description="Reserved; poll always writes watermarks"),
):
    _ = dry_run
    return _poll_or_404("steam", db)


# ── Anki ────────────────────────────────────────────────────────────────────


@router.get("/anki/status")
def anki_status_route(db: Session = Depends(get_db)):
    from app.ingest.anki import anki_status

    return anki_status(db)


@router.post("/anki/sync")
def anki_sync(db: Session = Depends(get_db)):
    return _poll_or_404("anki", db)


# ── Spotify ─────────────────────────────────────────────────────────────────


@router.get("/spotify/status")
def spotify_status_route(db: Session = Depends(get_db)):
    from app.ingest.spotify import spotify_status

    return spotify_status(db)


@router.post("/spotify/sync")
def spotify_sync(db: Session = Depends(get_db)):
    return _poll_or_404("spotify", db)


# ── Audiobookshelf ───────────────────────────────────────────────────────────


@router.get("/abs/status")
def abs_status_route(db: Session = Depends(get_db)):
    from app.ingest.audiobookshelf import get_status

    return get_status(db)


@router.get("/abs/preview")
def abs_preview_route(
    db: Session = Depends(get_db),
    refresh: bool = Query(True, description="Poll ABS sessions before preview"),
):
    from app.ingest.audiobookshelf import build_preview

    return build_preview(db, refresh=refresh)


@router.patch("/abs/settings")
def abs_patch_settings(body: dict, db: Session = Depends(get_db)):
    from app.ingest.audiobookshelf import AbsError, set_prefs

    try:
        return set_prefs(
            db,
            log_mode=body.get("log_mode"),
            min_submit_minutes=body.get("min_submit_minutes"),
            auto_submit_idle_minutes=body.get("auto_submit_idle_minutes"),
            auto_log_at_time_enabled=body.get("auto_log_at_time_enabled"),
            auto_log_at_hour=body.get("auto_log_at_hour"),
        )
    except AbsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/abs/sync")
def abs_sync(db: Session = Depends(get_db)):
    """Poll listening sessions into pending minute buckets (no log yet)."""
    from app.ingest.audiobookshelf import poll_sessions

    return poll_sessions(db)


@router.post("/abs/submit")
def abs_submit(body: dict | None = None, db: Session = Depends(get_db)):
    """
    Create immersion logs from pending ABS minutes.

    Body (optional):
      keys: [bucket keys] — subset; omit = all pending
      only_min: bool — require min_submit_minutes
    """
    from app.ingest.audiobookshelf import submit_pending
    from app.sheets.state import mark_sheets_dirty

    body = body or {}
    keys = body.get("keys")
    if keys is not None and not isinstance(keys, list):
        raise HTTPException(status_code=400, detail="keys must be a list")
    result = submit_pending(
        db,
        keys=keys,
        only_min=bool(body.get("only_min", False)),
        only_auto_ready=bool(body.get("only_auto_ready", False)),
        min_minutes=body.get("min_minutes"),
    )
    if result.get("created"):
        mark_sheets_dirty(db)
    return result


@router.post("/abs/auto-export")
def abs_auto_export_route(db: Session = Depends(get_db)):
    from app.ingest.audiobookshelf import process_auto_export
    from app.sheets.state import mark_sheets_dirty

    result = process_auto_export(db)
    if result.get("created"):
        mark_sheets_dirty(db)
    return result


@router.post("/abs/daily-export")
def abs_daily_export_route(
    db: Session = Depends(get_db),
    force: bool = Query(False, description="Ignore hour/enabled gates"),
):
    from app.ingest.audiobookshelf import process_daily_time_export
    from app.sheets.state import mark_sheets_dirty

    result = process_daily_time_export(db, force=force)
    if result.get("created"):
        mark_sheets_dirty(db)
    return result


@router.get("/abs/cover/{item_id}")
def abs_cover_route(
    item_id: str,
    w: int = Query(48, ge=24, le=96, description="Thumbnail edge px"),
):
    """Proxy small ABS/yaabsa cover; 404 if missing or too large."""
    from app.ingest.audiobookshelf import fetch_cover_bytes

    got = fetch_cover_bytes(item_id, width=w)
    if not got:
        raise HTTPException(status_code=404, detail="cover unavailable")
    data, content_type = got
    return Response(
        content=data,
        media_type=content_type,
        headers={"Cache-Control": "public, max-age=3600"},
    )


# ── mpv ─────────────────────────────────────────────────────────────────────


@router.get("/mpv/status")
def mpv_status_route(db: Session = Depends(get_db)):
    from app.ingest.mpv import mpv_status

    return mpv_status(db)


@router.post("/mpv/sync")
def mpv_sync(db: Session = Depends(get_db)):
    return _poll_or_404("mpv", db)


@router.post("/webhooks/mpv")
def webhook_mpv(
    body: dict,
    db: Session = Depends(get_db),
    _: None = Depends(verify_webhook_secret),
):
    from app.ingest.mpv import ingest_mpv_event

    result = ingest_mpv_event(db, body)
    data = result.to_dict() if hasattr(result, "to_dict") else (
        result.model_dump() if hasattr(result, "model_dump") else result
    )
    accepted = bool(data.get("accepted")) if isinstance(data, dict) else False
    if accepted:
        mark_sheets_dirty(db)
    status = 201 if accepted else 200
    return JSONResponse(status_code=status, content=data)


# ── asbplayer ───────────────────────────────────────────────────────────────


@router.get("/asbplayer/status")
def asbplayer_status_route():
    from app.core.config import get_settings

    cfg = get_settings().yaml_config.asbplayer
    return {
        "enabled": cfg.enabled,
        "completion_threshold": cfg.completion_threshold,
        "min_watched_seconds": cfg.min_watched_seconds,
        "content_type": cfg.content_type,
        "tadoku_default": cfg.tadoku_default,
        "webhook": "/api/webhooks/asbplayer",
    }


@router.post("/webhooks/asbplayer")
def webhook_asbplayer(
    body: dict,
    db: Session = Depends(get_db),
    _: None = Depends(verify_webhook_secret),
):
    from app.ingest.asbplayer import AsbplayerWatchEvent, ingest_asbplayer_watch

    try:
        event = AsbplayerWatchEvent.model_validate(body)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    result = ingest_asbplayer_watch(db, event)
    data = (
        result.model_dump()
        if hasattr(result, "model_dump")
        else result.to_dict()
        if hasattr(result, "to_dict")
        else result
    )
    accepted = bool(getattr(result, "accepted", False))
    if accepted:
        mark_sheets_dirty(db)
    status = 201 if accepted else 200
    return JSONResponse(status_code=status, content=data)
