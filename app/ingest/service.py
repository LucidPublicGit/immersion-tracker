from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import CatalogItem, LogEntry, utcnow
from app.tadoku.rules import (
    estimate_score,
    mode_to_initial_status,
    resolve_activity_unit,
    resolve_tadoku_mode,
)


class DuplicateLogError(Exception):
    def __init__(self, existing: LogEntry):
        self.existing = existing
        super().__init__(f"Duplicate log source={existing.source} ref={existing.source_ref}")


def ensure_catalog(
    db: Session,
    series_key: str,
    display_title: str,
    content_type: str,
    *,
    default_unit: Optional[str] = None,
) -> CatalogItem:
    """
    Ensure a catalog row exists. Never overwrite display_title/aliases on existing
    rows — those are user-controlled (sheet / API / Catalog UI).

    New rows get default_unit from the arg or content_type_defaults (still editable).
    """
    item = (
        db.query(CatalogItem)
        .filter(CatalogItem.series_key == series_key)
        .one_or_none()
    )
    if item:
        return item
    if not default_unit:
        _, default_unit = resolve_activity_unit(content_type)
    item = CatalogItem(
        series_key=series_key,
        display_title=display_title,
        content_type=content_type,
        default_unit=default_unit,
    )
    db.add(item)
    db.flush()
    return item


def create_log(
    db: Session,
    *,
    content_type: str,
    title: str,
    source: str,
    amount: float,
    unit: Optional[str] = None,
    activity: Optional[str] = None,
    series_key: Optional[str] = None,
    source_ref: Optional[str] = None,
    language: Optional[str] = None,
    notes: Optional[str] = None,
    tags: Optional[str] = None,
    timestamp: Optional[datetime] = None,
    watch_ratio: Optional[float] = None,
    tadoku_mode_override: Optional[str] = None,
    season: Optional[int] = None,
    episode: Optional[int] = None,
) -> LogEntry:
    settings = get_settings()
    cfg = settings.yaml_config

    # Normalize work identity: clean title, peel vol/ep, study tools → study
    from app.media.work_identity import prepare_log_identity

    # Pass unit/activity before defaults so pages→manga / minutes→anime split works
    ident = prepare_log_identity(
        content_type=content_type,
        title=title or "",
        source=source or "",
        series_key=series_key,
        season=season,
        episode=episode,
        unit=unit or "",
        activity=activity or "",
    )
    content_type = ident["content_type"]
    title = ident["title"]
    series_key = ident["series_key"]
    season = ident["season"]
    episode = ident["episode"]

    default_activity, type_default_unit = resolve_activity_unit(content_type, cfg)
    activity = activity or default_activity
    language = language or cfg.language_default

    catalog: Optional[CatalogItem] = None
    if series_key:
        # Catalog display = work name only (not SxxExx / volume tails)
        catalog = ensure_catalog(db, series_key, title, content_type)

    # explicit unit > catalog default_unit > content_type default
    if not unit and catalog and catalog.default_unit:
        unit = catalog.default_unit
    unit = unit or type_default_unit

    if not source_ref:
        source_ref = f"{source}:{uuid.uuid4().hex[:16]}"

    mode = tadoku_mode_override or resolve_tadoku_mode(
        db, content_type, series_key, source, cfg
    )
    status = mode_to_initial_status(mode)
    score = estimate_score(activity, amount, unit, cfg)

    entry = LogEntry(
        timestamp=timestamp or utcnow(),
        content_type=content_type,
        title=title,
        season=season,
        episode=episode,
        series_key=series_key,
        source=source,
        source_ref=source_ref,
        amount=amount,
        unit=unit,
        language=language,
        activity=activity,
        tadoku_mode=mode,
        tadoku_status=status,
        tadoku_score_estimate=score,
        notes=notes,
        tags=tags,
        watch_ratio=watch_ratio,
    )
    db.add(entry)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = (
            db.query(LogEntry)
            .filter(LogEntry.source == source, LogEntry.source_ref == source_ref)
            .one_or_none()
        )
        if existing:
            raise DuplicateLogError(existing) from None
        raise
    db.refresh(entry)
    # Defer sheet rewrite until push job; hash-skip if already mirrored
    try:
        from app.sheets.state import mark_sheets_dirty

        mark_sheets_dirty(db)
    except Exception:  # noqa: BLE001
        pass
    return entry


