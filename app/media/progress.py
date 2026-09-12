"""Aggregate immersion progress per piece of content (series/work)."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.db.models import CatalogItem, LogEntry, MediaMetadata
from app.media.catalog_resolve import normalize_title
from app.media.metadata_cache import (
    metadata_to_dict,
    preferred_title_from_metadata,
    strip_contest_noise,
)
from app.media.title_format import (
    format_episode_tag,
    format_progress_position,
    suggest_series_key,
)


VALID_PROGRESS_STATUSES = frozenset({"active", "finished", "dropped", "ignored"})


@dataclass
class _Agg:
    series_key: str
    title: str
    content_type: str
    progress_status: str = "active"
    progress_status_locked: bool = False
    log_count: int = 0
    total_amount_by_unit: dict[str, float] = field(default_factory=dict)
    max_season: Optional[int] = None
    max_episode: Optional[int] = None
    # for episode progress: highest (season, episode) pair
    progress_season: Optional[int] = None
    progress_episode: Optional[int] = None
    # distinct episode keys SxxExx seen
    episode_keys: set[str] = field(default_factory=set)
    # (season, episode, minutes) per log — for season breakdown
    log_season_rows: list[tuple[Optional[int], Optional[int], float]] = field(
        default_factory=list
    )
    # Seasons marked complete by bulk Tadoku logs ("Arcane S1+S2")
    bulk_complete_seasons: set[int] = field(default_factory=set)
    first_logged: Optional[datetime] = None
    last_logged: Optional[datetime] = None
    sources: set[str] = field(default_factory=set)
    score_sum: float = 0.0
    # True when catalog has a non-empty display_title (user/catalog authority)
    has_catalog_title: bool = False
    # For Japanese-only Progress filtering
    languages: set[str] = field(default_factory=set)
    tadoku_modes: set[str] = field(default_factory=set)


def _group_key(
    log: LogEntry,
    redirects: Optional[dict[str, str]] = None,
) -> str:
    """
    Prefer catalog-canonical series_key when aliases / old auto-keys redirect there
    (e.g. yanki-neko → yanineko after a catalog relink).

    Always collapse volume/episode fragment keys to the work key
    (``anime:one-piece-19-…`` → ``anime:one-piece``).
    """
    from app.media.work_identity import (
        canonical_series_key,
        needs_key_rewrite,
    )

    redirects = redirects or {}
    raw = (log.series_key or "").strip()
    if raw and raw in redirects:
        raw = redirects[raw]
    ct = (log.content_type or "other").strip().lower()
    title = (log.title or "").strip() or raw or "Unknown"
    # Keep clean intentional keys (catalog / Plex); rewrite fragments + aliases
    if (
        raw
        and not needs_key_rewrite(raw, title)
        and not raw.startswith("gsm:")
    ):
        return redirects.get(raw, raw)
    canon = canonical_series_key(
        ct,
        title,
        existing_key=raw,
        source=(log.source or ""),
        prefer_existing=False,
    )
    return redirects.get(canon, canon)


def _better_progress(
    a_s: Optional[int],
    a_e: Optional[int],
    b_s: Optional[int],
    b_e: Optional[int],
) -> tuple[Optional[int], Optional[int]]:
    """Return the later of two season/episode positions."""
    a = (a_s is not None, a_s or 0, a_e is not None, a_e or 0)
    b = (b_s is not None, b_s or 0, b_e is not None, b_e or 0)
    # Prefer entries that have episode info
    if a[0] or a[2]:
        if not (b[0] or b[2]):
            return a_s, a_e
        if (a[1], a[3]) >= (b[1], b[3]):
            return a_s, a_e
        return b_s, b_e
    if b[0] or b[2]:
        return b_s, b_e
    return a_s, a_e


def _normalize_status(raw: Optional[str]) -> str:
    st = (raw or "active").strip().lower()
    if st in ("unfinished", "watching", "current", "in_progress", "in-progress"):
        return "active"
    if st in ("ignore", "hidden", "hide"):
        return "ignored"
    if st in VALID_PROGRESS_STATUSES:
        return st
    return "active"


def _primary_amount_unit(amounts: dict[str, float]) -> tuple[Optional[float], Optional[str]]:
    for u in (
        "minutes",
        "minutes_high_density",
        "characters",
        "pages",
        "two_column_pages",
        "comic_pages",
        "sentences",
    ):
        if u in amounts and amounts[u] > 0:
            return round(amounts[u], 2), u
    if amounts:
        u, v = next(iter(amounts.items()))
        return round(v, 2), u
    return None, None


def _jiten_media_type(meta: Optional[MediaMetadata]) -> Optional[int]:
    """jiten mediaType from cached raw_json (1=anime, 4=book, 9=manga, …)."""
    if meta is None:
        return None
    raw_txt = getattr(meta, "raw_json", None) or ""
    if not raw_txt:
        return None
    try:
        raw = json.loads(raw_txt)
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(raw, dict):
        return None
    for key in ("detail_main", "match"):
        block = raw.get(key)
        if isinstance(block, dict) and block.get("mediaType") is not None:
            try:
                return int(block["mediaType"])
            except (TypeError, ValueError):
                return None
    return None


def _meta_length_fits_content_type(
    meta: Optional[MediaMetadata],
    content_type: str,
) -> bool:
    """
    False when cached length clearly belongs to another medium.

    Classic bug: audiobook:mushoku-tensei attached to jiten anime deck
    (11 episodes / 148 min) while the user logged 886 audiobook minutes.
    """
    if meta is None:
        return True
    ct = (content_type or "").strip().lower()
    label = (meta.total_units_label or "").strip().lower()
    mt = _jiten_media_type(meta)
    if ct in ("book", "novel", "audiobook", "web_novel", "webnovel"):
        if mt in (1, 2, 3):  # anime / drama / movie
            return False
        if label == "episodes":
            return False
    if ct in ("anime", "show", "movie", "drama"):
        if mt in (4, 5, 8, 9, 10):  # book / web / manga / audio
            return False
        if label in ("volumes", "chapters"):
            return False
    if ct == "manga" and mt in (1, 2, 3):
        return False
    return True


def _totals_from_meta(
    meta: Optional[MediaMetadata],
    *,
    content_type: str = "",
) -> tuple[Optional[int], Optional[str]]:
    if not meta:
        return None, None
    if not _meta_length_fits_content_type(meta, content_type):
        return None, None
    ct = (content_type or "").strip().lower()
    # Audiobooks: prefer runtime when present; never lead with anime-style episodes
    if ct == "audiobook":
        if meta.total_minutes is not None and meta.total_minutes > 0:
            return meta.total_minutes, "minutes"
        if meta.total_units is not None and (meta.total_units_label or "").lower() in (
            "volumes",
            "parts",
            "chapters",
            "",
        ):
            return meta.total_units, meta.total_units_label or "volumes"
        if meta.total_characters is not None:
            return meta.total_characters, "characters"
        return None, None
    if meta.total_units is not None:
        return meta.total_units, meta.total_units_label or "parts"
    if meta.total_characters is not None:
        return meta.total_characters, "characters"
    if meta.total_minutes is not None:
        return meta.total_minutes, "minutes"
    return None, None


def _pick_metadata_for_work(
    meta_by_key: dict[str, MediaMetadata],
    series_key: str,
    *,
    content_type: str = "",
    title: str = "",
) -> Optional[MediaMetadata]:
    """
    Resolve cached metadata for a work, including prefix/alias fallbacks.

    Example: movie:one-piece-film-red may still have a good jiten hit under
    anime:onepiecered while anime:one-piece-film-red wrongly points at the
    1088-ep TV series — prefer the film deck for movie works.
    """
    key = (series_key or "").strip()
    if not key:
        return None
    ct = (content_type or "").strip().lower()
    candidates: list[str] = [key]
    if ":" in key:
        _prefix, slug = key.split(":", 1)
        for pref in ("movie", "anime", "show"):
            candidates.append(f"{pref}:{slug}")
        slug_l = slug.lower()
        if (
            "film-red" in slug_l
            or slug_l in ("onepiecered", "one-piece-red")
            or "film" in slug_l
        ):
            candidates.extend(
                [
                    "movie:one-piece-film-red",
                    "anime:one-piece-film-red",
                    "anime:onepiecered",
                    "movie:onepiecered",
                ]
            )
    # Title-based film red fallback
    blob = f"{title} {key}".lower()
    if re.search(r"one\s*piece.*(film\s*)?red|film\s*red", blob):
        candidates.extend(
            [
                "movie:one-piece-film-red",
                "anime:onepiecered",
                "anime:one-piece-film-red",
            ]
        )

    seen: set[str] = set()
    metas: list[MediaMetadata] = []
    for c in candidates:
        if c in seen:
            continue
        seen.add(c)
        m = meta_by_key.get(c)
        if m is not None:
            metas.append(m)
    if not metas:
        return None
    if ct == "movie" or key.startswith("movie:"):
        def _movie_score(m: MediaMetadata) -> tuple:
            units = int(m.total_units or 0)
            mins = int(m.total_minutes or 0)
            title_l = (m.title or "").lower()
            looks_film = bool(
                re.search(r"film|red|movie|映画", title_l)
            )
            # Prefer film-shaped rows; heavily penalize long TV series
            return (
                0 if looks_film else 1,
                0 if units <= 2 else 1,
                0 if 20 <= mins <= 300 else 1,
                units if units else 9999,
                abs(mins - 115) if mins else 9999,
            )

        return min(metas, key=_movie_score)
    return metas[0]


def _completion_percent(
    a: _Agg,
    meta: Optional[MediaMetadata],
    *,
    primary_amount: Optional[float] = None,
    primary_unit: Optional[str] = None,
    season_info: Optional[dict[str, Any]] = None,
) -> Optional[float]:
    """
    0–100 when we can compare logged progress to known total length.

    Prefer per-season totals when present (franchise progress).
    Flat episode totals: max-episode fill only for single-season / unscoped;
    multi-season without season_totals uses distinct SxxExx keys only
    (flat totals from AniList are often S1-scoped and would mis-report).
    """
    # Franchise % when user/provider set season episode counts
    if season_info and season_info.get("franchise_percent") is not None:
        return float(season_info["franchise_percent"])

    total_value, total_label = _totals_from_meta(
        meta, content_type=getattr(a, "content_type", "") or ""
    )
    if not total_value or total_value <= 0:
        return None

    episodes_logged = len(a.episode_keys)
    multi_season = bool(season_info and season_info.get("is_multi_season"))
    if not multi_season:
        multi_season = (a.progress_season is not None and a.progress_season > 1) or (
            a.max_season is not None and a.max_season > 1
        )

    # Discrete units (eps / volumes / …)
    if total_label in ("episodes", "volumes", "chapters", "parts", "routes"):
        # Multi-season + only a flat total → distinct keys only (never max ep)
        if multi_season:
            if episodes_logged <= 0:
                return None
            return min(100.0, round(100.0 * episodes_logged / total_value, 1))

        pos = episodes_logged
        if a.progress_episode is not None and a.progress_season in (None, 1):
            filled = max(pos, a.progress_episode)
            # Single high episode number must not alone report 100%
            if (
                filled >= total_value
                and episodes_logged < total_value
                and episodes_logged <= 1
            ):
                pos = episodes_logged
            else:
                pos = filled
        if pos <= 0:
            return None
        return min(100.0, round(100.0 * pos / total_value, 1))

    # Continuous totals (characters / minutes) vs logged amounts
    if total_label == "characters":
        amt = primary_amount
        if primary_unit != "characters":
            amt = a.total_amount_by_unit.get("characters")
        if amt and amt > 0:
            return min(100.0, round(100.0 * float(amt) / total_value, 1))
    if total_label == "minutes":
        mins = a.total_amount_by_unit.get("minutes", 0.0) + a.total_amount_by_unit.get(
            "minutes_high_density", 0.0
        )
        if mins > 0:
            return min(100.0, round(100.0 * float(mins) / total_value, 1))
    return None


def _get_or_create_catalog_status_only(
    db: Session,
    series_key: str,
    title: str,
    content_type: str,
) -> CatalogItem:
    """
    Load catalog for status updates only.

    Never overwrites display_title or content_type on existing rows
    (unlike progress_fixup._ensure_catalog_for, which is for identity fixups).
    """
    from app.ingest.service import ensure_catalog

    item = (
        db.query(CatalogItem)
        .filter(CatalogItem.series_key == series_key)
        .one_or_none()
    )
    if item:
        return item
    return ensure_catalog(db, series_key, title, content_type)


def _auto_mark_finished(
    db: Session,
    aggs: dict[str, _Agg],
    meta_by_key: dict[str, MediaMetadata],
) -> int:
    """
    Promote unlocked active → finished when completion is 100%.

    Never overrides dropped, finished, ignored, or progress_status_locked rows.
    Only writes progress_status (and updated_at) — never title/type.
    Returns how many rows were updated.
    """
    from app.db.models import utcnow

    from app.media.season_progress import (
        build_season_rows,
        known_franchise_season_totals,
        season_totals_from_metadata,
        seasons_locked_from_metadata,
    )

    to_finish: list[str] = []
    to_unfinish: list[str] = []
    for key, a in aggs.items():
        if a.progress_status_locked:
            continue
        # Ignored works stay off the shelf until the user un-ignores them
        if a.progress_status == "ignored":
            continue
        meta = meta_by_key.get(key)
        primary_amount, primary_unit = _primary_amount_unit(a.total_amount_by_unit)
        total_value, total_label = _totals_from_meta(meta, content_type=a.content_type)
        st = season_totals_from_metadata(meta)
        if not seasons_locked_from_metadata(meta):
            known_st = known_franchise_season_totals(
                series_key=key, title=a.title
            )
            if known_st and (not st or len(st) < len(known_st)):
                st = known_st
                total_value = sum(st.values())
                total_label = total_label or "episodes"
        is_movie = a.content_type == "movie" or key.startswith("movie:")
        season_info = build_season_rows(
            episode_tags=set() if is_movie else a.episode_keys,
            log_seasons=[] if is_movie else a.log_season_rows,
            season_totals={} if is_movie else st,
            total_units=None if is_movie else total_value,
            total_units_label=total_label,
        )
        pct = _completion_percent(
            a,
            meta,
            primary_amount=primary_amount,
            primary_unit=primary_unit,
            season_info=season_info,
        )
        if is_movie and pct is None:
            mins = a.total_amount_by_unit.get("minutes", 0.0) + a.total_amount_by_unit.get(
                "minutes_high_density", 0.0
            )
            if mins >= 40 or a.log_count > 0:
                pct = 100.0
        if a.progress_status == "active" and pct is not None and pct >= 100.0:
            to_finish.append(key)
        elif (
            a.progress_status == "finished"
            and pct is not None
            and pct < 99.5
            and (season_info.get("is_multi_season") or (st and len(st) > 1))
        ):
            to_unfinish.append(key)

    if not to_finish and not to_unfinish:
        return 0

    updated = 0
    for key in to_finish:
        a = aggs[key]
        item = _get_or_create_catalog_status_only(db, key, a.title, a.content_type)
        if bool(getattr(item, "progress_status_locked", False)):
            continue
        cur = _normalize_status(getattr(item, "progress_status", None))
        if cur == "active":
            item.progress_status = "finished"
            item.updated_at = utcnow()
            a.progress_status = "finished"
            updated += 1
    for key in to_unfinish:
        a = aggs[key]
        item = _get_or_create_catalog_status_only(db, key, a.title, a.content_type)
        if bool(getattr(item, "progress_status_locked", False)):
            continue
        cur = _normalize_status(getattr(item, "progress_status", None))
        if cur == "finished":
            item.progress_status = "active"
            item.updated_at = utcnow()
            a.progress_status = "active"
            updated += 1
    if updated:
        db.commit()
        try:
            from app.sheets.state import mark_sheets_dirty

            mark_sheets_dirty(db)
        except Exception:  # noqa: BLE001
            pass
    return updated


def aggregate_progress(
    db: Session,
    *,
    content_type: Optional[str] = None,
    q: Optional[str] = None,
    status: Optional[str] = None,
    auto_finish: bool = False,
) -> list[dict[str, Any]]:
    """
    Build per-work progress rows from local log_entries + cached metadata.

    status filter: active | finished | dropped | ignored | unfinished (=active)

    auto_finish: when True, promote unlocked active@100% → finished and persist.
    Default False so GET /api/progress is a pure read.
    """
    from app.media.progress_fixup import build_catalog_key_redirects

    query = db.query(LogEntry)
    if content_type:
        query = query.filter(LogEntry.content_type == content_type.strip().lower())
    logs = query.all()
    redirects = build_catalog_key_redirects(db)
    status_filter = None
    if status and status.strip().lower() not in ("", "all"):
        status_filter = _normalize_status(status)
        if status.strip().lower() == "unfinished":
            status_filter = "active"

    aggs: dict[str, _Agg] = {}
    for log in logs:
        key = _group_key(log, redirects)
        if key not in aggs:
            aggs[key] = _Agg(
                series_key=key,
                title=(log.title or key).strip() or key,
                content_type=(log.content_type or "other").strip().lower(),
            )
        a = aggs[key]
        a.log_count += 1
        a.sources.add(log.source or "unknown")
        a.score_sum += float(log.tadoku_score_estimate or 0.0)
        lang = (getattr(log, "language", None) or "ja").strip().lower()
        if lang:
            a.languages.add(lang)
        mode = (getattr(log, "tadoku_mode", None) or "").strip().lower()
        if mode:
            a.tadoku_modes.add(mode)
        unit = (log.unit or "units").strip().lower()
        a.total_amount_by_unit[unit] = a.total_amount_by_unit.get(unit, 0.0) + float(
            log.amount or 0.0
        )
        if log.title and log.title.strip():
            raw = log.title.strip()
            cleaned = strip_contest_noise(raw) or raw
            if a.title in (key, "", "Unknown"):
                a.title = cleaned
            else:
                # Prefer the cleaner (noise-stripped) form when they refer to the same work
                cur = strip_contest_noise(a.title) or a.title
                if normalize_title(cleaned) == normalize_title(cur):
                    # same base — keep the shorter clean form
                    if len(cleaned) < len(a.title):
                        a.title = cleaned
                elif len(cleaned) > len(cur) and strip_contest_noise(raw) == raw:
                    # longer only when the new title has no contest notes
                    a.title = cleaned

        if log.season is not None:
            a.max_season = (
                log.season
                if a.max_season is None
                else max(a.max_season, log.season)
            )
        if log.episode is not None:
            a.max_episode = (
                log.episode
                if a.max_episode is None
                else max(a.max_episode, log.episode)
            )
        a.progress_season, a.progress_episode = _better_progress(
            a.progress_season,
            a.progress_episode,
            log.season,
            log.episode,
        )
        tag = format_episode_tag(log.season, log.episode)
        if tag:
            a.episode_keys.add(tag)
        unit_l = (log.unit or "").strip().lower()
        mins = 0.0
        if unit_l in ("minutes", "minutes_high_density"):
            mins = float(log.amount or 0.0)

        # Bulk multi-season Tadoku logs: "Arcane S1+S2 (740min half)"
        # Credit those seasons even when only a bulk description was stored.
        bulk_seasons: list[int] = []
        try:
            from app.tadoku.pull import parse_season_range

            blob = f"{log.title or ''} {log.notes or ''}"
            bulk_seasons = parse_season_range(blob)
        except Exception:  # noqa: BLE001
            bulk_seasons = []
        if bulk_seasons:
            a.bulk_complete_seasons.update(bulk_seasons)
            share = (mins / len(bulk_seasons)) if mins else 0.0
            for sn in bulk_seasons:
                a.log_season_rows.append((sn, None, share))
                a.max_season = (
                    sn if a.max_season is None else max(a.max_season, sn)
                )
                a.progress_season, a.progress_episode = _better_progress(
                    a.progress_season,
                    a.progress_episode,
                    sn,
                    None,
                )
        # Keep concrete SxxExx rows; skip duplicate unscoped minute dump when bulk handled it
        if log.season is not None or log.episode is not None:
            a.log_season_rows.append(
                (log.season, log.episode, 0.0 if bulk_seasons else mins)
            )
        elif not bulk_seasons:
            a.log_season_rows.append((log.season, log.episode, mins))
        if log.timestamp:
            if a.first_logged is None or log.timestamp < a.first_logged:
                a.first_logged = log.timestamp
            if a.last_logged is None or log.timestamp > a.last_logged:
                a.last_logged = log.timestamp
        # Prefer content_type that isn't generic
        if log.content_type and a.content_type in ("other", ""):
            a.content_type = log.content_type.strip().lower()

    # Catalog display titles + progress status (catalog is user authority)
    catalog_rows = db.query(CatalogItem).all()
    catalog_by_key = {c.series_key: c for c in catalog_rows}
    for key, a in aggs.items():
        cat = catalog_by_key.get(key)
        if cat and cat.display_title and str(cat.display_title).strip():
            a.title = strip_contest_noise(cat.display_title) or cat.display_title
            a.has_catalog_title = True
        if cat and cat.content_type:
            a.content_type = cat.content_type
        if cat is not None:
            a.progress_status = _normalize_status(
                getattr(cat, "progress_status", None)
            )
            a.progress_status_locked = bool(
                getattr(cat, "progress_status_locked", False)
            )
        # Always strip contest noise from whatever title we settled on
        a.title = strip_contest_noise(a.title) or a.title
        # Known identity + key prefix beat stale catalog type (Film Red → movie)
        from app.media.work_identity import _known_type_for

        known_ct = _known_type_for(a.title, key)
        if known_ct:
            a.content_type = known_ct
        elif key.startswith("movie:"):
            a.content_type = "movie"
        elif key.startswith("manga:"):
            a.content_type = "manga"
        elif key.startswith("show:"):
            a.content_type = "show"

    # Metadata titles only when catalog has no display_title
    meta_rows = db.query(MediaMetadata).all()
    meta_by_key = {m.series_key: m for m in meta_rows}
    for key, a in aggs.items():
        if a.has_catalog_title:
            continue
        web = preferred_title_from_metadata(meta_by_key.get(key))
        if web:
            a.title = web

    # Optional: promote Active → Finished at 100% (write paths only)
    if auto_finish:
        _auto_mark_finished(db, aggs, meta_by_key)

    from app.media.work_identity import (
        is_progress_shelf_work,
        is_study_tool,
        normalize_work_title,
    )

    needle = normalize_title(q) if q and q.strip() else ""
    out: list[dict[str, Any]] = []
    for key, a in aggs.items():
        # Prefer cleaned work title for shelf display
        cleaned = normalize_work_title(a.title) or a.title
        if cleaned:
            a.title = cleaned
        # Force study type when identity says tool
        if is_study_tool(
            a.title, series_key=key, content_type=a.content_type
        ):
            a.content_type = "study"
        # Library shelf: JP immersion works only (no YouTube, study tools, EN TV, …)
        if not is_progress_shelf_work(
            title=a.title,
            content_type=a.content_type,
            series_key=key,
            languages=a.languages,
            tadoku_modes=a.tadoku_modes,
        ):
            continue
        if status_filter and a.progress_status != status_filter:
            continue
        if needle:
            hay = normalize_title(f"{a.title} {key} {a.content_type}")
            if needle not in hay:
                continue
        meta = _pick_metadata_for_work(
            meta_by_key,
            key,
            content_type=a.content_type,
            title=a.title,
        )
        progress_label = format_progress_position(
            a.content_type, a.progress_season, a.progress_episode
        )
        primary_amount, primary_unit = _primary_amount_unit(a.total_amount_by_unit)
        episodes_logged = len(a.episode_keys)
        total_value, total_label = _totals_from_meta(
            meta, content_type=a.content_type
        )
        meta_length_ok = _meta_length_fits_content_type(meta, a.content_type)

        from app.media.season_progress import (
            build_season_rows,
            known_franchise_season_totals,
            season_totals_from_metadata,
            seasons_locked_from_metadata,
        )

        season_totals = (
            season_totals_from_metadata(meta) if meta_length_ok else {}
        )
        seasons_locked = (
            seasons_locked_from_metadata(meta) if meta_length_ok else False
        )
        # Provider often returns only S1 deck totals — expand with known franchise map
        if not seasons_locked:
            known_st = known_franchise_season_totals(
                series_key=key, title=a.title
            )
            if known_st:
                # Prefer known multi-season map when meta has no map, or only a
                # flat single-season-looking total that undercounts the franchise
                if not season_totals:
                    season_totals = known_st
                elif len(season_totals) == 1 and len(known_st) > 1:
                    season_totals = known_st
                elif sum(season_totals.values()) < sum(known_st.values()) and (
                    (total_value or 0) <= max(season_totals.values())
                ):
                    # e.g. jiten S1=10 but franchise is 31
                    season_totals = known_st
        # If season totals known, prefer their sum as episode total for display
        if season_totals and (
            not total_value
            or (total_label or "").lower() in ("episodes", "parts", "")
        ):
            franchise = sum(season_totals.values())
            if franchise > 0:
                total_value = franchise
                total_label = total_label or "episodes"

        # Expand bulk S1+S2 logs into full episode keys when we know season lengths
        # ("half" in Tadoku is score credit — still means those seasons were watched)
        if a.bulk_complete_seasons and season_totals:
            for sn in sorted(a.bulk_complete_seasons):
                tot = season_totals.get(sn)
                if not tot or tot <= 0:
                    continue
                for ep in range(1, int(tot) + 1):
                    a.episode_keys.add(f"S{int(sn):02d}E{int(ep):02d}")
                # Ensure progress position reflects end of the last bulk season
                a.progress_season, a.progress_episode = _better_progress(
                    a.progress_season,
                    a.progress_episode,
                    sn,
                    int(tot),
                )
        elif a.bulk_complete_seasons and not season_totals:
            # No per-season map: still surface numbered seasons with minute fill
            for sn in sorted(a.bulk_complete_seasons):
                a.log_season_rows.append((sn, None, 0.0))

        # Movies: one unit / runtime, never a multi-season episode ladder
        is_movie = a.content_type == "movie" or key.startswith("movie:")
        if is_movie:
            season_totals = {}
            meta_mins = int(meta.total_minutes) if meta and meta.total_minutes else None
            # Reject TV-series metadata wrongly attached to a movie key
            if (total_value or 0) > 6 and (total_label or "").lower() in (
                "episodes",
                "parts",
                "",
            ):
                total_value = 1
                total_label = "episodes"
                if meta_mins and meta_mins > 300:
                    meta_mins = None
            if meta_mins and 20 <= meta_mins <= 300:
                total_value = meta_mins
                total_label = "minutes"
            elif not total_value or total_value <= 0:
                total_value = 1
                total_label = "episodes"

        season_info = build_season_rows(
            episode_tags=set() if is_movie else a.episode_keys,
            log_seasons=[] if is_movie else a.log_season_rows,
            season_totals={} if is_movie else season_totals,
            total_units=(
                None
                if is_movie
                else (
                    total_value
                    if (total_label or "").lower()
                    in ("episodes", "volumes", "chapters", "parts", "")
                    else None
                )
            ),
            total_units_label=total_label,
        )

        def _fmt_amount(val: float, unit: str) -> str:
            u = (unit or "").strip().lower()
            short = {
                "minutes": "min",
                "minutes_high_density": "min",
                "characters": "chars",
                "pages": "pages",
                "comic_pages": "pages",
                "two_column_pages": "pages",
                "episodes": "eps",
                "volumes": "vols",
                "chapters": "chs",
                "parts": "parts",
            }.get(u, u or "units")
            if u in ("characters",) and val >= 10_000:
                return f"{val / 1000:.0f}k {short}"
            if u in ("characters", "pages", "comic_pages", "two_column_pages") and val >= 1000:
                return f"{val:,.0f} {short}"
            if abs(val - round(val)) < 1e-6:
                return f"{int(round(val))} {short}"
            return f"{val:g} {short}"

        def _fmt_total_units(val: int, label: str) -> str:
            lab = (label or "parts").strip().lower()
            short = {
                "episodes": "eps",
                "volumes": "vols",
                "chapters": "chs",
                "parts": "parts",
                "routes": "routes",
                "minutes": "min",
                "characters": "chars",
            }.get(lab, lab)
            if lab == "characters" and val >= 10_000:
                return f"{val / 1000:.0f}k {short}"
            if lab in ("characters",) and val >= 1000:
                return f"{val:,} {short}"
            return f"{val} {short}"

        # Position line stays short — season chips carry per-season fill.
        # (Never append "S1 3/12 · S2 …" here; it truncates badly in the card grid.)
        current_display = progress_label
        if is_movie:
            mins = a.total_amount_by_unit.get("minutes", 0.0) + a.total_amount_by_unit.get(
                "minutes_high_density", 0.0
            )
            if mins > 0:
                current_display = f"{mins:g} min"
            elif a.log_count:
                current_display = "Watched"
            else:
                current_display = "Movie"
        if not current_display and episodes_logged:
            current_display = f"{episodes_logged} eps"
        if not current_display and primary_amount is not None:
            current_display = _fmt_amount(float(primary_amount), primary_unit or "")

        total_display = None
        # Longer breakdown for tooltips / list detail (not the dense card line)
        total_display_detail: Optional[str] = None
        if is_movie:
            if total_value is not None and total_label:
                if total_label == "minutes":
                    total_display = f"{total_value} min"
                    total_display_detail = f"{total_value} min runtime"
                else:
                    total_display = "1 film"
            else:
                total_display = "1 film"
        elif season_totals:
            n_seasons = len(season_totals)
            parts = [f"S{s}:{n}" for s, n in sorted(season_totals.items())]
            detail_core = " + ".join(parts)
            if total_value:
                total_display_detail = f"{detail_core} = {total_value} eps"
                # Compact shelf line: "31 eps · 3S" — chips show S1/S2/S3 fill
                total_display = (
                    f"{total_value} eps · {n_seasons}S"
                    if n_seasons > 1
                    else f"{total_value} eps"
                )
            else:
                total_display = f"{n_seasons} seasons"
                total_display_detail = detail_core
        elif total_value is not None and total_label:
            total_display = _fmt_total_units(int(total_value), total_label)
            total_display_detail = f"{total_value} {total_label}"

        # Secondary length stats by immersion modality:
        #   listening (anime/show/…) → duration only
        #   reading (manga/book/VN/…) → characters only
        # Never mix jiten speech-deck chars onto anime totals (e.g. Solo Leveling).
        ct_l = (a.content_type or "").strip().lower()
        listening_types = frozenset(
            {"anime", "show", "movie", "podcast", "youtube", "drama"}
        )
        reading_types = frozenset(
            {"manga", "book", "novel", "visual_novel", "vn"}
        )
        # Audiobook: minutes only (never anime-style eps/chars from a wrong deck)
        show_chars_extra = ct_l in reading_types
        show_mins_extra = ct_l in listening_types or ct_l == "audiobook"
        if ct_l in ("game", "study", "other", ""):
            if primary_unit in ("characters", "pages", "comic_pages", "two_column_pages"):
                show_chars_extra = True
            elif primary_unit in ("minutes", "minutes_high_density"):
                show_mins_extra = True

        show_extra_stats = not is_movie and meta_length_ok
        if season_totals and len(season_totals) > 1:
            show_extra_stats = False
        if show_extra_stats and (total_label or "").lower() in (
            "episodes",
            "volumes",
            "chapters",
            "parts",
        ):
            mins = meta.total_minutes if meta else None
            chars = meta.total_characters if meta else None
            if (total_value or 0) <= 6 and (mins or 0) < 180 and (chars or 0) < 80_000:
                show_extra_stats = False
        # Audiobook: if "total minutes" is tiny vs logged time, it's almost always
        # a mis-attached anime deck runtime — hide it.
        if (
            ct_l == "audiobook"
            and meta
            and meta.total_minutes
            and primary_unit in ("minutes", "minutes_high_density")
            and primary_amount
            and float(primary_amount) > float(meta.total_minutes) * 1.5
            and int(meta.total_minutes) < 400
        ):
            show_mins_extra = False

        if (
            show_extra_stats
            and show_chars_extra
            and meta
            and meta.total_characters
            and total_label != "characters"
        ):
            chars = int(meta.total_characters)
            extra = f"{chars / 1000:.0f}k chars" if chars >= 10_000 else f"{chars:,} chars"
            total_display = f"{total_display} · {extra}" if total_display else extra
            if total_display_detail:
                total_display_detail = f"{total_display_detail} · {chars:,} chars"
        if (
            show_extra_stats
            and show_mins_extra
            and meta
            and meta.total_minutes
            and total_label != "minutes"
        ):
            extra = f"{int(meta.total_minutes)} min"
            total_display = f"{total_display} · {extra}" if total_display else extra
            if total_display_detail:
                total_display_detail = f"{total_display_detail} · {extra}"

        percent = _completion_percent(
            a,
            meta,
            primary_amount=primary_amount,
            primary_unit=primary_unit,
            season_info=season_info,
        )
        # Movies: minutes-based completion, or 100% once any substantial watch is logged
        if is_movie and percent is None:
            mins = a.total_amount_by_unit.get("minutes", 0.0) + a.total_amount_by_unit.get(
                "minutes_high_density", 0.0
            )
            if total_label == "minutes" and total_value and mins > 0:
                percent = min(100.0, round(100.0 * float(mins) / float(total_value), 1))
            elif mins >= 40 or a.log_count > 0:
                # Theatrical film logged as a single watch → complete
                if total_label == "episodes" and (total_value or 1) <= 1:
                    percent = 100.0

        # Unlocked "finished" with incomplete multi-season franchise → still active
        if (
            a.progress_status == "finished"
            and not a.progress_status_locked
            and percent is not None
            and percent < 99.5
            and (
                season_info.get("is_multi_season")
                or (season_totals and len(season_totals) > 1)
            )
        ):
            a.progress_status = "active"

        has_metadata = bool(meta and meta.source and meta.source != "none")
        has_cover = bool(
            meta
            and (meta.cover_local_path or meta.cover_url)
            and meta.source != "none"
        )
        # Manual covers count even when source was set manual without provider
        if meta and meta.source == "manual" and (meta.cover_local_path or meta.cover_url):
            has_cover = True
            has_metadata = True

        from app.media.manual_meta import (
            meta_issues_for_item,
            needs_user_input,
            provider_hints_for,
        )

        issues = meta_issues_for_item(
            has_cover=has_cover,
            has_metadata=has_metadata,
            percent_complete=percent,
            total_units=meta.total_units if meta else total_value,
            total_characters=meta.total_characters if meta else None,
            total_minutes=meta.total_minutes if meta else None,
            primary_amount=primary_amount,
            log_count=a.log_count,
            source=(meta.source if meta else "") or "",
        )
        # Games often have cover but no auto length — still flag for minutes
        if (
            a.content_type == "game"
            and has_cover
            and not (meta and (meta.total_minutes or meta.total_units))
            and a.log_count > 0
            and "no_length" not in issues
        ):
            issues.append("no_length")
        # Multi-season with only a flat total (often S1-scoped) → ask for season map
        if (
            season_info.get("is_multi_season")
            and not season_totals
            and a.content_type in ("anime", "show", "movie")
            and "no_length" not in issues
        ):
            # Flat total may exist but franchise % is unreliable without per-season counts
            if total_value and episodes_logged:
                issues.append("no_season_totals")

        out.append(
            {
                "series_key": key,
                "title": a.title,
                "content_type": a.content_type,
                "progress_status": a.progress_status,
                "log_count": a.log_count,
                "sources": sorted(a.sources),
                "score_estimate": round(a.score_sum, 2),
                "amounts": {
                    u: round(v, 2) for u, v in sorted(a.total_amount_by_unit.items())
                },
                "primary_amount": primary_amount,
                "primary_unit": primary_unit,
                "progress_season": a.progress_season,
                "progress_episode": a.progress_episode,
                "progress_label": progress_label or None,
                "episodes_logged": episodes_logged,
                "current_display": current_display,
                "total_display": total_display,
                "total_display_detail": total_display_detail or total_display,
                "total_units": total_value,
                "total_units_label": total_label,
                "percent_complete": percent,
                "season_mode": season_info.get("season_mode") or "none",
                "is_multi_season": bool(season_info.get("is_multi_season")),
                "seasons": season_info.get("seasons") or [],
                "seasons_summary": season_info.get("seasons_summary"),
                "season_totals": season_info.get("season_totals") or {},
                "franchise_total_episodes": season_info.get(
                    "franchise_total_episodes"
                ),
                "franchise_done_episodes": season_info.get("franchise_done_episodes"),
                "first_logged": a.first_logged.isoformat() if a.first_logged else None,
                "last_logged": a.last_logged.isoformat() if a.last_logged else None,
                "metadata": metadata_to_dict(meta) if meta else None,
                "has_metadata": has_metadata,
                "has_cover": has_cover,
                "needs_user_input": needs_user_input(issues),
                "meta_issues": issues,
                "provider_hints": provider_hints_for(a.content_type, a.title),
            }
        )

    # Sort: most recently logged first
    out.sort(key=lambda r: r.get("last_logged") or "", reverse=True)
    return out


def counts_from_progress_rows(
    rows: list[dict[str, Any]],
) -> tuple[dict[str, int], dict[str, int]]:
    """
    Derive content_type and status histograms from an already-built progress list.

    Prefer this over content_type_counts / progress_status_counts so API snapshots
    only run aggregate_progress once.
    """
    type_counts: dict[str, int] = defaultdict(int)
    status_counts: dict[str, int] = defaultdict(int)
    for r in rows:
        type_counts[r.get("content_type") or "other"] += 1
        status_counts[_normalize_status(r.get("progress_status"))] += 1
    for k in ("active", "finished", "dropped", "ignored"):
        status_counts.setdefault(k, 0)
    types_sorted = dict(sorted(type_counts.items(), key=lambda kv: (-kv[1], kv[0])))
    return types_sorted, dict(status_counts)


def content_type_counts(db: Session) -> dict[str, int]:
    """How many distinct works per content_type (read-only; no auto-finish)."""
    rows = aggregate_progress(db, auto_finish=False)
    types, _ = counts_from_progress_rows(rows)
    return types


def progress_status_counts(db: Session) -> dict[str, int]:
    """How many distinct works per progress_status (read-only; no auto-finish)."""
    rows = aggregate_progress(db, auto_finish=False)
    _, statuses = counts_from_progress_rows(rows)
    return statuses
