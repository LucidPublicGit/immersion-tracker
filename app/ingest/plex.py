from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.ingest.service import DuplicateLogError, create_log


class PlexWatchEvent(BaseModel):
    """Normalized Plex/Tautulli watch payload."""

    rating_key: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    grandparent_title: Optional[str] = None  # show name
    library_name: str = ""
    media_type: str = "episode"  # episode | movie
    duration_ms: Optional[float] = None
    view_offset_ms: Optional[float] = None
    progress_percent: Optional[float] = None  # 0-100 or 0-1
    watched: bool = False
    finished_at: Optional[datetime] = None
    year: Optional[int] = None


class PlexIngestResult(BaseModel):
    accepted: bool
    reason: str
    log_id: Optional[int] = None


def _ratio(event: PlexWatchEvent) -> float:
    if event.progress_percent is not None:
        p = event.progress_percent
        return p / 100.0 if p > 1.0 else p
    if event.duration_ms and event.view_offset_ms is not None and event.duration_ms > 0:
        return min(1.0, event.view_offset_ms / event.duration_ms)
    if event.watched:
        return 1.0
    return 0.0


def map_content_type(library_name: str, media_type: str) -> str:
    cfg = get_settings().yaml_config.plex
    if library_name in cfg.library_map:
        return cfg.library_map[library_name]
    if media_type == "movie":
        return "show"
    return "anime"


def _clean_tautulli(val: Any) -> Any:
    """Drop unreplaced Tautulli template tokens like '{rating_key}'."""
    if val is None:
        return None
    if isinstance(val, str):
        s = val.strip()
        if not s or (s.startswith("{") and s.endswith("}") and " " not in s):
            return None
        return s
    return val


def _parse_duration_ms(duration: Any) -> Optional[float]:
    """Tautulli may send minutes, ms, seconds, or mm:ss / hh:mm:ss."""
    if duration is None:
        return None
    if isinstance(duration, (int, float)):
        d = float(duration)
        if d > 10000:  # ms
            return d
        if d > 300:  # likely seconds for long media
            return d * 1000.0
        return d * 60_000.0  # minutes
    s = str(duration).strip()
    if not s:
        return None
    if ":" in s:
        parts = [float(p) for p in s.split(":")]
        if len(parts) == 3:
            h, m, sec = parts
            return ((h * 60 + m) * 60 + sec) * 1000.0
        if len(parts) == 2:
            m, sec = parts
            return (m * 60 + sec) * 1000.0
    try:
        return _parse_duration_ms(float(s))
    except (TypeError, ValueError):
        return None


def _parse_intish(val: Any) -> Optional[int]:
    val = _clean_tautulli(val)
    if val is None or val == "":
        return None
    try:
        return int(float(str(val).strip()))
    except (TypeError, ValueError):
        return None


def from_tautulli_webhook(payload: dict[str, Any]) -> PlexWatchEvent:
    """
    Accept common Tautulli webhook shapes (custom JSON body or nested data).
    """
    data = payload.get("data") or payload
    # nested tautulli often uses action + media fields
    action = str(_clean_tautulli(payload.get("action") or data.get("action")) or "").lower()
    watched_flag = data.get("watched")
    if isinstance(watched_flag, str):
        watched_flag = watched_flag.strip().lower() in ("1", "true", "yes", "watched")
    watched = action in ("watched", "on_watched", "stop") or bool(watched_flag)

    progress = _clean_tautulli(data.get("progress_percent") or data.get("progress"))
    if progress is not None:
        try:
            progress = float(progress)
        except (TypeError, ValueError):
            progress = None

    duration_ms = _parse_duration_ms(
        _clean_tautulli(data.get("duration") or data.get("duration_ms"))
    )

    rating_key = str(
        _clean_tautulli(data.get("rating_key"))
        or _clean_tautulli(data.get("ratingKey"))
        or _clean_tautulli(data.get("session_key"))
        or _clean_tautulli(data.get("id"))
        or ""
    )
    title = str(
        _clean_tautulli(data.get("title"))
        or _clean_tautulli(data.get("full_title"))
        or "Unknown"
    )
    show = _clean_tautulli(data.get("grandparent_title") or data.get("show_name"))
    library = str(
        _clean_tautulli(data.get("library_name") or data.get("section_name")) or ""
    )
    media_type = str(
        _clean_tautulli(data.get("media_type") or data.get("type")) or "episode"
    )
    season = _parse_intish(data.get("season_num") or data.get("season"))
    episode = _parse_intish(data.get("episode_num") or data.get("episode") or data.get("media_index"))

    event = PlexWatchEvent(
        rating_key=rating_key or title,
        title=title,
        grandparent_title=str(show) if show else None,
        library_name=library,
        media_type=media_type,
        duration_ms=duration_ms,
        progress_percent=progress,
        watched=watched or (progress is not None and float(progress) >= 90),
        finished_at=datetime.now(timezone.utc),
    )
    # Stash S/E for ingest without changing the public pydantic schema
    event.__dict__["season_num"] = season
    event.__dict__["episode_num"] = episode
    return event


