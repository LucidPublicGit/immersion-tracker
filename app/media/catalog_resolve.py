"""Resolve Plex/auto titles → catalog series_key + display_title via aliases."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Optional

from sqlalchemy.orm import Session

from app.db.models import CatalogItem, LogEntry, utcnow
from app.media.title_format import suggest_series_key
from app.tadoku.rules import mode_to_initial_status


def normalize_title(name: str) -> str:
    """Case/space-insensitive key for matching titles and aliases."""
    s = unicodedata.normalize("NFKC", name or "")
    s = s.casefold().strip()
    s = re.sub(r"\s+", " ", s)
    return s


def parse_aliases(raw: Optional[str]) -> list[str]:
    """
    Split alias field into titles.
    Accepts pipe, newline, or semicolon separators (pipe preferred in Sheets).
    """
    if not raw:
        return []
    parts = re.split(r"[|\n;]+", str(raw))
    return [p.strip() for p in parts if p.strip()]


def format_aliases(aliases: list[str]) -> str:
    cleaned = [a.strip() for a in aliases if a and a.strip()]
    # de-dupe preserving order
    seen: set[str] = set()
    out: list[str] = []
    for a in cleaned:
        key = normalize_title(a)
        if key in seen:
            continue
        seen.add(key)
        out.append(a.strip())
    return " | ".join(out)


def catalog_match_names(item: CatalogItem) -> list[str]:
    names = [item.display_title] if item.display_title else []
    names.extend(parse_aliases(item.aliases))
    return names


@dataclass
class ResolvedSeries:
    series_key: str
    display_title: str
    content_type: str
    catalog: Optional[CatalogItem]
    matched_by: str  # series_key | display_title | alias | generated


def _type_ok(
    item: CatalogItem, content_type: Optional[str], prefer_type: bool
) -> bool:
    if not prefer_type or not content_type or not item.content_type:
        return True
    return item.content_type == content_type


def _find_by_aliases(
    items: list[CatalogItem],
    needle: str,
    content_type: Optional[str],
    prefer_type: bool,
) -> Optional[CatalogItem]:
    """Explicit aliases win over auto-created display_title rows."""
    for item in items:
        if not _type_ok(item, content_type, prefer_type):
            continue
        for name in parse_aliases(item.aliases):
            if normalize_title(name) == needle:
                return item
    return None


def _find_by_display_title(
    items: list[CatalogItem],
    needle: str,
    content_type: Optional[str],
    prefer_type: bool,
) -> Optional[CatalogItem]:
    for item in items:
        if not _type_ok(item, content_type, prefer_type):
            continue
        if item.display_title and normalize_title(item.display_title) == needle:
            return item
    return None


def resolve_series(
    db: Session,
    content_type: str,
    raw_title: str,
    *,
    preferred_series_key: Optional[str] = None,
) -> ResolvedSeries:
    """
    Map a raw show/work title (e.g. Plex grandparent_title) to catalog identity.

    Order:
      1. preferred_series_key if it exists in catalog
      2. exact match on aliases (user-linked Plex names) — same type, then any
      3. exact match on display_title — same type, then any
      4. auto series_key from title — use catalog row if already present
      5. generate series_key; display_title = raw title
    """
    raw = (raw_title or "").strip() or "Unknown"
    ct = (content_type or "anime").strip().lower()

    if preferred_series_key:
        item = (
            db.query(CatalogItem)
            .filter(CatalogItem.series_key == preferred_series_key)
            .one_or_none()
        )
        if item:
            return ResolvedSeries(
                series_key=item.series_key,
                display_title=item.display_title or raw,
                content_type=item.content_type or ct,
                catalog=item,
                matched_by="series_key",
            )

    needle = normalize_title(raw)
    items = db.query(CatalogItem).all()
    if needle:
        for prefer_type in (True, False):
            item = _find_by_aliases(items, needle, ct, prefer_type)
            if item:
                return ResolvedSeries(
                    series_key=item.series_key,
                    display_title=item.display_title or raw,
                    content_type=item.content_type or ct,
                    catalog=item,
                    matched_by="alias",
                )
        for prefer_type in (True, False):
            item = _find_by_display_title(items, needle, ct, prefer_type)
            if item:
                return ResolvedSeries(
                    series_key=item.series_key,
                    display_title=item.display_title or raw,
                    content_type=item.content_type or ct,
                    catalog=item,
                    matched_by="display_title",
                )

    generated = suggest_series_key(ct, raw)
    item = (
        db.query(CatalogItem).filter(CatalogItem.series_key == generated).one_or_none()
    )
    if item:
        return ResolvedSeries(
            series_key=item.series_key,
            display_title=item.display_title or raw,
            content_type=item.content_type or ct,
            catalog=item,
            matched_by="series_key",
        )

    return ResolvedSeries(
        series_key=generated,
        display_title=raw,
        content_type=ct,
        catalog=None,
        matched_by="generated",
    )


def add_alias_to_catalog(
    item: CatalogItem,
    alias: str,
) -> bool:
    """Append alias if new. Returns True if changed."""
    alias = (alias or "").strip()
    if not alias:
        return False
    existing = parse_aliases(item.aliases)
    if normalize_title(alias) in {normalize_title(a) for a in existing}:
        return False
    if item.display_title and normalize_title(alias) == normalize_title(item.display_title):
        return False
    existing.append(alias)
    item.aliases = format_aliases(existing)
    return True


def apply_tadoku_override_to_log(log: LogEntry, override: Optional[str]) -> bool:
    """
    Apply catalog tadoku_override to an existing log.

    Guardrails:
      - no-op if override is empty
      - never touch pushed (already submitted)
      - leave user skips alone unless override is never
      - for pending / ready / failed: set mode + derived status
    """
    mode = (override or "").strip().lower()
    if mode not in ("auto", "pending", "never"):
        return False

    status = (log.tadoku_status or "").strip().lower()
    if status == "pushed":
        return False
    # Explicit skip was a human choice — don't re-open unless catalog says never
    if status == "skipped" and mode != "never":
        return False

    changed = False
    if log.tadoku_mode != mode:
        log.tadoku_mode = mode
        changed = True

    # Pipeline + never→skipped; skipped+never keeps skipped
    if status in ("pending", "ready", "failed", "skipped", ""):
        new_status = mode_to_initial_status(mode)
        if log.tadoku_status != new_status:
            log.tadoku_status = new_status
            changed = True
    return changed


def relink_logs_to_catalog(
    db: Session,
    item: CatalogItem,
    *,
    also_titles: Optional[list[str]] = None,
    also_series_keys: Optional[list[str]] = None,
) -> dict[str, int]:
    """
    Retarget existing logs that match this catalog's aliases / titles / old keys.

    Updates:
      - log.title → display_title
      - log.series_key → item.series_key
      - log.content_type when title matched (safer than key-only)
      - tadoku_mode / tadoku_status from catalog tadoku_override (guardrailed)
    """
    match_titles = {normalize_title(n) for n in catalog_match_names(item) if n}
    for t in also_titles or []:
        if t and normalize_title(t):
            match_titles.add(normalize_title(t))

    match_keys = {item.series_key}
    for sk in also_series_keys or []:
        if sk:
            match_keys.add(sk)
    # Auto keys that would be generated from each alias (common Plex path)
    for name in catalog_match_names(item):
        for ct in {item.content_type, "anime", "show"}:
            if ct:
                match_keys.add(suggest_series_key(ct, name))

    updated = 0
    tadoku_updated = 0
    logs = db.query(LogEntry).all()
    for log in logs:
        title_hit = log.title and normalize_title(log.title) in match_titles
        key_hit = log.series_key and log.series_key in match_keys
        if not title_hit and not key_hit:
            continue
        changed = False
        if item.display_title and log.title != item.display_title:
            log.title = item.display_title
            changed = True
        if log.series_key != item.series_key:
            log.series_key = item.series_key
            changed = True
        # Prefer catalog content type for plex/manual consistency when empty mismatch
        if item.content_type and log.content_type != item.content_type and title_hit:
            # only retarget type when title matched (safer than key-only)
            log.content_type = item.content_type
            changed = True
        if apply_tadoku_override_to_log(log, item.tadoku_override):
            changed = True
            tadoku_updated += 1
        if changed:
            log.updated_at = utcnow()
            updated += 1
    if updated:
        db.commit()
        # Ensure next sheet poll does not re-apply stale Logs (All) rows
        try:
            from app.sheets.state import mark_sheets_dirty

            mark_sheets_dirty(db)
        except Exception:  # noqa: BLE001
            pass
    return {"updated": updated, "tadoku_updated": tadoku_updated}
