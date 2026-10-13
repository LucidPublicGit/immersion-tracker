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
    # Plex movies often send season=0 episode=0 — not a real position.
    if s == 0 and e == 0:
        return ""
    if s is not None and e is not None:
        return f"S{s:02d}E{e:02d}"
    if s is not None and s != 0:
        return f"S{s:02d}"
    if e is not None and e != 0:
        return f"E{e:02d}"
    if s == 0 or e == 0:
        return ""
    return ""


def format_progress_position(
    content_type: str = "",
    season: Number = None,
    episode: Number = None,
) -> str:
    """
    Shelf position label.

    Manga/book store volume in the episode field → show ``Vol 3`` not ``E03``.
    Movies/films never use SxxExx (Plex often sends 0/0).
    """
    ct = (content_type or "").strip().lower()
    if ct in ("movie", "film"):
        return ""
    s = _parse_int(season)
    e = _parse_int(episode)
    if ct in ("manga", "book", "comic") and e is not None and s is None:
        return f"Vol {e}"
    return format_episode_tag(season, episode)


def tadoku_title(
    title: str,
    *,
    season: Number = None,
    episode: Number = None,
    content_type: str = "",
) -> str:
    """
    Title for Tadoku / exports.

    Anime/show: "KonoSuba S01E02". Manga/book: "Slam Dunk Vol 9".
    Movies: no S00E00 noise. Keep work name in `title`; position in fields.
    """
    base = (title or "").strip()
    ct = (content_type or "").strip().lower()
    # Movies are single works — never append SxxExx (Plex often sends 0/0).
    if ct in ("movie", "film"):
        return base
    tag = format_progress_position(content_type, season, episode)
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
