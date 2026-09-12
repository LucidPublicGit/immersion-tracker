from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.core.config import AppYamlConfig, ContentTypeDefault, get_settings
from app.db.models import CatalogItem, TadokuMode, TadokuStatus


def _type_default(cfg: AppYamlConfig, content_type: str) -> ContentTypeDefault:
    defaults = cfg.content_type_defaults
    if content_type in defaults:
        return defaults[content_type]
    return ContentTypeDefault()


def resolve_tadoku_mode(
    db: Session,
    content_type: str,
    series_key: Optional[str],
    source: str,
    cfg: Optional[AppYamlConfig] = None,
) -> str:
    """
    Resolution order:
      catalog item override > content_type default > source default > pending
    """
    cfg = cfg or get_settings().yaml_config

    if series_key:
        item = (
            db.query(CatalogItem)
            .filter(CatalogItem.series_key == series_key)
            .one_or_none()
        )
        if item and item.tadoku_override:
            return item.tadoku_override

    td = _type_default(cfg, content_type)
    if td.tadoku_mode:
        return td.tadoku_mode

    if source == "youtube":
        return cfg.youtube.tadoku_default
    if source == "plex":
        return cfg.plex.tadoku_default
    if source == "hoshi":
        hoshi_mode = (getattr(cfg, "hoshi", None) and cfg.hoshi.tadoku_default) or ""
        if str(hoshi_mode).strip():
            return str(hoshi_mode).strip()
    if source == "gsm":
        gsm_mode = (getattr(cfg, "gsm", None) and cfg.gsm.tadoku_default) or ""
        if str(gsm_mode).strip():
            return str(gsm_mode).strip()
    if source == "steam":
        mode = (getattr(cfg, "steam", None) and cfg.steam.tadoku_default) or ""
        if str(mode).strip():
            return str(mode).strip()
    if source == "anki":
        mode = (getattr(cfg, "anki", None) and cfg.anki.tadoku_default) or ""
        if str(mode).strip():
            return str(mode).strip()
    if source == "spotify":
        mode = (getattr(cfg, "spotify", None) and cfg.spotify.tadoku_default) or ""
        if str(mode).strip():
            return str(mode).strip()
    if source == "mpv":
        mode = (getattr(cfg, "mpv", None) and cfg.mpv.tadoku_default) or ""
        if str(mode).strip():
            return str(mode).strip()
    if source == "asbplayer":
        mode = (getattr(cfg, "asbplayer", None) and cfg.asbplayer.tadoku_default) or ""
        if str(mode).strip():
            return str(mode).strip()
    return TadokuMode.PENDING.value


def resolve_activity_unit(
    content_type: str, cfg: Optional[AppYamlConfig] = None
) -> tuple[str, str]:
    cfg = cfg or get_settings().yaml_config
    td = _type_default(cfg, content_type)
    return td.activity, td.unit


def mode_to_initial_status(mode: str) -> str:
    if mode == TadokuMode.NEVER.value:
        return TadokuStatus.SKIPPED.value
    if mode == TadokuMode.AUTO.value:
        return TadokuStatus.READY.value
    if mode == TadokuMode.PENDING.value:
        return TadokuStatus.PENDING.value
    return TadokuStatus.PENDING.value


# Built-in JP official contest multipliers (fallback if yaml incomplete)
_DEFAULT_SCORES: dict[str, dict[str, float]] = {
    "reading": {
        "pages": 1.0,
        "two_column_pages": 1.6,
        "comic_pages": 0.2,
        "sentences": 0.05,
        "characters": 0.0025,
        "minutes": 0.4,
    },
    "listening": {
        "minutes": 0.4,
        "minutes_high_density": 0.6,
    },
    "study": {"minutes": 0.5},
    "writing": {
        "pages": 1.0,
        "sentences": 0.05,
        "characters": 0.0025,
    },
    "speaking": {
        "minutes": 0.5,
        "minutes_high_density": 0.7,
    },
}


def estimate_score(
    activity: str,
    amount: float,
    unit: str,
    cfg: Optional[AppYamlConfig] = None,
) -> float:
    cfg = cfg or get_settings().yaml_config
    scores = cfg.tadoku_scores or {}
    defaults = _DEFAULT_SCORES.get(activity) or _DEFAULT_SCORES["listening"]
    by_activity = {**defaults, **(scores.get(activity) or {})}
    mult = by_activity.get(unit)
    if mult is None:
        mult = 0.4 if unit == "minutes" else 0.0
    return round(float(amount) * float(mult), 4)
