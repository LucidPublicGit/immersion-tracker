"""
Mokuro Reader Google Drive progress → manga page logs.

Reads ``mokuro-reader/volume-data.json`` (same Drive auth as Hoshi).
Logs positive page deltas. First sight of a volume is a baseline (no dump).
Tadoku mode is pending unless yaml ``tadoku_default`` says otherwise.
``series.json`` page counts are stored on the open log as ``total=N``.
Auto submit waits for Mokuro to mark that volume finished; Approve does not.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import LogEntry, utcnow
from app.ingest.base import PollResult
from app.ingest.service import DuplicateLogError, create_log
from app.media.title_format import suggest_series_key
from app.sheets.state import get_state, set_state
from app.tadoku.rules import estimate_score

logger = logging.getLogger(__name__)

SOURCE = "mokuro"
VOLUME_DATA_NAME = "volume-data.json"
SERIES_SECTION_KEY = "series"
STATE_PREFIX = "mokuro:progress:"
LAST_POLL_KEY = "mokuro:last_poll"
LAST_RESULT_KEY = "mokuro:last_result"
LAST_ERROR_KEY = "mokuro:last_error"


def _watermark_key(volume_id: str) -> str:
    return f"{STATE_PREFIX}{volume_id}"


def get_progress_watermark(db: Session, volume_id: str) -> Optional[int]:
    raw = get_state(db, _watermark_key(volume_id))
    if raw == "":
        return None
    try:
        return max(0, int(raw))
    except ValueError:
        return None


def set_progress_watermark(db: Session, volume_id: str, pages: int) -> None:
    set_state(db, _watermark_key(volume_id), str(max(0, int(pages))))


def parse_volume_data(raw: Any) -> dict[str, dict[str, Any]]:
    """Return volume_uuid → record, skipping series section and tombstones."""
    if isinstance(raw, str):
        data = json.loads(raw)
    else:
        data = raw
    if not isinstance(data, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for key, value in data.items():
        vid = str(key or "").strip()
        if not vid or vid == SERIES_SECTION_KEY:
            continue
        if not isinstance(value, dict):
            continue
        if value.get("deletedOn"):
            continue
        out[vid] = value
    return out


def _int_field(record: dict[str, Any], name: str) -> int:
    try:
        return max(0, int(record.get(name) or 0))
    except (TypeError, ValueError):
        return 0


OPEN_STATUSES = ("pending", "ready")


_VOL_NUM_RE = re.compile(
    r"(?:第\s*)?0*(?P<n>\d{1,3})\s*巻$|"
    r"(?:^|[_\-\s])(?:vol(?:ume)?\.?[_\-\s]*)?0*(?P<n2>\d{1,3})$",
    re.I,
)


def _volume_num(volume_title: str) -> Optional[int]:
    t = (volume_title or "").strip()
    if not t:
        return None
    m = _VOL_NUM_RE.search(t)
    if not m:
        return None
    raw = m.group("n") or m.group("n2")
    return int(raw) if raw else None


def _title_for(record: dict[str, Any], volume_id: str) -> str:
    series = str(record.get("series_title") or "").strip()
    if series:
        return series
    volume = str(record.get("volume_title") or "").strip()
    if volume:
        stripped = _VOL_NUM_RE.sub("", volume).replace("_", " ").strip(" -_")
        return stripped or volume.replace("_", " ")
    return volume_id[:12]


def _apply_identity(
    entry: LogEntry, rec: Optional[dict[str, Any]], volume_id: str
) -> bool:
    if not rec:
        return False
    changed = False
    title = _title_for(rec, volume_id)
    vol_n = _volume_num(str(rec.get("volume_title") or ""))
    if title and (entry.title or "") != title:
        entry.title = title
        changed = True
    if vol_n is not None and entry.episode != vol_n:
        entry.episode = vol_n
        changed = True
    series_name = str(rec.get("series_title") or title).strip() or title
    key = suggest_series_key(entry.content_type or "manga", series_name)
    if key and (entry.series_key or "") != key:
        entry.series_key = key
        changed = True
    return changed


def _source_ref(volume_id: str, pages: int) -> str:
    return f"mokuro:{volume_id}:{int(pages)}"


def _ref_pages(source_ref: Optional[str]) -> Optional[int]:
    if not source_ref or ":" not in source_ref:
        return None
    try:
        return int(str(source_ref).rsplit(":", 1)[-1])
    except ValueError:
        return None


def _page_count(rec: Optional[dict[str, Any]]) -> Optional[int]:
    if not rec:
        return None
    try:
        total = int(rec.get("page_count") or 0)
    except (TypeError, ValueError):
        return None
    return total if total > 0 else None


def _volume_notes(
    rec: dict[str, Any],
    *,
    start: int,
    pages: int,
    amount: int,
    chars: int,
) -> str:
    notes = f"pages {start}→{pages} (+{amount})"
    total = _page_count(rec)
    if total:
        notes += f"; total={total}"
    if chars:
        notes += f"; chars={chars}"
    if rec.get("completed"):
        notes += "; completed"
    vol = str(rec.get("volume_title") or "").strip()
    if vol:
        notes += f"; volume={vol}"
    return notes


def _pushed_volume_pages(db: Session, volume_id: str) -> int:
    prefix = f"mokuro:{volume_id}:"
    rows = (
        db.query(LogEntry)
        .filter(
            LogEntry.source == SOURCE,
            LogEntry.source_ref.startswith(prefix),
            LogEntry.tadoku_status == "pushed",
        )
        .all()
    )
    return sum(int(float(row.amount or 0)) for row in rows)


def parse_series_page_counts(raw: Any) -> dict[str, int]:
    """volume_uuid → page_count from one Mokuro series.json."""
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return {}
    else:
        data = raw
    if not isinstance(data, dict):
        return {}
    out: dict[str, int] = {}
    volumes = data.get("volumes")
    if not isinstance(volumes, list):
        return out
    for vol in volumes:
        if not isinstance(vol, dict):
            continue
        vid = str(vol.get("volume_uuid") or vol.get("volume_id") or "").strip()
        try:
            total = int(vol.get("page_count") or 0)
        except (TypeError, ValueError):
            continue
        if vid and total > 0:
            out[vid] = total
    return out


def _apply_page_counts(
    volumes: dict[str, dict[str, Any]], counts: dict[str, int]
) -> None:
    for volume_id, rec in volumes.items():
        total = counts.get(volume_id)
        if total:
            rec["page_count"] = total


def fetch_page_counts(
    *,
    client=None,
    folder_id: str = "",
    folder_name: str = "mokuro-reader",
) -> dict[str, int]:
    """Map volume_uuid → page_count from each series folder's series.json.

    volume-data.json has the reader position, not the volume length. Failures
    here must not fail the progress poll; the caller logs and continues.
    """
    from app.ingest.hoshi_drive import FOLDER_MIME, HoshiDriveClient, HoshiDriveError

    drive = client or HoshiDriveClient()
    try:
        root_id = drive.find_root_folder(folder_id=folder_id, folder_name=folder_name)
    except HoshiDriveError as exc:
        logger.warning("mokuro: page counts skipped, root not found: %s", exc)
        return {}

    rid = root_id.replace("'", "\\'")
    try:
        folders = drive.list_files(
            f"trashed=false and mimeType='{FOLDER_MIME}' and '{rid}' in parents",
            fields="files(id, name, parents)",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("mokuro: series folder list failed: %s", exc)
        return {}
    folder_ids = {f.id for f in folders}
    if not folder_ids:
        return {}

    try:
        files = drive.list_files(
            "trashed=false and name='series.json'",
            fields="files(id, name, parents)",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("mokuro: series.json search failed: %s", exc)
        return {}
    files = [f for f in files if folder_ids.intersection(f.parents or [])]

    counts: dict[str, int] = {}
    for info in files:
        try:
            counts.update(parse_series_page_counts(drive.download_file_text(info.id)))
        except Exception as exc:  # noqa: BLE001
            logger.warning("mokuro: series.json %s failed: %s", info.id, exc)
    return counts


def _attach_page_counts(
    volumes: dict[str, dict[str, Any]],
    *,
    client=None,
    folder_id: str = "",
    folder_name: str = "mokuro-reader",
) -> None:
    try:
        counts = fetch_page_counts(
            client=client, folder_id=folder_id, folder_name=folder_name
        )
        _apply_page_counts(volumes, counts)
    except Exception as exc:  # noqa: BLE001
        logger.warning("mokuro: page count fetch failed: %s", exc)


def _stamp_page_total(db: Session, volume_id: str, rec: dict[str, Any]) -> None:
    """Write the known volume length onto the open log, even when progress did not move."""
    if not _page_count(rec):
        return
    logs = _open_volume_logs(db, volume_id)
    if not logs:
        return
    keeper = logs[0]
    end = _ref_pages(keeper.source_ref) or 0
    amount = int(float(keeper.amount or 0))
    start = max(0, end - amount)
    notes = _volume_notes(
        rec,
        start=start,
        pages=end,
        amount=amount,
        chars=_int_field(rec, "chars"),
    )
    if keeper.notes == notes:
        return
    keeper.notes = notes
    keeper.updated_at = utcnow()
    db.commit()


def _open_volume_logs(db: Session, volume_id: str) -> list[LogEntry]:
    prefix = f"mokuro:{volume_id}:"
    return (
        db.query(LogEntry)
        .filter(
            LogEntry.source == SOURCE,
            LogEntry.source_ref.startswith(prefix),
            LogEntry.tadoku_status.in_(OPEN_STATUSES),
        )
        .order_by(LogEntry.id.asc())
        .all()
    )


def _coalesce_volume(
    db: Session, volume_id: str, rec: Optional[dict[str, Any]] = None
) -> Optional[LogEntry]:
    """Merge unpushed mokuro logs for one volume into the oldest row."""
    logs = _open_volume_logs(db, volume_id)
    if not logs:
        return None
    keeper = logs[0]
    extras = logs[1:]
    ident_changed = _apply_identity(keeper, rec, volume_id)
    if not extras:
        if ident_changed:
            keeper.updated_at = utcnow()
            db.commit()
            db.refresh(keeper)
        return keeper
    total = float(keeper.amount) + sum(float(x.amount) for x in extras)
    end = _ref_pages(keeper.source_ref) or 0
    for extra in extras:
        extra_end = _ref_pages(extra.source_ref)
        if extra_end is not None and extra_end > end:
            end = extra_end
        if extra.timestamp and (
            not keeper.timestamp or extra.timestamp > keeper.timestamp
        ):
            keeper.timestamp = extra.timestamp
        db.delete(extra)
    db.flush()
    keeper.amount = total
    keeper.source_ref = _source_ref(volume_id, end)
    start = max(0, end - int(total))
    chars = _int_field(rec, "chars") if rec else 0
    keeper.notes = _volume_notes(
        rec or {}, start=start, pages=end, amount=int(total), chars=chars
    )
    keeper.tadoku_score_estimate = estimate_score(
        keeper.activity, keeper.amount, keeper.unit
    )
    _apply_identity(keeper, rec, volume_id)
    keeper.updated_at = utcnow()
    db.commit()
    db.refresh(keeper)
    return keeper


def _parse_ts(raw: Any) -> Optional[datetime]:
    if not raw or not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _save_poll_meta(db: Session, result: PollResult) -> None:
    set_state(db, LAST_POLL_KEY, utcnow().isoformat().replace("+00:00", "Z"))
    set_state(db, LAST_RESULT_KEY, json.dumps(result.to_dict(), ensure_ascii=False))
    if result.errors:
        set_state(db, LAST_ERROR_KEY, "; ".join(result.errors[:5]))
    elif not result.ok and result.message:
        set_state(db, LAST_ERROR_KEY, result.message)
    else:
        set_state(db, LAST_ERROR_KEY, "")


def fetch_volume_data(
    *,
    client=None,
    folder_id: str = "",
    folder_name: str = "mokuro-reader",
) -> dict[str, dict[str, Any]]:
    from app.ingest.hoshi_drive import HoshiDriveClient, HoshiDriveError

    drive = client or HoshiDriveClient()
    try:
        root_id = drive.find_root_folder(folder_id=folder_id, folder_name=folder_name)
    except HoshiDriveError as exc:
        raise HoshiDriveError(
            f"Drive folder '{folder_name}' not found. In Mokuro Reader, connect "
            "Cloud → Google Drive so it creates that folder, then share it with "
            "the same Google OAuth account or Sheets service account."
        ) from exc
    # Name-only query: `'folderId' in parents` 500s on this large shared folder.
    name = VOLUME_DATA_NAME.replace("'", "\\'")
    matches = drive.list_files(
        f"trashed=false and name='{name}'",
        fields="files(id, name, parents)",
    )
    if root_id:
        pinned = [f for f in matches if root_id in (f.parents or [])]
        if pinned:
            matches = pinned
    if not matches:
        raise HoshiDriveError(
            f"{VOLUME_DATA_NAME} not found in Drive folder '{folder_name}'. "
            "Connect Mokuro Reader → Cloud → Google Drive once, then share "
            "the mokuro-reader folder with the same Google account / SA."
        )
    return parse_volume_data(drive.download_file_text(matches[0].id))


def ingest_volumes(
    db: Session,
    volumes: dict[str, dict[str, Any]],
    *,
    dry_run: bool = False,
) -> PollResult:
    cfg = get_settings().yaml_config.mokuro
    result = PollResult(ok=True, source=SOURCE)
    min_pages = max(1, int(cfg.min_pages or 1))
    bootstrap = bool(cfg.bootstrap)
    content_type = (cfg.content_type or "manga").strip() or "manga"
    unit = (cfg.unit or "comic_pages").strip() or "comic_pages"
    activity = (cfg.activity or "reading").strip() or "reading"
    tadoku_mode = (cfg.tadoku_default or "pending").strip() or "pending"

    baselined = 0
    rewound = 0

    for volume_id, rec in volumes.items():
        pages = _int_field(rec, "progress")
        chars = _int_field(rec, "chars")
        prev = get_progress_watermark(db, volume_id)
        if not dry_run:
            _coalesce_volume(db, volume_id, rec)

        if prev is None:
            if bootstrap and pages >= min_pages:
                if not dry_run:
                    _log_delta(
                        db,
                        result,
                        volume_id=volume_id,
                        rec=rec,
                        pages=pages,
                        chars=chars,
                        prev=0,
                        content_type=content_type,
                        unit=unit,
                        activity=activity,
                        tadoku_mode=tadoku_mode,
                    )
                    set_progress_watermark(db, volume_id, pages)
                else:
                    result.logs_created += 1
            else:
                baselined += 1
                result.skipped += 1
                if not dry_run:
                    set_progress_watermark(db, volume_id, pages)
            if not dry_run:
                _stamp_page_total(db, volume_id, rec)
            continue

        if pages < prev:
            # Restart / rewind — new baseline, no negative log
            rewound += 1
            result.skipped += 1
            if not dry_run:
                set_progress_watermark(db, volume_id, pages)
                _stamp_page_total(db, volume_id, rec)
            continue

        delta = pages - prev
        if delta < min_pages:
            result.skipped += 1
        elif dry_run:
            result.logs_created += 1
        else:
            _log_delta(
                db,
                result,
                volume_id=volume_id,
                rec=rec,
                pages=pages,
                chars=chars,
                prev=prev,
                content_type=content_type,
                unit=unit,
                activity=activity,
                tadoku_mode=tadoku_mode,
            )
            set_progress_watermark(db, volume_id, pages)

        if rec.get("completed") and not dry_run:
            _expand_completed_open_log(
                db, result, volume_id=volume_id, rec=rec, pages=pages, chars=chars
            )
        if not dry_run:
            _stamp_page_total(db, volume_id, rec)

    result.details = {
        "volumes": len(volumes),
        "baselined": baselined,
        "rewound": rewound,
    }
    if result.logs_created:
        result.message = f"created {result.logs_created} log(s)"
        if not dry_run:
            try:
                from app.sheets.state import mark_sheets_dirty

                mark_sheets_dirty(db)
            except Exception:  # noqa: BLE001
                pass
    elif not result.message:
        result.message = "ok"
    return result


def _log_delta(
    db: Session,
    result: PollResult,
    *,
    volume_id: str,
    rec: dict[str, Any],
    pages: int,
    chars: int,
    prev: int,
    content_type: str,
    unit: str,
    activity: str,
    tadoku_mode: str,
) -> None:
    delta = pages - prev
    title = _title_for(rec, volume_id)
    series_name = str(rec.get("series_title") or title).strip() or title
    amount = int(delta)
    start = int(prev)
    notes = _volume_notes(
        rec, start=start, pages=pages, amount=amount, chars=chars
    )
    open_log = _open_volume_logs(db, volume_id)
    keeper = open_log[0] if open_log else None
    # Fold into the unpushed volume log when it already counted up to `prev`.
    if keeper is not None and _ref_pages(keeper.source_ref) in (None, prev):
        try:
            new_amount = float(keeper.amount) + delta
            start = max(0, pages - int(new_amount))
            keeper.amount = new_amount
            keeper.source_ref = _source_ref(volume_id, pages)
            keeper.notes = _volume_notes(
                rec,
                start=start,
                pages=pages,
                amount=int(new_amount),
                chars=chars,
            )
            ts = _parse_ts(rec.get("lastProgressUpdate"))
            if ts:
                keeper.timestamp = ts
            keeper.tadoku_score_estimate = estimate_score(
                keeper.activity, keeper.amount, keeper.unit
            )
            _apply_identity(keeper, rec, volume_id)
            keeper.updated_at = utcnow()
            db.commit()
            result.logs_created += 1
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            logger.exception("mokuro: fold failed volume=%s", volume_id)
            result.errors.append(f"{volume_id}: {exc}")
        return
    try:
        create_log(
            db,
            content_type=content_type,
            title=title,
            source=SOURCE,
            amount=float(delta),
            unit=unit,
            activity=activity,
            series_key=suggest_series_key(content_type, series_name),
            source_ref=_source_ref(volume_id, pages),
            notes=notes,
            timestamp=_parse_ts(rec.get("lastProgressUpdate")),
            tadoku_mode_override=tadoku_mode,
            episode=_volume_num(str(rec.get("volume_title") or "")),
        )
        result.logs_created += 1
    except DuplicateLogError:
        result.skipped += 1
    except Exception as exc:  # noqa: BLE001
        logger.exception("mokuro: create_log failed volume=%s", volume_id)
        result.errors.append(f"{volume_id}: {exc}")


def _expand_completed_open_log(
    db: Session,
    result: PollResult,
    *,
    volume_id: str,
    rec: dict[str, Any],
    pages: int,
    chars: int,
) -> None:
    """Credit unread pages once Mokuro marks the volume done.

    Already-pushed pages stay pushed. The open log becomes the remainder,
    including a baseline that was never logged. If the pushed amount already
    covers the volume, the open log is left as it is.
    """
    logs = _open_volume_logs(db, volume_id)
    if not logs:
        return
    keeper = logs[0]
    pushed = _pushed_volume_pages(db, volume_id)
    if pushed >= int(pages):
        return
    target = int(pages) - pushed
    current = int(float(keeper.amount or 0))
    if current >= target:
        return
    start = max(0, int(pages) - target)
    keeper.amount = float(target)
    keeper.source_ref = _source_ref(volume_id, pages)
    keeper.notes = _volume_notes(
        rec, start=start, pages=pages, amount=target, chars=chars
    )
    ts = _parse_ts(rec.get("lastProgressUpdate"))
    if ts:
        keeper.timestamp = ts
    keeper.tadoku_score_estimate = estimate_score(
        keeper.activity, keeper.amount, keeper.unit
    )
    _apply_identity(keeper, rec, volume_id)
    keeper.updated_at = utcnow()
    db.commit()
    result.logs_created += 1


def poll_mokuro(
    db: Session,
    *,
    dry_run: bool = False,
    client=None,
    snapshot: Optional[dict[str, dict[str, Any]]] = None,
) -> PollResult:
    cfg = get_settings().yaml_config.mokuro
    result = PollResult(ok=True, source=SOURCE)
    if not cfg.enabled:
        result.message = "disabled"
        return result

    try:
        if snapshot is not None:
            volumes = snapshot
        else:
            from app.ingest.hoshi_drive import HoshiDriveClient

            drive = client or HoshiDriveClient()
            folder_name = cfg.root_folder_name or "mokuro-reader"
            volumes = fetch_volume_data(
                client=drive,
                folder_id=cfg.root_folder_id,
                folder_name=folder_name,
            )
            _attach_page_counts(
                volumes,
                client=drive,
                folder_id=cfg.root_folder_id,
                folder_name=folder_name,
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("mokuro: Drive fetch failed: %s", exc)
        result.ok = False
        result.message = str(exc)
        result.errors.append(result.message)
        try:
            _save_poll_meta(db, result)
        except Exception:  # noqa: BLE001
            pass
        return result

    result = ingest_volumes(db, volumes, dry_run=dry_run)
    try:
        _save_poll_meta(db, result)
    except Exception:  # noqa: BLE001
        logger.debug("mokuro: failed to save poll meta", exc_info=True)
    return result


def mokuro_status(db: Session) -> dict[str, Any]:
    cfg = get_settings().yaml_config.mokuro
    last_raw = get_state(db, LAST_RESULT_KEY)
    last: Any = None
    if last_raw:
        try:
            last = json.loads(last_raw)
        except json.JSONDecodeError:
            last = {"raw": "(unparseable)"}
    tracked = 0
    try:
        from app.db.models import SheetSyncState

        tracked = (
            db.query(SheetSyncState)
            .filter(SheetSyncState.key.like(f"{STATE_PREFIX}%"))
            .count()
        )
    except Exception:  # noqa: BLE001
        tracked = 0
    return {
        "enabled": bool(cfg.enabled),
        "root_folder_name": cfg.root_folder_name,
        "root_folder_id": cfg.root_folder_id or None,
        "poll_seconds": int(cfg.poll_seconds),
        "content_type": cfg.content_type,
        "unit": cfg.unit,
        "min_pages": int(cfg.min_pages),
        "bootstrap": bool(cfg.bootstrap),
        "tadoku_default": cfg.tadoku_default,
        "tracked_volumes": tracked,
        "last_poll_at": get_state(db, LAST_POLL_KEY) or None,
        "last_error": get_state(db, LAST_ERROR_KEY) or None,
        "last_result": last,
    }
