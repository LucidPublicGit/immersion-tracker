"""
Hoshi Reader statistics → reading buckets → immersion logs.

Sources:
  - **drive**: poll Google Drive ``ttu-reader-data`` (default)
  - **adb**: pull device statistics.json

Polls compute per-day character **deltas**, append them as session fragments
on per-book buckets, and only create formal logs via auto threshold or UI submit.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.ingest.hoshi_drive import (
    BookFolder,
    HoshiDriveClient,
    HoshiDriveError,
    ReadingStatDay,
    parse_statistics_json,
)
from app.sheets.state import get_state, set_state

logger = logging.getLogger(__name__)

SOURCE = "hoshi"
STATE_PREFIX = "hoshi:chars:"
LAST_POLL_KEY = "hoshi:last_poll"
LAST_RESULT_KEY = "hoshi:last_result"


@dataclass
class HoshiDayDelta:
    folder_id: str
    title: str
    date_key: str
    previous_chars: int
    new_chars: int
    delta: int
    reading_time: float
    last_statistic_modified: int
    position_chars: Optional[int] = None
    book_total_chars: Optional[int] = None


@dataclass
class HoshiPollResult:
    ok: bool
    reason: str = ""
    books_scanned: int = 0
    stats_files: int = 0
    days_seen: int = 0
    # Fragments added to buckets (not necessarily formal logs)
    sessions_added: int = 0
    chars_bucketed: float = 0.0
    # Formal LogEntry creations (auto-submit or legacy)
    logs_created: int = 0
    chars_logged: float = 0.0
    skipped_zero: int = 0
    skipped_no_increase: int = 0
    skipped_below_min: int = 0
    # Day-stat increases ignored because bookmark position did not advance (re-reads)
    skipped_reread: int = 0
    errors: list[str] = field(default_factory=list)
    created_log_ids: list[int] = field(default_factory=list)
    dry_run: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "reason": self.reason,
            "books_scanned": self.books_scanned,
            "stats_files": self.stats_files,
            "days_seen": self.days_seen,
            "sessions_added": self.sessions_added,
            "chars_bucketed": self.chars_bucketed,
            "logs_created": self.logs_created,
            "chars_logged": self.chars_logged,
            "skipped_zero": self.skipped_zero,
            "skipped_no_increase": self.skipped_no_increase,
            "skipped_below_min": self.skipped_below_min,
            "skipped_reread": self.skipped_reread,
            "errors": self.errors,
            "created_log_ids": self.created_log_ids,
            "dry_run": self.dry_run,
        }


def _state_key(folder_id: str, date_key: str) -> str:
    return f"{STATE_PREFIX}{folder_id}:{date_key}"


def get_seen_chars(db: Session, folder_id: str, date_key: str) -> int:
    raw = get_state(db, _state_key(folder_id, date_key))
    if not raw:
        return 0
    try:
        return max(0, int(raw))
    except ValueError:
        return 0


def set_seen_chars(
    db: Session, folder_id: str, date_key: str, characters: int
) -> None:
    set_state(db, _state_key(folder_id, date_key), str(max(0, int(characters))))


def series_key_for_title(title: str) -> str:
    """Stable-ish series_key from book title (user can override via catalog)."""
    t = (title or "").strip()
    if not t:
        return "hoshi:unknown"
    # Keep CJK; collapse whitespace; drop path-ish chars
    t = re.sub(r"\s+", " ", t)
    t = t.replace("/", "-").replace("\\", "-")
    if len(t) > 200:
        t = t[:200]
    return f"hoshi:{t}"


def parse_date_key_timestamp(date_key: str) -> Optional[datetime]:
    """``YYYY-MM-DD`` → UTC noon that day (stable, timezone-agnostic)."""
    try:
        y, m, d = (int(x) for x in date_key.split("-", 2))
        return datetime(y, m, d, 12, 0, 0, tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def apply_deltas(
    db: Session,
    deltas: list[HoshiDayDelta],
    state_updates: list[tuple[str, str, int]],
    *,
    dry_run: bool = False,
    content_type: str = "book",  # noqa: ARG001 — kept for call-site compat
    unit: str = "characters",  # noqa: ARG001
    tadoku_mode: Optional[str] = None,  # noqa: ARG001
    advance_credited_position: Optional[int] = None,
) -> HoshiPollResult:
    """Bucket deltas as session fragments; maybe auto-submit logs."""
    from app.ingest.hoshi_buckets import (
        add_session_fragment,
        set_credited_position,
        update_bucket_progress,
    )

    result = HoshiPollResult(ok=True, dry_run=dry_run)

    for d in deltas:
        result.days_seen += 1
        # Prefer explicit note from position-gated path; else day-stat range
        notes = f"{d.date_key}: {d.previous_chars}→{d.new_chars}"
        try:
            _bucket, _frag, entry = add_session_fragment(
                db,
                folder_id=d.folder_id,
                title=d.title,
                date_key=d.date_key,
                chars=float(d.delta),
                seconds=0.0,
                remote_total_for_day=int(d.new_chars),
                notes=notes,
                position_chars=d.position_chars,
                book_total_chars=d.book_total_chars,
                dry_run=dry_run,
            )
            result.sessions_added += 1
            result.chars_bucketed += float(d.delta)
            if entry is not None and not dry_run:
                result.logs_created += 1
                result.chars_logged += float(getattr(entry, "amount", 0) or 0)
                result.created_log_ids.append(int(entry.id))
        except Exception as exc:  # noqa: BLE001
            logger.exception("hoshi bucket failed for %s", d.folder_id)
            result.errors.append(f"{d.title} {d.date_key}: {exc}")

    if not dry_run:
        for folder_id, date_key, chars in state_updates:
            set_seen_chars(db, folder_id, date_key, chars)
        # Progress-only updates (no char delta) still refresh position
        pos = None
        total = None
        title = ""
        folder_id = None
        for d in deltas:
            if d.position_chars is not None:
                pos = d.position_chars
            if d.book_total_chars is not None:
                total = d.book_total_chars
            title = d.title or title
            folder_id = d.folder_id
        if folder_id and (pos is not None or total is not None):
            try:
                update_bucket_progress(
                    db,
                    folder_id,
                    title=title,
                    position_chars=pos,
                    book_total_chars=total,
                    reconcile=False,
                )
            except Exception:  # noqa: BLE001
                pass
        if advance_credited_position is not None and folder_id:
            try:
                set_credited_position(
                    db, folder_id, advance_credited_position, title=title
                )
            except Exception:  # noqa: BLE001
                pass

    return result


def ingest_book_days(
    db: Session,
    book: BookFolder,
    days: list[ReadingStatDay],
    *,
    dry_run: bool = False,
    min_characters: int = 1,
    bootstrap: bool = True,
    content_type: str = "book",
    unit: str = "characters",
    tadoku_mode: Optional[str] = None,
    position_chars: Optional[int] = None,
    book_total_chars: Optional[int] = None,
) -> HoshiPollResult:
    """
    Ingest one book's statistics days into reading buckets.

    When bookmark ``position_chars`` is known, credit is gated by progress:
    only ``max(0, position − credited_position)`` is bucketed. Hoshi day
    ``charactersRead`` can rise on re-reads; that no longer creates pending.
    Without position, fall back to day-stat watermarks (legacy).
    """
    from app.ingest.hoshi_buckets import (
        ensure_credited_position,
        reconcile_bucket_pending_to_position,
        update_bucket_progress,
    )

    seen: dict[tuple[str, str], int] = {}
    for day in days:
        key = _state_key(book.id, day.date_key)
        raw = get_state(db, key)
        if raw != "":
            try:
                seen[(book.id, day.date_key)] = max(0, int(raw))
            except ValueError:
                seen[(book.id, day.date_key)] = 0

    never_seen: set[tuple[str, str]] = set()
    for day in days:
        if get_state(db, _state_key(book.id, day.date_key)) == "":
            never_seen.add((book.id, day.date_key))

    deltas: list[HoshiDayDelta] = []
    updates: list[tuple[str, str, int]] = []
    skipped_zero = 0
    skipped_no_increase = 0
    skipped_below_min = 0
    skipped_reread = 0
    book_title = book.title
    for day in days:
        if day.title:
            book_title = day.title or book_title

    # Always advance day watermarks so re-reads don't re-fire later
    raw_stat_deltas: list[tuple[ReadingStatDay, int, int]] = []  # day, prev, delta
    for day in days:
        if day.characters_read <= 0:
            skipped_zero += 1
            continue
        key = (book.id, day.date_key)
        prev = seen.get(key, 0)

        if key in never_seen and not bootstrap:
            updates.append((book.id, day.date_key, day.characters_read))
            continue

        if day.characters_read <= prev:
            skipped_no_increase += 1
            continue

        delta = day.characters_read - prev
        updates.append((book.id, day.date_key, day.characters_read))
        if delta < min_characters:
            skipped_below_min += 1
            continue
        raw_stat_deltas.append((day, prev, delta))

    advance_credited_to: Optional[int] = None

    if position_chars is not None:
        # Position-gated path: re-reads that bump day stats without new progress
        # are ignored for pending credit.
        if not dry_run:
            try:
                update_bucket_progress(
                    db,
                    book.id,
                    title=book_title,
                    position_chars=position_chars,
                    book_total_chars=book_total_chars,
                    reconcile=True,
                )
            except Exception:  # noqa: BLE001
                logger.exception("hoshi position reconcile failed for %s", book.id)

        credited = ensure_credited_position(
            db,
            book.id,
            title=book_title,
            position_chars=int(position_chars),
            dry_run=dry_run,
        )
        pos_advance = max(0, int(position_chars) - int(credited or 0))
        if pos_advance >= min_characters:
            # Attribute advance to the most recent day that had a stat increase,
            # else today's calendar-ish key from latest day row.
            if raw_stat_deltas:
                day, prev, _ = raw_stat_deltas[-1]
                date_key = day.date_key
                # Show position range in notes (not inflated day-stat range)
                prev_show = int(credited or 0)
                new_show = int(position_chars)
                remote = day.characters_read
                modified = day.last_statistic_modified
                rtime = day.reading_time
            elif days:
                day = max(days, key=lambda d: d.date_key)
                date_key = day.date_key
                prev_show = int(credited or 0)
                new_show = int(position_chars)
                remote = day.characters_read
                modified = day.last_statistic_modified
                rtime = day.reading_time
            else:
                date_key = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                prev_show = int(credited or 0)
                new_show = int(position_chars)
                remote = new_show
                modified = 0
                rtime = 0.0

            # Count raw stat increases that we refused as re-read noise
            for _day, _prev, dlt in raw_stat_deltas:
                if dlt > pos_advance:
                    skipped_reread += 1
            # If stats rose but we only take position advance, any extra is re-read
            stat_sum = sum(d for _, _, d in raw_stat_deltas)
            if stat_sum > pos_advance:
                skipped_reread += max(1, len(raw_stat_deltas) - 1)

            deltas.append(
                HoshiDayDelta(
                    folder_id=book.id,
                    title=book_title,
                    date_key=date_key,
                    previous_chars=prev_show,
                    new_chars=new_show,
                    delta=pos_advance,
                    reading_time=rtime,
                    last_statistic_modified=modified,
                    position_chars=position_chars,
                    book_total_chars=book_total_chars,
                )
            )
            advance_credited_to = int(position_chars)
        else:
            # No new progress — drop all day-stat increases as re-read / noise
            if raw_stat_deltas:
                skipped_reread += len(raw_stat_deltas)
            if not dry_run:
                # Still mark credited at least at current pos so future re-reads
                # don't credit if init was low
                try:
                    ensure_credited_position(
                        db,
                        book.id,
                        title=book_title,
                        position_chars=int(position_chars),
                        dry_run=False,
                    )
                    # If we have pending already reconciled, credited should be
                    # at least position after reconcile; set if advance is 0 and
                    # credited < position but pending covers it (reconcile did it)
                except Exception:  # noqa: BLE001
                    pass
    else:
        # No bookmark position: legacy day-stat deltas
        for day, prev, delta in raw_stat_deltas:
            deltas.append(
                HoshiDayDelta(
                    folder_id=book.id,
                    title=day.title or book_title,
                    date_key=day.date_key,
                    previous_chars=prev,
                    new_chars=day.characters_read,
                    delta=delta,
                    reading_time=day.reading_time,
                    last_statistic_modified=day.last_statistic_modified,
                    position_chars=position_chars,
                    book_total_chars=book_total_chars,
                )
            )

    result = apply_deltas(
        db,
        deltas,
        updates,
        dry_run=dry_run,
        content_type=content_type,
        unit=unit,
        tadoku_mode=tadoku_mode,
        advance_credited_position=advance_credited_to,
    )
    # Position update when no credit fragment was created
    if not dry_run and not deltas and (
        position_chars is not None or book_total_chars is not None
    ):
        try:
            update_bucket_progress(
                db,
                book.id,
                title=book_title,
                position_chars=position_chars,
                book_total_chars=book_total_chars,
                reconcile=True,
            )
        except Exception:  # noqa: BLE001
            pass

    result.days_seen = len(days)
    result.skipped_zero = skipped_zero
    result.skipped_no_increase = skipped_no_increase
    result.skipped_below_min = skipped_below_min
    result.skipped_reread = skipped_reread
    return result


def _ingest_book_list(
    db: Session,
    books: list[tuple[BookFolder, list[ReadingStatDay]]],
    *,
    dry_run: bool,
) -> HoshiPollResult:
    """Shared delta ingest for ADB / Drive / API-pushed stats."""
    settings = get_settings()
    cfg = settings.yaml_config.hoshi
    aggregate = HoshiPollResult(ok=True, dry_run=dry_run, books_scanned=len(books))
    min_chars = max(1, int(cfg.min_characters or 1))
    tadoku = (cfg.tadoku_default or "").strip() or None

    for item in books:
        if isinstance(item, tuple) and len(item) >= 2:
            book, days = item[0], item[1]
            pos = item[2] if len(item) > 2 else None
            total = item[3] if len(item) > 3 else None
        else:
            continue
        if not days and pos is None:
            continue
        if days:
            aggregate.stats_files += 1
        part = ingest_book_days(
            db,
            book,
            days or [],
            dry_run=dry_run,
            min_characters=min_chars,
            bootstrap=bool(cfg.bootstrap),
            content_type=cfg.content_type or "book",
            unit=cfg.unit or "characters",
            tadoku_mode=tadoku,
            position_chars=pos,
            book_total_chars=total,
        )
        aggregate.days_seen += part.days_seen
        aggregate.sessions_added += part.sessions_added
        aggregate.chars_bucketed += part.chars_bucketed
        aggregate.logs_created += part.logs_created
        aggregate.chars_logged += part.chars_logged
        aggregate.skipped_zero += part.skipped_zero
        aggregate.skipped_no_increase += part.skipped_no_increase
        aggregate.skipped_below_min += part.skipped_below_min
        aggregate.skipped_reread += part.skipped_reread
        aggregate.created_log_ids.extend(part.created_log_ids)
        aggregate.errors.extend(part.errors)

    if aggregate.errors and aggregate.sessions_added == 0 and aggregate.stats_files == 0:
        aggregate.ok = False
        aggregate.reason = "; ".join(aggregate.errors[:3])
    elif aggregate.errors:
        aggregate.reason = f"{len(aggregate.errors)} book error(s)"

    if not dry_run:
        # Settled sessions (threshold met + idle) may not get another page turn
        try:
            from app.ingest.hoshi_buckets import process_auto_submit_idle_buckets

            idle_subs = process_auto_submit_idle_buckets(db)
            for item in idle_subs:
                aggregate.logs_created += 1
                aggregate.chars_logged += float(item.get("amount") or 0)
                if item.get("log_id"):
                    aggregate.created_log_ids.append(int(item["log_id"]))
        except Exception:  # noqa: BLE001
            logger.exception("hoshi idle auto-submit failed")
        _save_poll_meta(db, aggregate)

    if aggregate.sessions_added or aggregate.logs_created:
        logger.info(
            "hoshi poll: %s books, +%s sessions (%s chars bucketed), %s logs",
            aggregate.books_scanned,
            aggregate.sessions_added,
            int(aggregate.chars_bucketed),
            aggregate.logs_created,
        )
    else:
        logger.debug("hoshi poll: no new characters (%s)", aggregate.to_dict())

    return aggregate


def poll_hoshi_adb(
    db: Session,
    *,
    dry_run: bool = False,
    client=None,
) -> HoshiPollResult:
    """Pull Hoshi statistics.json files via ADB and log character deltas."""
    from app.ingest.hoshi_adb import (
        HoshiAdbClient,
        HoshiAdbError,
        adb_book_to_folder,
        client_from_settings,
    )

    settings = get_settings()
    cfg = settings.yaml_config.hoshi
    if not cfg.enabled and client is None:
        return HoshiPollResult(ok=False, reason="hoshi.enabled is false")

    try:
        adb: HoshiAdbClient = client or client_from_settings()
        device_books = adb.fetch_all_books()
    except HoshiAdbError as e:
        logger.warning("hoshi adb poll failed: %s", e)
        result = HoshiPollResult(ok=False, reason=str(e))
        if not dry_run:
            _save_poll_meta(db, result)
        return result
    except Exception as e:  # noqa: BLE001
        logger.exception("hoshi adb poll unexpected error")
        result = HoshiPollResult(ok=False, reason=str(e))
        if not dry_run:
            _save_poll_meta(db, result)
        return result

    pairs: list[tuple] = []
    for b in device_books:
        folder = adb_book_to_folder(b)
        days = [
            ReadingStatDay(
                title=d.title or b.title,
                date_key=d.date_key,
                characters_read=d.characters_read,
                reading_time=d.reading_time,
                last_statistic_modified=d.last_statistic_modified,
            )
            for d in b.days
        ]
        pairs.append((folder, days, None, None))

    return _ingest_book_list(db, pairs, dry_run=dry_run)


def poll_hoshi_drive(
    db: Session,
    *,
    dry_run: bool = False,
    client: Optional[HoshiDriveClient] = None,
) -> HoshiPollResult:
    """Full Drive poll: list books under ttu-reader-data, ingest statistics deltas."""
    settings = get_settings()
    cfg = settings.yaml_config.hoshi
    if not cfg.enabled and client is None:
        return HoshiPollResult(ok=False, reason="hoshi.enabled is false")

    try:
        drive = client or HoshiDriveClient()
        root_id = drive.find_root_folder(
            folder_id=cfg.root_folder_id,
            folder_name=cfg.root_folder_name,
        )
        books = drive.list_book_folders(root_id)
    except HoshiDriveError as e:
        logger.warning("hoshi drive poll failed: %s", e)
        result = HoshiPollResult(ok=False, reason=str(e))
        if not dry_run:
            _save_poll_meta(db, result)
        return result
    except Exception as e:  # noqa: BLE001
        logger.exception("hoshi drive poll unexpected error")
        result = HoshiPollResult(ok=False, reason=str(e))
        if not dry_run:
            _save_poll_meta(db, result)
        return result

    pairs: list[tuple] = []
    fetch_errors: list[str] = []
    for book in books:
        try:
            stats_file, days = drive.fetch_book_statistics(book)
            pos, total = drive.fetch_book_progress(book)
        except Exception as e:  # noqa: BLE001
            logger.exception("hoshi stats fetch failed for %s", book.title)
            fetch_errors.append(f"{book.title}: {e}")
            continue
        if stats_file is None and pos is None:
            continue
        pairs.append((book, days or [], pos, total))

    aggregate = _ingest_book_list(db, pairs, dry_run=dry_run)
    aggregate.books_scanned = len(books)
    aggregate.errors.extend(fetch_errors)
    if fetch_errors and aggregate.logs_created == 0 and aggregate.stats_files == 0:
        aggregate.ok = False
        aggregate.reason = "; ".join(fetch_errors[:3])
    return aggregate


def poll_hoshi(
    db: Session,
    *,
    dry_run: bool = False,
    source: Optional[str] = None,
) -> HoshiPollResult:
    """Dispatch to ADB or Drive based on ``hoshi.source`` (or override)."""
    settings = get_settings()
    cfg = settings.yaml_config.hoshi
    if not cfg.enabled:
        return HoshiPollResult(ok=False, reason="hoshi.enabled is false")

    src = (source or cfg.source or "adb").strip().lower()
    if src == "drive":
        return poll_hoshi_drive(db, dry_run=dry_run)
    if src in ("adb", "device", "usb"):
        return poll_hoshi_adb(db, dry_run=dry_run)
    if src == "auto":
        adb_result = poll_hoshi_adb(db, dry_run=dry_run)
        if adb_result.ok:
            return adb_result
        logger.info(
            "hoshi auto: ADB failed (%s); trying Google Drive",
            adb_result.reason,
        )
        drive_result = poll_hoshi_drive(db, dry_run=dry_run)
        if drive_result.ok:
            drive_result.reason = (
                f"via drive (adb failed: {adb_result.reason})"
            )
            return drive_result
        return HoshiPollResult(
            ok=False,
            reason=(
                f"adb: {adb_result.reason}; drive: {drive_result.reason}"
            ),
            errors=list(adb_result.errors) + list(drive_result.errors),
        )
    return HoshiPollResult(ok=False, reason=f"unknown hoshi.source: {src!r}")


def ingest_stats_payload(
    db: Session,
    books_payload: list[dict[str, Any]],
    *,
    dry_run: bool = False,
) -> HoshiPollResult:
    """
    Ingest pre-fetched book statistics (host ADB script → API).

    Each item: ``{ "folder_id": "...", "title": "...", "statistics": [ ... ] }``
    """
    settings = get_settings()
    cfg = settings.yaml_config.hoshi
    # Allow ingest even when scheduler disabled? Require enabled for consistency.
    if not cfg.enabled:
        return HoshiPollResult(ok=False, reason="hoshi.enabled is false")

    pairs: list[tuple] = []
    errors: list[str] = []
    for item in books_payload:
        if not isinstance(item, dict):
            continue
        folder_id = str(item.get("folder_id") or item.get("id") or "").strip()
        title = str(item.get("title") or folder_id or "Unknown").strip()
        if not folder_id:
            folder_id = f"push:{re.sub(r'[^\w.\-]+', '_', title)[:80]}"
        if not folder_id.startswith("adb:") and not folder_id.startswith("push:"):
            folder_id = f"adb:{folder_id}"
        raw_stats = item.get("statistics") or item.get("days") or []
        try:
            days = parse_statistics_json(raw_stats)  # type: ignore[arg-type]
        except Exception as e:  # noqa: BLE001
            errors.append(f"{title}: {e}")
            continue
        pos = item.get("position_chars") or item.get("explored_char_count")
        total = item.get("book_total_chars") or item.get("character_count")
        try:
            pos_i = int(pos) if pos is not None else None
        except (TypeError, ValueError):
            pos_i = None
        try:
            total_i = int(total) if total is not None else None
        except (TypeError, ValueError):
            total_i = None
        pairs.append(
            (
                BookFolder(id=folder_id, name=folder_id, title=title),
                days,
                pos_i,
                total_i,
            )
        )

    result = _ingest_book_list(db, pairs, dry_run=dry_run)
    result.errors.extend(errors)
    if errors and result.logs_created == 0:
        result.ok = False
        result.reason = "; ".join(errors[:3])
    return result


def _save_poll_meta(db: Session, result: HoshiPollResult) -> None:
    import json
    from app.db.models import utcnow

    set_state(db, LAST_POLL_KEY, utcnow().isoformat().replace("+00:00", "Z"))
    set_state(db, LAST_RESULT_KEY, json.dumps(result.to_dict(), ensure_ascii=False))


def hoshi_status(db: Session) -> dict[str, Any]:
    """Status blob for API / UI."""
    import json

    settings = get_settings()
    cfg = settings.yaml_config.hoshi
    last_raw = get_state(db, LAST_RESULT_KEY)
    last: Any = None
    if last_raw:
        try:
            last = json.loads(last_raw)
        except json.JSONDecodeError:
            last = {"raw": last_raw}

    adb_info: dict[str, Any] = {}
    if (cfg.source or "adb").lower() in ("adb", "device", "usb"):
        try:
            from app.ingest.hoshi_adb import probe_adb_status

            adb_info = probe_adb_status()
        except Exception as e:  # noqa: BLE001
            adb_info = {"error": str(e)}

    return {
        "enabled": bool(cfg.enabled),
        "source": (cfg.source or "adb").lower(),
        "adb": {
            "binary": cfg.adb.binary,
            "serial": cfg.adb.serial or None,
            "connect": cfg.adb.connect or None,
            "package": cfg.adb.package,
            "books_path": cfg.adb.books_path or None,
            "probe": adb_info,
        },
        "root_folder_name": cfg.root_folder_name,
        "root_folder_id": cfg.root_folder_id or None,
        "poll_seconds": int(cfg.poll_seconds),
        "content_type": cfg.content_type,
        "unit": cfg.unit,
        "min_characters": int(cfg.min_characters),
        "bootstrap": bool(cfg.bootstrap),
        "log_mode": (cfg.log_mode or "manual").strip().lower(),
        "min_submit_characters": int(cfg.min_submit_characters or 500),
        "auto_submit_idle_minutes": float(cfg.auto_submit_idle_minutes or 0),
        "tadoku_default": cfg.tadoku_default,
        "last_poll_at": get_state(db, LAST_POLL_KEY) or None,
        "last_result": last,
    }
