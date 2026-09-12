"""
Hoshi reading buckets + session fragments.

Drive/ADB polls detect character deltas and **accumulate** them here.
Formal immersion logs are created only when:

  - log_mode is ``auto`` and pending chars ≥ ``min_submit_characters``, or
  - the user manually submits a bucket (or selected fragments).
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import HoshiBookBucket, HoshiSessionFragment, LogEntry, utcnow
from app.ingest.hoshi import series_key_for_title
from app.ingest.service import DuplicateLogError, create_log
from app.sheets.state import get_state, set_state
from app.tadoku.rules import estimate_score

logger = logging.getLogger(__name__)

SOURCE = "hoshi"
STATUS_PENDING = "pending"
STATUS_LOGGED = "logged"
STATUS_DISCARDED = "discarded"

# Runtime overrides (UI) — take precedence over settings.yaml
PREF_LOG_MODE = "hoshi:pref:log_mode"
PREF_MIN_SUBMIT = "hoshi:pref:min_submit_characters"
PREF_IDLE_MINUTES = "hoshi:pref:auto_submit_idle_minutes"


def _cfg():
    return get_settings().yaml_config.hoshi


def get_log_mode(db: Optional[Session] = None) -> str:
    if db is not None:
        raw = (get_state(db, PREF_LOG_MODE) or "").strip().lower()
        if raw in ("manual", "auto", "automatic", "pending"):
            # "pending" alias = manual (UI wording)
            return "manual" if raw == "pending" else ("auto" if raw == "automatic" else raw)
    return (_cfg().log_mode or "manual").strip().lower() or "manual"


def get_global_min_submit(db: Optional[Session] = None) -> int:
    if db is not None:
        raw = (get_state(db, PREF_MIN_SUBMIT) or "").strip()
        if raw:
            try:
                return max(1, int(raw))
            except ValueError:
                pass
    return max(1, int(_cfg().min_submit_characters or 500))


def get_idle_minutes(db: Optional[Session] = None) -> float:
    if db is not None:
        raw = (get_state(db, PREF_IDLE_MINUTES) or "").strip()
        if raw:
            try:
                return max(0.0, float(raw))
            except ValueError:
                pass
    return max(0.0, float(_cfg().auto_submit_idle_minutes or 0.0))


def set_reading_prefs(
    db: Session,
    *,
    log_mode: Optional[str] = None,
    min_submit_characters: Optional[int] = None,
    auto_submit_idle_minutes: Optional[float] = None,
) -> dict[str, Any]:
    if log_mode is not None:
        m = str(log_mode).strip().lower()
        if m in ("pending", "manual"):
            m = "manual"
        elif m in ("auto", "automatic"):
            m = "auto"
        else:
            raise ValueError("log_mode must be manual/pending or auto")
        set_state(db, PREF_LOG_MODE, m)
    if min_submit_characters is not None:
        set_state(db, PREF_MIN_SUBMIT, str(max(1, int(min_submit_characters))))
    if auto_submit_idle_minutes is not None:
        set_state(db, PREF_IDLE_MINUTES, str(max(0.0, float(auto_submit_idle_minutes))))
    return {
        "log_mode": get_log_mode(db),
        "min_submit_characters": get_global_min_submit(db),
        "auto_submit_idle_minutes": get_idle_minutes(db),
    }


def effective_min_submit(db: Session, bucket: HoshiBookBucket) -> int:
    if bucket.min_submit_characters is not None:
        return max(1, int(bucket.min_submit_characters))
    return get_global_min_submit(db)


def _idle_minutes(db: Optional[Session] = None) -> float:
    return get_idle_minutes(db)


def _as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def bucket_idle_seconds(bucket: HoshiBookBucket) -> Optional[float]:
    """Seconds since last session fragment; None if never had a session."""
    last = _as_utc(bucket.last_session_at)
    if last is None:
        return None
    return max(0.0, (utcnow() - last).total_seconds())


def bucket_meets_auto_threshold(
    bucket: HoshiBookBucket, db: Optional[Session] = None
) -> bool:
    min_submit = (
        effective_min_submit(db, bucket)
        if db is not None
        else max(1, int(_cfg().min_submit_characters or 500))
    )
    return float(bucket.pending_chars or 0) >= min_submit


def bucket_is_idle_enough(
    bucket: HoshiBookBucket, db: Optional[Session] = None
) -> bool:
    """True if quiet long enough for auto-submit (or idle wait disabled)."""
    idle_m = _idle_minutes(db)
    if idle_m <= 0:
        return True
    idle_s = bucket_idle_seconds(bucket)
    if idle_s is None:
        return False
    return idle_s >= idle_m * 60.0


def get_or_create_bucket(
    db: Session,
    *,
    folder_id: str,
    title: str,
) -> HoshiBookBucket:
    row = (
        db.query(HoshiBookBucket)
        .filter(HoshiBookBucket.folder_id == folder_id)
        .one_or_none()
    )
    if row:
        if title and row.title != title:
            row.title = title
            row.series_key = series_key_for_title(title)
            row.updated_at = utcnow()
        return row
    row = HoshiBookBucket(
        folder_id=folder_id,
        title=title or folder_id,
        series_key=series_key_for_title(title or folder_id),
    )
    db.add(row)
    db.flush()
    return row


def add_session_fragment(
    db: Session,
    *,
    folder_id: str,
    title: str,
    date_key: str,
    chars: float,
    seconds: float = 0.0,
    remote_total_for_day: int = 0,
    notes: str = "",
    position_chars: Optional[int] = None,
    book_total_chars: Optional[int] = None,
    dry_run: bool = False,
) -> tuple[HoshiBookBucket, HoshiSessionFragment, Optional[Any]]:
    """
    Append a poll delta to the book bucket.

    Returns (bucket, fragment, auto_submitted LogEntry or None).
    """
    if chars <= 0:
        raise ValueError("chars must be > 0")

    if dry_run:
        # Fake objects for dry-run callers
        bucket = HoshiBookBucket(
            folder_id=folder_id,
            title=title,
            series_key=series_key_for_title(title),
            pending_chars=chars,
            pending_seconds=seconds,
            session_count=1,
            last_session_chars=chars,
        )
        frag = HoshiSessionFragment(
            bucket_id=0,
            folder_id=folder_id,
            title=title,
            date_key=date_key,
            chars=chars,
            seconds=seconds,
            remote_total_for_day=remote_total_for_day,
            status=STATUS_PENDING,
            notes=notes or None,
        )
        return bucket, frag, None

    bucket = get_or_create_bucket(db, folder_id=folder_id, title=title)
    if position_chars is not None:
        bucket.position_chars = int(position_chars)
    if book_total_chars is not None:
        bucket.book_total_chars = int(book_total_chars)

    frag = HoshiSessionFragment(
        bucket_id=bucket.id,
        folder_id=folder_id,
        title=title or bucket.title,
        date_key=date_key,
        chars=float(chars),
        seconds=float(seconds or 0.0),
        remote_total_for_day=int(remote_total_for_day or 0),
        status=STATUS_PENDING,
        notes=notes or None,
    )
    db.add(frag)

    bucket.pending_chars = float(bucket.pending_chars or 0) + float(chars)
    bucket.pending_seconds = float(bucket.pending_seconds or 0) + float(seconds or 0)
    bucket.session_count = int(bucket.session_count or 0) + 1
    bucket.last_session_chars = float(chars)
    bucket.last_session_at = utcnow()
    bucket.updated_at = utcnow()
    db.commit()
    db.refresh(bucket)
    db.refresh(frag)

    entry = maybe_auto_submit_bucket(db, bucket)
    if entry is not None:
        db.refresh(bucket)
    return bucket, frag, entry


def maybe_auto_submit_bucket(db: Session, bucket: HoshiBookBucket) -> Optional[Any]:
    """
    Auto-submit only when:
      - log_mode is auto
      - pending chars ≥ per-book or global min_submit_characters
      - no new session fragment for auto_submit_idle_minutes (session settled)

    Mid-read uploads (page-turn stats) only grow the bucket; they do not log
    until reading has been quiet for the idle window.
    """
    mode = get_log_mode(db)
    if mode not in ("auto", "automatic"):
        return None
    if not bucket_meets_auto_threshold(bucket, db):
        return None
    if not bucket_is_idle_enough(bucket, db):
        idle_s = bucket_idle_seconds(bucket)
        need = _idle_minutes(db) * 60.0
        logger.debug(
            "hoshi bucket %s threshold met but still active "
            "(idle %.0fs / need %.0fs) — defer auto-submit",
            bucket.id,
            idle_s or 0,
            need,
        )
        return None
    return submit_bucket(db, bucket.id, force=True)


def process_auto_submit_idle_buckets(db: Session) -> list[dict[str, Any]]:
    """
    Submit any auto-mode buckets that hit threshold and finished the idle window.

    Call after each Hoshi poll and on a light schedule so sessions that stop
    receiving updates still get logged without another page turn.
    """
    mode = get_log_mode(db)
    if mode not in ("auto", "automatic"):
        return []

    submitted: list[dict[str, Any]] = []
    for bucket in list_buckets(db, pending_only=True):
        if not bucket_meets_auto_threshold(bucket, db):
            continue
        if not bucket_is_idle_enough(bucket, db):
            continue
        entry = submit_bucket(db, bucket.id, force=True)
        if entry:
            submitted.append(
                {
                    "bucket_id": bucket.id,
                    "title": bucket.title,
                    "log_id": entry.id,
                    "amount": entry.amount,
                }
            )
    if submitted:
        logger.info(
            "hoshi idle auto-submit: %s bucket(s)",
            len(submitted),
        )
    return submitted


def pending_fragments(db: Session, bucket_id: int) -> list[HoshiSessionFragment]:
    return (
        db.query(HoshiSessionFragment)
        .filter(
            HoshiSessionFragment.bucket_id == bucket_id,
            HoshiSessionFragment.status == STATUS_PENDING,
        )
        .order_by(HoshiSessionFragment.id.asc())
        .all()
    )


def submit_bucket(
    db: Session,
    bucket_id: int,
    *,
    force: bool = False,
    min_chars: Optional[float] = None,
) -> Optional[Any]:
    """
    Create a LogEntry from all pending fragments on a bucket.

    ``force=True`` allows submit below auto threshold (manual UI).
    """
    bucket = db.get(HoshiBookBucket, bucket_id)
    if not bucket:
        return None
    frags = pending_fragments(db, bucket_id)
    if not frags:
        return None

    total_chars = sum(float(f.chars or 0) for f in frags)
    total_secs = sum(float(f.seconds or 0) for f in frags)
    if total_chars <= 0:
        return None

    cfg = _cfg()
    if not force:
        threshold = (
            float(min_chars)
            if min_chars is not None
            else float(effective_min_submit(db, bucket))
        )
        if total_chars < threshold:
            return None

    date_keys = sorted({f.date_key for f in frags if f.date_key})
    notes_parts = [
        f"Hoshi reading bucket: {len(frags)} session(s)",
        f"{int(total_chars)} chars",
    ]
    if total_secs > 0:
        notes_parts.append(f"{int(total_secs)}s tracked")
    if date_keys:
        notes_parts.append("days " + ",".join(date_keys))
    if bucket.position_chars is not None:
        pos = f"pos {bucket.position_chars}"
        if bucket.book_total_chars:
            pos += f"/{bucket.book_total_chars}"
        notes_parts.append(pos)

    # Timestamp: latest fragment day noon UTC, else now
    ts: Optional[datetime] = None
    if date_keys:
        try:
            y, m, d = (int(x) for x in date_keys[-1].split("-", 2))
            ts = datetime(y, m, d, 12, 0, 0, tzinfo=timezone.utc)
        except ValueError:
            ts = None

    tadoku = (cfg.tadoku_default or "").strip() or None
    source_ref = f"hoshi:bucket:{bucket.id}:{int(utcnow().timestamp())}:{int(total_chars)}"

    try:
        entry = create_log(
            db,
            content_type=cfg.content_type or "book",
            title=bucket.title or "Hoshi book",
            source=SOURCE,
            amount=float(total_chars),
            unit=cfg.unit or "characters",
            activity="reading",
            series_key=bucket.series_key or series_key_for_title(bucket.title),
            source_ref=source_ref,
            notes="; ".join(notes_parts),
            tags="hoshi,reading",
            timestamp=ts,
            tadoku_mode_override=tadoku,
        )
    except DuplicateLogError as e:
        entry = e.existing

    for f in frags:
        f.status = STATUS_LOGGED
        f.log_id = entry.id

    bucket.pending_chars = 0.0
    bucket.pending_seconds = 0.0
    bucket.session_count = 0
    bucket.total_logged_chars = float(bucket.total_logged_chars or 0) + float(total_chars)
    bucket.total_logged_seconds = float(bucket.total_logged_seconds or 0) + float(
        total_secs
    )
    bucket.submit_count = int(bucket.submit_count or 0) + 1
    bucket.last_log_id = entry.id
    # Progress-bar marker: bookmark at the moment this batch entered the log/Tadoku queue
    if bucket.position_chars is not None:
        bucket.last_logged_position_chars = int(bucket.position_chars)
        # Submitted progress is fully counted
        cur_c = bucket.credited_position_chars
        if cur_c is None or int(bucket.position_chars) > int(cur_c):
            bucket.credited_position_chars = int(bucket.position_chars)
    bucket.updated_at = utcnow()
    db.commit()
    db.refresh(entry)
    logger.info(
        "hoshi bucket %s submitted %s chars → log %s",
        bucket.id,
        int(total_chars),
        entry.id,
    )
    return entry


def discard_bucket(db: Session, bucket_id: int) -> bool:
    """Drop pending fragments without logging."""
    bucket = db.get(HoshiBookBucket, bucket_id)
    if not bucket:
        return False
    frags = pending_fragments(db, bucket_id)
    for f in frags:
        f.status = STATUS_DISCARDED
    bucket.pending_chars = 0.0
    bucket.pending_seconds = 0.0
    bucket.session_count = 0
    bucket.updated_at = utcnow()
    db.commit()
    return True


def _open_hoshi_logs_for_bucket(db: Session, bucket: HoshiBookBucket) -> list[LogEntry]:
    """Hoshi character logs not yet successfully on Tadoku for this book."""
    sk = (bucket.series_key or series_key_for_title(bucket.title or "")).strip()
    q = db.query(LogEntry).filter(
        LogEntry.source == SOURCE,
        LogEntry.unit == "characters",
        LogEntry.tadoku_status.in_(["pending", "ready", "failed"]),
    )
    if sk:
        q = q.filter(LogEntry.series_key == sk)
    else:
        return []
    return q.order_by(LogEntry.id.asc()).all()


def consolidate_bucket_for_tadoku(db: Session, bucket_id: int) -> Optional[LogEntry]:
    """
    Merge buffer + all open (pending/ready/failed) Hoshi logs into **one** log.

    Old open logs are marked skipped (merged). Returns the single combined log,
    or None if there is nothing to log.
    """
    bucket = db.get(HoshiBookBucket, bucket_id)
    if not bucket:
        return None

    # 1) Fold any unlogged Hoshi buffer into a temporary formal log first
    if float(bucket.pending_chars or 0) > 0:
        submit_bucket(db, bucket_id, force=True)
        db.refresh(bucket)

    open_logs = _open_hoshi_logs_for_bucket(db, bucket)
    if not open_logs:
        return None

    total_chars = sum(float(e.amount or 0) for e in open_logs)
    if total_chars <= 0:
        return None

    # If already exactly one open log, reuse it (reset failed → pending)
    if len(open_logs) == 1:
        only = open_logs[0]
        if only.tadoku_status == "failed":
            only.tadoku_status = "pending"
            only.tadoku_remote_id = None
            only.updated_at = utcnow()
            db.commit()
            db.refresh(only)
        return only

    # 2) Build one combined log, skip the rest
    old_ids = [int(e.id) for e in open_logs]
    date_keys: list[str] = []
    for e in open_logs:
        if e.timestamp:
            try:
                date_keys.append(e.timestamp.strftime("%Y-%m-%d"))
            except Exception:  # noqa: BLE001
                pass
        # parse dateKey from notes if present
        if e.notes:
            for m in re.finditer(r"(20\d{2}-\d{2}-\d{2})", e.notes):
                date_keys.append(m.group(1))
    date_keys = sorted(set(date_keys))
    ts = None
    if date_keys:
        try:
            y, m, d = (int(x) for x in date_keys[-1].split("-", 2))
            ts = datetime(y, m, d, 12, 0, 0, tzinfo=timezone.utc)
        except ValueError:
            ts = None

    cfg = _cfg()
    tadoku = (cfg.tadoku_default or "").strip() or None
    notes = (
        f"Hoshi combined log: {int(total_chars)} chars from {len(open_logs)} prior "
        f"log(s) #{','.join(str(i) for i in old_ids)}"
    )
    if date_keys:
        notes += f"; days {','.join(date_keys)}"
    if bucket.position_chars is not None:
        pos = f"pos {bucket.position_chars}"
        if bucket.book_total_chars:
            pos += f"/{bucket.book_total_chars}"
        notes += f"; {pos}"

    source_ref = (
        f"hoshi:combined:{bucket.id}:{int(utcnow().timestamp())}:{int(total_chars)}"
    )
    try:
        combined = create_log(
            db,
            content_type=cfg.content_type or "book",
            title=bucket.title or "Hoshi book",
            source=SOURCE,
            amount=float(total_chars),
            unit=cfg.unit or "characters",
            activity="reading",
            series_key=bucket.series_key or series_key_for_title(bucket.title),
            source_ref=source_ref,
            notes=notes,
            tags="hoshi,reading,combined",
            timestamp=ts,
            tadoku_mode_override=tadoku or "pending",
        )
    except DuplicateLogError as e:
        combined = e.existing

    # Avoid double-counting total_logged_chars: buffer was already added in
    # submit_bucket; old open logs already counted when first created.
    # Do not add total_chars again here.

    for e in open_logs:
        if e.id == combined.id:
            continue
        e.tadoku_status = "skipped"
        e.tadoku_mode = "never"
        e.tadoku_remote_id = None
        extra = f"[merged into log #{combined.id}]"
        e.notes = ((e.notes or "").rstrip() + "\n" + extra).strip()
        e.updated_at = utcnow()

    bucket.last_log_id = combined.id
    if bucket.position_chars is not None:
        bucket.last_logged_position_chars = int(bucket.position_chars)
        cur_c = bucket.credited_position_chars
        if cur_c is None or int(bucket.position_chars) > int(cur_c):
            bucket.credited_position_chars = int(bucket.position_chars)
    bucket.updated_at = utcnow()
    db.commit()
    db.refresh(combined)
    logger.info(
        "hoshi bucket %s consolidated %s logs → log %s (%s chars)",
        bucket.id,
        len(open_logs),
        combined.id,
        int(total_chars),
    )
    return combined


def log_bucket_to_tadoku(db: Session, bucket_id: int) -> dict[str, Any]:
    """
    Manual force: one combined log of all chars since last Tadoku success,
    then push that single log to tadoku.app.

    Ignores min_submit_characters. After success, not-on-Tadoku ≈ 0; auto mode
    must accumulate to the min threshold again before auto-logging.
    """
    from app.tadoku.client import TadokuClient
    from app.tadoku.queue import _submit_entry

    bucket = db.get(HoshiBookBucket, bucket_id)
    if not bucket:
        return {"ok": False, "reason": "bucket not found", "chars_logged": 0.0}

    combined = consolidate_bucket_for_tadoku(db, bucket_id)
    db.refresh(bucket)
    if combined is None:
        return {
            "ok": False,
            "reason": "nothing to log to Tadoku",
            "bucket_id": bucket_id,
            "title": bucket.title,
            "created_log_ids": [],
            "pushed": 0,
            "failed": 0,
            "chars_logged": 0.0,
            "chars_failed": 0.0,
            "results": [],
            "bucket": bucket_to_dict(db, bucket),
        }

    client = TadokuClient()
    ok, remote_id, err = _submit_entry(db, combined, client)
    amt = float(combined.amount or 0)
    results = [
        {
            "log_id": combined.id,
            "amount": amt,
            "status": "pushed" if ok else "failed",
            "remote_id": remote_id,
            "error": None if ok else err,
            "note": err if ok else None,
        }
    ]
    db.refresh(bucket)
    return {
        "ok": ok,
        "bucket_id": bucket_id,
        "title": bucket.title,
        "created_log_ids": [int(combined.id)],
        "combined_log_id": int(combined.id),
        "pushed": 1 if ok else 0,
        "failed": 0 if ok else 1,
        "chars_logged": amt if ok else 0.0,
        "chars_failed": 0.0 if ok else amt,
        "results": results,
        "reason": None if ok else (err or "Tadoku push failed"),
        "bucket": bucket_to_dict(db, bucket),
    }


def log_all_to_tadoku(db: Session) -> dict[str, Any]:
    """Force log every book that has chars not yet on Tadoku."""
    out = []
    total_chars = 0.0
    total_failed = 0.0
    for b in list_buckets(db, pending_only=False):
        # Skip books with nothing pending and no awaiting logs
        stats = tadoku_char_stats_for_series(db, b.series_key)
        unlogged = float(b.pending_chars or 0)
        awaiting = float(stats.get("tadoku_awaiting_chars") or 0)
        if unlogged <= 0 and awaiting <= 0:
            continue
        r = log_bucket_to_tadoku(db, b.id)
        out.append(r)
        total_chars += float(r.get("chars_logged") or 0)
        total_failed += float(r.get("chars_failed") or 0)
    return {
        "ok": True,
        "books": len(out),
        "chars_logged": total_chars,
        "chars_failed": total_failed,
        "results": out,
    }


def _logged_position_floor(bucket: HoshiBookBucket, position: int) -> int:
    """
    Progress already in formal logs (not the unlogged buffer).

    Prefer last-log bookmark; else sequential assumption from total_logged_chars.
    """
    if bucket.last_logged_position_chars is not None:
        return max(0, min(int(position), int(bucket.last_logged_position_chars)))
    logged = float(bucket.total_logged_chars or 0)
    if logged > 0:
        return max(0, min(int(position), int(logged)))
    return 0


def ensure_credited_position(
    db: Session,
    folder_id: str,
    *,
    title: str = "",
    position_chars: int,
    dry_run: bool = False,
) -> int:
    """
    Return high-water of progress already counted (logs + unlogged buffer).

    Initializes from log floor + current pending when unset.
    """
    if dry_run:
        return 0
    bucket = get_or_create_bucket(db, folder_id=folder_id, title=title or folder_id)
    pos = max(0, int(position_chars))
    if bucket.credited_position_chars is None:
        log_floor = _logged_position_floor(bucket, pos)
        pending = float(bucket.pending_chars or 0)
        bucket.credited_position_chars = min(pos, log_floor + int(round(pending)))
        bucket.updated_at = utcnow()
        db.commit()
        db.refresh(bucket)
    return max(0, int(bucket.credited_position_chars or 0))


def set_credited_position(
    db: Session,
    folder_id: str,
    position_chars: int,
    *,
    title: str = "",
) -> None:
    """Raise the credited high-water mark (never lower it)."""
    bucket = get_or_create_bucket(db, folder_id=folder_id, title=title or folder_id)
    pos = max(0, int(position_chars))
    cur = bucket.credited_position_chars
    if cur is None or pos > int(cur):
        bucket.credited_position_chars = pos
        bucket.updated_at = utcnow()
        db.commit()


def reconcile_bucket_pending_to_position(
    db: Session, bucket: HoshiBookBucket
) -> bool:
    """
    Clamp unlogged buffer so it cannot exceed new bookmark progress past logs.

    Re-reads inflate Hoshi day counters; pending may already be too high.
    Max unlogged ≈ position − logged_floor (not position − credited, since
    credited already includes pending).
    """
    if bucket.position_chars is None:
        return False
    pos = max(0, int(bucket.position_chars))
    log_floor = _logged_position_floor(bucket, pos)
    allowed = max(0, pos - log_floor)
    pending = float(bucket.pending_chars or 0)
    changed = False

    if pending > allowed + 0.01:
        frags = pending_fragments(db, bucket.id)
        excess = pending - allowed
        for f in frags:
            if excess <= 0.01:
                break
            fc = float(f.chars or 0)
            if fc <= excess + 0.01:
                f.status = STATUS_DISCARDED
                excess -= fc
                pending -= fc
            else:
                f.chars = fc - excess
                note = (f.notes or "").strip()
                extra = "trimmed re-read"
                f.notes = f"{note} · {extra}" if note else extra
                pending -= excess
                excess = 0
        bucket.pending_chars = max(0.0, float(pending))
        live = pending_fragments(db, bucket.id)
        bucket.session_count = len(live)
        if not live:
            bucket.last_session_chars = 0.0
        changed = True
        logger.info(
            "hoshi bucket %s re-read clamp: pending → %s (allowed %s at pos %s)",
            bucket.id,
            int(bucket.pending_chars),
            allowed,
            pos,
        )

    # credited = logs + remaining unlogged buffer (≤ bookmark)
    new_credited = min(
        pos, log_floor + int(round(float(bucket.pending_chars or 0)))
    )
    # Never lower an already-higher watermark without reason; but after clamp
    # we must set exactly so re-reads don't re-credit.
    if bucket.credited_position_chars is None or int(
        bucket.credited_position_chars
    ) != new_credited:
        bucket.credited_position_chars = new_credited
        changed = True

    if changed:
        bucket.updated_at = utcnow()
        db.commit()
        db.refresh(bucket)
    return changed


def update_bucket_progress(
    db: Session,
    folder_id: str,
    *,
    title: str = "",
    position_chars: Optional[int] = None,
    book_total_chars: Optional[int] = None,
    reconcile: bool = True,
) -> None:
    bucket = get_or_create_bucket(db, folder_id=folder_id, title=title or folder_id)
    if position_chars is not None:
        bucket.position_chars = int(position_chars)
    if book_total_chars is not None:
        bucket.book_total_chars = int(book_total_chars)
    bucket.updated_at = utcnow()
    db.commit()
    if reconcile and bucket.position_chars is not None:
        reconcile_bucket_pending_to_position(db, bucket)


def list_buckets(db: Session, *, pending_only: bool = False) -> list[HoshiBookBucket]:
    q = db.query(HoshiBookBucket)
    if pending_only:
        q = q.filter(HoshiBookBucket.pending_chars > 0)
    return q.order_by(
        HoshiBookBucket.pending_chars.desc(),
        HoshiBookBucket.updated_at.desc(),
    ).all()


def _parse_pos_from_log_notes(notes: Optional[str]) -> Optional[int]:
    """Extract ``pos N`` or ``pos N/total`` from Hoshi log notes."""
    if not notes:
        return None
    m = re.search(r"\bpos\s+(\d+)", str(notes), flags=re.IGNORECASE)
    if not m:
        return None
    try:
        return max(0, int(m.group(1)))
    except ValueError:
        return None


def backfill_logged_totals_from_logs(db: Session) -> int:
    """
    Sync bucket.total_logged_chars from existing hoshi LogEntries.

    Older path logged without updating bucket totals — Reading UI would show
    position only. Returns number of buckets updated.
    """
    logs = (
        db.query(LogEntry)
        .filter(LogEntry.source == SOURCE, LogEntry.unit == "characters")
        .order_by(LogEntry.id.asc())
        .all()
    )
    if not logs:
        return 0

    # Aggregate by series_key and title
    by_series: dict[str, float] = {}
    by_title: dict[str, float] = {}
    count_by_series: dict[str, int] = {}
    last_id_by_series: dict[str, int] = {}
    last_pos_by_series: dict[str, int] = {}
    for e in logs:
        amt = float(e.amount or 0)
        pos = _parse_pos_from_log_notes(e.notes)
        if e.series_key:
            by_series[e.series_key] = by_series.get(e.series_key, 0.0) + amt
            count_by_series[e.series_key] = count_by_series.get(e.series_key, 0) + 1
            last_id_by_series[e.series_key] = e.id
            if pos is not None:
                last_pos_by_series[e.series_key] = pos
        t = (e.title or "").strip()
        if t:
            by_title[t] = by_title.get(t, 0.0) + amt

    updated = 0
    for bucket in db.query(HoshiBookBucket).all():
        total = 0.0
        submits = 0
        last_id = bucket.last_log_id
        last_pos = bucket.last_logged_position_chars
        if bucket.series_key and bucket.series_key in by_series:
            total = by_series[bucket.series_key]
            submits = count_by_series.get(bucket.series_key, 0)
            last_id = last_id_by_series.get(bucket.series_key, last_id)
            if bucket.series_key in last_pos_by_series:
                last_pos = last_pos_by_series[bucket.series_key]
        elif bucket.title and bucket.title in by_title:
            total = by_title[bucket.title]
        else:
            # try series_key from title
            sk = series_key_for_title(bucket.title)
            if sk in by_series:
                total = by_series[sk]
                submits = count_by_series.get(sk, 0)
                last_id = last_id_by_series.get(sk, last_id)
                if sk in last_pos_by_series:
                    last_pos = last_pos_by_series[sk]
        changed = False
        if abs(float(bucket.total_logged_chars or 0) - total) > 0.01 or (
            total > 0 and int(bucket.submit_count or 0) == 0 and submits > 0
        ):
            bucket.total_logged_chars = total
            if submits > int(bucket.submit_count or 0):
                bucket.submit_count = submits
            if last_id:
                bucket.last_log_id = last_id
            changed = True
        if (
            last_pos is not None
            and bucket.last_logged_position_chars != last_pos
        ):
            bucket.last_logged_position_chars = int(last_pos)
            changed = True
        if changed:
            bucket.updated_at = utcnow()
            updated += 1
    if updated:
        db.commit()
    return updated


def update_bucket_settings(
    db: Session,
    bucket_id: int,
    *,
    min_submit_characters: Optional[int] = None,
    clear_min_submit: bool = False,
    title: Optional[str] = None,
) -> Optional[HoshiBookBucket]:
    bucket = db.get(HoshiBookBucket, bucket_id)
    if not bucket:
        return None
    if clear_min_submit:
        bucket.min_submit_characters = None
    elif min_submit_characters is not None:
        bucket.min_submit_characters = max(1, int(min_submit_characters))
    if title is not None and title.strip():
        bucket.title = title.strip()
        bucket.series_key = series_key_for_title(bucket.title)
    bucket.updated_at = utcnow()
    db.commit()
    db.refresh(bucket)
    return bucket


# Log statuses that still need user/queue action before they are on Tadoku
_TADOKU_AWAITING = frozenset({"pending", "ready", "failed"})
_TADOKU_PUSHED = frozenset({"pushed"})
_TADOKU_SKIPPED = frozenset({"skipped", "n/a", "na"})


def list_logs_for_series(
    db: Session, series_key: Optional[str], *, limit: int = 50
) -> list[dict[str, Any]]:
    """Formal immersion logs for a book (shown in Reading UI history)."""
    sk = (series_key or "").strip()
    if not sk:
        return []
    rows = (
        db.query(LogEntry)
        .filter(
            LogEntry.source == SOURCE,
            LogEntry.series_key == sk,
            LogEntry.unit == "characters",
        )
        .order_by(LogEntry.timestamp.asc(), LogEntry.id.asc())
        .limit(max(1, min(200, int(limit))))
        .all()
    )
    out: list[dict[str, Any]] = []
    for e in rows:
        ts = e.timestamp
        day = ""
        if ts is not None:
            try:
                day = ts.strftime("%Y-%m-%d")
            except Exception:  # noqa: BLE001
                day = str(ts)[:10]
        out.append(
            {
                "id": e.id,
                "timestamp": ts.isoformat() if ts else None,
                "date_key": day,
                "chars": float(e.amount or 0),
                "tadoku_status": e.tadoku_status,
                "tadoku_score_estimate": float(e.tadoku_score_estimate or 0),
                "notes": e.notes,
            }
        )
    return out


def tadoku_char_stats_for_series(
    db: Session, series_key: Optional[str]
) -> dict[str, float]:
    """
    Sum character amounts + score estimates from formal Hoshi LogEntries.

    This is what users care about for Tadoku — not Hoshi session-fragment
    buffers (bucket.pending_chars), which are pre-log internal state.
    """
    empty = {
        "tadoku_awaiting_chars": 0.0,
        "tadoku_pushed_chars": 0.0,
        "tadoku_skipped_chars": 0.0,
        "tadoku_log_chars": 0.0,
        "tadoku_awaiting_score": 0.0,
        "tadoku_pushed_score": 0.0,
        "tadoku_skipped_score": 0.0,
        "tadoku_log_score": 0.0,
    }
    sk = (series_key or "").strip()
    if not sk:
        return empty

    rows = (
        db.query(
            LogEntry.tadoku_status,
            LogEntry.amount,
            LogEntry.tadoku_score_estimate,
        )
        .filter(
            LogEntry.source == SOURCE,
            LogEntry.series_key == sk,
            LogEntry.unit == "characters",
        )
        .all()
    )
    awaiting = 0.0
    pushed = 0.0
    skipped = 0.0
    total = 0.0
    awaiting_score = 0.0
    pushed_score = 0.0
    skipped_score = 0.0
    total_score = 0.0
    for status, amount, score_est in rows:
        amt = float(amount or 0)
        score = float(score_est or 0)
        total += amt
        total_score += score
        st = (status or "").strip().lower()
        if st in _TADOKU_AWAITING:
            awaiting += amt
            awaiting_score += score
        elif st in _TADOKU_PUSHED:
            pushed += amt
            pushed_score += score
        elif st in _TADOKU_SKIPPED:
            skipped += amt
            skipped_score += score
        else:
            # Unknown status: treat as still in queue so nothing is hidden
            awaiting += amt
            awaiting_score += score
    return {
        "tadoku_awaiting_chars": awaiting,
        "tadoku_pushed_chars": pushed,
        "tadoku_skipped_chars": skipped,
        "tadoku_log_chars": total,
        "tadoku_awaiting_score": round(awaiting_score, 3),
        "tadoku_pushed_score": round(pushed_score, 3),
        "tadoku_skipped_score": round(skipped_score, 3),
        "tadoku_log_score": round(total_score, 3),
    }


def bucket_to_dict(
    db: Session, bucket: HoshiBookBucket, *, include_sessions: bool = True
) -> dict[str, Any]:
    min_submit = effective_min_submit(db, bucket)
    global_min = get_global_min_submit(db)
    idle_m = _idle_minutes(db)
    mode = get_log_mode(db)
    # Pre-log Hoshi buffer (internal). Kept for submit/discard ops; not primary UI.
    unlogged = float(bucket.pending_chars or 0)
    frags = pending_fragments(db, bucket.id) if include_sessions else []
    pos = bucket.position_chars
    total = bucket.book_total_chars
    pct = None
    if pos is not None and total and total > 0:
        pct = round(100.0 * pos / total, 2)

    meets = unlogged >= min_submit
    idle_s = bucket_idle_seconds(bucket)
    idle_ok = bucket_is_idle_enough(bucket, db)
    waiting_idle = (
        mode in ("auto", "automatic") and meets and not idle_ok and idle_m > 0
    )
    idle_remaining_s = None
    if waiting_idle and idle_s is not None:
        idle_remaining_s = max(0.0, idle_m * 60.0 - idle_s)

    logged = float(bucket.total_logged_chars or 0)
    # Lifetime = chars that actually became immersion logs (not unlogged buffer).
    lifetime = logged
    tadoku = tadoku_char_stats_for_series(db, bucket.series_key)
    formal_logs = list_logs_for_series(db, bucket.series_key) if include_sessions else []

    unlogged_score = (
        float(estimate_score("reading", unlogged, "characters")) if unlogged > 0 else 0.0
    )
    not_on = float(tadoku["tadoku_awaiting_chars"] or 0) + unlogged
    not_on_score = round(
        float(tadoku["tadoku_awaiting_score"] or 0) + unlogged_score, 3
    )
    progress_chars = int(pos) if pos is not None else int(round(logged + unlogged))

    return {
        "id": bucket.id,
        "folder_id": bucket.folder_id,
        "title": bucket.title,
        "series_key": bucket.series_key,
        # Legacy alias: pending_chars = unlogged Hoshi buffer (pre-log)
        "pending_chars": unlogged,
        "unlogged_chars": unlogged,
        "unlogged_score": round(unlogged_score, 3),
        "pending_seconds": float(bucket.pending_seconds or 0),
        "session_count": int(bucket.session_count or 0),
        "last_session_chars": float(bucket.last_session_chars or 0),
        "last_session_at": (
            bucket.last_session_at.isoformat() if bucket.last_session_at else None
        ),
        "position_chars": pos,
        "book_total_chars": total,
        "position_percent": pct,
        "progress_chars": progress_chars,
        "last_logged_position_chars": bucket.last_logged_position_chars,
        "last_logged_percent": (
            round(
                100.0
                * int(bucket.last_logged_position_chars)
                / total,
                2,
            )
            if bucket.last_logged_position_chars is not None
            and total
            and total > 0
            else None
        ),
        "total_logged_chars": logged,
        "lifetime_chars": lifetime,
        # Primary UI metrics
        "not_on_tadoku_chars": not_on,
        "not_on_tadoku_score": not_on_score,
        "tadoku_awaiting_chars": tadoku["tadoku_awaiting_chars"],
        "tadoku_pushed_chars": tadoku["tadoku_pushed_chars"],
        "tadoku_skipped_chars": tadoku["tadoku_skipped_chars"],
        "tadoku_awaiting_score": tadoku["tadoku_awaiting_score"],
        "tadoku_pushed_score": tadoku["tadoku_pushed_score"],
        "tadoku_skipped_score": tadoku["tadoku_skipped_score"],
        "tadoku_log_score": tadoku["tadoku_log_score"],
        "total_logged_seconds": float(bucket.total_logged_seconds or 0),
        "submit_count": int(bucket.submit_count or 0),
        "last_log_id": bucket.last_log_id,
        "threshold_met": meets,
        "auto_ready": mode in ("auto", "automatic") and meets and idle_ok,
        "waiting_idle": waiting_idle,
        "idle_seconds": idle_s,
        "idle_remaining_seconds": idle_remaining_s,
        "auto_submit_idle_minutes": idle_m,
        "manual_ready": unlogged > 0,
        "min_submit_characters": min_submit,
        "min_submit_characters_override": bucket.min_submit_characters,
        "global_min_submit_characters": global_min,
        "log_mode": mode,
        "updated_at": bucket.updated_at.isoformat() if bucket.updated_at else None,
        "logs": formal_logs,
        "sessions": [
            {
                "id": f.id,
                "date_key": f.date_key,
                "chars": float(f.chars or 0),
                "seconds": float(f.seconds or 0),
                "remote_total_for_day": f.remote_total_for_day,
                "status": f.status,
                "created_at": f.created_at.isoformat() if f.created_at else None,
                "notes": f.notes,
            }
            for f in frags
        ],
    }


def reading_dashboard(db: Session) -> dict[str, Any]:
    cfg = _cfg()
    backfill_logged_totals_from_logs(db)
    # Clamp any re-read-inflated buffers now that we have positions
    for b in list_buckets(db, pending_only=False):
        if b.position_chars is not None:
            try:
                reconcile_bucket_pending_to_position(db, b)
            except Exception:  # noqa: BLE001
                logger.exception("reconcile failed for bucket %s", b.id)
    buckets = list_buckets(db, pending_only=False)
    unlogged_buckets = [b for b in buckets if float(b.pending_chars or 0) > 0]
    total_unlogged = sum(float(b.pending_chars or 0) for b in unlogged_buckets)
    total_logged = sum(float(b.total_logged_chars or 0) for b in buckets)
    mode = get_log_mode(db)
    auto_ready = [
        b
        for b in unlogged_buckets
        if mode in ("auto", "automatic")
        and bucket_meets_auto_threshold(b, db)
        and bucket_is_idle_enough(b, db)
    ]
    waiting_idle = [
        b
        for b in unlogged_buckets
        if mode in ("auto", "automatic")
        and bucket_meets_auto_threshold(b, db)
        and not bucket_is_idle_enough(b, db)
    ]
    bucket_dicts = [bucket_to_dict(db, b) for b in buckets]
    total_tadoku_awaiting = sum(
        float(b.get("tadoku_awaiting_chars") or 0) for b in bucket_dicts
    )
    total_tadoku_pushed = sum(
        float(b.get("tadoku_pushed_chars") or 0) for b in bucket_dicts
    )
    total_tadoku_awaiting_score = round(
        sum(float(b.get("tadoku_awaiting_score") or 0) for b in bucket_dicts), 3
    )
    total_tadoku_pushed_score = round(
        sum(float(b.get("tadoku_pushed_score") or 0) for b in bucket_dicts), 3
    )
    total_not_on = sum(float(b.get("not_on_tadoku_chars") or 0) for b in bucket_dicts)
    total_not_on_score = round(
        sum(float(b.get("not_on_tadoku_score") or 0) for b in bucket_dicts), 3
    )
    total_progress = sum(int(b.get("progress_chars") or 0) for b in bucket_dicts)
    tadoku_awaiting_books = sum(
        1 for b in bucket_dicts if float(b.get("not_on_tadoku_chars") or 0) > 0
    )
    return {
        "log_mode": mode,
        "min_submit_characters": get_global_min_submit(db),
        "auto_submit_idle_minutes": get_idle_minutes(db),
        "content_type": cfg.content_type or "book",
        "unit": cfg.unit or "characters",
        # Primary user-facing totals
        "total_progress_chars": total_progress,
        "total_progress_label": f"{int(total_progress):,} chars",
        "total_not_on_tadoku_chars": total_not_on,
        "total_not_on_tadoku_score": total_not_on_score,
        "total_tadoku_awaiting_chars": total_tadoku_awaiting,
        "total_tadoku_pushed_chars": total_tadoku_pushed,
        "total_tadoku_awaiting_score": total_tadoku_awaiting_score,
        "total_tadoku_pushed_score": total_tadoku_pushed_score,
        "tadoku_awaiting_book_count": tadoku_awaiting_books,
        # Logged into immersion tracker (may still await Tadoku)
        "total_logged_chars": total_logged,
        # Internal Hoshi buffer (pre-log). Kept for API/compat.
        "total_pending_chars": total_unlogged,
        "total_unlogged_chars": total_unlogged,
        "pending_book_count": len(unlogged_buckets),
        "auto_ready_count": len(auto_ready),
        "waiting_idle_count": len(waiting_idle),
        "buckets": bucket_dicts,
    }