def ingest_plex_watch(db: Session, event: PlexWatchEvent) -> PlexIngestResult:
    cfg = get_settings().yaml_config.plex
    ratio = _ratio(event)
    if not event.watched and ratio < cfg.watch_threshold:
        return PlexIngestResult(
            accepted=False,
            reason=f"below_threshold:{ratio:.3f}<{cfg.watch_threshold}",
        )

    content_type = map_content_type(event.library_name, event.media_type)
    series = event.grandparent_title or event.title
    from app.media.catalog_resolve import resolve_series

    # Alias / display_title from Catalog: links Plex English names → manual series_key
    key_ct = content_type if content_type != "show" else "anime"
    resolved = resolve_series(db, key_ct, series)
    # Keep mapped library content_type (anime vs show) unless catalog forces another
    if resolved.catalog and resolved.catalog.content_type:
        content_type = resolved.catalog.content_type
    series_key = resolved.series_key
    title = resolved.display_title

    if event.duration_ms and event.duration_ms > 0:
        amount = round(event.duration_ms / 60_000.0, 3)
    else:
        amount = 0.0

    source_ref = f"{event.rating_key}:{event.finished_at.date().isoformat() if event.finished_at else 'na'}"
    season = event.__dict__.get("season_num")
    episode = event.__dict__.get("episode_num")
    notes = (
        f"library={event.library_name}; ratio={ratio:.3f}; ep_title={event.title}; "
        f"plex_title={series}; match={resolved.matched_by}"
    )

    # Language from library map (TV Shows → en) so Progress can hide non-JP media
    lib_lang = ""
    try:
        lib_lang = (cfg.library_language or {}).get(event.library_name or "", "") or ""
    except Exception:  # noqa: BLE001
        lib_lang = ""
    if not lib_lang:
        # Heuristic: non-anime libraries default to English unless name suggests JP
        ln = (event.library_name or "").lower()
        if any(x in ln for x in ("anime", "animoo", "jdrama", "japanese", "jp ")):
            lib_lang = "ja"
        elif any(x in ln for x in ("tv", "movie", "film", "shows", "netflix", "western")):
            lib_lang = "en"
        else:
            lib_lang = "ja"

    try:
        entry = create_log(
            db,
            content_type=content_type,
            title=title,
            source="plex",
            amount=amount if amount > 0 else 24.0,  # fallback ~episode
            unit="minutes",
            series_key=series_key,
            source_ref=source_ref,
            notes=notes,
            timestamp=event.finished_at,
            watch_ratio=ratio if ratio > 0 else 1.0,
            season=season,
            episode=episode,
            language=lib_lang or None,
        )
    except DuplicateLogError as dup:
        return PlexIngestResult(accepted=False, reason="duplicate", log_id=dup.existing.id)

    return PlexIngestResult(accepted=True, reason="logged", log_id=entry.id)
