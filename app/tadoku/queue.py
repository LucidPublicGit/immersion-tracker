from __future__ import annotations

import logging
import uuid
from typing import Optional

from sqlalchemy import or_, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import LogEntry, TadokuStatus, utcnow
from app.tadoku.client import TadokuClient

logger = logging.getLogger(__name__)

# In-flight claim so approve + process_ready cannot both POST to tadoku.app
_CLAIM_PREFIX = "submitting:"


def list_queue(
    db: Session,
    status: Optional[str] = None,
    limit: int = 100,
    *,
    include_pushed: bool = False,
) -> list[LogEntry]:
    """
    Default: actionable statuses only (pending / ready / failed).
    include_pushed=True also returns submitted items (API/debug only; queue UI omits them).
    """
    q = db.query(LogEntry).filter(LogEntry.tadoku_status != TadokuStatus.NA.value)
    if status:
        q = q.filter(LogEntry.tadoku_status == status)
    else:
        statuses = [
            TadokuStatus.PENDING.value,
            TadokuStatus.READY.value,
            TadokuStatus.FAILED.value,
        ]
        if include_pushed:
            statuses.append(TadokuStatus.PUSHED.value)
        q = q.filter(LogEntry.tadoku_status.in_(statuses))
    return q.order_by(LogEntry.timestamp.desc()).limit(limit).all()


def list_recent_pushed(db: Session, limit: int = 30) -> list[LogEntry]:
    """
    Recently submitted logs from local DB only (status=pushed).

    Ordered by immersion timestamp (when the activity happened / when Tadoku
    recorded it), not updated_at. updated_at is bumped by imports, progress
    fixups, and edits — so it is a poor "recent" key (old pulled progress
    logs would float to the top).

    Does not call tadoku.app.
    """
    return (
        db.query(LogEntry)
        .filter(LogEntry.tadoku_status == TadokuStatus.PUSHED.value)
        .order_by(LogEntry.timestamp.desc(), LogEntry.id.desc())
        .limit(limit)
        .all()
    )


def _is_real_remote_id(remote_id: Optional[str]) -> bool:
    rid = (remote_id or "").strip()
    if not rid:
        return False
    if rid.startswith(_CLAIM_PREFIX):
        return False
    return True


def _mark_sheets_dirty_safe(db: Session) -> None:
    try:
        from app.sheets.state import mark_sheets_dirty

        mark_sheets_dirty(db)
    except Exception:  # noqa: BLE001
        pass


def _already_submitted(entry: LogEntry) -> bool:
    """True if this log must not POST again to tadoku.app."""
    if entry.tadoku_status == TadokuStatus.PUSHED.value and _is_real_remote_id(
        entry.tadoku_remote_id
    ):
        return True
    if _is_real_remote_id(entry.tadoku_remote_id):
        return True
    return False


def _restore_pushed_if_remote(db: Session, entry: LogEntry) -> LogEntry:
    """If we already have a real remote id, force status=pushed (sheet lag recovery)."""
    if _is_real_remote_id(entry.tadoku_remote_id) and entry.tadoku_status != TadokuStatus.PUSHED.value:
        entry.tadoku_status = TadokuStatus.PUSHED.value
        entry.updated_at = utcnow()
        db.commit()
        db.refresh(entry)
        _mark_sheets_dirty_safe(db)
        logger.info(
            "restored tadoku_status=pushed for log_id=%s remote_id=%s",
            entry.id,
            entry.tadoku_remote_id,
        )
    return entry


def _try_claim_for_submit(db: Session, entry_id: int) -> Optional[LogEntry]:
    """
    Atomically claim a log for one submit attempt.
    Returns the entry if this caller owns the claim; None if another worker
    already submitted or claimed it.
    """
    claim = f"{_CLAIM_PREFIX}{uuid.uuid4().hex[:16]}"
    # Only claim rows that are not finished and have no real remote id
    stmt = (
        update(LogEntry)
        .where(LogEntry.id == entry_id)
        .where(
            LogEntry.tadoku_status.in_(
                [
                    TadokuStatus.PENDING.value,
                    TadokuStatus.READY.value,
                    TadokuStatus.FAILED.value,
                ]
            )
        )
        .where(
            or_(
                LogEntry.tadoku_remote_id.is_(None),
                LogEntry.tadoku_remote_id == "",
            )
        )
        .values(
            tadoku_status=TadokuStatus.READY.value,
            tadoku_remote_id=claim,
            updated_at=utcnow(),
        )
    )
    result = db.execute(stmt)
    db.commit()
    if not result.rowcount:
        entry = db.get(LogEntry, entry_id)
        if entry:
            _restore_pushed_if_remote(db, entry)
        return None

    entry = db.get(LogEntry, entry_id)
    if not entry or entry.tadoku_remote_id != claim:
        return None
    return entry