# Allowed enum values for API edits (match sheet dropdowns)
VALID_TADOKU_MODES = frozenset({"auto", "pending", "never"})
VALID_TADOKU_STATUSES = frozenset(
    {"n/a", "pending", "ready", "pushed", "failed", "skipped"}
)

# Fields that may be explicitly set to null/empty
_NULLABLE_LOG_FIELDS = frozenset(
    {"series_key", "season", "episode", "notes", "tags", "tadoku_remote_id"}
)


class LogUpdateError(ValueError):
    """Invalid log field update."""


def _sync_series_tadoku_mode(
    db: Session,
    entry: LogEntry,
    mode: str,
    *,
    except_id: Optional[int] = None,
) -> int:
    """
    Queue/Logs mode dropdown is per-row, but users treat it as a series preference.

    Persist mode onto Catalog.tadoku_override so the next Plex/Hoshi episode
    inherits auto/pending/never, and apply to other pipeline logs on this key
    (never reopens pushed; leaves user skips alone unless mode is never).
    """
    sk = (entry.series_key or "").strip()
    if not sk or mode not in VALID_TADOKU_MODES:
        return 0

    item = ensure_catalog(
        db,
        sk,
        entry.title or sk,
        entry.content_type or "anime",
    )
    if item.tadoku_override != mode:
        item.tadoku_override = mode
        item.updated_at = utcnow()

    from app.media.catalog_resolve import apply_tadoku_override_to_log

    n = 0
    siblings = (
        db.query(LogEntry)
        .filter(LogEntry.series_key == sk)
        .all()
    )
    skip_id = except_id if except_id is not None else entry.id
    for log in siblings:
        if log.id == skip_id:
            continue
        if apply_tadoku_override_to_log(log, mode):
            log.updated_at = utcnow()
            n += 1
    return n


