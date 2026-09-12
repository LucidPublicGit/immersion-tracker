"""
Quick fixups for Progress works: category, rename, merge/group, cover refetch.

Typical problems this solves:
  - Manual Tadoku logs like "GTO 3" / "Yugi 0-13" each got their own series_key
  - content_type stuck as "other"
  - display titles wrong after a catalog rename (yanki neko → yanineko)
  - missing/wrong jiten cover because the search title was an episode slug
"""

from __future__ import annotations

import re
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.db.models import CatalogItem, LogEntry, MediaMetadata, utcnow
from app.ingest.service import ensure_catalog
from app.media.catalog_resolve import (
    add_alias_to_catalog,
    format_aliases,
    normalize_title,
    parse_aliases,
    relink_logs_to_catalog,
)
from app.media.metadata_cache import ensure_metadata
from app.media.title_format import suggest_series_key

VALID_CONTENT_TYPES = frozenset(
    {
        "anime",
        "show",
        "manga",
        "book",
        "audiobook",
        "visual_novel",
        "game",
        "youtube",
        "podcast",
        "study",
        "movie",
        "other",
    }
)

# Progress page status on catalog rows
VALID_PROGRESS_STATUSES = frozenset({"active", "finished", "dropped", "ignored"})

# "GTO 11", "GTO 12-14", "GTO 5,6", "Gachiakuta 2,3", "Yugi 0-13 (double pts)"
_TRAIL_EP = re.compile(
    r"^(?P<base>.+?)\s+"
    r"(?:"
    r"[Ss](?P<season>\d{1,2})[Ee](?P<episode>\d{1,3})"
    # Comma list first (2,3 or 2, 3, 4) — end episode is last number
    r"|(?P<ep_list>\d{1,3}(?:\s*[,，]\s*\d{1,3}){1,8})"
    r"|(?P<ep_a>\d{1,3})(?:\s*[-–]\s*(?P<ep_b>\d{1,3}))?"
    r")\s*$"
)
_PARENS = re.compile(r"\s*\([^)]*\)\s*$")


def strip_title_notes(title: str) -> str:
    return _PARENS.sub("", (title or "").strip()).strip()


def split_embedded_episode(title: str) -> dict[str, Any]:
    """
    Pull a trailing episode number/range off a manual title when possible.
    Returns base title + optional season/episode (episode = end of range).

    Does **not** parse volume/page logs (``vol 1 page 50-100``) — those would
    wrongly become E50/E100.
    """
    raw = strip_title_notes(title)
    if not raw:
        return {"title": title or "", "season": None, "episode": None, "matched": False}
    # Volume / page logs are not episode tails
    if re.search(r"\bvol(?:ume)?\.?\b|\bpage\b|巻|頁", raw, re.I):
        return {"title": raw, "season": None, "episode": None, "matched": False}
    m = _TRAIL_EP.match(raw)
    if not m:
        return {"title": raw, "season": None, "episode": None, "matched": False}
    base = (m.group("base") or "").strip()
    if not base or len(base) < 1:
        return {"title": raw, "season": None, "episode": None, "matched": False}
    if m.group("season") is not None:
        return {
            "title": base,
            "season": int(m.group("season")),
            "episode": int(m.group("episode")),
            "matched": True,
        }
    if m.group("ep_list"):
        parts = re.split(r"[,，]\s*", m.group("ep_list"))
        try:
            nums = [int(p) for p in parts if p.strip()]
        except ValueError:
            nums = []
        if not nums or any(n > 500 for n in nums):
            return {"title": raw, "season": None, "episode": None, "matched": False}
        return {
            "title": base,
            "season": None,
            "episode": max(nums),
            "matched": True,
        }
    ep_a = int(m.group("ep_a"))
    ep_b = m.group("ep_b")
    ep = int(ep_b) if ep_b is not None else ep_a
    # Guard: don't treat years like "Show 2024" as episode 2024
    if ep > 500:
        return {"title": raw, "season": None, "episode": None, "matched": False}
    return {"title": base, "season": None, "episode": ep, "matched": True}


def _mark_dirty(db: Session) -> None:
    try:
        from app.sheets.state import mark_sheets_dirty

        mark_sheets_dirty(db)
    except Exception:  # noqa: BLE001
        pass


def _logs_for_keys(db: Session, series_keys: list[str]) -> list[LogEntry]:
    keys = [k for k in series_keys if k]
    if not keys:
        return []
    return db.query(LogEntry).filter(LogEntry.series_key.in_(keys)).all()


def _ensure_catalog_for(
    db: Session,
    series_key: str,
    title: str,
    content_type: str,
) -> CatalogItem:
    item = (
        db.query(CatalogItem)
        .filter(CatalogItem.series_key == series_key)
        .one_or_none()
    )
    if item:
        if title and item.display_title != title:
            item.display_title = title
        if content_type and item.content_type != content_type:
            item.content_type = content_type
        item.updated_at = utcnow()
        return item
    return ensure_catalog(db, series_key, title, content_type)


# series_key prefixes that should follow content_type (not yt:/gsm:/hoshi:)
_REWRITABLE_KEY_PREFIXES = frozenset(
    {
        "anime",
        "show",
        "manga",
        "book",
        "audiobook",
        "game",
        "visual_novel",
        "movie",
        "podcast",
        "other",
        "study",
    }
)


