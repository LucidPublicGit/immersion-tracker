"""Persist sheet push hashes / dirty flags so we skip no-op Google writes."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.db.models import SheetSyncState, utcnow

logger = logging.getLogger(__name__)

DIRTY_KEY = "sheets_dirty"
# Per-tab content hashes: push_hash:<tab_key>
HASH_PREFIX = "push_hash:"
# ISO timestamps of last successful DB→sheet push per scope (logs | catalog)
LAST_PUSH_PREFIX = "last_push_at:"


def rows_content_hash(rows: list[list[Any]]) -> str:
    """Stable SHA-256 of sheet payload (None → empty string)."""
    normalized: list[list[str]] = []
    for row in rows:
        normalized.append(["" if c is None else str(c) for c in row])
    payload = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def get_state(db: Session, key: str) -> str:
    row = db.query(SheetSyncState).filter(SheetSyncState.key == key).one_or_none()
    return row.value if row else ""


def set_state(db: Session, key: str, value: str) -> None:
    row = db.query(SheetSyncState).filter(SheetSyncState.key == key).one_or_none()
    if row is None:
        row = SheetSyncState(key=key, value=value, updated_at=utcnow())
        db.add(row)
    else:
        row.value = value
        row.updated_at = utcnow()
    db.commit()


def get_push_hash(db: Session, tab_key: str) -> str:
    return get_state(db, f"{HASH_PREFIX}{tab_key}")


def set_push_hash(db: Session, tab_key: str, digest: str) -> None:
    set_state(db, f"{HASH_PREFIX}{tab_key}", digest)


def is_sheets_dirty(db: Session) -> bool:
    return get_state(db, DIRTY_KEY) in ("1", "true", "yes")


def mark_sheets_dirty(db: Optional[Session] = None) -> None:
    """
    Signal that DB changed and a sheet push should run soon.
    Safe no-op if db is omitted — opens a short-lived session.
    """
    if db is not None:
        set_state(db, DIRTY_KEY, "1")
        return
    try:
        from app.db.session import get_engine
        from sqlalchemy.orm import sessionmaker

        SessionLocal = sessionmaker(bind=get_engine(), autoflush=False, autocommit=False)
        s = SessionLocal()
        try:
            set_state(s, DIRTY_KEY, "1")
        finally:
            s.close()
    except Exception:  # noqa: BLE001
        logger.debug("mark_sheets_dirty failed", exc_info=True)


def clear_sheets_dirty(db: Session) -> None:
    set_state(db, DIRTY_KEY, "0")


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_iso_dt(raw: str) -> Optional[datetime]:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return _as_utc(dt)


def get_last_push_at(db: Session, scope: str) -> Optional[datetime]:
    """Last successful DB→sheet push for scope ('logs' or 'catalog')."""
    return _parse_iso_dt(get_state(db, f"{LAST_PUSH_PREFIX}{scope}"))


def set_last_push_at(db: Session, scope: str, when: Optional[datetime] = None) -> None:
    """Record that scope content is now reflected on the sheet."""
    ts = _as_utc(when or utcnow()).isoformat()
    set_state(db, f"{LAST_PUSH_PREFIX}{scope}", ts)


def get_dirty_marked_at(db: Session) -> Optional[datetime]:
    """When sheets_dirty was last set/cleared (row updated_at)."""
    row = db.query(SheetSyncState).filter(SheetSyncState.key == DIRTY_KEY).one_or_none()
    if not row or not row.updated_at:
        return None
    return _as_utc(row.updated_at)


def is_row_local_ahead(
    db: Session,
    updated_at: Optional[datetime],
    *,
    scope: str,
) -> bool:
    """
    True when a DB row was modified after the last successful sheet push.

    Prevents frequent sheet→DB polls from overwriting local API/UI work
    (catalog link, relink, queue approve) that has not been pushed yet.

    Fallback when no push baseline exists: while dirty, protect rows touched
    at/after the dirty mark (same batch as the local edit).
    """
    if not updated_at:
        return False
    ua = _as_utc(updated_at)
    last = get_last_push_at(db, scope)
    if last is not None:
        return ua > last
    if is_sheets_dirty(db):
        dirty_at = get_dirty_marked_at(db)
        if dirty_at is not None:
            # 2s skew: mark_dirty commit vs row updated_at ordering
            return ua >= dirty_at - timedelta(seconds=2)
    return False