def _clear_claim_on_failure(db: Session, entry: LogEntry, claim: str) -> None:
    """Release in-flight claim so a later retry can run."""
    if entry.tadoku_remote_id == claim:
        entry.tadoku_remote_id = None
        entry.updated_at = utcnow()
        db.commit()
        db.refresh(entry)


def _submit_entry(
    db: Session,
    entry: LogEntry,
    client: TadokuClient,
    *,
    already_claimed: bool = False,
) -> tuple[bool, Optional[str], Optional[str]]:
    """
    Submit one log to Tadoku. Idempotent: never POSTs twice for a real remote id.
    Uses an atomic claim so concurrent approve + process_ready cannot double-log.
    """
    db.refresh(entry)

    if _already_submitted(entry):
        _restore_pushed_if_remote(db, entry)
        return True, entry.tadoku_remote_id, "already_submitted"

    if entry.tadoku_status in (
        TadokuStatus.SKIPPED.value,
        TadokuStatus.PUSHED.value,
    ):
        return True, entry.tadoku_remote_id, "skipped_status"

    claim = entry.tadoku_remote_id if (
        already_claimed and (entry.tadoku_remote_id or "").startswith(_CLAIM_PREFIX)
    ) else None

    if not claim:
        claimed = _try_claim_for_submit(db, entry.id)
        if not claimed:
            entry = db.get(LogEntry, entry.id)
            if entry and _already_submitted(entry):
                return True, entry.tadoku_remote_id, "already_submitted"
            # Another worker is submitting or row is not eligible
            if entry:
                db.refresh(entry)
            return (
                entry is not None and entry.tadoku_status == TadokuStatus.PUSHED.value,
                entry.tadoku_remote_id if entry else None,
                "claim_failed",
            )
        entry = claimed
        claim = entry.tadoku_remote_id

    ok, remote_id, err = client.submit(entry)
    if ok:
        entry.tadoku_status = TadokuStatus.PUSHED.value
        entry.tadoku_remote_id = remote_id
        if err and err != "already_submitted":
            entry.notes = (entry.notes or "") + f"\n[tadoku] {err}"
    else:
        entry.tadoku_status = TadokuStatus.FAILED.value
        # Drop claim so retry can re-claim
        if entry.tadoku_remote_id == claim:
            entry.tadoku_remote_id = None
        entry.notes = (entry.notes or "") + f"\n[tadoku] {err}"
    entry.updated_at = utcnow()
    db.commit()
    db.refresh(entry)
    _mark_sheets_dirty_safe(db)
    return ok, remote_id if ok else entry.tadoku_remote_id, err


def _maybe_complete_gsm_export(db: Session) -> None:
    """Advance GSM/local export watermark when a queued GSM batch is fully done."""
    try:
        from app.ingest.gsm import finish_pending_export_work

        result = finish_pending_export_work(db)
        if result.get("advanced") or result.get("synced"):
            logger.info("gsm export cursor advanced/synced: %s", result)
    except Exception:  # noqa: BLE001
        logger.debug("gsm export completion check failed", exc_info=True)


def approve(db: Session, log_id: int) -> Optional[LogEntry]:
    """
    Mark ready; if tadoku.auto_submit_on_approve, immediately submit to tadoku.app
    (using saved contest registration). Idempotent if already pushed.
    """
    entry = db.get(LogEntry, log_id)
    if not entry:
        return None

    if entry.tadoku_status == TadokuStatus.SKIPPED.value:
        return entry

    if _already_submitted(entry):
        return _restore_pushed_if_remote(db, entry)

    if entry.tadoku_status == TadokuStatus.PUSHED.value:
        return entry

    cfg = get_settings().yaml_config.tadoku
    if cfg.auto_submit_on_approve:
        # Claim + submit without leaving a long READY window for the scheduler
        _submit_entry(db, entry, TadokuClient())
        _maybe_complete_gsm_export(db)
        return db.get(LogEntry, log_id)

    entry.tadoku_status = TadokuStatus.READY.value
    entry.updated_at = utcnow()
    db.commit()
    db.refresh(entry)
    _mark_sheets_dirty_safe(db)
    return entry


