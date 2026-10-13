from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import quote
from urllib.request import Request, urlopen

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.ingest.plex import (
    PlexIngestResult,
    PlexWatchEvent,
    _clean_tautulli,
    _parse_intish,
    ingest_plex_watch,
)

# .NET ticks: 10_000 per millisecond
_TICKS_PER_MS = 10_000.0

_WATCH_EVENTS = {
    "playbackstop",
    "playbackprogress",
    "userdatasaved",
    "watched",
    "on_watched",
    "stop",
}


def _truthy(val: Any) -> bool:
    if isinstance(val, bool):
        return val
    if val is None:
        return False
    return str(val).strip().lower() in ("1", "true", "yes", "watched")


def _ticks_to_ms(val: Any) -> Optional[float]:
    val = _clean_tautulli(val)
    if val is None or val == "":
        return None
    try:
        n = float(val)
    except (TypeError, ValueError):
        return None
    if n <= 0:
        return None
    # Ticks for real media are huge (24min ≈ 1.44e10). Small numbers are already ms.
    if n >= 10_000:
        return n / _TICKS_PER_MS
    return n


def _notification_type(payload: dict[str, Any], data: dict[str, Any]) -> str:
    raw = (
        _clean_tautulli(payload.get("NotificationType") or payload.get("notification_type"))
        or _clean_tautulli(data.get("NotificationType") or data.get("notification_type") or data.get("action"))
        or ""
    )
    return str(raw).strip().lower()


def from_jellyfin_webhook(payload: dict[str, Any]) -> PlexWatchEvent:
    """
    Jellyfin Webhook plugin (Generic destination) or a compact JSON template.

    Official fields: NotificationType, ItemId, Name, SeriesName, ItemType,
    RunTimeTicks, PlaybackPositionTicks, PlayedToCompletion, Played,
    SeasonNumber, EpisodeNumber, LibraryName / LibraryNameByMaxPath.
    """
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    ntype = _notification_type(payload, data)

    progress = _clean_tautulli(
        data.get("progress_percent") or data.get("progress") or payload.get("progress_percent")
    )
    if progress is not None:
        try:
            progress = float(progress)
        except (TypeError, ValueError):
            progress = None

    duration_ms = _ticks_to_ms(
        data.get("RunTimeTicks") or data.get("run_time_ticks") or data.get("duration_ms") or data.get("duration")
    )
    offset_ms = _ticks_to_ms(
        data.get("PlaybackPositionTicks") or data.get("playback_position_ticks") or data.get("view_offset_ms")
    )
    if progress is None and duration_ms and offset_ms is not None and duration_ms > 0:
        progress = (offset_ms / duration_ms) * 100.0

    played = _truthy(
        data.get("PlayedToCompletion")
        or data.get("played_to_completion")
        or data.get("Played")
        or data.get("played")
        or data.get("watched")
    )
    watched = played or (
        ntype in ("playbackstop", "userdatasaved", "watched", "on_watched")
        and progress is not None
        and float(progress) >= 90
    )

    item_type = str(
        _clean_tautulli(data.get("ItemType") or data.get("item_type") or data.get("media_type") or data.get("type"))
        or "episode"
    ).strip()
    media_type = "movie" if item_type.lower() == "movie" else "episode"

    rating_key = str(
        _clean_tautulli(data.get("ItemId") or data.get("item_id") or data.get("rating_key") or data.get("Id"))
        or ""
    )
    title = str(
        _clean_tautulli(data.get("Name") or data.get("title") or data.get("full_title")) or "Unknown"
    )
    show = _clean_tautulli(data.get("SeriesName") or data.get("grandparent_title") or data.get("show_name"))
    library = str(
        _clean_tautulli(
            data.get("LibraryName")
            or data.get("LibraryNameByMaxPath")
            or data.get("library_name")
            or data.get("section_name")
        )
        or ""
    )
    season = _parse_intish(data.get("SeasonNumber") or data.get("season_num") or data.get("season"))
    episode = _parse_intish(data.get("EpisodeNumber") or data.get("episode_num") or data.get("episode"))
    year = _parse_intish(data.get("Year") or data.get("year"))

    event = PlexWatchEvent(
        rating_key=rating_key or title,
        title=title,
        grandparent_title=str(show) if show else None,
        library_name=library,
        media_type=media_type,
        duration_ms=duration_ms,
        view_offset_ms=offset_ms,
        progress_percent=progress,
        watched=bool(watched or (progress is not None and float(progress) >= 90)),
        finished_at=datetime.now(timezone.utc),
        year=year,
        season_num=season,
        episode_num=episode,
    )
    event.__dict__["notification_type"] = ntype
    return event


def ingest_jellyfin_watch(db: Session, event: PlexWatchEvent) -> PlexIngestResult:
    ntype = str(event.__dict__.get("notification_type") or "")
    if ntype and ntype not in _WATCH_EVENTS and ntype != "generic":
        return PlexIngestResult(accepted=False, reason=f"ignored_event:{ntype}")
    settings = get_settings()
    cfg = settings.yaml_config.jellyfin
    if not event.library_name:
        try:
            event.library_name = _lookup_library(event.rating_key, settings.jellyfin_url, settings.jellyfin_api_key)
        except (OSError, ValueError, KeyError) as exc:
            return PlexIngestResult(accepted=False, reason=f"library_lookup_failed:{type(exc).__name__}")
        if not event.library_name:
            return PlexIngestResult(accepted=False, reason="library_not_found")
    return ingest_plex_watch(db, event, source="jellyfin", cfg=cfg)


def _lookup_library(item_id: str, url: str, key: str) -> str:
    """Resolve the item's media path against Jellyfin's configured library roots."""
    if not url or not key:
        raise ValueError("Jellyfin API is not configured")

    def get(path: str) -> Any:
        request = Request(url.rstrip("/") + path, headers={"X-Emby-Token": key})
        with urlopen(request, timeout=5) as response:
            return json.load(response)

    items = get("/Items?Ids=" + quote(item_id, safe="") + "&Fields=Path")["Items"]
    if not items:
        return ""
    path = items[0].get("Path", "")
    matches = (
        (len(root), library["Name"])
        for library in get("/Library/VirtualFolders")
        for root in library.get("Locations", [])
        if path.startswith(root.rstrip("/") + "/")
    )
    return max(matches, default=(0, ""))[1]