def update_log(db: Session, entry: LogEntry, fields: dict) -> LogEntry:
    """
    Apply partial updates to a log row (source of truth = SQLite).

    ``fields`` should only include keys the client explicitly set
    (e.g. pydantic model_dump(exclude_unset=True)).

    Marks Google Sheets dirty so the next push mirrors the change.
    Demoting from pushed → non-pushed clears tadoku_remote_id so re-submit works.

    Changing tadoku_mode also updates Catalog.tadoku_override for the log's
    series_key (when set) so future ingest inherits the same mode.
    """
    if not fields:
        return entry

    changed = False
    status_before = entry.tadoku_status
    mode_changed = False
    status_changed = False
    score_inputs_changed = False

    def set_str(attr: str, *, required: bool = False) -> None:
        nonlocal changed
        if attr not in fields:
            return
        raw = fields[attr]
        if raw is None:
            if attr in _NULLABLE_LOG_FIELDS:
                if getattr(entry, attr) is not None:
                    setattr(entry, attr, None)
                    changed = True
            return
        val = str(raw).strip()
        if not val:
            if attr in _NULLABLE_LOG_FIELDS:
                if getattr(entry, attr) is not None:
                    setattr(entry, attr, None)
                    changed = True
            elif required:
                raise LogUpdateError(f"{attr} cannot be empty")
            return
        if (getattr(entry, attr) or "") != val:
            setattr(entry, attr, val)
            changed = True

    if "content_type" in fields:
        set_str("content_type", required=True)
    if "title" in fields:
        set_str("title", required=True)
    if "unit" in fields:
        set_str("unit", required=True)
        score_inputs_changed = True
    if "activity" in fields:
        set_str("activity", required=True)
        score_inputs_changed = True
    if "source" in fields:
        set_str("source", required=True)
    if "language" in fields:
        set_str("language", required=True)
    if "series_key" in fields:
        set_str("series_key")
    if "notes" in fields:
        raw = fields["notes"]
        n = None if raw is None else str(raw)
        if (entry.notes or None) != (n or None):
            entry.notes = n or None
            changed = True
    if "tags" in fields:
        set_str("tags")

    if "amount" in fields:
        amt = fields["amount"]
        if amt is None:
            raise LogUpdateError("amount cannot be null")
        try:
            amt_f = float(amt)
        except (TypeError, ValueError) as e:
            raise LogUpdateError("amount must be a number") from e
        if amt_f <= 0:
            raise LogUpdateError("amount must be > 0")
        if entry.amount != amt_f:
            entry.amount = amt_f
            changed = True
            score_inputs_changed = True

    for attr in ("season", "episode"):
        if attr not in fields:
            continue
        raw = fields[attr]
        if raw is None or raw == "":
            if getattr(entry, attr) is not None:
                setattr(entry, attr, None)
                changed = True
            continue
        try:
            iv = int(raw)
        except (TypeError, ValueError) as e:
            raise LogUpdateError(f"{attr} must be an integer") from e
        if getattr(entry, attr) != iv:
            setattr(entry, attr, iv)
            changed = True

    if "timestamp" in fields and fields["timestamp"] is not None:
        ts = fields["timestamp"]
        if isinstance(ts, str):
            try:
                ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except ValueError as e:
                raise LogUpdateError("invalid timestamp") from e
        if entry.timestamp != ts:
            entry.timestamp = ts
            changed = True

    if "tadoku_mode" in fields and fields["tadoku_mode"] is not None:
        m = str(fields["tadoku_mode"]).strip().lower()
        if m not in VALID_TADOKU_MODES:
            raise LogUpdateError(f"invalid tadoku_mode: {m}")
        if entry.tadoku_mode != m:
            entry.tadoku_mode = m
            mode_changed = True
            changed = True

    if "tadoku_status" in fields and fields["tadoku_status"] is not None:
        st = str(fields["tadoku_status"]).strip().lower()
        if st not in VALID_TADOKU_STATUSES:
            raise LogUpdateError(f"invalid tadoku_status: {st}")
        if entry.tadoku_status != st:
            entry.tadoku_status = st
            status_changed = True
            changed = True

    # Mode change without explicit status → derive status (like sheet merge)
    if mode_changed and "tadoku_status" not in fields:
        new_st = mode_to_initial_status(entry.tadoku_mode)
        if entry.tadoku_status != new_st:
            entry.tadoku_status = new_st
            status_changed = True
            changed = True

    # auto + pending → ready (same as sheet merge)
    if (
        entry.tadoku_mode == "auto"
        and entry.tadoku_status == "pending"
        and status_before != "pushed"
    ):
        entry.tadoku_status = "ready"
        status_changed = True
        changed = True

    # Status ↔ mode shortcuts
    if entry.tadoku_status == "skipped" and entry.tadoku_mode != "never":
        entry.tadoku_mode = "never"
        changed = True
    if entry.tadoku_status == "ready" and entry.tadoku_mode == "never":
        entry.tadoku_mode = "auto"
        changed = True
    if entry.tadoku_status == "pending" and entry.tadoku_mode == "never":
        entry.tadoku_mode = "pending"
        changed = True

    # Demoting from pushed: clear remote id so approve/process can re-submit
    demoted = status_before == "pushed" and entry.tadoku_status != "pushed" and status_changed
    clear_remote = bool(fields.get("clear_remote_id"))
    if demoted or clear_remote:
        if entry.tadoku_remote_id:
            entry.tadoku_remote_id = None
            changed = True

    if "content_type" in fields:
        score_inputs_changed = True
    if score_inputs_changed:
        new_score = estimate_score(entry.activity, entry.amount, entry.unit)
        if entry.tadoku_score_estimate != new_score:
            entry.tadoku_score_estimate = new_score
            changed = True

    # Series preference: mode dropdown → catalog override + sibling pipeline logs.
    # Skip() sets mode=never on one row outside this path intentionally.
    if mode_changed and entry.series_key:
        _sync_series_tadoku_mode(db, entry, entry.tadoku_mode)
        changed = True

    if changed:
        entry.updated_at = utcnow()
        db.commit()
        db.refresh(entry)
        try:
            from app.sheets.state import mark_sheets_dirty

            mark_sheets_dirty(db)
        except Exception:  # noqa: BLE001
            pass
    return entry


def delete_log(db: Session, entry: LogEntry) -> None:
    """Delete a log row and mark sheets dirty for push."""
    db.delete(entry)
    db.commit()
    try:
        from app.sheets.state import mark_sheets_dirty

        mark_sheets_dirty(db)
    except Exception:  # noqa: BLE001
        pass
