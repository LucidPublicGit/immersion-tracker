"""
Local media metadata cache (covers + total length).

Provider cascade (type-aware):
  anime  → jiten → AniList → Jikan/MAL → TMDB
  manga  → jiten → AniList → Jikan manga
  show/movie → TMDB (key) → AniList → Wikipedia → Jikan
  visual_novel → VNDB → jiten → AniList
  book/audiobook → jiten → AniList → Open Library
  game   → Steam store → jiten → VNDB → Wikipedia

Negative results (source=none) are cached but re-tried after none_retry_days.
Everything is stored in SQLite + cover files under data/media_cache.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

import httpx
from sqlalchemy.orm import Session

from app.db.models import MediaMetadata, utcnow
from app.media.catalog_resolve import normalize_title

logger = logging.getLogger(__name__)

JITEN_API = "https://api.jiten.moe/api"
VNDB_API = "https://api.vndb.org/kana"
# Descriptive UA — Wikipedia REST rejects bare bot-like agents (403)
USER_AGENT = (
    "ImmersionTracker/1.0 (local immersion logging; "
    "+https://github.com/local/immersion-tracker)"
)

# Pace public Jikan cloud instance
_jikan_last_call: float = 0.0

# jiten MediaType enum
JITEN_MEDIA_TYPE = {
    "anime": 1,
    "show": 2,
    "drama": 2,
    "movie": 3,
    "book": 4,
    "novel": 4,
    "audiobook": 10,  # jiten audio decks
    "nonfiction": 5,
    "game": 6,
    "visual_novel": 7,
    "vn": 7,
    "web_novel": 8,
    "webnovel": 8,
    "manga": 9,
    "audio": 10,
    "podcast": 10,
}

# Wikipedia page titles for popular works AniList/Jikan miss
_WIKI_PAGE_ALIASES: dict[str, list[str]] = {
    "arcane": [
        "Arcane (TV series)",
        "Arcane: League of Legends",
        "Arcane",
    ],
    "hogwarts legacy": ["Hogwarts Legacy"],
    "terrace house": ["Terrace House"],
    "hajime no ippo": ["Hajime no Ippo"],
    "mushoku tensei": [
        "Mushoku Tensei",
        "Mushoku Tensei: Jobless Reincarnation",
    ],
    "無職転生": [
        "Mushoku Tensei",
        "Mushoku Tensei: Jobless Reincarnation",
    ],
}

# content types we skip external lookup for (no useful deck match)
SKIP_LOOKUP_TYPES = frozenset({"youtube", "study", "other"})


def _cache_root() -> Path:
    docker = Path("/app/data/media_cache")
    if docker.parent.is_dir():
        return docker
    root = Path("data/media_cache")
    root.mkdir(parents=True, exist_ok=True)
    return root


def cover_dir() -> Path:
    d = _cache_root() / "covers"
    d.mkdir(parents=True, exist_ok=True)
    return d


def safe_filename(source: str, external_id: str, ext: str = ".jpg") -> str:
    sid = re.sub(r"[^a-zA-Z0-9._-]+", "_", f"{source}_{external_id}")[:120]
    if not ext.startswith("."):
        ext = f".{ext}"
    return f"{sid}{ext}"


@dataclass
class ResolvedMedia:
    source: str
    external_id: Optional[str]
    external_url: Optional[str]
    title: str  # preferred display (Japanese/native first when available)
    cover_url: Optional[str]
    total_units: Optional[int]
    total_units_label: Optional[str]
    total_characters: Optional[int]
    total_minutes: Optional[int]
    raw: dict[str, Any]
    title_native: Optional[str] = None
    title_romaji: Optional[str] = None
    title_english: Optional[str] = None


def prefer_web_title(
    *,
    native: Optional[str] = None,
    romaji: Optional[str] = None,
    english: Optional[str] = None,
    fallback: str = "",
) -> str:
    """Prefer Japanese/native, then romaji, then English."""
    for t in (native, romaji, english, fallback):
        if t and str(t).strip():
            return str(t).strip()
    return fallback or ""


def strip_contest_noise(title: str) -> str:
    """
    Remove Tadoku/contest fluff from log titles for display.

    e.g. ``Gashiakuta (double)`` → ``Gashiakuta``
         ``Bookworm (1x past pick)`` → ``Bookworm``
         ``Mahoyo (double]`` → ``Mahoyo``
    """
    t = (title or "").strip()
    if not t:
        return t
    # Trailing "Finished" without parens (do first so paren strip can match $)
    t = re.sub(r"\s+Finished\s*$", "", t, flags=re.I).strip()
    # Known contest / logging notes in trailing parentheses / brackets
    noise = (
        r"double|past\s*pick|half|finished|chars?|bonus|carry[\s-]?over|"
        r"correcting|estimate|true\s*ending|good\s*ending|missed|event|"
        r"from\s+switch|conservative|x\s*\d+|pts?|points|high\s*density"
    )
    t = re.sub(
        rf"\s*[\(\[（][^\)\]）]*?(?:{noise})[^\)\]）]*[\)\]）]\s*$",
        "",
        t,
        flags=re.I,
    ).strip()
    # Unclosed trailing bracket/paren (common in bad exports: "(double")
    t = re.sub(r"\s*[\(\[（][^\)\]）]*$", "", t).strip()
    return t or (title or "").strip()


def preferred_title_from_metadata(meta: Optional[MediaMetadata]) -> Optional[str]:
    """
    Best display title from a cached web match.

    Prefer Japanese/native when present in provider payload; only when
    ``source`` is a real provider (not ``none``).
    """
    if not meta or (meta.source or "").strip().lower() in ("", "none"):
        return None
    raw: dict[str, Any] = {}
    if meta.raw_json:
        try:
            raw = json.loads(meta.raw_json)
        except (json.JSONDecodeError, TypeError):
            raw = {}

    source = (meta.source or "").strip().lower()
    native = romaji = english = None

    if source == "jiten":
        main = raw.get("detail_main") or raw.get("match") or {}
        native = main.get("originalTitle")
        romaji = main.get("romajiTitle")
        english = main.get("englishTitle")
    elif source == "anilist":
        t = (raw.get("anilist") or {}).get("title") or {}
        native = t.get("native")
        romaji = t.get("romaji")
        english = t.get("english")
    elif source in ("mal", "jikan"):
        j = raw.get("jikan") or {}
        native = j.get("title_japanese")
        romaji = j.get("title")
        english = j.get("title_english")
        for entry in j.get("titles") or []:
            if not isinstance(entry, dict):
                continue
            typ = (entry.get("type") or "").lower()
            val = entry.get("title")
            if not val:
                continue
            if typ == "japanese" and not native:
                native = val
            elif typ == "english" and not english:
                english = val
            elif typ in ("default", "synonym") and not romaji:
                romaji = val
    elif source == "vndb":
        v = raw.get("vndb") or {}
        romaji = v.get("title")
        english = v.get("alttitle")
    elif source == "openlibrary":
        english = (raw.get("openlibrary") or {}).get("title")
    elif source == "tmdb":
        t = raw.get("tmdb") or {}
        english = t.get("name") or t.get("title")
        native = t.get("original_name") or t.get("original_title")

    # Explicit fields stored on force-refresh after this change
    titles = raw.get("titles") or {}
    if isinstance(titles, dict):
        native = native or titles.get("native")
        romaji = romaji or titles.get("romaji")
        english = english or titles.get("english")

    preferred = prefer_web_title(
        native=native, romaji=romaji, english=english, fallback=meta.title or ""
    )
    return preferred or None


def _jiten_type_for(content_type: str) -> Optional[int]:
    ct = (content_type or "").strip().lower()
    return JITEN_MEDIA_TYPE.get(ct)


def _units_label_for_jiten(media_type: int) -> str:
    if media_type in (1, 2):  # anime, drama
        return "episodes"
    if media_type == 3:
        return "episodes"  # often 1 for movies
    if media_type == 9:
        return "volumes"
    if media_type in (4, 5, 8):
        return "volumes"
    if media_type == 7:
        return "routes"
    if media_type == 6:
        return "chapters"
    return "parts"


def _speech_ms_to_minutes(ms: Any) -> Optional[int]:
    try:
        v = int(float(ms))
    except (TypeError, ValueError):
        return None
    if v <= 0:
        return None
    return max(1, int(round(v / 60000.0)))


def _jiten_allowed_types(content_type: str) -> Optional[set[int]]:
    """
    jiten mediaType values allowed for a Progress content_type.

    Strict: anime must not accept manga (9) or movie (3) decks unless
    content_type is movie. Empty set means "no filter".
    """
    ct = (content_type or "").strip().lower()
    if not ct:
        return None
    if ct == "anime":
        return {1}  # TV/series anime only — not movie(3) / manga(9)
    if ct in ("show", "drama"):
        return {2, 1}  # drama, fall back to anime-coded JP shows
    if ct == "movie":
        return {3}
    if ct in ("manga",):
        return {9}
    if ct in ("book", "novel", "audiobook"):
        return {4, 5, 8, 10}
    if ct in ("visual_novel", "vn"):
        return {7}
    if ct == "game":
        return {6}
    if ct in ("podcast", "audio"):
        return {10}
    single = JITEN_MEDIA_TYPE.get(ct)
    return {single} if single is not None else None


def _filter_jiten_by_type(
    items: list[dict[str, Any]], content_type: str
) -> list[dict[str, Any]]:
    allowed = _jiten_allowed_types(content_type)
    if not allowed:
        return list(items)
    return [s for s in items if s.get("mediaType") in allowed]


def search_jiten(
    title: str,
    *,
    content_type: str = "",
    limit: int = 5,
    client: Optional[httpx.Client] = None,
) -> list[dict[str, Any]]:
    """Autocomplete + filtered list search on jiten (content-type strict)."""
    q = (title or "").strip()
    if len(q) < 2:
        return []
    owns = client is None
    client = client or httpx.Client(
        timeout=20.0,
        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
        follow_redirects=True,
    )
    try:
        mt = _jiten_type_for(content_type)
        allowed = _jiten_allowed_types(content_type)
        # Prefer suggestions (fast, ranked)
        r = client.get(
            f"{JITEN_API}/media-deck/search-suggestions",
            params={"query": q, "limit": min(max(limit, 1), 12)},
        )
        r.raise_for_status()
        suggestions = list((r.json() or {}).get("suggestions") or [])
        if allowed:
            typed = _filter_jiten_by_type(suggestions, content_type)
            # STRICT: never return manga/movie hits for anime (etc.)
            suggestions = typed
        if suggestions:
            return suggestions[:limit]

        # Fallback: title filter on full list endpoint (typed when possible)
        params: dict[str, Any] = {
            "offset": 0,
            "titleFilter": q,
            "sortBy": "title",
            "sortOrder": 0,
            "status": "none",
        }
        if mt is not None:
            params["mediaType"] = mt
        r2 = client.get(f"{JITEN_API}/media-deck/get-media-decks", params=params)
        r2.raise_for_status()
        data = list((r2.json() or {}).get("data") or [])
        if allowed:
            data = _filter_jiten_by_type(data, content_type)
        return data[:limit]
    except Exception as exc:  # noqa: BLE001
        logger.warning("jiten search failed for %r: %s", q, type(exc).__name__)
        return []
    finally:
        if owns:
            client.close()


def fetch_jiten_detail(
    deck_id: int,
    *,
    client: Optional[httpx.Client] = None,
) -> Optional[dict[str, Any]]:
    owns = client is None
    client = client or httpx.Client(
        timeout=25.0,
        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
        follow_redirects=True,
    )
    try:
        r = client.get(
            f"{JITEN_API}/media-deck/{int(deck_id)}/detail",
            params={"offset": 0},
        )
        r.raise_for_status()
        return r.json()
    except Exception as exc:  # noqa: BLE001
        logger.warning("jiten detail %s failed: %s", deck_id, type(exc).__name__)
        return None
    finally:
        if owns:
            client.close()


def compact_title(name: str) -> str:
    """Casefold + strip spaces/punct for fuzzy equality (yani neko ≈ yanineko)."""
    s = normalize_title(name)
    s = re.sub(r"[\s\u3000\-–—_'\".,:;!?/\\()\[\]{}]+", "", s)
    return s


_TITLE_BOUNDARY = frozenset(" :：～~-–—|/（(【[・'\"")


def score_title_match(query: str, *names: str) -> int:
    """
    0–100 confidence that a candidate is the same work as query.

    Requires a real match — never invent one from weak substring noise
    (e.g. yanineko must not become A Whisker Away).

    Subtitle-heavy AniList/MAL titles still match their base name:
      ``Hajime no Ippo`` ≈ ``Hajime no Ippo: Rising`` → high score
      ``無職転生`` ≈ ``無職転生 ～異世界行ったら本気だす～`` → high score
    """
    needle = normalize_title(query)
    compact = compact_title(query)
    if not needle and not compact:
        return 0
    best = 0
    for raw in names:
        if not raw:
            continue
        nn = normalize_title(str(raw))
        cc = compact_title(str(raw))
        if not nn and not cc:
            continue
        if nn == needle or (compact and cc == compact):
            best = max(best, 100)
            continue
        # Base title vs "Title: Season / Subtitle" (very common on AniList)
        if needle and nn and len(needle) >= 3:
            if nn.startswith(needle) and (
                len(nn) == len(needle) or nn[len(needle)] in _TITLE_BOUNDARY
            ):
                best = max(best, 94)
            elif needle.startswith(nn) and (
                len(needle) == len(nn) or needle[len(nn)] in _TITLE_BOUNDARY
            ):
                best = max(best, 90)
        if compact and cc and len(compact) >= 4:
            if cc.startswith(compact):
                # Allow long season subtitles (ratio can be low)
                best = max(best, 92 if len(cc) <= len(compact) * 3 else 86)
            elif compact.startswith(cc) and len(cc) >= 6:
                best = max(best, 88)
        # Containment only when both sides are reasonably long
        if compact and cc and len(compact) >= 4 and len(cc) >= 4:
            if compact == cc:
                best = max(best, 100)
            elif compact in cc or cc in compact:
                ratio = min(len(compact), len(cc)) / max(len(compact), len(cc))
                if ratio >= 0.4:
                    best = max(best, 82 if ratio >= 0.55 else 76)
        if needle and nn and len(needle) >= 4:
            if needle in nn or nn in needle:
                ratio = min(len(needle), len(nn)) / max(len(needle), len(nn))
                if ratio >= 0.4:
                    best = max(best, 80 if ratio >= 0.55 else 76)
    return best


# Minimum score to accept a provider hit (strict — wrong covers are worse than none)
MIN_MATCH_SCORE = 75


def _meta_cfg():
    try:
        from app.core.config import get_settings

        return get_settings().yaml_config.metadata
    except Exception:  # noqa: BLE001
        return None


def _min_score() -> int:
    cfg = _meta_cfg()
    if cfg is not None and getattr(cfg, "min_match_score", None):
        return int(cfg.min_match_score)
    return MIN_MATCH_SCORE


def _jikan_pace() -> None:
    global _jikan_last_call
    cfg = _meta_cfg()
    ms = int(getattr(cfg, "jikan_min_interval_ms", 400) or 400)
    gap = max(0.0, ms / 1000.0)
    now = time.monotonic()
    wait = gap - (now - _jikan_last_call)
    if wait > 0:
        time.sleep(wait)
    _jikan_last_call = time.monotonic()


def _jiten_format_bonus(
    content_type: str,
    *,
    media_type: int,
    units: Optional[int],
    min_episode: Optional[int] = None,
) -> int:
    """
    Adjust match score so franchise titles pick the right format.

    Example: Yu-Gi-Oh! as anime must prefer Duel Monsters (144 eps), not the
    4-episode Toei pilot or a movie deck.
    """
    ct = (content_type or "").strip().lower()
    bonus = 0
    if ct == "anime":
        if media_type == 3:
            bonus -= 30
        if media_type == 9:
            bonus -= 50
        if units is not None:
            if units >= 26:
                bonus += 18
            elif units >= 12:
                bonus += 14
            elif units >= 8:
                bonus += 6
            elif units <= 4:
                bonus -= 28  # pilot / movie-length "anime" decks
            elif units <= 6:
                bonus -= 12
        if min_episode is not None and units is not None and units < min_episode:
            bonus -= 40  # user logged E18 but deck has 4 eps
    elif ct == "movie":
        if media_type == 3:
            bonus += 20
        if units is not None and units <= 2:
            bonus += 10
    elif ct == "manga":
        if media_type == 9:
            bonus += 10
        if media_type == 1:
            bonus -= 40
        if units is not None and units >= 5:
            bonus += 5
    elif ct in ("show", "drama"):
        if media_type == 2:
            bonus += 10
        if units is not None and units >= 8:
            bonus += 8
    return bonus


def _pick_jiten_match(
    title: str,
    candidates: list[dict[str, Any]],
    *,
    content_type: str = "",
    client: Optional[httpx.Client] = None,
    min_episode: Optional[int] = None,
) -> Optional[tuple[dict[str, Any], Optional[dict[str, Any]], int]]:
    """
    Pick best jiten candidate for content_type.

    Returns (pick, detail_json, score) or None.
    Fetches details for top title matches so episode counts rank franchises.
    """
    if not candidates:
        return None
    ct = (content_type or "").strip().lower()
    candidates = _filter_jiten_by_type(candidates, ct)
    if not candidates:
        return None

    # Title-score first, then detail-rank top few
    prelim: list[tuple[int, dict[str, Any]]] = []
    for c in candidates:
        names = [
            c.get("englishTitle") or "",
            c.get("romajiTitle") or "",
            c.get("originalTitle") or "",
        ]
        score = score_title_match(title, *names)
        if score >= _min_score() - 10:  # keep near-misses for format boost
            prelim.append((score, c))
    if not prelim:
        return None
    prelim.sort(key=lambda x: -x[0])
    # Detail-fetch top candidates (cap to control latency)
    best: Optional[tuple[dict[str, Any], Optional[dict[str, Any]], int]] = None
    best_rank = -10_000
    for title_score, c in prelim[:6]:
        deck_id = c.get("deckId")
        detail = None
        units = None
        mt = int(c.get("mediaType") or 0)
        if deck_id is not None:
            detail = fetch_jiten_detail(int(deck_id), client=client)
            main = ((detail or {}).get("data") or {}).get("mainDeck") or c
            mt = int(main.get("mediaType") or mt or 0)
            allowed = _jiten_allowed_types(ct)
            if allowed is not None and mt not in allowed:
                continue
            try:
                units = int(
                    (detail or {}).get("totalItems")
                    or main.get("childrenDeckCount")
                    or 0
                ) or None
            except (TypeError, ValueError):
                units = None
        rank = title_score + _jiten_format_bonus(
            ct, media_type=mt, units=units, min_episode=min_episode
        )
        # Prefer longer series on ties (main TV over short specials)
        tie = units or 0
        composite = rank * 1000 + min(tie, 999)
        if composite > best_rank and title_score + max(
            0, _jiten_format_bonus(ct, media_type=mt, units=units, min_episode=min_episode)
        ) >= _min_score() - 5:
            # Final gate: still need a reasonable title score
            if title_score < _min_score() and rank < _min_score():
                continue
            if title_score < 60:
                continue
            best_rank = composite
            best = (c, detail, max(title_score, min(100, rank)))
    if best is None:
        # Fall back to pure title score among typed candidates
        for title_score, c in prelim:
            if title_score >= _min_score():
                return (c, None, title_score)
        return None
    return best


def resolve_from_jiten(
    title: str,
    content_type: str,
    *,
    client: Optional[httpx.Client] = None,
    min_episode: Optional[int] = None,
) -> Optional[ResolvedMedia]:
    # Try a few query variants (spaced romanization, original)
    variants = []
    for v in (title, title.replace("-", " "), re.sub(r"([a-z])([A-Z])", r"\1 \2", title)):
        v = (v or "").strip()
        if v and v not in variants:
            variants.append(v)
    candidates: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    for v in variants:
        for c in search_jiten(v, content_type=content_type, client=client):
            did = c.get("deckId")
            if did in seen_ids:
                continue
            if did is not None:
                seen_ids.add(int(did))
            candidates.append(c)
    picked = _pick_jiten_match(
        title,
        candidates,
        content_type=content_type,
        client=client,
        min_episode=min_episode,
    )
    if not picked:
        return None
    pick, detail, match_score = picked
    deck_id = pick.get("deckId")
    if deck_id is None:
        return None

    if detail is None:
        detail = fetch_jiten_detail(int(deck_id), client=client)
    main = ((detail or {}).get("data") or {}).get("mainDeck") or pick
    mt = int(main.get("mediaType") or pick.get("mediaType") or 0)
    allowed = _jiten_allowed_types(content_type)
    if allowed is not None and mt not in allowed:
        return None
    children = main.get("childrenDeckCount")
    try:
        children_i = int(children) if children is not None else None
    except (TypeError, ValueError):
        children_i = None
    # Prefer totalItems from detail for episode list accuracy
    total_items = (detail or {}).get("totalItems")
    try:
        if total_items is not None:
            children_i = int(total_items) or children_i
    except (TypeError, ValueError):
        pass

    # Reject decks shorter than progress already logged (E18 vs 4-ep pilot)
    if (
        min_episode is not None
        and children_i is not None
        and children_i > 0
        and min_episode > children_i
        and (content_type or "").strip().lower() in ("anime", "show", "drama")
    ):
        return None

    chars = main.get("characterCount")
    try:
        chars_i = int(chars) if chars is not None else None
    except (TypeError, ValueError):
        chars_i = None

    minutes = _speech_ms_to_minutes(main.get("speechDuration"))
    cover = main.get("coverName") or pick.get("coverName")
    if cover and not str(cover).startswith("http"):
        if str(cover) == "nocover.jpg":
            cover = None
        else:
            cover = f"https://cdn.jiten.moe/{deck_id}/cover.jpg"

    native = main.get("originalTitle") or pick.get("originalTitle")
    romaji = main.get("romajiTitle") or pick.get("romajiTitle")
    english = main.get("englishTitle") or pick.get("englishTitle")
    display = prefer_web_title(
        native=native, romaji=romaji, english=english, fallback=title
    )
    label = _units_label_for_jiten(mt) if mt else "parts"
    # Movies often have 0 children — treat as 1 episode
    if mt == 3 and not children_i:
        children_i = 1
    # For anime TV, don't surface character counts as if they were primary length
    # (still stored; progress prefers episode totals)

    return ResolvedMedia(
        source="jiten",
        external_id=str(deck_id),
        external_url=f"https://jiten.moe/decks/media/{deck_id}/detail",
        title=str(display),
        cover_url=str(cover) if cover else None,
        total_units=children_i,
        total_units_label=label,
        total_characters=chars_i,
        total_minutes=minutes,
        title_native=str(native).strip() if native else None,
        title_romaji=str(romaji).strip() if romaji else None,
        title_english=str(english).strip() if english else None,
        raw={
            "match": pick,
            "detail_main": {
                k: main.get(k)
                for k in (
                    "deckId",
                    "mediaType",
                    "originalTitle",
                    "romajiTitle",
                    "englishTitle",
                    "characterCount",
                    "childrenDeckCount",
                    "speechDuration",
                    "coverName",
                    "links",
                )
            },
            "titles": {
                "native": native,
                "romaji": romaji,
                "english": english,
            },
            "totalItems": total_items,
            "content_type": content_type,
            "match_score": match_score if match_score else score_title_match(
                title,
                pick.get("englishTitle") or "",
                pick.get("romajiTitle") or "",
                pick.get("originalTitle") or "",
            ),
        },
    )


def resolve_from_jikan(
    title: str,
    content_type: str,
    *,
    client: Optional[httpx.Client] = None,
    min_episode: Optional[int] = None,
) -> Optional[ResolvedMedia]:
    """
    MAL via Jikan (no API key). Anime or manga endpoints by content_type.
    """
    cfg = _meta_cfg()
    if cfg is not None and not getattr(cfg, "jikan", True):
        return None
    ct = (content_type or "").strip().lower()
    kind = "manga" if ct in ("manga", "book", "audiobook") else "anime"
    if kind == "anime" and ct not in ("anime", "show", "movie", "drama", ""):
        return None
    q = (title or "").strip()
    if len(q) < 1:
        return None

    owns = client is None
    # Short timeout — Jikan public often 504s; don't block enrich for 25s each
    jikan_timeout = httpx.Timeout(8.0, connect=4.0)
    client = client or httpx.Client(
        timeout=jikan_timeout,
        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
        follow_redirects=True,
    )
    endpoint = f"https://api.jikan.moe/v4/{kind}"
    try:
        queries = [q]
        if " " not in q and re.fullmatch(r"[A-Za-z0-9\-]+", q or ""):
            spaced = re.sub(
                r"([a-z]{3,})(neko|chan|kun|san|sama)", r"\1 \2", q, flags=re.I
            )
            if spaced != q:
                queries.append(spaced)
            if q.lower() == "yanineko":
                queries.extend(["Yani Neko", "Chainsmoker Cat"])
        best_score = -1
        best_item = None
        jikan_failures = 0
        for query in queries[:3]:
            if jikan_failures >= 2:
                break
            _jikan_pace()
            try:
                r = client.get(endpoint, params={"q": query, "limit": 6}, timeout=jikan_timeout)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                jikan_failures += 1
                logger.warning("jikan timeout/transport for %r: %s", query, type(exc).__name__)
                continue
            if r.status_code in (429, 500, 502, 503, 504):
                jikan_failures += 1
                logger.warning("jikan HTTP %s for %r", r.status_code, query)
                if r.status_code == 429:
                    time.sleep(1.2)
                continue
            r.raise_for_status()
            data = (r.json() or {}).get("data") or []
            for item in data:
                titles = [
                    item.get("title") or "",
                    item.get("title_english") or "",
                    item.get("title_japanese") or "",
                ]
                for t in item.get("titles") or []:
                    if isinstance(t, dict) and t.get("title"):
                        titles.append(t["title"])
                score = max(
                    score_title_match(q, *titles),
                    score_title_match(query, *titles),
                )
                # Prefer TV series for anime content_type over Movie/OVA
                mal_type = (item.get("type") or "").strip()
                if kind == "anime" and ct == "anime":
                    if mal_type == "TV":
                        score += 8
                    elif mal_type == "Movie":
                        score -= 20
                    elif mal_type in ("OVA", "Special"):
                        score -= 8
                    try:
                        eps_n = int(item.get("episodes") or 0)
                    except (TypeError, ValueError):
                        eps_n = 0
                    if eps_n >= 26:
                        score += 6
                    elif eps_n >= 12:
                        score += 4
                    elif 0 < eps_n <= 4:
                        score -= 15
                    if min_episode and eps_n and min_episode > eps_n:
                        continue
                if kind == "manga" and mal_type and mal_type not in (
                    "Manga",
                    "Manhwa",
                    "Manhua",
                    "Novel",
                    "One-shot",
                    "Light Novel",
                    "",
                ):
                    score -= 10
                if score > best_score:
                    best_score = score
                    best_item = item
        if not best_item or best_score < _min_score():
            return None

        mal_id = best_item.get("mal_id")
        images = (best_item.get("images") or {}).get("jpg") or {}
        cover = (
            images.get("large_image_url")
            or images.get("image_url")
            or images.get("small_image_url")
        )
        if kind == "manga":
            units = best_item.get("volumes") or best_item.get("chapters")
            units_label = "volumes" if best_item.get("volumes") else "chapters"
        else:
            units = best_item.get("episodes")
            units_label = "episodes"
        try:
            units_i = int(units) if units is not None else None
        except (TypeError, ValueError):
            units_i = None
        if (
            min_episode is not None
            and units_i is not None
            and min_episode > units_i
            and ct in ("anime", "show", "drama")
        ):
            return None
        native = best_item.get("title_japanese")
        romaji = best_item.get("title")
        english = best_item.get("title_english")
        display = prefer_web_title(
            native=native, romaji=romaji, english=english, fallback=q
        )
        path = "manga" if kind == "manga" else "anime"
        return ResolvedMedia(
            source="mal",
            external_id=str(mal_id) if mal_id is not None else None,
            external_url=(
                f"https://myanimelist.net/{path}/{mal_id}"
                if mal_id is not None
                else None
            ),
            title=str(display),
            cover_url=str(cover) if cover else None,
            total_units=units_i,
            total_units_label=units_label if units_i else None,
            total_characters=None,
            total_minutes=None,
            title_native=str(native).strip() if native else None,
            title_romaji=str(romaji).strip() if romaji else None,
            title_english=str(english).strip() if english else None,
            raw={
                "jikan": best_item,
                "match_score": best_score,
                "query": q,
                "kind": kind,
                "titles": {
                    "native": native,
                    "romaji": romaji,
                    "english": english,
                },
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("jikan search failed for %r: %s", q, type(exc).__name__)
        return None
    finally:
        if owns:
            client.close()


def resolve_from_anilist(
    title: str,
    content_type: str,
    *,
    client: Optional[httpx.Client] = None,
    min_episode: Optional[int] = None,
) -> Optional[ResolvedMedia]:
    """AniList GraphQL fallback (no key). Good when Jikan/MAL is down."""
    cfg = _meta_cfg()
    if cfg is not None and not getattr(cfg, "anilist", True):
        return None
    ct = (content_type or "").strip().lower()
    if ct not in (
        "anime",
        "show",
        "movie",
        "drama",
        "manga",
        "book",
        "audiobook",
        "visual_novel",
        "vn",
        "",
    ):
        return None
    q = (title or "").strip()
    if len(q) < 1:
        return None
    # Light novels + manga share AniList MANGA type; audiobook LN art still useful
    media_type = "MANGA" if ct in ("manga", "book", "audiobook") else "ANIME"

    owns = client is None
    client = client or httpx.Client(
        timeout=25.0,
        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
        follow_redirects=True,
    )
    query = """
    query ($search: String, $type: MediaType) {
      Page(perPage: 8) {
        media(search: $search, type: $type) {
          id
          idMal
          format
          episodes
          chapters
          volumes
          popularity
          siteUrl
          title { romaji english native }
          coverImage { large extraLarge }
        }
      }
    }
    """
    # Format preference for anime vs movie content_type
    _ANIME_TV = frozenset({"TV", "TV_SHORT", "ONA", "OVA"})
    _ANIME_MOVIE = frozenset({"MOVIE"})

    def _format_rank(fmt: str) -> int:
        f = (fmt or "").upper()
        if ct == "movie":
            return 30 if f in _ANIME_MOVIE else (10 if f in _ANIME_TV else 0)
        if ct == "anime":
            if f == "TV":
                return 25
            if f in ("ONA", "TV_SHORT"):
                return 15
            if f == "OVA":
                return 5
            if f in _ANIME_MOVIE:
                return -25
            if f == "SPECIAL":
                return -10
        if ct == "manga" and f in ("MANGA", "NOVEL", "ONE_SHOT"):
            return 10
        return 0

    try:
        searches = [q]
        if q.lower() == "yanineko":
            searches.extend(["Yani Neko", "ヤニねこ", "Chainsmoker Cat"])
        best = None
        best_rank = -10_000
        for search in searches:
            r = client.post(
                "https://graphql.anilist.co",
                json={
                    "query": query,
                    "variables": {"search": search, "type": media_type},
                },
            )
            r.raise_for_status()
            media = (((r.json() or {}).get("data") or {}).get("Page") or {}).get("media") or []
            for item in media:
                t = item.get("title") or {}
                titles = [t.get("romaji") or "", t.get("english") or "", t.get("native") or ""]
                score = max(
                    score_title_match(q, *titles),
                    score_title_match(search, *titles),
                )
                if score < _min_score() - 5:
                    continue
                try:
                    pop = int(item.get("popularity") or 0)
                except (TypeError, ValueError):
                    pop = 0
                try:
                    eps = int(item.get("episodes") or 0) or None
                except (TypeError, ValueError):
                    eps = None
                fmt = (item.get("format") or "") or ""
                if ct == "anime" and media_type == "ANIME":
                    # Skip pure movies when looking for series (unless only hit)
                    if min_episode and eps and min_episode > eps:
                        continue
                rank = (
                    score * 1000
                    + _format_rank(fmt) * 20
                    + min(pop // 1000, 50)
                    + (min(eps or 0, 200) if ct == "anime" else 0)
                )
                if rank > best_rank:
                    best_rank = rank
                    best = item
        if not best:
            return None
        # Re-check title score on winner
        t = best.get("title") or {}
        best_score = score_title_match(
            q, t.get("romaji") or "", t.get("english") or "", t.get("native") or ""
        )
        if best_score < _min_score():
            return None
        t = best.get("title") or {}
        native = t.get("native")
        romaji = t.get("romaji")
        english = t.get("english")
        display = prefer_web_title(
            native=native, romaji=romaji, english=english, fallback=q
        )
        cover = (best.get("coverImage") or {}).get("extraLarge") or (
            best.get("coverImage") or {}
        ).get("large")
        if media_type == "ANIME":
            units = best.get("episodes")
            units_label = "episodes"
            if (best.get("format") or "").upper() == "MOVIE" and not units:
                units = 1
        else:
            # Prefer tankōbon volumes when present (manga progress)
            if best.get("volumes"):
                units = best.get("volumes")
                units_label = "volumes"
            else:
                units = best.get("chapters")
                units_label = "chapters"
        try:
            units_i = int(units) if units is not None else None
        except (TypeError, ValueError):
            units_i = None
        if (
            min_episode is not None
            and units_i is not None
            and min_episode > units_i
            and ct in ("anime", "show", "drama")
        ):
            return None
        mal_id = best.get("idMal")
        season_totals: dict[int, int] = {}
        if ct == "anime" and media_type == "ANIME" and best.get("id"):
            try:
                season_totals = _anilist_tv_franchise_season_totals(
                    client, int(best["id"])
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "anilist franchise seasons failed for %s: %s",
                    best.get("id"),
                    type(exc).__name__,
                )
                season_totals = {}
        franchise_total = sum(season_totals.values()) if season_totals else None
        # Prefer franchise sum when AniList only returned the first season's eps
        if franchise_total and franchise_total > (units_i or 0):
            units_i = franchise_total
            units_label = "episodes"
        raw_payload: dict[str, Any] = {
            "anilist": best,
            "match_score": best_score,
            "query": q,
            "format": best.get("format"),
            "content_type": ct,
            "titles": {
                "native": native,
                "romaji": romaji,
                "english": english,
            },
        }
        if season_totals:
            raw_payload["season_totals"] = {
                str(k): int(v) for k, v in sorted(season_totals.items())
            }
        return ResolvedMedia(
            source="anilist",
            external_id=str(best.get("id")),
            external_url=best.get("siteUrl")
            or (f"https://myanimelist.net/anime/{mal_id}" if mal_id else None),
            title=str(display),
            cover_url=str(cover) if cover else None,
            total_units=units_i,
            total_units_label=units_label if units_i else None,
            total_characters=None,
            total_minutes=None,
            title_native=str(native).strip() if native else None,
            title_romaji=str(romaji).strip() if romaji else None,
            title_english=str(english).strip() if english else None,
            raw=raw_payload,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("anilist search failed for %r: %s", q, type(exc).__name__)
        return None
    finally:
        if owns:
            client.close()


_ANILIST_TV_FORMATS = frozenset({"TV", "TV_SHORT", "ONA"})


def _anilist_fetch_media_node(
    client: httpx.Client, media_id: int
) -> Optional[dict[str, Any]]:
    """Single AniList media node with relation edges (for franchise walks)."""
    query = """
    query ($id: Int) {
      Media(id: $id, type: ANIME) {
        id
        format
        episodes
        title { romaji english native }
        relations {
          edges {
            relationType
            node { id format episodes title { romaji english } }
          }
        }
      }
    }
    """
    r = client.post(
        "https://graphql.anilist.co",
        json={"query": query, "variables": {"id": int(media_id)}},
    )
    r.raise_for_status()
    return ((r.json() or {}).get("data") or {}).get("Media")


def _anilist_pick_relation(
    edges: list[dict[str, Any]],
    *,
    relation: str,
    prefer_tv: bool = True,
) -> Optional[dict[str, Any]]:
    rel = (relation or "").upper()
    cands = [
        (e.get("node") or {})
        for e in (edges or [])
        if (e.get("relationType") or "").upper() == rel and e.get("node")
    ]
    if not cands:
        return None
    if prefer_tv:
        for n in cands:
            if (n.get("format") or "").upper() in _ANILIST_TV_FORMATS:
                return n
    return cands[0]


def _anilist_tv_franchise_season_totals(
    client: httpx.Client,
    media_id: int,
    *,
    max_nodes: int = 14,
) -> dict[int, int]:
    """
    Walk AniList PREQUEL/SEQUEL edges to map main TV seasons → episode counts.

    Movies/OVAs between seasons are stepped through but not counted as seasons
    (e.g. Yowamushi Pedal Grande Road → movie → New Generation).
    """
    cache: dict[int, dict[str, Any]] = {}

    def _get(mid: int) -> Optional[dict[str, Any]]:
        if mid in cache:
            return cache[mid]
        if len(cache) >= max_nodes:
            return None
        try:
            node = _anilist_fetch_media_node(client, mid)
        except Exception:  # noqa: BLE001
            return None
        if node and node.get("id") is not None:
            cache[int(node["id"])] = node
        return node

    start = _get(int(media_id))
    if not start:
        return {}

    # Walk PREQUEL toward the first TV entry (skip movie-only prequels to a TV root)
    root = start
    guard = 0
    while guard < max_nodes:
        guard += 1
        edges = ((root.get("relations") or {}).get("edges")) or []
        tv_pre = _anilist_pick_relation(edges, relation="PREQUEL", prefer_tv=True)
        if tv_pre and (tv_pre.get("format") or "").upper() in _ANILIST_TV_FORMATS:
            nxt = _get(int(tv_pre["id"]))
            if not nxt:
                break
            root = nxt
            continue
        # Movie/OVA prequel: step once and look for a TV prequel behind it
        other_pre = _anilist_pick_relation(edges, relation="PREQUEL", prefer_tv=False)
        if other_pre and other_pre.get("id"):
            mid = _get(int(other_pre["id"]))
            if not mid:
                break
            mid_edges = ((mid.get("relations") or {}).get("edges")) or []
            tv_behind = _anilist_pick_relation(
                mid_edges, relation="PREQUEL", prefer_tv=True
            )
            if tv_behind and (tv_behind.get("format") or "").upper() in _ANILIST_TV_FORMATS:
                nxt = _get(int(tv_behind["id"]))
                if nxt:
                    root = nxt
                    continue
        break

    # Walk SEQUEL forward; count TV nodes as seasons
    totals: dict[int, int] = {}
    season_n = 0
    cur = root
    seen: set[int] = set()
    guard = 0
    while cur and guard < max_nodes:
        guard += 1
        cid = int(cur.get("id") or 0)
        if not cid or cid in seen:
            break
        seen.add(cid)
        fmt = (cur.get("format") or "").upper()
        try:
            eps = int(cur.get("episodes") or 0)
        except (TypeError, ValueError):
            eps = 0
        if fmt in _ANILIST_TV_FORMATS and eps > 0:
            season_n += 1
            totals[season_n] = eps

        edges = ((cur.get("relations") or {}).get("edges")) or []
        tv_seq = _anilist_pick_relation(edges, relation="SEQUEL", prefer_tv=True)
        if tv_seq and tv_seq.get("id"):
            cur = _get(int(tv_seq["id"]))
            continue
        # Intermediate movie/OVA sequel — step through to next TV season
        other_seq = _anilist_pick_relation(edges, relation="SEQUEL", prefer_tv=False)
        if other_seq and other_seq.get("id"):
            mid = _get(int(other_seq["id"]))
            if not mid:
                break
            mid_edges = ((mid.get("relations") or {}).get("edges")) or []
            tv_next = _anilist_pick_relation(mid_edges, relation="SEQUEL", prefer_tv=True)
            if tv_next and tv_next.get("id"):
                cur = _get(int(tv_next["id"]))
                continue
            # Sometimes the intermediate is itself listed only as ALTERNATIVE; stop
        break

    # Only useful when we found more than a single-season flat total
    return totals if len(totals) >= 2 else {}


def resolve_from_vndb(
    title: str,
    content_type: str,
    *,
    client: Optional[httpx.Client] = None,
) -> Optional[ResolvedMedia]:
    """VNDB Kana API — visual novels (no key required for search)."""
    cfg = _meta_cfg()
    if cfg is not None and not getattr(cfg, "vndb", True):
        return None
    ct = (content_type or "").strip().lower()
    if ct not in ("visual_novel", "vn", "game", ""):
        return None
    q = (title or "").strip()
    if len(q) < 1:
        return None
    owns = client is None
    headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
    token = (getattr(cfg, "vndb_token", None) or "").strip() if cfg else ""
    if token:
        headers["Authorization"] = f"token {token}"
    client = client or httpx.Client(timeout=25.0, headers=headers, follow_redirects=True)
    try:
        r = client.post(
            f"{VNDB_API}/vn",
            json={
                "filters": ["search", "=", q],
                "fields": "title, alttitle, image.url, image.thumbnail, length_minutes",
                "results": 8,
                "sort": "searchrank",
            },
        )
        r.raise_for_status()
        results = (r.json() or {}).get("results") or []
        best = None
        best_score = -1
        for item in results:
            names = [item.get("title") or "", item.get("alttitle") or ""]
            score = score_title_match(q, *names)
            if score > best_score:
                best_score = score
                best = item
        if not best or best_score < _min_score():
            return None
        img = best.get("image") or {}
        cover = img.get("url") or img.get("thumbnail")
        vid = best.get("id")  # e.g. v17
        minutes = best.get("length_minutes")
        try:
            minutes_i = int(minutes) if minutes is not None else None
        except (TypeError, ValueError):
            minutes_i = None
        display = (best.get("title") or q).strip()
        return ResolvedMedia(
            source="vndb",
            external_id=str(vid) if vid else None,
            external_url=f"https://vndb.org/{vid}" if vid else None,
            title=display,
            cover_url=str(cover) if cover else None,
            total_units=None,
            total_units_label=None,
            total_characters=None,
            total_minutes=minutes_i,
            title_native=None,
            title_romaji=display,
            title_english=best.get("alttitle"),
            raw={
                "vndb": best,
                "match_score": best_score,
                "query": q,
                "titles": {"romaji": display, "english": best.get("alttitle")},
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("vndb search failed for %r: %s", q, type(exc).__name__)
        return None
    finally:
        if owns:
            client.close()


def resolve_from_tvmaze(
    title: str,
    content_type: str,
    *,
    client: Optional[httpx.Client] = None,
) -> Optional[ResolvedMedia]:
    """
    TVMaze single-search (no API key) — Western TV covers + episode counts.
    Excellent for Arcane / Terrace House when TMDB key is absent.
    """
    cfg = _meta_cfg()
    if cfg is not None and not getattr(cfg, "tvmaze", True):
        return None
    ct = (content_type or "").strip().lower()
    if ct not in ("show", "movie", "drama", "anime", ""):
        return None
    q = (title or "").strip()
    if len(q) < 2:
        return None
    owns = client is None
    client = client or httpx.Client(
        timeout=20.0,
        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
        follow_redirects=True,
    )
    try:
        r = client.get(
            "https://api.tvmaze.com/singlesearch/shows",
            params={"q": q, "embed": "episodes"},
        )
        if r.status_code == 404:
            return None
        r.raise_for_status()
        data = r.json() or {}
        names = [
            data.get("name") or "",
            # web channel / network sometimes redundant
        ]
        score = score_title_match(q, *names)
        if score < _min_score():
            return None
        img = data.get("image") or {}
        cover = img.get("original") or img.get("medium")
        units_i = None
        embedded = (data.get("_embedded") or {}).get("episodes") or []
        if embedded:
            units_i = len(embedded)
        else:
            # fallback: follow self link for episode list
            try:
                self_url = ((data.get("_links") or {}).get("self") or {}).get("href")
                if self_url:
                    er = client.get(f"{self_url}/episodes")
                    if er.is_success:
                        units_i = len(er.json() or [])
            except Exception:  # noqa: BLE001
                pass
        display = (data.get("name") or q).strip()
        show_id = data.get("id")
        from app.media.season_progress import season_totals_from_tvmaze_episodes

        season_totals = season_totals_from_tvmaze_episodes(embedded)
        return ResolvedMedia(
            source="tvmaze",
            external_id=str(show_id) if show_id is not None else None,
            external_url=data.get("url")
            or (f"https://www.tvmaze.com/shows/{show_id}" if show_id else None),
            title=display,
            cover_url=str(cover) if cover else None,
            total_units=units_i,
            total_units_label="episodes" if units_i else None,
            total_characters=None,
            total_minutes=None,
            title_native=None,
            title_romaji=None,
            title_english=display,
            raw={
                "tvmaze": {
                    "id": show_id,
                    "name": display,
                    "premiered": data.get("premiered"),
                    "genres": data.get("genres"),
                },
                "match_score": score,
                "query": q,
                "titles": {"english": display},
                "season_totals": {str(k): v for k, v in sorted(season_totals.items())},
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("tvmaze search failed for %r: %s", q, type(exc).__name__)
        return None
    finally:
        if owns:
            client.close()


def resolve_from_steam(
    title: str,
    content_type: str,
    *,
    client: Optional[httpx.Client] = None,
) -> Optional[ResolvedMedia]:
    """
    Steam store search (no API key) — covers for popular games.
    Uses storesearch + appdetails for header art.
    """
    cfg = _meta_cfg()
    if cfg is not None and not getattr(cfg, "steam", True):
        return None
    ct = (content_type or "").strip().lower()
    if ct not in ("game", ""):
        return None
    q = (title or "").strip()
    if len(q) < 2:
        return None
    owns = client is None
    client = client or httpx.Client(
        timeout=25.0,
        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
        follow_redirects=True,
    )
    try:
        r = client.get(
            "https://store.steampowered.com/api/storesearch/",
            params={"term": q, "l": "english", "cc": "US"},
        )
        r.raise_for_status()
        items = (r.json() or {}).get("items") or []
        best = None
        best_score = -1
        for item in items:
            name = item.get("name") or ""
            score = score_title_match(q, name)
            if score > best_score:
                best_score = score
                best = item
        if not best or best_score < _min_score():
            return None
        app_id = best.get("id")
        display = (best.get("name") or q).strip()
        cover = None
        minutes = None
        detail = None
        if app_id is not None:
            try:
                d = client.get(
                    "https://store.steampowered.com/api/appdetails",
                    params={"appids": str(app_id), "l": "english"},
                )
                if d.is_success:
                    payload = (d.json() or {}).get(str(app_id)) or {}
                    if payload.get("success"):
                        detail = payload.get("data") or {}
                        cover = (
                            detail.get("header_image")
                            or detail.get("capsule_image")
                            or detail.get("capsule_imagev5")
                        )
                        # approximate playtime from metacritic is not available;
                        # leave total_minutes empty — user tracks immersion time
            except Exception:  # noqa: BLE001
                pass
        if not cover:
            cover = best.get("tiny_image")
        return ResolvedMedia(
            source="steam",
            external_id=str(app_id) if app_id is not None else None,
            external_url=(
                f"https://store.steampowered.com/app/{app_id}/"
                if app_id is not None
                else None
            ),
            title=display,
            cover_url=str(cover) if cover else None,
            total_units=None,
            total_units_label=None,
            total_characters=None,
            total_minutes=minutes,
            title_native=None,
            title_romaji=None,
            title_english=display,
            raw={
                "steam": best,
                "steam_detail": detail,
                "match_score": best_score,
                "query": q,
                "titles": {"english": display},
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("steam search failed for %r: %s", q, type(exc).__name__)
        return None
    finally:
        if owns:
            client.close()


def resolve_from_wikipedia(
    title: str,
    content_type: str,
    *,
    client: Optional[httpx.Client] = None,
) -> Optional[ResolvedMedia]:
    """
    Wikipedia REST summary — free cover art for Western TV/games AniList misses.
    """
    cfg = _meta_cfg()
    if cfg is not None and not getattr(cfg, "wikipedia", True):
        return None
    ct = (content_type or "").strip().lower()
    if ct not in ("show", "movie", "game", "anime", "book", "audiobook", ""):
        return None
    q = (title or "").strip()
    if len(q) < 2:
        return None
    from app.media.title_search import clean_search_title

    cleaned = clean_search_title(q)
    pages: list[str] = []
    key = normalize_title(cleaned)
    for alias_key, names in _WIKI_PAGE_ALIASES.items():
        if key == normalize_title(alias_key) or key.startswith(
            normalize_title(alias_key) + " "
        ):
            pages.extend(names)
    pages.extend([cleaned, q])
    # de-dupe
    seen: set[str] = set()
    uniq_pages: list[str] = []
    for p in pages:
        pk = normalize_title(p)
        if pk and pk not in seen:
            seen.add(pk)
            uniq_pages.append(p)

    owns = client is None
    client = client or httpx.Client(
        timeout=20.0,
        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
        follow_redirects=True,
    )
    try:
        for page in uniq_pages[:6]:
            try:
                # REST API encodes title path segment
                from urllib.parse import quote

                path = quote(page.replace(" ", "_"), safe="()_,:'")
                r = client.get(
                    f"https://en.wikipedia.org/api/rest_v1/page/summary/{path}"
                )
                if r.status_code == 404:
                    continue
                r.raise_for_status()
                data = r.json() or {}
                if data.get("type") == "disambiguation":
                    continue
                wtitle = data.get("title") or page
                desc = (data.get("description") or "").lower()
                # Prefer actual works over soundtrack / cast list / album pages
                if any(
                    bad in desc
                    for bad in (
                        "soundtrack",
                        "album",
                        "song by",
                        "single by",
                        "disambiguation",
                    )
                ):
                    continue
                score = score_title_match(q, wtitle, cleaned, page)
                # Boost TV/game pages when content_type matches description
                if ct in ("show", "movie", "drama") and any(
                    k in desc for k in ("television", "series", "animated", "tv series")
                ):
                    score = max(score, min(100, score + 5) if score else 80)
                if ct == "game" and "video game" in desc:
                    score = max(score, min(100, score + 5) if score else 80)
                # Also score against description lead when title is generic
                if score < _min_score():
                    if desc and score_title_match(q, desc) >= 60:
                        score = max(score, 78)
                if score < _min_score():
                    continue
                thumb = (data.get("originalimage") or {}).get("source") or (
                    data.get("thumbnail") or {}
                ).get("source")
                if not thumb:
                    continue
                return ResolvedMedia(
                    source="wikipedia",
                    external_id=str(data.get("pageid") or wtitle),
                    external_url=data.get("content_urls", {})
                    .get("desktop", {})
                    .get("page")
                    or f"https://en.wikipedia.org/wiki/{path}",
                    title=str(wtitle),
                    cover_url=str(thumb),
                    total_units=None,
                    total_units_label=None,
                    total_characters=None,
                    total_minutes=None,
                    title_native=None,
                    title_romaji=None,
                    title_english=str(wtitle),
                    raw={
                        "wikipedia": {
                            "title": wtitle,
                            "description": data.get("description"),
                            "pageid": data.get("pageid"),
                        },
                        "match_score": score,
                        "query": q,
                        "titles": {"english": wtitle},
                    },
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug("wikipedia page %r failed: %s", page, type(exc).__name__)
                continue
        return None
    finally:
        if owns:
            client.close()


def resolve_from_open_library(
    title: str,
    content_type: str,
    *,
    client: Optional[httpx.Client] = None,
) -> Optional[ResolvedMedia]:
    """Open Library search + covers (no API key)."""
    cfg = _meta_cfg()
    if cfg is not None and not getattr(cfg, "open_library", True):
        return None
    ct = (content_type or "").strip().lower()
    if ct not in ("book", "manga", "audiobook", ""):
        return None
    q = (title or "").strip()
    if len(q) < 2:
        return None
    owns = client is None
    client = client or httpx.Client(
        timeout=25.0,
        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
        follow_redirects=True,
    )
    try:
        r = client.get(
            "https://openlibrary.org/search.json",
            params={
                "q": q,
                "limit": 8,
                "fields": "key,title,cover_i,isbn,author_name,edition_count",
            },
        )
        r.raise_for_status()
        docs = (r.json() or {}).get("docs") or []
        best = None
        best_score = -1
        for doc in docs:
            score = score_title_match(q, doc.get("title") or "")
            if score > best_score:
                best_score = score
                best = doc
        if not best or best_score < _min_score():
            return None
        cover_i = best.get("cover_i")
        cover = (
            f"https://covers.openlibrary.org/b/id/{cover_i}-L.jpg"
            if cover_i
            else None
        )
        key = (best.get("key") or "").strip()  # /works/OL…
        work_id = key.rsplit("/", 1)[-1] if key else None
        display = (best.get("title") or q).strip()
        return ResolvedMedia(
            source="openlibrary",
            external_id=work_id,
            external_url=f"https://openlibrary.org{key}" if key else None,
            title=display,
            cover_url=cover,
            total_units=None,
            total_units_label=None,
            total_characters=None,
            total_minutes=None,
            title_native=None,
            title_romaji=None,
            title_english=display,
            raw={
                "openlibrary": best,
                "match_score": best_score,
                "query": q,
                "titles": {"english": display},
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("openlibrary search failed for %r: %s", q, type(exc).__name__)
        return None
    finally:
        if owns:
            client.close()


def resolve_from_tmdb(
    title: str,
    content_type: str,
    *,
    client: Optional[httpx.Client] = None,
) -> Optional[ResolvedMedia]:
    """TMDB TV/movie search — requires free API key."""
    cfg = _meta_cfg()
    if cfg is not None and not getattr(cfg, "tmdb", True):
        return None
    api_key = (getattr(cfg, "tmdb_api_key", None) or "").strip() if cfg else ""
    if not api_key:
        return None
    ct = (content_type or "").strip().lower()
    if ct not in ("show", "movie", "drama", "anime", ""):
        return None
    q = (title or "").strip()
    if len(q) < 1:
        return None
    kind = "movie" if ct == "movie" else "tv"
    owns = client is None
    client = client or httpx.Client(
        timeout=25.0,
        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
        follow_redirects=True,
    )
    try:
        r = client.get(
            f"https://api.themoviedb.org/3/search/{kind}",
            params={
                "api_key": api_key,
                "query": q,
                "include_adult": "false",
                "language": "en-US",
            },
        )
        r.raise_for_status()
        results = (r.json() or {}).get("results") or []
        best = None
        best_score = -1
        for item in results:
            names = [
                item.get("name") or item.get("title") or "",
                item.get("original_name") or item.get("original_title") or "",
            ]
            score = score_title_match(q, *names)
            if score > best_score:
                best_score = score
                best = item
        if not best or best_score < _min_score():
            return None
        tid = best.get("id")
        poster = best.get("poster_path")
        cover = f"https://image.tmdb.org/t/p/w500{poster}" if poster else None
        units_i = None
        # Detail call for episode count on TV
        if kind == "tv" and tid is not None:
            try:
                d = client.get(
                    f"https://api.themoviedb.org/3/tv/{tid}",
                    params={"api_key": api_key, "language": "en-US"},
                )
                if d.is_success:
                    detail = d.json() or {}
                    eps = detail.get("number_of_episodes")
                    if eps is not None:
                        units_i = int(eps)
                    best = {**best, "detail": detail}
            except Exception:  # noqa: BLE001
                pass
        elif kind == "movie":
            units_i = 1
        display = (
            best.get("name")
            or best.get("title")
            or best.get("original_name")
            or best.get("original_title")
            or q
        )
        path = "tv" if kind == "tv" else "movie"
        return ResolvedMedia(
            source="tmdb",
            external_id=str(tid) if tid is not None else None,
            external_url=f"https://www.themoviedb.org/{path}/{tid}" if tid else None,
            title=str(display).strip(),
            cover_url=cover,
            total_units=units_i,
            total_units_label="episodes" if kind == "tv" else "episodes",
            total_characters=None,
            total_minutes=None,
            title_native=best.get("original_name") or best.get("original_title"),
            title_romaji=None,
            title_english=str(display).strip(),
            raw={
                "tmdb": best,
                "match_score": best_score,
                "query": q,
                "kind": kind,
                "titles": {
                    "english": display,
                    "native": best.get("original_name") or best.get("original_title"),
                },
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("tmdb search failed for %r: %s", q, type(exc).__name__)
        return None
    finally:
        if owns:
            client.close()


def download_cover(
    cover_url: str,
    *,
    source: str,
    external_id: str,
    client: Optional[httpx.Client] = None,
) -> Optional[str]:
    """
    Download cover to local cache. Returns relative path under media_cache
    (e.g. covers/jiten_18054.jpg) or None.
    """
    if not cover_url or not cover_url.startswith("http"):
        return None
    path_ext = Path(urlparse(cover_url).path).suffix.lower()
    if path_ext not in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
        path_ext = ".jpg"
    fname = safe_filename(source, external_id, path_ext)
    dest = cover_dir() / fname
    if dest.is_file() and dest.stat().st_size > 0:
        return f"covers/{fname}"

    owns = client is None
    client = client or httpx.Client(
        timeout=30.0,
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
    )
    try:
        r = client.get(cover_url)
        r.raise_for_status()
        if not r.content or len(r.content) < 32:
            return None
        dest.write_bytes(r.content)
        return f"covers/{fname}"
    except Exception as exc:  # noqa: BLE001
        logger.warning("cover download failed %s: %s", cover_url, type(exc).__name__)
        return None
    finally:
        if owns:
            client.close()


def get_cached(db: Session, series_key: str) -> Optional[MediaMetadata]:
    if not series_key:
        return None
    return (
        db.query(MediaMetadata)
        .filter(MediaMetadata.series_key == series_key)
        .one_or_none()
    )


def _is_cjk(s: str) -> bool:
    return bool(re.search(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]", s or ""))


def build_search_queries(
    title: str,
    *,
    series_key: str = "",
    aliases: Optional[list[str]] = None,
    extra_titles: Optional[list[str]] = None,
    max_queries: int = 14,
) -> list[str]:
    """
    Expand a work into multiple lookup strings (JP, EN, aliases, key slug).

    Higher hit rate without bulk-scraping: we try several clean queries and
    keep the single best high-confidence match.
    """
    from app.media.title_search import clean_search_title, expand_title_aliases

    seeds: list[str] = []
    for raw in [title, *(extra_titles or []), *(aliases or [])]:
        if raw and str(raw).strip():
            seeds.append(str(raw).strip())

    # Humanize series_key suffix: anime:konosuba → konosuba
    sk = (series_key or "").strip()
    if ":" in sk:
        suffix = sk.split(":", 1)[1].strip()
        if suffix and suffix not in ("unknown",) and not re.fullmatch(
            r"[0-9a-f]{8}-[0-9a-f-]{20,}", suffix, re.I
        ):
            seeds.append(suffix.replace("-", " "))
            seeds.append(suffix)

    out: list[str] = []
    seen: set[str] = set()

    def _add(q: str) -> None:
        q = clean_search_title(q)
        q = strip_contest_noise((q or "").strip())
        if not q or len(q) < 1:
            return
        if re.fullmatch(r"\d{1,6}", q):
            return
        # drop pure series_key forms
        if ":" in q and q.count(":") == 1 and " " not in q and not _is_cjk(q):
            if q.startswith(
                (
                    "anime:",
                    "show:",
                    "other:",
                    "vn:",
                    "manga:",
                    "gsm:",
                    "hoshi:",
                    "game:",
                    "audiobook:",
                    "book:",
                )
            ):
                return
        # Drop 1–2 char slug leftovers (series_key "x" / "ch") — they match wrong works
        if len(q) <= 2 and not _is_cjk(q):
            return
        key = normalize_title(q)
        if not key or key in seen:
            return
        seen.add(key)
        out.append(q)

    for seed in seeds:
        _add(seed)
        cleaned = clean_search_title(seed)
        _add(cleaned)
        for alias in expand_title_aliases(seed):
            _add(alias)

        # Fullwidth / halfwidth bang variants (mostly JP media titles)
        if _is_cjk(cleaned):
            if cleaned.endswith("!") or cleaned.endswith("！"):
                _add(cleaned[:-1])
                _add(cleaned[:-1] + "！")
                _add(cleaned[:-1] + "!")
            else:
                _add(cleaned + "！")
                _add(cleaned + "!")

        # Episode / volume tails → base name
        m = re.match(
            r"^(.+?)\s+(?:[Ss]\d{1,2}[Ee]\d{1,3}|[Ee]?\d{1,3}(?:\s*[-–,]\s*\d{1,3})?)\s*$",
            cleaned,
        )
        if m:
            _add(m.group(1))

        # Latin spacing helpers
        if re.search(r"[A-Za-z]", cleaned) and not _is_cjk(cleaned):
            spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", cleaned)
            _add(spaced)
            _add(cleaned.replace("-", " "))
            _add(cleaned.replace("_", " "))
            _add(re.sub(r"([A-Za-z])(\d)", r"\1 \2", cleaned))
            glued = re.sub(
                r"(neko|chan|kun|san|sama|sensei|senpai)$",
                r" \1",
                cleaned,
                flags=re.I,
            )
            if glued != cleaned:
                _add(glued)

    # Prefer: CJK titles first (often best for jiten/anilist), then shorter clean names
    def _rank(q: str) -> tuple:
        return (0 if _is_cjk(q) else 1, len(q), q)

    out_sorted = sorted(out, key=_rank)
    return out_sorted[:max_queries]


def _resolved_score(resolved: ResolvedMedia, queries: list[str]) -> int:
    names = [
        resolved.title or "",
        resolved.title_native or "",
        resolved.title_romaji or "",
        resolved.title_english or "",
    ]
    best = int((resolved.raw or {}).get("match_score") or 0)
    for q in queries:
        best = max(best, score_title_match(q, *names))
    return best


def _try_jiten_queries(
    qs: list[str],
    content_type: str,
    client: httpx.Client,
    *,
    min_episode: Optional[int] = None,
) -> Optional[ResolvedMedia]:
    cfg = _meta_cfg()
    if cfg is not None and not getattr(cfg, "jiten", True):
        return None
    jiten_cands: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    for q in qs:
        for c in search_jiten(q, content_type=content_type, client=client, limit=8):
            did = c.get("deckId")
            if did is None:
                continue
            di = int(did)
            if di in seen_ids:
                continue
            seen_ids.add(di)
            jiten_cands.append(c)
    if not jiten_cands:
        return None
    # Use the strongest query string for title scoring inside pick
    best_q = qs[0]
    best_q_score = -1
    for q in qs:
        for c in jiten_cands:
            names = [
                c.get("englishTitle") or "",
                c.get("romajiTitle") or "",
                c.get("originalTitle") or "",
            ]
            sc = score_title_match(q, *names)
            if sc > best_q_score:
                best_q_score = sc
                best_q = q
    r = resolve_from_jiten(
        best_q,
        content_type,
        client=client,
        min_episode=min_episode,
    )
    if r:
        sc = max(best_q_score, _resolved_score(r, qs))
        if isinstance(r.raw, dict):
            r.raw["match_score"] = sc
            r.raw["search_queries"] = qs
    return r


def _provider_order(content_type: str) -> list[str]:
    """Named phases: jiten | tmdb | vndb | openlibrary | jikan | anilist | steam | wikipedia."""
    ct = (content_type or "").strip().lower()
    if ct in ("show", "movie", "drama"):
        # TVMaze covers Western shows without TMDB key (Arcane, Terrace House, …)
        return ["tmdb", "tvmaze", "anilist", "wikipedia", "jiten", "jikan"]
    if ct in ("visual_novel", "vn"):
        return ["vndb", "jiten", "anilist"]
    if ct == "game":
        return ["steam", "jiten", "vndb", "wikipedia"]
    if ct in ("book", "audiobook"):
        # jiten/anilist first for JP LN art; Open Library for EN editions
        return ["jiten", "anilist", "openlibrary", "wikipedia"]
    if ct == "manga":
        return ["jiten", "anilist", "jikan"]
    # AniList before Jikan — public Jikan often 504s under batch load
    return ["jiten", "anilist", "jikan", "tmdb", "tvmaze", "wikipedia"]


def _resolved_fits_content_type(
    resolved: ResolvedMedia,
    content_type: str,
    *,
    min_episode: Optional[int] = None,
) -> bool:
    """Reject cross-type hits (manga art for anime, 4-ep pilot when user is on E18)."""
    ct = (content_type or "").strip().lower()
    if not ct or not resolved or resolved.source in ("", "none"):
        return True
    label = (resolved.total_units_label or "").strip().lower()
    units = resolved.total_units
    raw = resolved.raw if isinstance(resolved.raw, dict) else {}

    if ct == "anime":
        if label in ("volumes", "chapters"):
            return False
        mt = None
        if isinstance(raw.get("detail_main"), dict):
            mt = raw["detail_main"].get("mediaType")
        elif isinstance(raw.get("match"), dict):
            mt = raw["match"].get("mediaType")
        if mt is not None and int(mt) not in (0, 1):
            return False
        fmt = (raw.get("format") or raw.get("anilist", {}).get("format") or "")
        if isinstance(raw.get("anilist"), dict):
            fmt = raw["anilist"].get("format") or fmt
        if str(fmt).upper() == "MOVIE" and min_episode and min_episode > 1:
            return False
        if (
            min_episode is not None
            and units is not None
            and units > 0
            and min_episode > units
        ):
            return False
    if ct == "manga":
        if label == "episodes":
            mt = None
            if isinstance(raw.get("detail_main"), dict):
                mt = raw["detail_main"].get("mediaType")
            if mt is not None and int(mt) == 1:
                return False
        kind = (raw.get("kind") or "").lower()
        if kind == "anime":
            return False
    if ct in ("book", "novel", "audiobook", "web_novel", "webnovel"):
        # Never attach anime/drama/movie decks to reading/listening books
        mt = None
        if isinstance(raw.get("detail_main"), dict):
            mt = raw["detail_main"].get("mediaType")
        elif isinstance(raw.get("match"), dict):
            mt = raw["match"].get("mediaType")
        if mt is not None and int(mt) in (1, 2, 3):  # anime / drama / movie
            return False
        if label == "episodes":
            return False
        fmt = ""
        if isinstance(raw.get("anilist"), dict):
            fmt = (raw["anilist"].get("format") or "").upper()
        elif raw.get("format"):
            fmt = str(raw.get("format") or "").upper()
        if fmt in ("TV", "TV_SHORT", "ONA", "OVA", "MOVIE", "SPECIAL"):
            return False
    if ct == "movie":
        # Long TV episode counts never belong on a movie work
        if units is not None and units > 6 and label in ("episodes", "parts", ""):
            return False
        fmt = ""
        if isinstance(raw.get("anilist"), dict):
            fmt = (raw["anilist"].get("format") or "").upper()
        elif raw.get("format"):
            fmt = str(raw.get("format") or "").upper()
        if fmt in ("TV", "TV_SHORT", "ONA", "OVA"):
            return False
        mt = None
        if isinstance(raw.get("detail_main"), dict):
            mt = raw["detail_main"].get("mediaType")
        elif isinstance(raw.get("match"), dict):
            mt = raw["match"].get("mediaType")
        # jiten: 1=anime series, 3=movie
        if mt is not None and int(mt) == 1:
            return False
    return True


def resolve_media_smart(
    queries: list[str],
    content_type: str,
    *,
    client: Optional[httpx.Client] = None,
    min_episode: Optional[int] = None,
) -> Optional[ResolvedMedia]:
    """
    Type-aware multi-provider lookup. Keeps best match ≥ min_match_score.
    Stops early on a perfect 100.

    min_episode: highest episode number already logged — rejects decks shorter
    than progress (e.g. Yu-Gi-Oh! E18 must not match a 4-episode pilot).
    """
    qs = [q for q in queries if q and q.strip()]
    if not qs:
        return None

    owns = client is None
    client = client or httpx.Client(
        timeout=25.0,
        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
        follow_redirects=True,
    )
    best: Optional[ResolvedMedia] = None
    best_score = -1
    threshold = _min_score()
    single_resolvers = {
        "tmdb": resolve_from_tmdb,
        "tvmaze": resolve_from_tvmaze,
        "vndb": resolve_from_vndb,
        "openlibrary": resolve_from_open_library,
        "jikan": resolve_from_jikan,
        "anilist": resolve_from_anilist,
        "steam": resolve_from_steam,
        "wikipedia": resolve_from_wikipedia,
    }
    try:
        for phase in _provider_order(content_type):
            if best_score >= 100:
                break
            if phase == "jiten":
                r = _try_jiten_queries(
                    qs, content_type, client, min_episode=min_episode
                )
                if r and _resolved_fits_content_type(
                    r, content_type, min_episode=min_episode
                ):
                    sc = _resolved_score(r, qs)
                    if sc >= threshold and sc > best_score:
                        if isinstance(r.raw, dict):
                            r.raw["search_queries"] = qs
                            r.raw["match_score"] = sc
                        best, best_score = r, sc
                continue
            resolver = single_resolvers.get(phase)
            if not resolver:
                continue
            # Fewer query variants for external APIs (rate limits / noisy titles)
            q_try = qs[:5]
            for q in q_try:
                try:
                    r = resolver(
                        q, content_type, client=client, min_episode=min_episode
                    )
                except TypeError:
                    # Resolvers without min_episode kwarg
                    r = resolver(q, content_type, client=client)
                if not r:
                    continue
                if not _resolved_fits_content_type(
                    r, content_type, min_episode=min_episode
                ):
                    continue
                sc = _resolved_score(r, qs)
                # Format bonus already applied inside resolvers; still prefer TV-scale
                if (
                    (content_type or "").lower() == "anime"
                    and r.total_units
                    and r.total_units >= 12
                    and (r.total_units_label or "") == "episodes"
                ):
                    sc = min(100, sc + 3)
                if sc >= threshold and sc > best_score:
                    if isinstance(r.raw, dict):
                        r.raw["search_queries"] = qs
                        r.raw["match_score"] = sc
                        r.raw["matched_query"] = q
                    best, best_score = r, sc
                    if best_score >= 100:
                        break
        return best if best_score >= threshold else None
    finally:
        if owns:
            client.close()


def lookup_context_for_series(
    db: Session,
    series_key: str,
    title: str,
) -> list[str]:
    """Catalog aliases + sample log titles → search query list."""
    from app.db.models import CatalogItem, LogEntry
    from app.media.catalog_resolve import parse_aliases

    aliases: list[str] = []
    extras: list[str] = []
    cat = (
        db.query(CatalogItem)
        .filter(CatalogItem.series_key == series_key)
        .one_or_none()
    )
    if cat:
        if cat.display_title:
            extras.append(cat.display_title)
        aliases.extend(parse_aliases(cat.aliases))
    # Recent distinct log titles for this key (messy notes OK — strip later)
    rows = (
        db.query(LogEntry.title)
        .filter(LogEntry.series_key == series_key)
        .order_by(LogEntry.id.desc())
        .limit(30)
        .all()
    )
    for (t,) in rows:
        if t:
            extras.append(t)

    return build_search_queries(
        title,
        series_key=series_key,
        aliases=aliases,
        extra_titles=extras,
    )


def ensure_metadata(
    db: Session,
    *,
    series_key: str,
    title: str,
    content_type: str,
    force: bool = False,
    search_queries: Optional[list[str]] = None,
) -> MediaMetadata:
    """
    Return cached metadata for series_key, looking up externally only if missing
    (or force=True). Negative results (source=none) are also cached to avoid
    hammering providers.

    Lookup tries Japanese title, English, catalog aliases, and series_key slug
    variants across jiten → MAL/Jikan → AniList.
    """
    key = (series_key or "").strip()
    if not key:
        raise ValueError("series_key required")

    existing = get_cached(db, key)
    cfg = _meta_cfg()
    none_retry_days = int(getattr(cfg, "none_retry_days", 14) or 14)

    if existing and not force:
        src = (existing.source or "").strip().lower()
        # User-set metadata is sticky — never clobber with auto lookup
        if src == "manual":
            if (
                not existing.cover_local_path
                and existing.cover_url
            ):
                local = download_cover(
                    existing.cover_url,
                    source="manual",
                    external_id=existing.external_id
                    or key.replace(":", "_")[:40],
                )
                if local:
                    existing.cover_local_path = local
                    existing.updated_at = utcnow()
                    db.commit()
                    db.refresh(existing)
            return existing
        # Sticky positive hits — only backfill missing local cover file
        if src and src != "none":
            if (
                not existing.cover_local_path
                and existing.cover_url
                and existing.external_id
            ):
                local = download_cover(
                    existing.cover_url,
                    source=existing.source or "jiten",
                    external_id=existing.external_id,
                )
                if local:
                    existing.cover_local_path = local
                    existing.updated_at = utcnow()
                    db.commit()
                    db.refresh(existing)
            return existing
        # source=none: re-try after TTL (title cleaners / new providers may help)
        fetched = existing.fetched_at
        if fetched is not None:
            try:
                age = utcnow() - fetched
                if age < timedelta(days=max(0, none_retry_days)):
                    return existing
            except TypeError:
                # naive vs aware datetime edge
                return existing
        # else fall through and re-lookup (treat like force for this key)

    ct = (content_type or "").strip().lower()
    resolved: Optional[ResolvedMedia] = None

    # Highest episode already logged — reject short movies/pilots for long series
    min_episode: Optional[int] = None
    try:
        from app.db.models import LogEntry

        ep_rows = (
            db.query(LogEntry.episode)
            .filter(LogEntry.series_key == key, LogEntry.episode.isnot(None))
            .all()
        )
        eps = [int(e[0]) for e in ep_rows if e[0] is not None]
        if eps:
            min_episode = max(eps)
    except Exception:  # noqa: BLE001
        min_episode = None

    if ct not in SKIP_LOOKUP_TYPES and ((title or "").strip() or search_queries):
        queries = search_queries or lookup_context_for_series(db, key, title or key)
        with httpx.Client(
            timeout=30.0,
            headers={"Accept": "application/json", "User-Agent": USER_AGENT},
            follow_redirects=True,
        ) as client:
            resolved = resolve_media_smart(
                queries, ct, client=client, min_episode=min_episode
            )

    if resolved is None:
        resolved = ResolvedMedia(
            source="none",
            external_id=None,
            external_url=None,
            title=title or key,
            cover_url=None,
            total_units=None,
            total_units_label=None,
            total_characters=None,
            total_minutes=None,
            raw={},
        )

    local_cover: Optional[str] = None
    if resolved.cover_url and resolved.external_id:
        local_cover = download_cover(
            resolved.cover_url,
            source=resolved.source,
            external_id=resolved.external_id,
        )

    now = utcnow()
    if existing:
        row = existing
    else:
        row = MediaMetadata(series_key=key)
        db.add(row)

    row.content_type = ct
    # On a real web hit, store preferred web title (JP first). Keep query in raw.
    if resolved.source and resolved.source != "none":
        row.title = resolved.title or strip_contest_noise(title) or key
        if isinstance(resolved.raw, dict):
            resolved.raw.setdefault("query", title)
    else:
        row.title = strip_contest_noise(title) or title or key
    row.source = resolved.source
    row.external_id = resolved.external_id
    row.external_url = resolved.external_url
    row.cover_url = resolved.cover_url
    if local_cover:
        row.cover_local_path = local_cover
    elif force and resolved.source == "none":
        # Clear wrong art when a forced re-lookup finds nothing reliable
        row.cover_local_path = None
    row.total_units = resolved.total_units
    row.total_units_label = resolved.total_units_label
    row.total_characters = resolved.total_characters
    row.total_minutes = resolved.total_minutes
    # Preserve user-locked season totals across auto re-fetch
    from app.media.season_progress import (
        merge_season_totals_into_raw,
        parse_season_totals_map,
        season_totals_from_metadata,
        seasons_locked_from_metadata,
    )

    resolved_raw = dict(resolved.raw or {}) if isinstance(resolved.raw, dict) else {}
    if seasons_locked_from_metadata(existing):
        locked = season_totals_from_metadata(existing)
        if locked:
            resolved_raw["season_totals"] = {
                str(k): v for k, v in sorted(locked.items())
            }
            resolved_raw["seasons_locked"] = True
            # Keep franchise total consistent with locked seasons
            franchise = sum(locked.values())
            if franchise > 0 and (
                not row.total_units
                or (row.total_units_label or "").lower() in ("episodes", "parts", "")
            ):
                row.total_units = franchise
                row.total_units_label = row.total_units_label or "episodes"
    else:
        # Import season_totals from provider when present
        imported = parse_season_totals_map(resolved_raw.get("season_totals"))
        # jiten decks are often S1-only (e.g. Yowamushi Pedal 38) — fill franchise map
        if not imported and (ct or "").strip().lower() == "anime":
            from app.media.season_progress import known_franchise_season_totals

            imported = known_franchise_season_totals(
                series_key=key, title=row.title or title or ""
            )
        if imported:
            resolved_raw["season_totals"] = {
                str(k): v for k, v in sorted(imported.items())
            }
            franchise = sum(imported.values())
            if franchise > 0 and (
                not row.total_units
                or franchise > int(row.total_units or 0)
                or (row.total_units_label or "").lower() in ("episodes", "parts", "")
            ):
                # Prefer franchise length over a single-season deck total
                if franchise >= int(row.total_units or 0):
                    row.total_units = franchise
                    row.total_units_label = "episodes"
    row.raw_json = json.dumps(resolved_raw, ensure_ascii=False)[:50000]
    row.fetched_at = now
    row.updated_at = now
    db.commit()
    db.refresh(row)
    return row


def metadata_to_dict(row: MediaMetadata) -> dict[str, Any]:
    from app.media.season_progress import (
        season_totals_from_metadata,
        seasons_locked_from_metadata,
    )

    cover_local = None
    if row.cover_local_path:
        cover_local = f"/media-cache/{row.cover_local_path.replace(chr(92), '/')}"
    display = preferred_title_from_metadata(row) or row.title
    st = season_totals_from_metadata(row)
    return {
        "series_key": row.series_key,
        "content_type": row.content_type,
        "title": row.title,
        "display_title": display,
        "source": row.source,
        "external_id": row.external_id,
        "external_url": row.external_url,
        "cover_url": row.cover_url,
        "cover_local": cover_local,
        "total_units": row.total_units,
        "total_units_label": row.total_units_label,
        "total_characters": row.total_characters,
        "total_minutes": row.total_minutes,
        "fetched_at": row.fetched_at.isoformat() if row.fetched_at else None,
        "season_totals": {str(k): v for k, v in sorted(st.items())},
        "seasons_locked": seasons_locked_from_metadata(row),
    }
