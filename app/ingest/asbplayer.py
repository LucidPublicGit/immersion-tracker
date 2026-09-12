"""
asbplayer / local subtitled media → immersion logs via webhook.

asbplayer has no stable server-side stats export. A companion userscript
(or curl) POSTs an AsbplayerWatchEvent when a video is finished.

Webhook always accepts payloads; ``AsbplayerConfig.enabled`` is informational
/ tadoku-related only — ingest is not gated by it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import LogEntry
from app.ingest.service import DuplicateLogError, create_log
from app.media.title_format import slugify_series


class AsbplayerWatchEvent(BaseModel):
    """
    Finished-watch payload from asbplayer companion / manual POST.

    Provide ``media_id`` and/or ``path`` (file path or other stable id).
    At least one is required and becomes the once-ever dedupe key.
    """

    media_id: Optional[str] = None
    path: Optional[str] = None
    title: str = Field(..., min_length=1)
    duration_seconds: Optional[float] = Field(default=None, gt=0)
    watched_seconds: Optional[float] = Field(default=None, ge=0)
    ratio: Optional[float] = None
    series_title: Optional[str] = None
    url: Optional[str] = None
    finished_at: Optional[datetime] = None
    # Optional per-event override of yaml content_type (default anime)
    content_type: Optional[str] = None

    @model_validator(mode="after")
    def require_media_id_or_path(self) -> AsbplayerWatchEvent:
        if not (self.media_id or "").strip() and not (self.path or "").strip():
            raise ValueError("media_id or path is required")
        return self

    def resolved_media_id(self) -> str:
        """Stable string id for dedupe: prefer media_id, else path."""
        mid = (self.media_id or "").strip()
        if mid:
            return mid
        return (self.path or "").strip()

    def computed_ratio(self) -> float:
        if self.ratio is not None:
            return max(0.0, min(1.0, float(self.ratio)))
        dur = float(self.duration_seconds or 0)
        if dur > 0:
            return max(0.0, min(1.0, float(self.watched_seconds or 0) / dur))
        return 0.0


class AsbplayerIngestResult(BaseModel):
    accepted: bool
    reason: str
    log_id: Optional[int] = None
    log: Optional[dict] = None


def find_existing_asbplayer_log(db: Session, media_id: str) -> Optional[LogEntry]:
    """Once-ever uniqueness by source_ref = asbplayer:{media_id}."""
    mid = (media_id or "").strip()
    if not mid:
        return None
    source_ref = f"asbplayer:{mid}"
    return (
        db.query(LogEntry)
        .filter(LogEntry.source == "asbplayer", LogEntry.source_ref == source_ref)
        .one_or_none()
    )


def ingest_asbplayer_watch(
    db: Session, event: AsbplayerWatchEvent
) -> AsbplayerIngestResult:
    """
    Ingest a finished asbplayer watch.

    Always processes when called (``enabled`` does not reject). Applies
    completion_threshold + min_watched_seconds from AsbplayerConfig.
    """
    cfg = get_settings().yaml_config.asbplayer
    media_id = event.resolved_media_id()
    if not media_id:
        return AsbplayerIngestResult(accepted=False, reason="missing_media_id")

    duration = float(event.duration_seconds or 0)
    if duration <= 0:
        return AsbplayerIngestResult(accepted=False, reason="missing_duration")

    ratio = event.computed_ratio()
    if ratio < cfg.completion_threshold:
        return AsbplayerIngestResult(
            accepted=False,
            reason=f"below_threshold:{ratio:.3f}<{cfg.completion_threshold}",
        )

    min_watched = float(cfg.min_watched_seconds or 0)
    effective_watched = max(
        float(event.watched_seconds or 0),
        duration * ratio,
    )
    if min_watched > 0 and effective_watched < min_watched:
        return AsbplayerIngestResult(
            accepted=False,
            reason=f"below_min_watched:{effective_watched:.1f}<{min_watched:.0f}",
        )

    existing = find_existing_asbplayer_log(db, media_id)
    if existing:
        return AsbplayerIngestResult(
            accepted=False,
            reason="duplicate",
            log_id=existing.id,
            log=_log_dict(existing),
        )

    # Original media duration in minutes (Tadoku-friendly for speed-watching)
    amount_minutes = round(duration / 60.0, 3)
    series_name = (event.series_title or event.title or "").strip() or "unknown"
    series_key = f"asb:{slugify_series(series_name)}"
    content_type = (
        (event.content_type or "").strip()
        or (cfg.content_type or "anime").strip()
        or "anime"
    )
    unit = (cfg.unit or "minutes").strip() or "minutes"
    activity = (cfg.activity or "listening").strip() or "listening"

    title = (event.title or "").strip()

    source_ref = f"asbplayer:{media_id}"
    notes = (
        f"ratio={ratio:.3f}; duration_s={duration}; "
        f"watched_s={effective_watched:.1f}; media_id={media_id}"
    )
    if event.path and (event.path or "").strip() != media_id:
        notes += f"; path={event.path.strip()}"
    if event.url:
        notes += f"; url={event.url}"
    if event.series_title:
        notes += f"; series={event.series_title.strip()}"

    try:
        entry = create_log(
            db,
            content_type=content_type,
            title=title,
            source="asbplayer",
            amount=amount_minutes,
            unit=unit,
            activity=activity,
            series_key=series_key,
            source_ref=source_ref,
            notes=notes,
            timestamp=event.finished_at,
            watch_ratio=ratio,
        )
    except DuplicateLogError as dup:
        return AsbplayerIngestResult(
            accepted=False,
            reason="duplicate",
            log_id=dup.existing.id,
            log=_log_dict(dup.existing),
        )

    return AsbplayerIngestResult(
        accepted=True,
        reason="logged",
        log_id=entry.id,
        log=_log_dict(entry),
    )


def _log_dict(entry: LogEntry) -> dict:
    return {
        "id": entry.id,
        "title": entry.title,
        "amount": entry.amount,
        "unit": entry.unit,
        "tadoku_status": entry.tadoku_status,
        "tadoku_mode": entry.tadoku_mode,
        "tadoku_score_estimate": entry.tadoku_score_estimate,
        "watch_ratio": entry.watch_ratio,
        "series_key": entry.series_key,
        "source_ref": entry.source_ref,
        "content_type": entry.content_type,
    }
