"""Canonical enum lists for Google Sheet dropdowns and type tabs."""

from __future__ import annotations

from app.core.config import get_settings

# Friendly tab names for per-type log sheets
CONTENT_TYPE_LABELS: dict[str, str] = {
    "anime": "Anime",
    "visual_novel": "VN",
    "book": "Book",
    "audiobook": "Audiobook",
    "game": "Game",
    "manga": "Manga",
    "show": "Show",
    "youtube": "YouTube",
    "podcast": "Podcast",
    "study": "Study",
}

# Preferred tab order (unknown types sort after)
CONTENT_TYPE_ORDER: list[str] = [
    "anime",
    "visual_novel",
    "book",
    "audiobook",
    "manga",
    "game",
    "show",
    "youtube",
    "podcast",
    "study",
]

ACTIVITIES = ["reading", "listening", "writing", "speaking", "study"]

UNITS = [
    "pages",
    "two_column_pages",
    "comic_pages",
    "sentences",
    "characters",
    "minutes",
    "minutes_high_density",
]

TADOKU_MODES = ["auto", "pending", "never"]
TADOKU_OVERRIDES = ["", "auto", "pending", "never"]  # blank = inherit
TADOKU_STATUSES = ["n/a", "pending", "ready", "pushed", "failed", "skipped"]
SOURCES = [
    "manual",
    "youtube",
    "plex",
    "hoshi",
    "gsm",
    "steam",
    "anki",
    "spotify",
    "mpv",
    "asbplayer",
    "sheet",
    "other",
]
IMPORTED_FLAGS = ["TRUE", "FALSE"]
YES_NO = ["TRUE", "FALSE"]


def content_types() -> list[str]:
    cfg = get_settings().yaml_config
    keys = list(cfg.content_type_defaults.keys()) if cfg.content_type_defaults else []
    # stable order: known first, then extras
    ordered = [k for k in CONTENT_TYPE_ORDER if k in keys or k in CONTENT_TYPE_LABELS]
    for k in keys:
        if k not in ordered:
            ordered.append(k)
    for k in CONTENT_TYPE_LABELS:
        if k not in ordered:
            ordered.append(k)
    return ordered


def type_tab_title(content_type: str) -> str:
    label = CONTENT_TYPE_LABELS.get(content_type, content_type.replace("_", " ").title())
    return f"Logs · {label}"


def all_type_tab_titles() -> dict[str, str]:
    """content_type -> worksheet title"""
    return {ct: type_tab_title(ct) for ct in content_types()}


# Log sheet column headers (shared)
# title = show/work only; season + episode separate → Tadoku uses "Title S01E02"
LOG_HEADERS = [
    "id",
    "timestamp",
    "content_type",
    "title",
    "season",
    "episode",
    "series_key",
    "source",
    "amount",
    "unit",
    "activity",
    "tadoku_mode",
    "tadoku_status",
    "tadoku_score_estimate",
    "watch_ratio",
    "notes",
]

MANUAL_HEADERS = [
    "content_type",
    "title",
    "season",
    "episode",
    "amount",
    "unit",
    "series_key",
    "activity",
    "notes",
    "imported",
]

CATALOG_HEADERS = [
    "series_key",
    "display_title",
    "content_type",
    # Pipe-separated alternate titles (Plex English names) → resolve to series_key
    "aliases",
    "tadoku_override",
    "default_unit",
    "notes",
]

QUEUE_HEADERS = [
    "id",
    "timestamp",
    "title",
    "season",
    "episode",
    "tadoku_title",
    "content_type",
    "amount",
    "unit",
    "score",
    "tadoku_mode",
    "tadoku_status",
    "remote_id",
]
