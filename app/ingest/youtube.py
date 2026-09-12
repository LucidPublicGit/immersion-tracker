from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import LogEntry
from app.ingest.service import DuplicateLogError, create_log


class YouTubeWatchEvent(BaseModel):
    video_id: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    channel_id: str = ""
    channel_title: str = ""
    duration_seconds: float = Field(..., gt=0)
    watched_seconds: float = Field(..., ge=0)
    ratio: Optional[float] = None
    url: Optional[str] = None
    finished_at: Optional[datetime] = None
    # Signed-in YouTube account that watched (not the video uploader)
    viewer_channel_id: str = ""
    viewer_handle: str = ""
    # "history" = user-approved log from YouTube watch history (catch-up / any device)
    import_source: Optional[str] = None

    @field_validator("video_id")
    @classmethod
    def strip_id(cls, v: str) -> str:
        return v.strip()

    @field_validator("import_source")
    @classmethod
    def norm_import_source(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        s = str(v).strip().lower()
        return s or None

    def computed_ratio(self) -> float:
        if self.ratio is not None:
            return max(0.0, min(1.0, self.ratio))
        return max(0.0, min(1.0, self.watched_seconds / self.duration_seconds))

    def is_history_import(self) -> bool:
        return (self.import_source or "") == "history"


class YouTubeIngestResult(BaseModel):
    accepted: bool
    reason: str
    log_id: Optional[int] = None
    log: Optional[dict] = None


def _norm_account_token(value: str) -> str:
    from urllib.parse import unquote

    v = (value or "").strip()
    if not v:
        return ""
    # Extension may send URL-encoded handles (@%E3%83%86… → @テスト…)
    if "%" in v:
        try:
            v = unquote(v)
        except Exception:  # noqa: BLE001
            pass
    if v.startswith("UC") and len(v) >= 22:
        return v
    # Case-fold ASCII only so Japanese handles stay intact
    def _fold(s: str) -> str:
        return "".join(ch.lower() if "A" <= ch <= "Z" else ch for ch in s)

    if v.startswith("@"):
        return "@" + _fold(v[1:])
    # bare handle
    if "/" not in v and " " not in v:
        return "@" + _fold(v)
    return v


def _account_tokens(*parts: str) -> set[str]:
    out: set[str] = set()
    for p in parts:
        t = _norm_account_token(p)
        if t:
            out.add(t)
            if t.startswith("@"):
                out.add(t[1:])  # also bare handle
    return out


def channel_allowed(channel_id: str) -> tuple[bool, str]:
    """Filter by *uploader* channel (who made the video)."""
    cfg = get_settings().yaml_config.youtube
    cid = (channel_id or "").strip()
    if cfg.channel_blocklist and cid in cfg.channel_blocklist:
        return False, "channel_blocked"
    if cfg.channel_allowlist:
        if not cid:
            return False, "channel_unknown_with_allowlist"
        allowed = set(cfg.channel_allowlist)
        if cid not in allowed and f"@{cid.lstrip('@')}" not in allowed:
            return False, "channel_not_allowlisted"
    return True, "ok"


def viewer_allowed(viewer_channel_id: str, viewer_handle: str) -> tuple[bool, str]:
    """Filter by signed-in *viewer* account. Empty allowlist = allow all."""
    cfg = get_settings().yaml_config.youtube
    allow = [_norm_account_token(x) for x in (cfg.viewer_allowlist or []) if str(x).strip()]
    if not allow:
        return True, "ok"

    present = _account_tokens(viewer_channel_id, viewer_handle)
    if not present:
        return False, "viewer_unknown_with_allowlist"

    allowed_set = set(allow)
    # expand bare handles in allowlist
    for a in list(allowed_set):
        if a.startswith("@"):
            allowed_set.add(a[1:])
    if present.intersection(allowed_set):
        return True, "ok"
    return False, "viewer_not_allowlisted"


def find_existing_youtube_log(db: Session, video_id: str) -> Optional[LogEntry]:
    """
    Once-ever uniqueness by video_id.

    New rows use source_ref = video_id. Legacy rows used video_id:YYYY-MM-DD —
    treat those as already logged so rewatches do not create a second entry.
    """
    vid = (video_id or "").strip()
    if not vid:
        return None
    exact = (
        db.query(LogEntry)
        .filter(LogEntry.source == "youtube", LogEntry.source_ref == vid)
        .one_or_none()
    )
    if exact:
        return exact
    legacy = (
        db.query(LogEntry)
        .filter(
            LogEntry.source == "youtube",
            LogEntry.source_ref.like(f"{vid}:%"),
        )
        .order_by(LogEntry.id.asc())
        .first()
    )
    return legacy


def ingest_youtube_watch(db: Session, event: YouTubeWatchEvent) -> YouTubeIngestResult:
    cfg = get_settings().yaml_config.youtube
    ratio = event.computed_ratio()

    if ratio < cfg.completion_threshold:
        return YouTubeIngestResult(
            accepted=False,
            reason=f"below_threshold:{ratio:.3f}<{cfg.completion_threshold}",
        )

    min_watched = float(cfg.min_watched_seconds or 0)
    # Peak progress and reported watch time both count toward the floor
    effective_watched = max(
        float(event.watched_seconds or 0),
        float(event.duration_seconds or 0) * ratio,
    )
    # Log-from-history: user explicitly approved each video after a history scan.
    # Keep completion_threshold + channel/viewer filters; skip min-watch floor
    # so shorter full watches can still be logged after review.
    if (
        min_watched > 0
        and effective_watched < min_watched
        and not event.is_history_import()
    ):
        return YouTubeIngestResult(
            accepted=False,
            reason=f"below_min_watched:{effective_watched:.1f}<{min_watched:.0f}",
        )

    ok, why = channel_allowed(event.channel_id)
    if not ok:
        return YouTubeIngestResult(accepted=False, reason=why)

    ok_v, why_v = viewer_allowed(event.viewer_channel_id, event.viewer_handle)
    if not ok_v:
        return YouTubeIngestResult(accepted=False, reason=why_v)

    # Same video_id only once (ever) — not once per calendar day
    existing = find_existing_youtube_log(db, event.video_id)
    if existing:
        return YouTubeIngestResult(
            accepted=False,
            reason="duplicate",
            log_id=existing.id,
            log=_log_dict(existing),
        )

    # Original media duration in minutes (Tadoku-friendly for speed-watching)
    amount_minutes = round(event.duration_seconds / 60.0, 3)
    series_key = (
        f"yt:{event.channel_id}" if event.channel_id else f"yt:video:{event.video_id}"
    )
    title = event.title
    if event.channel_title:
        title = f"{event.title} — {event.channel_title}"

    source_ref = event.video_id
    notes = (
        f"ratio={ratio:.3f}; duration_s={event.duration_seconds}; "
        f"watched_s={effective_watched:.1f}; video_id={event.video_id}"
    )
    if event.is_history_import():
        notes += "; import=history"
    if event.url:
        notes += f"; url={event.url}"
    if event.viewer_channel_id or event.viewer_handle:
        notes += (
            f"; viewer={event.viewer_handle or event.viewer_channel_id}"
        )

    try:
        entry = create_log(
            db,
            content_type="youtube",
            title=title,
            source="youtube",
            amount=amount_minutes,
            unit="minutes",
            series_key=series_key,
            source_ref=source_ref,
            notes=notes,
            timestamp=event.finished_at,
            watch_ratio=ratio,
        )
    except DuplicateLogError as dup:
        return YouTubeIngestResult(
            accepted=False,
            reason="duplicate",
            log_id=dup.existing.id,
            log=_log_dict(dup.existing),
        )

    return YouTubeIngestResult(
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
    }
