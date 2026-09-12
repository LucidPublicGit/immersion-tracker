"""Title / series_key helpers for shows & Tadoku export."""

from __future__ import annotations

import re
from typing import Optional, Union

Number = Union[int, float, str, None]


def _parse_int(val: Number) -> Optional[int]:
    if val is None or val == "":
        return None
    try:
        return int(float(str(val).strip()))
    except (TypeError, ValueError):
        return None


def format_episode_tag(season: Number = None, episode: Number = None) -> str:
    """Return e.g. S01E02, S01, E05 — empty if neither set."""
    s = _parse_int(season)
    e = _parse_int(episode)
    if s is not None and e is not None:
        return f"S{s:02d}E{e:02d}"
    if s is not None:
        return f"S{s:02d}"
    if e is not None:
        return f"E{e:02d}"
    return ""


def format_progress_position(
    content_type: str = "",
    season: Number = None,
    episode: Number = None,
) -> str:
    """
    Shelf position label.

    Manga/book store volume in the episode field → show ``Vol 3`` not ``E03``.
    """
    ct = (content_type or "").strip().lower()
    s = _parse_int(season)
    e = _parse_int(episode)
    if ct in ("manga", "book") and e is not None and s is None:
        return f"Vol {e}"
    return format_episode_tag(season, episode)


def tadoku_title(
    title: str,
    *,
    season: Number = None,
    episode: Number = None,
) -> str:
    """
    Title for Tadoku / exports: "KonoSuba S01E02"
    Keep show name in `title`; season/episode stay separate fields.
    """
    base = (title or "").strip()
    tag = format_episode_tag(season, episode)
    if not tag:
        return base
    if not base:
        return tag
    return f"{base} {tag}"


def slugify_series(name: str) -> str:
    """
    Slug for series_key suffix.

    Keeps ASCII alphanumerics and letters from other scripts (Japanese, etc.).
    Older code stripped non-ASCII, so JP-only titles all collapsed to ``unknown``.
    """
    import unicodedata

    s = unicodedata.normalize("NFKC", name or "").strip().casefold()
    s = s.replace("'", "").replace("'", "")
    # \w includes unicode letters/digits; drop other punctuation to hyphens
    s = re.sub(r"[^\w]+", "-", s, flags=re.UNICODE)
    s = re.sub(r"-+", "-", s).strip("-")
    return s[:80] or "unknown"


def suggest_series_key(content_type: str, title: str) -> str:
    """
    Recommended series_key: stable id for the *show/work*, not the episode.

    Examples:
      anime:konosuba
      anime:frieren
      book:kokoro
      vn:steins-gate
    """
    ct = (content_type or "other").strip().lower().replace(" ", "_")
    # map aliases
    if ct in ("visual_novel", "vn"):
        prefix = "vn"
    elif ct == "youtube":
        prefix = "yt"
    else:
        prefix = ct
    return f"{prefix}:{slugify_series(title)}"
