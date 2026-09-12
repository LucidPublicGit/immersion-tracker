"""
Manual Progress metadata: paste provider URLs, set cover/totals by hand.

When auto lookup fails (or is wrong), users fill gaps so % complete and
covers work. Manual rows are sticky (source=manual) unless force re-fetch.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional
from urllib.parse import parse_qs, unquote, urlparse

import httpx
from sqlalchemy.orm import Session

from app.db.models import CatalogItem, LogEntry, MediaMetadata, utcnow
from app.media.metadata_cache import (
    USER_AGENT,
    ResolvedMedia,
    download_cover,
    get_cached,
    metadata_to_dict,
    prefer_web_title,
)

logger = logging.getLogger(__name__)

VALID_UNIT_LABELS = frozenset(
    {
        "episodes",
        "volumes",
        "chapters",
        "parts",
        "routes",
        "minutes",
        "characters",
        "hours",
        "pages",
    }
)

# Provider search pages (open-in-browser hints by content type)
PROVIDER_SEARCH_HINTS: dict[str, list[dict[str, str]]] = {
    "anime": [
        {"id": "anilist", "label": "AniList", "search": "https://anilist.co/search/anime?search={q}"},
        {"id": "mal", "label": "MyAnimeList", "search": "https://myanimelist.net/anime.php?q={q}"},
        {"id": "jiten", "label": "jiten.moe", "search": "https://jiten.moe/?q={q}"},
    ],
    "manga": [
        {"id": "anilist", "label": "AniList", "search": "https://anilist.co/search/manga?search={q}"},
        {"id": "mal", "label": "MyAnimeList", "search": "https://myanimelist.net/manga.php?q={q}"},
        {"id": "jiten", "label": "jiten.moe", "search": "https://jiten.moe/?q={q}"},
    ],
    "show": [
        {"id": "tvmaze", "label": "TVMaze", "search": "https://www.tvmaze.com/search?q={q}"},
        {"id": "tmdb", "label": "TMDB", "search": "https://www.themoviedb.org/search/tv?query={q}"},
        {"id": "wikipedia", "label": "Wikipedia", "search": "https://en.wikipedia.org/w/index.php?search={q}"},
    ],
    "movie": [
        {"id": "tmdb", "label": "TMDB", "search": "https://www.themoviedb.org/search/movie?query={q}"},
        {"id": "wikipedia", "label": "Wikipedia", "search": "https://en.wikipedia.org/w/index.php?search={q}"},
    ],
    "game": [
        {"id": "steam", "label": "Steam", "search": "https://store.steampowered.com/search/?term={q}"},
        {"id": "wikipedia", "label": "Wikipedia", "search": "https://en.wikipedia.org/w/index.php?search={q}"},
    ],
    "visual_novel": [
        {"id": "vndb", "label": "VNDB", "search": "https://vndb.org/v/all?q={q}"},
        {"id": "jiten", "label": "jiten.moe", "search": "https://jiten.moe/?q={q}"},
    ],
    "book": [
        {"id": "jiten", "label": "jiten.moe", "search": "https://jiten.moe/?q={q}"},
        {"id": "openlibrary", "label": "Open Library", "search": "https://openlibrary.org/search?q={q}"},
        {"id": "anilist", "label": "AniList (LN)", "search": "https://anilist.co/search/manga?search={q}"},
    ],
    "audiobook": [
        {"id": "jiten", "label": "jiten.moe", "search": "https://jiten.moe/?q={q}"},
        {"id": "anilist", "label": "AniList", "search": "https://anilist.co/search/manga?search={q}"},
        {"id": "openlibrary", "label": "Open Library", "search": "https://openlibrary.org/search?q={q}"},
    ],
    "podcast": [
        {"id": "wikipedia", "label": "Wikipedia", "search": "https://en.wikipedia.org/w/index.php?search={q}"},
    ],
}


def provider_hints_for(content_type: str, title: str = "") -> list[dict[str, str]]:
    ct = (content_type or "anime").strip().lower()
    if ct == "vn":
        ct = "visual_novel"
    hints = list(PROVIDER_SEARCH_HINTS.get(ct) or PROVIDER_SEARCH_HINTS["anime"])
    from urllib.parse import quote_plus

    q = quote_plus((title or "").strip() or " ")
    out = []
    for h in hints:
        out.append(
            {
                "id": h["id"],
                "label": h["label"],
                "url": h["search"].format(q=q),
            }
        )
    return out


def parse_media_url(url: str) -> Optional[dict[str, str]]:
    """
    Recognize a provider page URL.

    Returns {provider, media_kind, external_id, url} or None.
    """
    raw = (url or "").strip()
    if not raw:
        return None
    if not re.match(r"^https?://", raw, re.I):
        raw = "https://" + raw
    try:
        parsed = urlparse(raw)
    except Exception:  # noqa: BLE001
        return None
    host = (parsed.netloc or "").lower().removeprefix("www.")
    path = unquote(parsed.path or "")
    full = raw.split("#")[0].rstrip("/")

    # Direct image → cover-only
    if re.search(r"\.(jpe?g|png|webp|gif)(?:\?|$)", path, re.I) or host.endswith(
        ("imgur.com", "image.tmdb.org", "cdn.jiten.moe", "s4.anilist.co")
    ):
        if re.search(r"\.(jpe?g|png|webp|gif)(?:\?|$)", path, re.I) or "/file/" in path:
            return {
                "provider": "image",
                "media_kind": "cover",
                "external_id": re.sub(r"[^a-zA-Z0-9]+", "_", path)[-40:] or "img",
                "url": full,
            }

    # AniList
    m = re.search(r"anilist\.co/(anime|manga)/(\d+)", full, re.I)
    if m:
        return {
            "provider": "anilist",
            "media_kind": m.group(1).lower(),
            "external_id": m.group(2),
            "url": f"https://anilist.co/{m.group(1).lower()}/{m.group(2)}",
        }

    # MAL
    m = re.search(r"myanimelist\.net/(anime|manga)/(\d+)", full, re.I)
    if m:
        return {
            "provider": "mal",
            "media_kind": m.group(1).lower(),
            "external_id": m.group(2),
            "url": f"https://myanimelist.net/{m.group(1).lower()}/{m.group(2)}",
        }

    # jiten.moe
    m = re.search(r"jiten\.moe/(?:decks/media/|media-decks?/)?(\d+)", full, re.I)
    if m:
        return {
            "provider": "jiten",
            "media_kind": "deck",
            "external_id": m.group(1),
            "url": f"https://jiten.moe/decks/media/{m.group(1)}/detail",
        }

    # Steam
    m = re.search(r"store\.steampowered\.com/app/(\d+)", full, re.I)
    if m:
        return {
            "provider": "steam",
            "media_kind": "game",
            "external_id": m.group(1),
            "url": f"https://store.steampowered.com/app/{m.group(1)}/",
        }

    # VNDB
    m = re.search(r"vndb\.org/(v\d+)", full, re.I)
    if m:
        return {
            "provider": "vndb",
            "media_kind": "vn",
            "external_id": m.group(1).lower(),
            "url": f"https://vndb.org/{m.group(1).lower()}",
        }

    # TMDB
    m = re.search(r"themoviedb\.org/(tv|movie)/(\d+)", full, re.I)
    if m:
        return {
            "provider": "tmdb",
            "media_kind": m.group(1).lower(),
            "external_id": m.group(2),
            "url": f"https://www.themoviedb.org/{m.group(1).lower()}/{m.group(2)}",
        }

    # TVMaze
    m = re.search(r"tvmaze\.com/shows/(\d+)", full, re.I)
    if m:
        return {
            "provider": "tvmaze",
            "media_kind": "show",
            "external_id": m.group(1),
            "url": f"https://www.tvmaze.com/shows/{m.group(1)}",
        }

    # Open Library
    m = re.search(r"openlibrary\.org/(works|books)/(OL[^/?#]+)", full, re.I)
    if m:
        return {
            "provider": "openlibrary",
            "media_kind": m.group(1).lower(),
            "external_id": m.group(2),
            "url": f"https://openlibrary.org/{m.group(1).lower()}/{m.group(2)}",
        }

    # Wikipedia
    if "wikipedia.org" in host and "/wiki/" in path:
        title = path.split("/wiki/", 1)[-1]
        if title and title not in ("Main_Page",):
            return {
                "provider": "wikipedia",
                "media_kind": "page",
                "external_id": title,
                "url": f"https://en.wikipedia.org/wiki/{title}",
            }

    return None


def _client() -> httpx.Client:
    return httpx.Client(
        timeout=25.0,
        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
        follow_redirects=True,
    )


def resolve_from_user_url(
    url: str,
    content_type: str = "",
    *,
    client: Optional[httpx.Client] = None,
) -> Optional[ResolvedMedia]:
    """Fetch metadata from a recognized provider URL."""
    parsed = parse_media_url(url)
    if not parsed:
        return None
    provider = parsed["provider"]
    ext_id = parsed["external_id"]
    kind = parsed["media_kind"]
    page_url = parsed["url"]

    owns = client is None
    client = client or _client()
    try:
        if provider == "image":
            return ResolvedMedia(
                source="manual",
                external_id=ext_id,
                external_url=page_url,
                title="",
                cover_url=page_url,
                total_units=None,
                total_units_label=None,
                total_characters=None,
                total_minutes=None,
                raw={"import_url": page_url, "provider": "image"},
            )
        if provider == "anilist":
            return _fetch_anilist_id(client, ext_id, kind)
        if provider == "mal":
            return _fetch_jikan_id(client, ext_id, kind)
        if provider == "jiten":
            return _fetch_jiten_id(client, ext_id)
        if provider == "steam":
            return _fetch_steam_id(client, ext_id)
        if provider == "vndb":
            return _fetch_vndb_id(client, ext_id)
        if provider == "tvmaze":
            return _fetch_tvmaze_id(client, ext_id)
        if provider == "tmdb":
            return _fetch_tmdb_id(client, ext_id, kind)
        if provider == "openlibrary":
            return _fetch_openlibrary_id(client, ext_id, kind)
        if provider == "wikipedia":
            return _fetch_wikipedia_id(client, ext_id)
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("resolve_from_user_url failed %s: %s", url, type(exc).__name__)
        return None
    finally:
        if owns:
            client.close()


def _fetch_anilist_id(
    client: httpx.Client, media_id: str, kind: str
) -> Optional[ResolvedMedia]:
    media_type = "MANGA" if kind == "manga" else "ANIME"
    query = """
    query ($id: Int, $type: MediaType) {
      Media(id: $id, type: $type) {
        id idMal episodes chapters volumes siteUrl
        title { romaji english native }
        coverImage { large extraLarge }
      }
    }
    """
    r = client.post(
        "https://graphql.anilist.co",
        json={
            "query": query,
            "variables": {"id": int(media_id), "type": media_type},
        },
    )
    r.raise_for_status()
    media = ((r.json() or {}).get("data") or {}).get("Media")
    if not media:
        return None
    t = media.get("title") or {}
    native, romaji, english = t.get("native"), t.get("romaji"), t.get("english")
    display = prefer_web_title(
        native=native, romaji=romaji, english=english, fallback=str(media_id)
    )
    cover = (media.get("coverImage") or {}).get("extraLarge") or (
        media.get("coverImage") or {}
    ).get("large")
    if media_type == "ANIME":
        units, label = media.get("episodes"), "episodes"
    elif media.get("volumes"):
        units, label = media.get("volumes"), "volumes"
    else:
        units, label = media.get("chapters"), "chapters"
    try:
        units_i = int(units) if units is not None else None
    except (TypeError, ValueError):
        units_i = None
    return ResolvedMedia(
        source="anilist",
        external_id=str(media.get("id")),
        external_url=media.get("siteUrl") or f"https://anilist.co/{kind}/{media_id}",
        title=display,
        cover_url=str(cover) if cover else None,
        total_units=units_i,
        total_units_label=label if units_i else None,
        total_characters=None,
        total_minutes=None,
        title_native=native,
        title_romaji=romaji,
        title_english=english,
        raw={"anilist": media, "import": True},
    )


def _fetch_jikan_id(
    client: httpx.Client, mal_id: str, kind: str
) -> Optional[ResolvedMedia]:
    path = "manga" if kind == "manga" else "anime"
    r = client.get(f"https://api.jikan.moe/v4/{path}/{mal_id}")
    r.raise_for_status()
    item = (r.json() or {}).get("data") or {}
    if not item:
        return None
    images = (item.get("images") or {}).get("jpg") or {}
    cover = (
        images.get("large_image_url")
        or images.get("image_url")
        or images.get("small_image_url")
    )
    if path == "manga":
        units = item.get("volumes") or item.get("chapters")
        label = "volumes" if item.get("volumes") else "chapters"
    else:
        units = item.get("episodes")
        label = "episodes"
    try:
        units_i = int(units) if units is not None else None
    except (TypeError, ValueError):
        units_i = None
    native = item.get("title_japanese")
    romaji = item.get("title")
    english = item.get("title_english")
    display = prefer_web_title(
        native=native, romaji=romaji, english=english, fallback=str(mal_id)
    )
    return ResolvedMedia(
        source="mal",
        external_id=str(mal_id),
        external_url=f"https://myanimelist.net/{path}/{mal_id}",
        title=display,
        cover_url=str(cover) if cover else None,
        total_units=units_i,
        total_units_label=label if units_i else None,
        total_characters=None,
        total_minutes=None,
        title_native=native,
        title_romaji=romaji,
        title_english=english,
        raw={"jikan": item, "import": True},
    )


def _fetch_jiten_id(client: httpx.Client, deck_id: str) -> Optional[ResolvedMedia]:
    from app.media.metadata_cache import (
        _speech_ms_to_minutes,
        _units_label_for_jiten,
        fetch_jiten_detail,
    )

    detail = fetch_jiten_detail(int(deck_id), client=client)
    if not detail:
        return None
    main = ((detail or {}).get("data") or {}).get("mainDeck") or {}
    if not main:
        return None
    mt = int(main.get("mediaType") or 0)
    children = main.get("childrenDeckCount")
    try:
        units_i = int(children) if children is not None else None
    except (TypeError, ValueError):
        units_i = None
    total_items = detail.get("totalItems")
    try:
        if total_items is not None:
            units_i = int(total_items) or units_i
    except (TypeError, ValueError):
        pass
    if mt == 3 and not units_i:
        units_i = 1
    label = _units_label_for_jiten(mt) if mt else "parts"
    chars = main.get("characterCount")
    try:
        chars_i = int(chars) if chars is not None else None
    except (TypeError, ValueError):
        chars_i = None
    minutes = _speech_ms_to_minutes(main.get("speechDuration"))
    cover = main.get("coverName")
    if cover and not str(cover).startswith("http"):
        if str(cover) == "nocover.jpg":
            cover = None
        else:
            cover = f"https://cdn.jiten.moe/{deck_id}/cover.jpg"
    native = main.get("originalTitle")
    romaji = main.get("romajiTitle")
    english = main.get("englishTitle")
    display = prefer_web_title(
        native=native, romaji=romaji, english=english, fallback=str(deck_id)
    )
    return ResolvedMedia(
        source="jiten",
        external_id=str(deck_id),
        external_url=f"https://jiten.moe/decks/media/{deck_id}/detail",
        title=display,
        cover_url=str(cover) if cover else None,
        total_units=units_i,
        total_units_label=label if units_i else None,
        total_characters=chars_i,
        total_minutes=minutes,
        title_native=native,
        title_romaji=romaji,
        title_english=english,
        raw={"jiten": main, "import": True},
    )


def _fetch_steam_id(client: httpx.Client, app_id: str) -> Optional[ResolvedMedia]:
    r = client.get(
        "https://store.steampowered.com/api/appdetails",
        params={"appids": app_id, "l": "english"},
    )
    r.raise_for_status()
    payload = (r.json() or {}).get(str(app_id)) or {}
    if not payload.get("success"):
        return None
    detail = payload.get("data") or {}
    display = (detail.get("name") or app_id).strip()
    cover = (
        detail.get("header_image")
        or detail.get("capsule_image")
        or detail.get("capsule_imagev5")
    )
    return ResolvedMedia(
        source="steam",
        external_id=str(app_id),
        external_url=f"https://store.steampowered.com/app/{app_id}/",
        title=display,
        cover_url=str(cover) if cover else None,
        total_units=None,
        total_units_label=None,
        total_characters=None,
        total_minutes=None,
        title_english=display,
        raw={"steam_detail": detail, "import": True},
    )


def _fetch_vndb_id(client: httpx.Client, vid: str) -> Optional[ResolvedMedia]:
    r = client.post(
        "https://api.vndb.org/kana/vn",
        json={
            "filters": ["id", "=", vid],
            "fields": "title, alttitle, image.url, image.thumbnail, length_minutes",
            "results": 1,
        },
    )
    r.raise_for_status()
    results = (r.json() or {}).get("results") or []
    if not results:
        return None
    best = results[0]
    img = best.get("image") or {}
    cover = img.get("url") or img.get("thumbnail")
    minutes = best.get("length_minutes")
    try:
        minutes_i = int(minutes) if minutes is not None else None
    except (TypeError, ValueError):
        minutes_i = None
    display = (best.get("title") or vid).strip()
    return ResolvedMedia(
        source="vndb",
        external_id=vid,
        external_url=f"https://vndb.org/{vid}",
        title=display,
        cover_url=str(cover) if cover else None,
        total_units=None,
        total_units_label=None,
        total_characters=None,
        total_minutes=minutes_i,
        title_romaji=display,
        title_english=best.get("alttitle"),
        raw={"vndb": best, "import": True},
    )


def _fetch_tvmaze_id(client: httpx.Client, show_id: str) -> Optional[ResolvedMedia]:
    r = client.get(f"https://api.tvmaze.com/shows/{show_id}", params={"embed": "episodes"})
    r.raise_for_status()
    data = r.json() or {}
    img = data.get("image") or {}
    cover = img.get("original") or img.get("medium")
    embedded = (data.get("_embedded") or {}).get("episodes") or []
    units_i = len(embedded) if embedded else None
    if units_i is None:
        try:
            er = client.get(f"https://api.tvmaze.com/shows/{show_id}/episodes")
            if er.is_success:
                units_i = len(er.json() or [])
        except Exception:  # noqa: BLE001
            pass
    display = (data.get("name") or show_id).strip()
    from app.media.season_progress import season_totals_from_tvmaze_episodes

    season_totals = season_totals_from_tvmaze_episodes(embedded)
    return ResolvedMedia(
        source="tvmaze",
        external_id=str(show_id),
        external_url=data.get("url") or f"https://www.tvmaze.com/shows/{show_id}",
        title=display,
        cover_url=str(cover) if cover else None,
        total_units=units_i,
        total_units_label="episodes" if units_i else None,
        total_characters=None,
        total_minutes=None,
        title_english=display,
        raw={
            "tvmaze": data,
            "import": True,
            "season_totals": {str(k): v for k, v in sorted(season_totals.items())},
        },
    )


def _fetch_tmdb_id(
    client: httpx.Client, tmdb_id: str, kind: str
) -> Optional[ResolvedMedia]:
    try:
        from app.core.config import get_settings

        api_key = (get_settings().yaml_config.metadata.tmdb_api_key or "").strip()
    except Exception:  # noqa: BLE001
        api_key = ""
    if not api_key:
        return None
    path = "tv" if kind == "tv" else "movie"
    r = client.get(
        f"https://api.themoviedb.org/3/{path}/{tmdb_id}",
        params={"api_key": api_key, "language": "en-US"},
    )
    r.raise_for_status()
    best = r.json() or {}
    poster = best.get("poster_path")
    cover = f"https://image.tmdb.org/t/p/w500{poster}" if poster else None
    if path == "tv":
        units = best.get("number_of_episodes")
        label = "episodes"
        display = best.get("name") or best.get("original_name") or tmdb_id
    else:
        units = 1
        label = "episodes"
        display = best.get("title") or best.get("original_title") or tmdb_id
    try:
        units_i = int(units) if units is not None else None
    except (TypeError, ValueError):
        units_i = None
    return ResolvedMedia(
        source="tmdb",
        external_id=str(tmdb_id),
        external_url=f"https://www.themoviedb.org/{path}/{tmdb_id}",
        title=str(display).strip(),
        cover_url=cover,
        total_units=units_i,
        total_units_label=label if units_i else None,
        total_characters=None,
        total_minutes=None,
        title_english=str(display).strip(),
        raw={"tmdb": best, "import": True},
    )


def _fetch_openlibrary_id(
    client: httpx.Client, work_id: str, kind: str
) -> Optional[ResolvedMedia]:
    path = f"/{kind}/{work_id}.json" if not work_id.startswith("/") else f"{work_id}.json"
    if not path.startswith("/"):
        path = f"/{kind}/{work_id}.json"
    r = client.get(f"https://openlibrary.org{path}")
    r.raise_for_status()
    data = r.json() or {}
    title = data.get("title") or work_id
    covers = data.get("covers") or []
    cover = (
        f"https://covers.openlibrary.org/b/id/{covers[0]}-L.jpg" if covers else None
    )
    return ResolvedMedia(
        source="openlibrary",
        external_id=work_id,
        external_url=f"https://openlibrary.org/{kind}/{work_id}",
        title=str(title).strip(),
        cover_url=cover,
        total_units=None,
        total_units_label=None,
        total_characters=None,
        total_minutes=None,
        title_english=str(title).strip(),
        raw={"openlibrary": data, "import": True},
    )


def _fetch_wikipedia_id(client: httpx.Client, title: str) -> Optional[ResolvedMedia]:
    from urllib.parse import quote

    path = quote(title.replace(" ", "_"), safe="()_,:'%")
    r = client.get(f"https://en.wikipedia.org/api/rest_v1/page/summary/{path}")
    if r.status_code == 404:
        return None
    r.raise_for_status()
    data = r.json() or {}
    if data.get("type") == "disambiguation":
        return None
    wtitle = data.get("title") or title
    thumb = (data.get("originalimage") or {}).get("source") or (
        data.get("thumbnail") or {}
    ).get("source")
    return ResolvedMedia(
        source="wikipedia",
        external_id=str(data.get("pageid") or wtitle),
        external_url=data.get("content_urls", {})
        .get("desktop", {})
        .get("page")
        or f"https://en.wikipedia.org/wiki/{path}",
        title=str(wtitle),
        cover_url=str(thumb) if thumb else None,
        total_units=None,
        total_units_label=None,
        total_characters=None,
        total_minutes=None,
        title_english=str(wtitle),
        raw={"wikipedia": data, "import": True},
    )


def _coerce_int(val: Any) -> Optional[int]:
    if val is None or val == "":
        return None
    try:
        return int(float(val))
    except (TypeError, ValueError):
        return None


def apply_manual_metadata(
    db: Session,
    series_key: str,
    *,
    content_type: str = "",
    title: Optional[str] = None,
    import_url: Optional[str] = None,
    cover_url: Optional[str] = None,
    total_units: Optional[int] = None,
    total_units_label: Optional[str] = None,
    total_characters: Optional[int] = None,
    total_minutes: Optional[int] = None,
    external_url: Optional[str] = None,
    season_totals: Optional[Any] = None,
    # When True, blank strings clear fields; when False, None means leave alone
    replace_totals: bool = False,
) -> dict[str, Any]:
    """
    Apply user metadata for one work.

    If ``import_url`` is set, fetch provider page first; explicit fields then
    override the import. Marks source as provider (when imported) or ``manual``.
    """
    key = (series_key or "").strip()
    if not key:
        raise ValueError("series_key required")

    logs = (
        db.query(LogEntry)
        .filter(LogEntry.series_key == key)
        .order_by(LogEntry.id.desc())
        .limit(1)
        .all()
    )
    cat = (
        db.query(CatalogItem).filter(CatalogItem.series_key == key).one_or_none()
    )
    ct = (
        (content_type or "").strip().lower()
        or (cat.content_type if cat else "")
        or (logs[0].content_type if logs else "anime")
        or "anime"
    )
    display_title = (
        (title or "").strip()
        or (cat.display_title if cat else "")
        or (logs[0].title if logs else key)
    )

    resolved: Optional[ResolvedMedia] = None
    parse_info = None
    if (import_url or "").strip():
        parse_info = parse_media_url(import_url)
        if not parse_info:
            raise ValueError(
                "Unrecognized URL. Paste a link from AniList, MAL, jiten, Steam, "
                "VNDB, TVMaze, TMDB, Open Library, Wikipedia, or a direct image."
            )
        resolved = resolve_from_user_url(import_url, ct)
        if resolved is None:
            raise ValueError(
                f"Could not load metadata from that {parse_info.get('provider')} URL."
            )

    row = get_cached(db, key)
    if not row:
        row = MediaMetadata(series_key=key)
        db.add(row)

    # Start from import, then layer manual overrides
    if resolved:
        if resolved.title:
            row.title = resolved.title
        row.source = resolved.source if resolved.source != "manual" else "manual"
        row.external_id = resolved.external_id
        row.external_url = resolved.external_url
        if resolved.cover_url:
            row.cover_url = resolved.cover_url
        if resolved.total_units is not None:
            row.total_units = resolved.total_units
            row.total_units_label = resolved.total_units_label
        if resolved.total_characters is not None:
            row.total_characters = resolved.total_characters
        if resolved.total_minutes is not None:
            row.total_minutes = resolved.total_minutes
        row.raw_json = json.dumps(resolved.raw or {}, ensure_ascii=False)[:50000]
    else:
        # Pure manual edit
        if (row.source or "").strip().lower() in ("", "none"):
            row.source = "manual"
        elif replace_totals or cover_url or total_units is not None:
            # User is correcting auto data — sticky as manual going forward
            row.source = "manual"

    if (title or "").strip():
        row.title = title.strip()
        if cat and cat.display_title != title.strip():
            cat.display_title = title.strip()
            cat.updated_at = utcnow()
        for log in (
            db.query(LogEntry).filter(LogEntry.series_key == key).limit(50).all()
        ):
            # Only rewrite log titles if they were the old display or empty
            pass  # leave logs; catalog display is enough for shelf

    if (external_url or "").strip():
        row.external_url = external_url.strip()

    cov = (cover_url or "").strip()
    if cov:
        row.cover_url = cov
        local = download_cover(
            cov,
            source=row.source or "manual",
            external_id=row.external_id or key.replace(":", "_")[:40],
        )
        if local:
            row.cover_local_path = local
    elif resolved and resolved.cover_url:
        local = download_cover(
            resolved.cover_url,
            source=resolved.source or "manual",
            external_id=resolved.external_id or key.replace(":", "_")[:40],
        )
        if local:
            row.cover_local_path = local

    tu = _coerce_int(total_units)
    if tu is not None:
        row.total_units = tu
        label = (total_units_label or row.total_units_label or "").strip().lower()
        if label in VALID_UNIT_LABELS:
            row.total_units_label = label
        elif not row.total_units_label:
            # Infer default label from content type
            row.total_units_label = {
                "manga": "volumes",
                "book": "volumes",
                "audiobook": "episodes",
                "game": "parts",
                "visual_novel": "routes",
                "show": "episodes",
                "movie": "episodes",
            }.get(ct, "episodes")
    elif replace_totals and total_units is None and total_units_label is not None:
        pass
    if total_units_label is not None and str(total_units_label).strip():
        label = str(total_units_label).strip().lower()
        if label in VALID_UNIT_LABELS:
            row.total_units_label = label

    tc = _coerce_int(total_characters)
    if tc is not None:
        row.total_characters = tc
    tm = _coerce_int(total_minutes)
    if tm is not None:
        row.total_minutes = tm

    row.content_type = ct
    if not row.title:
        row.title = display_title
    now = utcnow()
    row.fetched_at = now
    row.updated_at = now
    # Preserve import + manual flags in raw
    try:
        raw = json.loads(row.raw_json) if row.raw_json else {}
    except Exception:  # noqa: BLE001
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    raw["manual"] = True
    if import_url:
        raw["import_url"] = import_url.strip()

    # Season episode counts (user or TVMaze import)
    from app.media.season_progress import (
        merge_season_totals_into_raw,
        parse_season_totals_map,
        season_totals_from_tvmaze_episodes,
    )

    st_map = parse_season_totals_map(season_totals) if season_totals is not None else {}
    if season_totals is not None and not st_map and str(season_totals).strip() in (
        "",
        "{}",
        "[]",
    ):
        # Explicit clear
        row.raw_json = merge_season_totals_into_raw(
            json.dumps(raw), {}, locked=False
        )
        try:
            raw = json.loads(row.raw_json)
        except Exception:  # noqa: BLE001
            pass
    elif st_map:
        # Prefer franchise sum as total_units when episodes
        franchise = sum(st_map.values())
        if franchise > 0 and (
            row.total_units is None
            or (row.total_units_label or "").lower() in ("", "episodes", "parts")
        ):
            row.total_units = franchise
            row.total_units_label = row.total_units_label or "episodes"
        row.raw_json = merge_season_totals_into_raw(
            json.dumps(raw), st_map, locked=True
        )
        try:
            raw = json.loads(row.raw_json)
        except Exception:  # noqa: BLE001
            pass
    elif resolved and isinstance(resolved.raw, dict):
        # Pull season breakdown from provider if user didn't set one
        imported_st = parse_season_totals_map(resolved.raw.get("season_totals"))
        if not imported_st and resolved.source == "tvmaze":
            eps = (
                ((resolved.raw.get("tvmaze") or {}).get("_embedded") or {}).get(
                    "episodes"
                )
                or []
            )
            imported_st = season_totals_from_tvmaze_episodes(eps)
        if imported_st:
            franchise = sum(imported_st.values())
            if franchise > 0 and not row.total_units:
                row.total_units = franchise
                row.total_units_label = "episodes"
            row.raw_json = merge_season_totals_into_raw(
                json.dumps({**raw, **(resolved.raw or {})}),
                imported_st,
                locked=False,
            )
            try:
                raw = json.loads(row.raw_json)
            except Exception:  # noqa: BLE001
                pass
        else:
            row.raw_json = json.dumps(raw, ensure_ascii=False)[:50000]
    else:
        row.raw_json = json.dumps(raw, ensure_ascii=False)[:50000]

    db.commit()
    db.refresh(row)
    return {
        "ok": True,
        "action": "set_metadata",
        "series_key": key,
        "imported_from": (parse_info or {}).get("provider") if parse_info else None,
        "item": metadata_to_dict(row),
    }


def meta_issues_for_item(
    *,
    has_cover: bool,
    has_metadata: bool,
    percent_complete: Optional[float],
    total_units: Optional[int],
    total_characters: Optional[int],
    total_minutes: Optional[int],
    primary_amount: Optional[float],
    log_count: int,
    source: str = "",
) -> list[str]:
    """Machine-readable reasons this work needs user help."""
    issues: list[str] = []
    if not has_cover:
        issues.append("no_cover")
    has_length = bool(
        (total_units and total_units > 0)
        or (total_characters and total_characters > 0)
        or (total_minutes and total_minutes > 0)
    )
    if not has_length and (log_count > 0 or (primary_amount or 0) > 0):
        issues.append("no_length")
    if not has_metadata or (source or "").lower() in ("", "none"):
        if "no_cover" in issues or "no_length" in issues:
            issues.append("lookup_failed")
    if percent_complete is None and has_length is False and log_count > 0:
        if "no_length" not in issues:
            issues.append("no_length")
    return issues


def needs_user_input(issues: list[str]) -> bool:
    return bool(issues)