def approve_many(db: Session, log_ids: list[int]) -> dict:
    """Approve (+ submit) many logs in id order (stable for episode sequences)."""
    client = TadokuClient()
    cfg = get_settings().yaml_config.tadoku
    results = []
    pushed = failed = skipped = 0
    for log_id in sorted(set(log_ids)):
        entry = db.get(LogEntry, log_id)
        if not entry:
            results.append({"id": log_id, "status": "missing"})
            failed += 1
            continue
        if entry.tadoku_status == TadokuStatus.SKIPPED.value:
            results.append(
                {
                    "id": log_id,
                    "status": entry.tadoku_status,
                    "remote_id": entry.tadoku_remote_id,
                }
            )
            skipped += 1
            continue
        if _already_submitted(entry) or entry.tadoku_status == TadokuStatus.PUSHED.value:
            entry = _restore_pushed_if_remote(db, entry)
            results.append(
                {
                    "id": log_id,
                    "status": "pushed",
                    "remote_id": entry.tadoku_remote_id,
                    "note": "already_submitted",
                }
            )
            skipped += 1
            continue

        if cfg.auto_submit_on_approve:
            ok, remote_id, err = _submit_entry(db, entry, client)
            if ok:
                pushed += 1
                results.append(
                    {
                        "id": log_id,
                        "status": "pushed",
                        "remote_id": remote_id,
                        "note": err if err == "already_submitted" else None,
                    }
                )
            else:
                failed += 1
                results.append({"id": log_id, "status": "failed", "error": err})
        else:
            entry.tadoku_status = TadokuStatus.READY.value
            entry.updated_at = utcnow()
            db.commit()
            results.append({"id": log_id, "status": "ready"})
    _mark_sheets_dirty_safe(db)
    if pushed or skipped:
        _maybe_complete_gsm_export(db)
    return {
        "pushed": pushed,
        "failed": failed,
        "skipped": skipped,
        "results": results,
    }


def skip(db: Session, log_id: int) -> Optional[LogEntry]:
    entry = db.get(LogEntry, log_id)
    if not entry:
        return None
    entry.tadoku_status = TadokuStatus.SKIPPED.value
    entry.tadoku_mode = "never"
    entry.updated_at = utcnow()
    db.commit()
    db.refresh(entry)
    _mark_sheets_dirty_safe(db)
    _maybe_complete_gsm_export(db)
    return entry


def skip_many(db: Session, log_ids: list[int]) -> dict:
    skipped = 0
    for log_id in set(log_ids):
        if skip(db, log_id):
            skipped += 1
    if skipped:
        _maybe_complete_gsm_export(db)
    return {"skipped": skipped}


def promote_auto_pending(db: Session) -> int:
    """
    tadoku_mode=auto means submit without Approve. Sheet rows often keep a stale
    tadoku_status=pending next to mode=auto — promote those to ready so process_ready
    (and the scheduler) will post them.
    Never promotes rows that already have a real Tadoku remote id.
    """
    rows = (
        db.query(LogEntry)
        .filter(
            LogEntry.tadoku_mode == "auto",
            LogEntry.tadoku_status == TadokuStatus.PENDING.value,
        )
        .all()
    )
    n = 0
    for entry in rows:
        if _already_submitted(entry):
            _restore_pushed_if_remote(db, entry)
            continue
        entry.tadoku_status = TadokuStatus.READY.value
        entry.updated_at = utcnow()
        n += 1
    if n:
        db.commit()
        _mark_sheets_dirty_safe(db)
    return n


def process_ready(db: Session, client: Optional[TadokuClient] = None) -> dict:
    """Push READY entries via Tadoku client (live API and/or local export)."""
    client = client or TadokuClient()
    promoted = promote_auto_pending(db)
    ready = (
        db.query(LogEntry)
        .filter(LogEntry.tadoku_status == TadokuStatus.READY.value)
        .order_by(LogEntry.timestamp.asc())
        .all()
    )
    pushed = 0
    failed = 0
    skipped = 0
    results = []
    for entry in ready:
        if _already_submitted(entry):
            _restore_pushed_if_remote(db, entry)
            skipped += 1
            results.append(
                {
                    "id": entry.id,
                    "status": "pushed",
                    "remote_id": entry.tadoku_remote_id,
                    "note": "already_submitted",
                }
            )
            continue
        # Skip rows claimed by another in-flight submit
        rid = entry.tadoku_remote_id or ""
        if rid.startswith(_CLAIM_PREFIX):
            skipped += 1
            results.append({"id": entry.id, "status": "claim_held", "remote_id": rid})
            continue

        ok, remote_id, err = _submit_entry(db, entry, client)
        if ok:
            pushed += 1
            results.append(
                {
                    "id": entry.id,
                    "status": "pushed",
                    "remote_id": remote_id,
                    "note": err if err in ("already_submitted", "claim_failed") else None,
                }
            )
        else:
            failed += 1
            results.append({"id": entry.id, "status": "failed", "error": err})
    # Always retry GSM export completion / local→GSM cursor sync (even with an
    # empty READY queue — e.g. manual-mode submit already pushed, file was locked).
    _maybe_complete_gsm_export(db)
    return {
        "promoted_auto": promoted,
        "pushed": pushed,
        "failed": failed,
        "skipped": skipped,
        "results": results,
    }