def _key_for_content_type(series_key: str, content_type: str) -> str:
    """
    When category changes (manga→show), rewrite the key prefix so shelf
    filters and metadata providers match. Keep opaque prefixes (yt, gsm, hoshi, vn).
    """
    sk = (series_key or "").strip()
    ct = (content_type or "").strip().lower()
    if not sk or ":" not in sk or not ct:
        return sk
    prefix, slug = sk.split(":", 1)
    prefix_l = prefix.lower()
    if prefix_l in ("yt", "gsm", "hoshi", "vn"):
        return sk
    if prefix_l not in _REWRITABLE_KEY_PREFIXES:
        return sk
    # visual_novel keys historically use visual_novel: (gsm uses gsm:)
    new_prefix = ct
    if prefix_l == new_prefix:
        return sk
    return f"{new_prefix}:{slug}"


def set_content_type(
    db: Session,
    series_keys: list[str],
    content_type: str,
    *,
    refetch_meta: bool = True,
) -> dict[str, Any]:
    """
    Change content_type on logs + catalog (+ series_key prefix when safe).

    When the category changes, force a fresh metadata lookup for the new type
    (manga providers ≠ show providers — stale covers/totals would stay wrong).
    """
    ct = (content_type or "").strip().lower()
    if ct not in VALID_CONTENT_TYPES:
        raise ValueError(f"invalid content_type: {content_type}")
    keys = list(dict.fromkeys(k for k in series_keys if k))
    logs = _logs_for_keys(db, keys)
    updated_logs = 0
    key_rewrites: dict[str, str] = {}

    # Plan key rewrites from old → new prefix
    for old_key in keys:
        new_key = _key_for_content_type(old_key, ct)
        if new_key != old_key:
            key_rewrites[old_key] = new_key

    for log in logs:
        old_key = (log.series_key or "").strip()
        changed = False
        if log.content_type != ct:
            log.content_type = ct
            changed = True
        if old_key in key_rewrites:
            log.series_key = key_rewrites[old_key]
            changed = True
        if changed:
            log.updated_at = utcnow()
            updated_logs += 1

    updated_catalog = 0
    final_keys: list[str] = []
    for old_key in keys:
        new_key = key_rewrites.get(old_key, old_key)
        final_keys.append(new_key)
        item = (
            db.query(CatalogItem)
            .filter(CatalogItem.series_key == old_key)
            .one_or_none()
        )
        target = (
            db.query(CatalogItem)
            .filter(CatalogItem.series_key == new_key)
            .one_or_none()
        )
        if old_key != new_key and item and target and item.id != target.id:
            # Merge into existing target catalog row
            if item.display_title and not target.display_title:
                target.display_title = item.display_title
            target.content_type = ct
            target.updated_at = utcnow()
            db.delete(item)
            updated_catalog += 1
        elif item:
            if item.content_type != ct:
                item.content_type = ct
                updated_catalog += 1
            if old_key != new_key:
                item.series_key = new_key
                updated_catalog += 1
            item.updated_at = utcnow()
        elif not target:
            # Ensure catalog exists at final key
            title = next(
                (lg.title for lg in logs if (lg.series_key or "") in (old_key, new_key)),
                new_key,
            )
            _ensure_catalog_for(db, new_key, title or new_key, ct)
            updated_catalog += 1
        elif target and target.content_type != ct:
            target.content_type = ct
            target.updated_at = utcnow()
            updated_catalog += 1

        # Move / retarget media_metadata row with the key
        meta = (
            db.query(MediaMetadata)
            .filter(MediaMetadata.series_key == old_key)
            .one_or_none()
        )
        if old_key != new_key and meta:
            existing_new = (
                db.query(MediaMetadata)
                .filter(MediaMetadata.series_key == new_key)
                .one_or_none()
            )
            if existing_new and existing_new.id != meta.id:
                db.delete(meta)  # drop stale; re-fetch will repopulate new_key
            else:
                meta.series_key = new_key
                meta.content_type = ct
                meta.updated_at = utcnow()
        elif meta:
            meta.content_type = ct
            meta.updated_at = utcnow()

    db.commit()

    # Force metadata re-lookup under the *new* content type (providers differ)
    meta_results: list[dict[str, Any]] = []
    if refetch_meta:
        from app.media.metadata_cache import ensure_metadata, metadata_to_dict
        from app.media.work_identity import normalize_work_title

        for new_key in list(dict.fromkeys(final_keys)):
            title = ""
            cat = (
                db.query(CatalogItem)
                .filter(CatalogItem.series_key == new_key)
                .one_or_none()
            )
            if cat and cat.display_title:
                title = cat.display_title
            if not title:
                lg = (
                    db.query(LogEntry)
                    .filter(LogEntry.series_key == new_key)
                    .order_by(LogEntry.id.desc())
                    .first()
                )
                if lg:
                    title = lg.title or ""
            title = normalize_work_title(title) or title or new_key
            try:
                # Clear sticky "manual" only when type changed — force always re-queries
                row = ensure_metadata(
                    db,
                    series_key=new_key,
                    title=title,
                    content_type=ct,
                    force=True,
                )
                meta_results.append(
                    {
                        "series_key": new_key,
                        "source": row.source,
                        "has_cover": bool(row.cover_local_path or row.cover_url),
                        "total_units": row.total_units,
                        "total_units_label": row.total_units_label,
                        "title": row.title,
                    }
                )
            except Exception as exc:  # noqa: BLE001
                meta_results.append(
                    {
                        "series_key": new_key,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )

    _mark_dirty(db)
    return {
        "ok": True,
        "action": "set_type",
        "content_type": ct,
        "series_keys": list(dict.fromkeys(final_keys)),
        "key_rewrites": key_rewrites,
        "updated_logs": updated_logs,
        "updated_catalog": updated_catalog,
        "refetch_meta": refetch_meta,
        "metadata": meta_results,
    }


def set_progress_status(
    db: Session,
    series_keys: list[str],
    status: str,
    *,
    titles: Optional[dict[str, str]] = None,
    content_types: Optional[dict[str, str]] = None,
) -> dict[str, Any]:
    """
    Set progress_status on catalog for each series_key (creates catalog if needed).

    status: active | finished | dropped | ignored

    ``ignored`` hides the work from the default Progress shelf (still viewable
    under the Ignored filter). Logs are kept.
    """
    st = (status or "").strip().lower()
    if st in ("ignore", "hidden", "hide"):
        st = "ignored"
    if st not in VALID_PROGRESS_STATUSES:
        raise ValueError("status must be active | finished | dropped | ignored")
    keys = list(dict.fromkeys(k for k in series_keys if k))
    titles = titles or {}
    content_types = content_types or {}
    updated = 0
    for key in keys:
        logs = _logs_for_keys(db, [key])
        title = titles.get(key) or (logs[0].title if logs else key)
        ct = content_types.get(key) or (logs[0].content_type if logs else "anime")
        item = _ensure_catalog_for(db, key, title, ct)
        changed = False
        if getattr(item, "progress_status", None) != st:
            item.progress_status = st
            changed = True
        elif not getattr(item, "progress_status", None):
            item.progress_status = st
            changed = True
        # User-set status is locked so auto-finish cannot reverse it
        if not bool(getattr(item, "progress_status_locked", False)):
            item.progress_status_locked = True
            changed = True
        if changed:
            item.updated_at = utcnow()
            updated += 1
    db.commit()
    _mark_dirty(db)
    return {
        "ok": True,
        "action": "set_status",
        "status": st,
        "series_keys": keys,
        "updated_catalog": updated,
    }


def rename_works(
    db: Session,
    series_keys: list[str],
    title: str,
    *,
    also_parse_episodes: bool = True,
) -> dict[str, Any]:
    """
    Set display title on logs + catalog for the given series_keys.
    Optionally peel trailing episode numbers off old titles into season/episode.
    """
    new_title = (title or "").strip()
    if not new_title:
        raise ValueError("title required")
    keys = list(dict.fromkeys(k for k in series_keys if k))
    logs = _logs_for_keys(db, keys)
    updated_logs = 0
    for log in logs:
        changed = False
        if also_parse_episodes and (log.season is None and log.episode is None):
            parsed = split_embedded_episode(log.title or "")
            if parsed["matched"]:
                if log.season is None and parsed["season"] is not None:
                    log.season = parsed["season"]
                    changed = True
                if log.episode is None and parsed["episode"] is not None:
                    log.episode = parsed["episode"]
                    changed = True
        if log.title != new_title:
            log.title = new_title
            changed = True
        if changed:
            log.updated_at = utcnow()
            updated_logs += 1
    updated_catalog = 0
    for key in keys:
        # Prefer content_type from first log
        ct = "anime"
        for log in logs:
            if log.series_key == key and log.content_type:
                ct = log.content_type
                break
        item = _ensure_catalog_for(db, key, new_title, ct)
        if item.display_title != new_title:
            item.display_title = new_title
            item.updated_at = utcnow()
            updated_catalog += 1
        meta = (
            db.query(MediaMetadata)
            .filter(MediaMetadata.series_key == key)
            .one_or_none()
        )
        if meta and meta.title != new_title:
            meta.title = new_title
            meta.updated_at = utcnow()
    db.commit()
    _mark_dirty(db)
    return {
        "ok": True,
        "action": "rename",
        "title": new_title,
        "series_keys": keys,
        "updated_logs": updated_logs,
        "updated_catalog": updated_catalog,
    }


def _safe_alias_candidates(
    *,
    new_title: str,
    source_keys: list[str],
    log_titles: list[str],
) -> list[str]:
    """
    Aliases that are safe for catalog redirects.

    Never dump every episode/amount slug (Demonbane 53099 x 2) into aliases —
    that previously caused unrelated works to collapse under one key.
    """
    out: list[str] = [new_title]
    for key in source_keys:
        out.append(key)
        # humanized key suffix only if short/clean
        suffix = key.split(":", 1)[-1].replace("-", " ").strip()
        if suffix and len(suffix) <= 40 and not re.search(r"\d{3,}", suffix):
            out.append(suffix)
    bases: set[str] = set()
    for t in log_titles:
        parsed = split_embedded_episode(t)
        base = (parsed["title"] if parsed["matched"] else strip_title_notes(t)).strip()
        if not base:
            continue
        # skip amount-heavy titles like "Demonbane 53099 x 2"
        if re.search(r"\b\d{3,}\b", base) and re.search(r"\bx\b", base, re.I):
            # keep only leading word(s) before big numbers
            m = re.match(r"^(.+?)\s+\d", base)
            if m:
                bases.add(m.group(1).strip())
            continue
        bases.add(base)
    # Only keep base names shared or equal to new_title / short names
    for b in bases:
        if normalize_title(b) == normalize_title(new_title):
            out.append(b)
        elif len(b) <= 48 and not re.search(r"\d{4,}", b):
            # single clean alternate (e.g. yani neko) — ok
            out.append(b)
    # de-dupe
    seen: set[str] = set()
    cleaned: list[str] = []
    for a in out:
        k = normalize_title(a)
        if not k or k in seen:
            continue
        seen.add(k)
        cleaned.append(a)
    return cleaned[:40]


def merge_works(
    db: Session,
    source_keys: list[str],
    *,
    target_series_key: Optional[str] = None,
    title: str,
    content_type: str = "anime",
    parse_episodes: bool = True,
    refetch_meta: bool = True,
) -> dict[str, Any]:
    """
    Collapse multiple Progress works into one series_key.

    - Creates/updates catalog target with display_title + content_type
    - Adds *safe* aliases only (old series_keys + clean base titles)
    - Rewrites all source logs onto the target
    - Peels "GTO 11" style episode tails when parse_episodes
    - Optionally force-refetches cover under the clean title
    """
    new_title = (title or "").strip()
    if not new_title:
        raise ValueError("title required")
    ct = (content_type or "anime").strip().lower()
    if ct not in VALID_CONTENT_TYPES:
        raise ValueError(f"invalid content_type: {content_type}")

    sources = list(dict.fromkeys(k for k in source_keys if k))
    if not sources:
        raise ValueError("series_keys required")

    target = (target_series_key or "").strip() or suggest_series_key(ct, new_title)
    if target in ("anime:unknown", "other:unknown", "unknown"):
        raise ValueError(
            "Refusing to merge into anime:unknown / other:unknown — pick a real series_key "
            "(e.g. anime:gto, vn:demonbane)"
        )

    logs = _logs_for_keys(db, sources)
    log_titles = [log.title for log in logs if log.title]
    aliases = _safe_alias_candidates(
        new_title=new_title, source_keys=sources, log_titles=log_titles
    )

    item = _ensure_catalog_for(db, target, new_title, ct)
    item.display_title = new_title
    item.content_type = ct
    for a in aliases:
        add_alias_to_catalog(item, a)
    item.updated_at = utcnow()
    db.commit()

    # Direct log rewrite (more reliable than alias-only match for distinct keys)
    updated_logs = 0
    for log in logs:
        changed = False
        if parse_episodes and (log.season is None or log.episode is None):
            parsed = split_embedded_episode(log.title or "")
            if parsed["matched"]:
                if log.season is None and parsed["season"] is not None:
                    log.season = parsed["season"]
                    changed = True
                if log.episode is None and parsed["episode"] is not None:
                    log.episode = parsed["episode"]
                    changed = True
        if log.title != new_title:
            log.title = new_title
            changed = True
        if log.series_key != target:
            log.series_key = target
            changed = True
        if log.content_type != ct:
            log.content_type = ct
            changed = True
        if changed:
            log.updated_at = utcnow()
            updated_logs += 1

    # Relink only by explicit old series_keys — not by every historical title
    relink = relink_logs_to_catalog(
        db,
        item,
        also_titles=[new_title],
        also_series_keys=sources,
    )

    # Drop orphan source catalog rows (optional cleanup)
    removed_catalog = 0
    for key in sources:
        if key == target:
            continue
        # Only remove if no logs left on that key
        remaining = (
            db.query(LogEntry).filter(LogEntry.series_key == key).count()
        )
        if remaining:
            continue
        old = (
            db.query(CatalogItem)
            .filter(CatalogItem.series_key == key)
            .one_or_none()
        )
        if old:
            db.delete(old)
            removed_catalog += 1
        old_meta = (
            db.query(MediaMetadata)
            .filter(MediaMetadata.series_key == key)
            .one_or_none()
        )
        if old_meta:
            db.delete(old_meta)

    db.commit()
    _mark_dirty(db)

    meta_info = None
    if refetch_meta:
        try:
            # Clear prior none/wrong cache for target so jiten runs on clean title
            existing = (
                db.query(MediaMetadata)
                .filter(MediaMetadata.series_key == target)
                .one_or_none()
            )
            row = ensure_metadata(
                db,
                series_key=target,
                title=new_title,
                content_type=ct,
                force=True,
            )
            meta_info = {
                "source": row.source,
                "external_id": row.external_id,
                "has_cover": bool(row.cover_local_path or row.cover_url),
                "replaced": bool(existing),
            }
        except Exception as exc:  # noqa: BLE001
            meta_info = {"error": f"{type(exc).__name__}: {exc}"}

    return {
        "ok": True,
        "action": "merge",
        "target_series_key": target,
        "title": new_title,
        "content_type": ct,
        "source_keys": sources,
        "updated_logs": updated_logs,
        "relink": relink,
        "removed_catalog": removed_catalog,
        "metadata": meta_info,
    }


def refetch_covers(
    db: Session,
    series_keys: list[str],
    *,
    title_override: Optional[str] = None,
) -> dict[str, Any]:
    """Force jiten (etc.) lookup using catalog/log title or override."""
    keys = list(dict.fromkeys(k for k in series_keys if k))
    results: list[dict[str, Any]] = []
    for key in keys:
        logs = (
            db.query(LogEntry)
            .filter(LogEntry.series_key == key)
            .order_by(LogEntry.id.desc())
            .limit(1)
            .all()
        )
        cat = (
            db.query(CatalogItem)
            .filter(CatalogItem.series_key == key)
            .one_or_none()
        )
        title = (
            (title_override or "").strip()
            or (cat.display_title if cat else "")
            or (logs[0].title if logs else key)
        )
        ct = (
            (cat.content_type if cat else "")
            or (logs[0].content_type if logs else "anime")
            or "anime"
        )
        # Prefer base name without episode tail; ensure_metadata also expands
        # JP/EN/aliases via catalog + log titles for higher hit rate.
        base = split_embedded_episode(title)["title"] or title
        try:
            row = ensure_metadata(
                db,
                series_key=key,
                title=base,
                content_type=ct,
                force=True,
            )
            results.append(
                {
                    "series_key": key,
                    "title": base,
                    "source": row.source,
                    "has_cover": bool(row.cover_local_path or row.cover_url),
                    "external_id": row.external_id,
                }
            )
        except Exception as exc:  # noqa: BLE001
            results.append(
                {
                    "series_key": key,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
    return {
        "ok": True,
        "action": "refetch_cover",
        "series_keys": keys,
        "results": results,
    }


def build_catalog_key_redirects(db: Session) -> dict[str, str]:
    """
    Map alternate series_keys → catalog series_key (safe subset only).

    Only:
      - the catalog row's own series_key
      - aliases that look like series_keys (contain ':')
      - auto keys generated from the *display_title* alone

    We deliberately do NOT generate redirects from every free-text alias
    (that is what swallowed Demonbane into ヤニねこ via anime:unknown).
    """
    redirects: dict[str, str] = {}
    items = db.query(CatalogItem).all()
    for item in items:
        # Skip poisoned catch-all rows
        if item.series_key in ("anime:unknown", "other:unknown"):
            redirects[item.series_key] = item.series_key
            continue
        canonical = item.series_key
        redirects[canonical] = canonical
        if item.display_title:
            for ct in {item.content_type, "anime", "show", "manga", "visual_novel"}:
                if ct:
                    redirects[suggest_series_key(ct, item.display_title)] = canonical
        for name in parse_aliases(item.aliases):
            if not name:
                continue
            # Literal old series_key aliases only
            if ":" in name and name.count(":") == 1 and " " not in name:
                redirects[name.strip()] = canonical
    return redirects


def normalize_library(db: Session, *, dry_run: bool = False) -> dict[str, Any]:
    """
    One-shot / maintain: rewrite logs to canonical work keys + clean titles.

    - Anki / Bunpro / Italki → content_type=study, stable study:* keys
    - Volume/episode fragment keys collapse (One Piece 19 → anime:one-piece)
    - Peels embedded episode numbers into season/episode when missing
    - Cleans catalog display titles for affected keys

    Progress aggregation already groups canonically; this makes fixups and
    future logs consistent.
    """
    from app.media.work_identity import (
        canonical_series_key,
        infer_content_type,
        is_study_tool,
        normalize_work_title,
        peel_log_fields,
    )

    logs = db.query(LogEntry).all()
    updated = 0
    study_n = 0
    merged_into: dict[str, int] = {}
    samples: list[str] = []

    for log in logs:
        old_key = (log.series_key or "").strip()
        old_title = (log.title or "").strip()
        old_ct = (log.content_type or "").strip().lower()
        # Never rewrite YouTube identity (each video is its own row off the shelf)
        if old_ct == "youtube" or old_key.startswith("yt:"):
            continue
        # Repair known over-collapse / wrong type: Film Red is a movie, not OP TV
        _film_red_keys = {
            "anime:one-piece-film-red",
            "anime:onepiecered",
            "anime:one-piece-red",
            "movie:one-piece-film-red",
            "movie:onepiecered",
            "movie:one-piece-red",
        }
        looks_film_red = (
            old_key in _film_red_keys
            or (
                "one-piece" in old_key
                and ("film" in old_key or "red" in old_key or "onepiecered" in old_key)
            )
            or bool(
                re.search(
                    r"one\s*piece\s*(film\s*)?red|film\s*red",
                    f"{old_title} {old_key}",
                    re.I,
                )
            )
        )
        if looks_film_red and not re.search(
            r"\bvol(?:ume)?\b|\bpage\b|巻", old_title or "", re.I
        ):
            # Keep as theatrical film even if title was collapsed to bare One Piece
            if (
                normalize_work_title(old_title) in ("One Piece", "ONE PIECE FILM RED")
                or "red" in (old_title or "").lower()
                or "film" in (old_title or "").lower()
                or old_key in _film_red_keys
            ):
                new_title = "ONE PIECE FILM RED"
                new_key = "movie:one-piece-film-red"
                if (
                    log.title != new_title
                    or log.series_key != new_key
                    or (log.content_type or "").lower() != "movie"
                ):
                    log.title = new_title
                    log.series_key = new_key
                    log.content_type = "movie"
                    log.updated_at = utcnow()
                    updated += 1
                continue
        # Repair "1,000,000 yen…" title that lost its leading 1
        if (old_title or "").startswith(",000") or (old_title or "").startswith(",0"):
            log.title = "1" + old_title
            old_title = log.title
            updated += 1
        # Mark known English shows as language=en so japanese_only filter works
        from app.media.work_identity import is_non_japanese_work

        blob = f"{old_title} {old_key}".lower()
        if (log.tadoku_mode or "").lower() == "never" and re.search(
            r"\bsilo\b|house.of.the.dragon|game.of.thrones|"
            r"breaking.bad|stranger.things|the.last.of.us",
            blob,
        ):
            if (log.language or "").lower() in ("", "ja", "jpn", "japanese", "jp"):
                log.language = "en"
                log.updated_at = utcnow()
                updated += 1
        elif is_non_japanese_work(
            title=old_title,
            series_key=old_key,
            languages={(log.language or "ja").lower()},
            tadoku_modes={(log.tadoku_mode or "").lower()},
        ):
            if (log.language or "").lower() in ("", "ja", "jpn", "japanese", "jp"):
                if re.search(
                    r"\bsilo\b|house.of.the.dragon|game.of.thrones",
                    blob,
                ):
                    log.language = "en"
                    log.updated_at = utcnow()
                    updated += 1
        # Optional: Tadoku import notes carry vol/page detail not in title
        notes = (log.notes or "").strip()
        note_desc = ""
        if notes.lower().startswith("imported from tadoku"):
            parts = re.split(r"[·•|]\s*", notes, maxsplit=1)
            if len(parts) > 1 and parts[1].strip():
                note_desc = parts[1].strip()

        # Peel volume/page from notes first (safer), else title
        peeled_note = peel_log_fields(note_desc) if note_desc else None
        peeled_title = peel_log_fields(old_title)
        peeled = peeled_title
        if peeled_note and peeled_note.get("kind") in ("volume", "pages"):
            peeled = peeled_note

        # Keep catalog-clean titles: never re-expand into "Demonbane 53099 x 2"
        new_title = normalize_work_title(old_title) or old_title
        # Strip character-count noise left in display titles
        cleaned_amt = re.sub(
            r"\s+\d{3,}\s*[x×]\s*\d+\s*$", "", new_title or "", flags=re.I
        ).strip()
        if cleaned_amt and cleaned_amt != new_title:
            new_title = cleaned_amt
        if peeled.get("kind") in ("volume", "pages") and peeled.get("title"):
            # Only replace title when peel clearly extracted a work name
            cand = peeled["title"]
            if cand and len(cand) >= 2 and not re.search(r"\b\d{3,}\b", cand):
                new_title = cand

        new_ct = infer_content_type(
            new_title,
            old_ct,
            source=log.source or "",
            series_key=old_key,
            unit=log.unit or "",
            activity=log.activity or "",
        )
        # Prefer existing clean keys; only rebuild when type/unit split needs it
        unit_l = (log.unit or "").lower()
        act_l = (log.activity or "").lower()
        needs_type_split = False
        if old_key and ":" in old_key:
            pref = old_key.split(":", 1)[0].lower()
            if new_ct != pref and pref in (
                "anime",
                "show",
                "manga",
                "book",
                "other",
                "movie",
            ):
                needs_type_split = True
            if unit_l in ("pages", "comic_pages", "two_column_pages", "characters") and pref in (
                "anime",
                "show",
            ):
                needs_type_split = True
                new_ct = "manga" if new_ct in ("anime", "show", "other", "") else new_ct
            if unit_l in ("minutes", "minutes_high_density") and pref == "manga" and act_l == "listening":
                needs_type_split = True
                new_ct = "anime"

        if needs_type_split:
            new_key = canonical_series_key(
                new_ct,
                new_title,
                existing_key=old_key,
                source=log.source or "",
                prefer_existing=False,
            )
            if new_key and ":" in new_key:
                pfx, slug = new_key.split(":", 1)
                if pfx != new_ct:
                    new_key = f"{new_ct}:{slug}"
        else:
            new_key = canonical_series_key(
                new_ct,
                new_title,
                existing_key=old_key,
                source=log.source or "",
                prefer_existing=True,
            )

        changed = False
        # Clean amount-noise titles ("Demonbane 53099 x 2" → "Demonbane")
        if new_title and new_title != log.title and re.search(
            r"\b\d{3,}\s*[x×]\b", old_title or "", re.I
        ):
            log.title = new_title
            changed = True
        elif (
            peeled.get("kind") in ("volume", "pages")
            and new_title
            and new_title != log.title
            and not re.search(r"\b\d{3,}\s*x\b", old_title, re.I)
        ):
            log.title = new_title
            changed = True
        if new_ct and new_ct != (log.content_type or ""):
            log.content_type = new_ct
            changed = True
            if new_ct == "study":
                study_n += 1
        if new_key and new_key != old_key:
            log.series_key = new_key
            changed = True
            merged_into[new_key] = merged_into.get(new_key, 0) + 1
        if log.season is None and peeled.get("season") is not None:
            log.season = peeled["season"]
            changed = True
        # Volume position: set episode = volume; clear page-range false episodes
        if peeled.get("kind") == "volume" and peeled.get("volume") is not None:
            if log.episode != peeled["volume"] or log.season is not None:
                log.episode = int(peeled["volume"])
                log.season = None
                changed = True
        elif peeled.get("kind") == "pages":
            if log.episode is not None and log.episode >= 40:
                log.episode = None
                changed = True
        # Clear absurd "episodes" on page-reading logs (E50/E100 from page ranges)
        if unit_l in ("pages", "comic_pages", "two_column_pages") and log.episode is not None:
            if log.episode >= 40 and peeled.get("kind") != "volume":
                log.episode = None
                changed = True
        # Repair amount-noise series keys (Demonbane 53099 x 2 → vn:demonbane)
        sk_now = (log.series_key or new_key or old_key or "")
        if re.search(
            r"(?:-\d{2,}(?:-\d+)?-x(?:-|$)|-\d{3,}x|-start-file|-\d+k-x)",
            sk_now,
            re.I,
        ):
            work = normalize_work_title(log.title or new_title or "") or "unknown"
            ct_fix = (log.content_type or new_ct or "visual_novel").strip().lower()
            if sk_now.startswith("vn:") or "demonbane" in sk_now.lower():
                fixed = f"vn:{re.sub(r'[^a-z0-9]+', '-', work.lower()).strip('-')[:80]}"
                if "demonbane" in sk_now.lower():
                    fixed = "vn:demonbane"
            else:
                fixed = canonical_series_key(
                    ct_fix,
                    work,
                    existing_key="",
                    source=log.source or "",
                    prefer_existing=False,
                )
            if fixed and fixed != sk_now:
                log.series_key = fixed
                changed = True
                merged_into[fixed] = merged_into.get(fixed, 0) + 1
        if changed:
            log.updated_at = utcnow()
            updated += 1
            if len(samples) < 24:
                samples.append(
                    f"{old_key or '∅'} / {old_title[:40]!r} → {new_key} / {new_title[:40]!r}"
                )

    # Catalog: ensure targets + clean display titles; drop empty fragment rows
    catalog_updated = 0
    removed_catalog = 0
    if not dry_run and updated:
        # Touch catalogs for surviving keys
        keys_now = {
            (log.series_key or "").strip()
            for log in db.query(LogEntry.series_key).distinct().all()
            if (log.series_key or "").strip()
        }
        # group titles per key
        title_by_key: dict[str, str] = {}
        ct_by_key: dict[str, str] = {}
        for log in db.query(LogEntry).all():
            k = (log.series_key or "").strip()
            if not k:
                continue
            t = normalize_work_title(log.title or "") or (log.title or k)
            if k not in title_by_key or len(t) > len(title_by_key[k]):
                title_by_key[k] = t
            ct_by_key[k] = (log.content_type or ct_by_key.get(k) or "anime").lower()

        for k, t in title_by_key.items():
            ct = ct_by_key.get(k) or "anime"
            item = _ensure_catalog_for(db, k, t, ct)
            clean = normalize_work_title(item.display_title or t) or t
            if item.display_title != clean:
                item.display_title = clean
                item.updated_at = utcnow()
                catalog_updated += 1
            if is_study_tool(clean, series_key=k, content_type=item.content_type):
                if item.content_type != "study":
                    item.content_type = "study"
                    item.updated_at = utcnow()
                    catalog_updated += 1

        # Remove orphan catalog rows with no logs
        for cat in db.query(CatalogItem).all():
            if cat.series_key in keys_now:
                continue
            # keep if has aliases only? drop empty
            remaining = (
                db.query(LogEntry)
                .filter(LogEntry.series_key == cat.series_key)
                .count()
            )
            if remaining == 0:
                # also drop metadata for orphan fragment keys
                meta = (
                    db.query(MediaMetadata)
                    .filter(MediaMetadata.series_key == cat.series_key)
                    .one_or_none()
                )
                if meta:
                    db.delete(meta)
                db.delete(cat)
                removed_catalog += 1

        db.commit()
        _mark_dirty(db)
    elif dry_run:
        db.rollback()

    return {
        "ok": True,
        "action": "normalize_library",
        "dry_run": dry_run,
        "updated_logs": updated,
        "study_reclassified": study_n,
        "targets": len(merged_into),
        "merged_into": dict(
            sorted(merged_into.items(), key=lambda kv: -kv[1])[:40]
        ),
        "catalog_updated": catalog_updated,
        "removed_catalog": removed_catalog,
        "samples": samples,
    }


_TADOKU_NOTE_RE = re.compile(
    r"^Imported from Tadoku\s*[·•\-|:]\s*(.+)$",
    re.IGNORECASE,
)


def _infer_work_from_tadoku_description(desc: str) -> dict[str, Any]:
    """
    Map a Tadoku description back to a sensible work identity.
    """
    raw = (desc or "").strip()
    low = raw.lower()

    # Demonbane character dumps: "Demonbane 53099 x 2"
    if "demonbane" in low:
        return {
            "title": "Demonbane",
            "content_type": "visual_novel",
            "series_key": "vn:demonbane",
            "season": None,
            "episode": None,
        }

    # Yani Neko variants
    if re.search(r"yani\s*neko|yanineko|やにねこ|ヤニねこ", raw, re.I):
        cleaned = re.sub(r"\bep\.?\s*", " ", raw, flags=re.I)
        parsed = split_embedded_episode(cleaned)
        season = parsed.get("season")
        episode = parsed.get("episode")
        if parsed.get("matched") and episode is not None and season is None:
            season = 1
        return {
            "title": "ヤニねこ",
            "content_type": "anime",
            "series_key": "anime:yanineko",
            "season": season,
            "episode": episode,
        }

    # Wednesday Downtown segments
    if "wednesday downtown" in low:
        # keep segment-specific keys
        base = strip_title_notes(raw)
        return {
            "title": base,
            "content_type": "show",
            "series_key": suggest_series_key("show", base),
            "season": None,
            "episode": None,
        }

    parsed = split_embedded_episode(raw)
    title = parsed["title"] if parsed["matched"] else strip_title_notes(raw)
    ct = "anime"
    return {
        "title": title or raw,
        "content_type": ct,
        "series_key": suggest_series_key(ct, title or raw),
        "season": parsed.get("season"),
        "episode": parsed.get("episode"),
    }


def _needs_note_recovery(
    log: LogEntry,
    desc: str,
    inferred: dict[str, Any],
    *,
    force_keys: Optional[set[str]],
) -> bool:
    """
    Only rewrite logs that look wrongly merged / stuck on :unknown.

    When force_keys is set (user selected series), recover all notes in those keys.
    """
    sk = (log.series_key or "").strip()
    if force_keys is not None:
        return sk in force_keys

    # Catch-all bucket from JP titles or bad merges
    if sk.endswith(":unknown") or sk in ("anime:unknown", "other:unknown"):
        return True

    # Demonbane swallowed under another work
    if "demonbane" in desc.lower() and sk != "vn:demonbane":
        return True

    # Yani title but notes are a different work
    title_l = (log.title or "").lower()
    if title_l in ("ヤニねこ", "yanineko", "yani neko") or "ヤニねこ" in (log.title or ""):
        if not re.search(r"yani\s*neko|yanineko|やにねこ|ヤニねこ", desc, re.I):
            return True

    # Title was overwritten to something that doesn't match the Tadoku description
    from app.media.metadata_cache import score_title_match as _score

    if (
        _score(log.title or "", desc) < 40
        and _score(log.title or "", inferred["title"]) < 40
        and len(desc) >= 2
        and normalize_title(log.title or "") != normalize_title(desc)
    ):
        return True
    return False


def recover_tadoku_notes(
    db: Session,
    *,
    series_keys: Optional[list[str]] = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """
    Undo bad merges for logs that still have original Tadoku descriptions in notes.

    Notes look like: ``Imported from Tadoku · Demonbane 53099 x 2``

    By default only touches:
      - series_key ending in ``:unknown``
      - Demonbane notes not on ``vn:demonbane``
      - ヤニねこ title with non-yani notes

    Pass series_keys to force recovery within those keys only.
    """
    q = db.query(LogEntry).filter(LogEntry.notes.isnot(None))
    force_keys: Optional[set[str]] = None
    if series_keys:
        force_keys = set(series_keys)
        q = q.filter(LogEntry.series_key.in_(list(series_keys)))
    logs = q.all()

    recovered = 0
    skipped = 0
    by_target: dict[str, int] = {}
    samples: list[str] = []

    for log in logs:
        notes = (log.notes or "").strip()
        m = _TADOKU_NOTE_RE.match(notes)
        if not m:
            skipped += 1
            continue
        desc = m.group(1).strip()
        if not desc:
            skipped += 1
            continue
        inferred = _infer_work_from_tadoku_description(desc)
        target = inferred["series_key"]
        title = inferred["title"]
        ct = inferred["content_type"]

        if not _needs_note_recovery(log, desc, inferred, force_keys=force_keys):
            skipped += 1
            continue

        # Skip if already correct
        if (
            log.series_key == target
            and log.title == title
            and (log.content_type or "") == ct
        ):
            skipped += 1
            continue

        if dry_run:
            recovered += 1
            by_target[target] = by_target.get(target, 0) + 1
            if len(samples) < 12:
                samples.append(f"{log.series_key!r} → {target} ({title})")
            continue

        log.series_key = target
        log.title = title
        log.content_type = ct
        if log.season is None and inferred.get("season") is not None:
            log.season = inferred["season"]
        if log.episode is None and inferred.get("episode") is not None:
            log.episode = inferred["episode"]
        log.updated_at = utcnow()
        recovered += 1
        by_target[target] = by_target.get(target, 0) + 1
        if len(samples) < 12:
            samples.append(f"→ {target} · {title}")

        _ensure_catalog_for(db, target, title, ct)

    cleaned_catalog = 0
    if not dry_run and recovered:
        # Strip polluted aliases off catch-all / yanineko rows
        for key in ("anime:unknown", "other:unknown", "anime:yanineko"):
            item = (
                db.query(CatalogItem)
                .filter(CatalogItem.series_key == key)
                .one_or_none()
            )
            if not item or not item.aliases:
                continue
            aliases = parse_aliases(item.aliases)
            keep: list[str] = []
            for a in aliases:
                al = a.lower()
                # drop demonbane / wednesday junk from yanineko/unknown
                if "demonbane" in al:
                    continue
                if "wednesday" in al:
                    continue
                if a.startswith("other:demonbane") or a.startswith("other:wednesday"):
                    continue
                if key == "anime:yanineko":
                    # keep only yani-related aliases
                    if not re.search(r"yani|やに|ヤニ", a, re.I):
                        # allow exact old key aliases that look yani-ish
                        if "yani" not in al and "neko" not in al:
                            continue
                keep.append(a)
            new_aliases = format_aliases(keep) or None
            if new_aliases != item.aliases:
                item.aliases = new_aliases
                item.updated_at = utcnow()
                cleaned_catalog += 1
            if key == "anime:yanineko":
                item.display_title = "ヤニねこ"
                item.content_type = "anime"

        # Ensure demonbane catalog is clean
        dbane = (
            db.query(CatalogItem)
            .filter(CatalogItem.series_key == "vn:demonbane")
            .one_or_none()
        )
        if dbane:
            dbane.display_title = "Demonbane"
            dbane.content_type = "visual_novel"
            dbane.aliases = format_aliases(
                [
                    a
                    for a in parse_aliases(dbane.aliases)
                    if "demonbane" in a.lower() or a.startswith("other:demonbane")
                ]
            ) or None
            dbane.updated_at = utcnow()

        db.commit()
        _mark_dirty(db)

        # Clear wrong yanineko cover (A Whisker Away) so next enrich can use MAL
        meta = (
            db.query(MediaMetadata)
            .filter(MediaMetadata.series_key == "anime:yanineko")
            .one_or_none()
        )
        if meta and (
            meta.external_id == "7923"
            or (meta.cover_local_path or "").endswith("jiten_7923.jpg")
            or "whisker" in (meta.title or "").lower()
        ):
            meta.source = "none"
            meta.external_id = None
            meta.external_url = None
            meta.cover_url = None
            meta.cover_local_path = None
            meta.total_units = None
            meta.raw_json = None
            meta.updated_at = utcnow()
            db.commit()

    return {
        "ok": True,
        "action": "recover_notes",
        "recovered": recovered,
        "skipped": skipped,
        "by_target": by_target,
        "cleaned_catalog": cleaned_catalog,
        "dry_run": dry_run,
        "samples": samples,
    }

