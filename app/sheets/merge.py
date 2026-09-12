"""Apply sheet row edits onto LogEntry models (pure-ish helpers for tests)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from app.db.models import LogEntry, utcnow
from app.tadoku.rules import estimate_score, mode_to_initial_status


def _parse_float(val: Any) -> Optional[float]:
    if val is None or val == "":
        return None
    try:
        return float(str(val).replace(",", "").strip())
    except ValueError:
        return None


def _parse_int(val: Any) -> Optional[int]:
    if val is None or val == "":
        return None
    try:
        return int(float(str(val).strip()))
    except (TypeError, ValueError):
        return None


def _parse_dt(val: Any) -> Optional[datetime]:
    if val is None or str(val).strip() == "":
        return None
    s = str(val).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def _dt_equal(a: Optional[datetime], b: Optional[datetime]) -> bool:
    """
    Compare timestamps for sheet round-trip stability.
    SQLite often stores naive UTC; Sheets may return +00:00 or drop tz —
    treat same wall time as equal.
    """
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False

    def _norm(d: datetime) -> datetime:
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc).replace(microsecond=0)

    return _norm(a) == _norm(b)


def is_delete_row(data: dict[str, str]) -> bool:
    """True if the sheet row should delete the log."""
    action = (data.get("action") or data.get("delete") or "").strip().lower()
    if action in ("delete", "true", "1", "yes", "y"):
        return True
    # Empty title + empty amount with an id → treat as delete
    title = (data.get("title") or "").strip()
    amount = (data.get("amount") or "").strip()
    return title == "" and amount == ""


def apply_log_fields(entry: LogEntry, data: dict[str, str]) -> list[str]:
    """
    Mutate entry from sheet row dict (keys lowercased).
    Returns list of field names changed.
    """
    changed: list[str] = []

    def set_str(attr: str, key: str, *, allow_empty: bool = False) -> None:
        if key not in data:
            return
        raw = data[key]
        if raw is None:
            return
        val = str(raw).strip()
        if val == "" and not allow_empty:
            return
        cur = getattr(entry, attr)
        if (cur or "") != val:
            setattr(entry, attr, val if val != "" else None)
            changed.append(attr)

    def set_float(attr: str, key: str) -> None:
        if key not in data:
            return
        parsed = _parse_float(data[key])
        if parsed is None:
            return
        cur = getattr(entry, attr)
        if cur is not None and abs(float(cur) - parsed) <= 1e-9:
            return
        setattr(entry, attr, parsed)
        changed.append(attr)

    if "timestamp" in data:
        dt = _parse_dt(data.get("timestamp"))
        if dt is not None and not _dt_equal(entry.timestamp, dt):
            entry.timestamp = dt
            changed.append("timestamp")

    set_str("content_type", "content_type")
    set_str("title", "title")
    set_str("series_key", "series_key", allow_empty=True)
    set_str("source", "source")
    set_float("amount", "amount")
    set_str("unit", "unit")
    set_str("activity", "activity")
    set_str("notes", "notes", allow_empty=True)

    # Reject unit-name junk left over from mis-applied dropdowns on season/episode
    _unit_junk = {
        "minutes",
        "minute",
        "pages",
        "page",
        "characters",
        "character",
        "sentences",
        "comic_pages",
        "comic pages",
    }
    for attr, key in (("season", "season"), ("episode", "episode")):
        if key not in data:
            continue
        raw = data[key]
        if raw is None or str(raw).strip() == "":
            if getattr(entry, attr) is not None:
                setattr(entry, attr, None)
                changed.append(attr)
            continue
        raw_s = str(raw).strip().lower()
        if raw_s in _unit_junk:
            continue  # ignore invalid selector values
        parsed = _parse_int(raw)
        if parsed is not None and getattr(entry, attr) != parsed:
            setattr(entry, attr, parsed)
            changed.append(attr)

    mode_before = entry.tadoku_mode
    status_before = entry.tadoku_status
    remote_before = entry.tadoku_remote_id
    set_str("tadoku_mode", "tadoku_mode")
    set_str("tadoku_status", "tadoku_status")

    # Mode change without explicit status → derive status
    if "tadoku_mode" in changed and "tadoku_status" not in data:
        entry.tadoku_status = mode_to_initial_status(entry.tadoku_mode)
        if entry.tadoku_status != status_before:
            changed.append("tadoku_status")

    # mode=auto means "no manual approve". Sheets always send both mode + status
    # columns, so a stale status=pending would stick forever without this.
    # Promote auto+pending → ready (does not touch pushed/skipped/failed).
    if (
        entry.tadoku_mode == "auto"
        and entry.tadoku_status == "pending"
        and status_before != "pushed"
    ):
        entry.tadoku_status = "ready"
        if "tadoku_status" not in changed:
            changed.append("tadoku_status")

    # Status shortcuts
    if entry.tadoku_status == "skipped" and entry.tadoku_mode != "never":
        entry.tadoku_mode = "never"
        if "tadoku_mode" not in changed:
            changed.append("tadoku_mode")
    if entry.tadoku_status == "ready" and entry.tadoku_mode == "never":
        entry.tadoku_mode = "auto"
        if "tadoku_mode" not in changed:
            changed.append("tadoku_mode")

    # Sticky pushed: sheet tabs lag live submit (and queue pull can race Logs).
    # Never re-queue a successfully submitted log from a stale pending/ready row.
    # Manual re-open is not done via sheet pull — use the API or edit SQLite.
    if status_before == "pushed" and entry.tadoku_status != "pushed":
        entry.tadoku_status = "pushed"
        if "tadoku_status" in changed:
            changed = [c for c in changed if c != "tadoku_status"]

    if "watch_ratio" in data:
        wr = _parse_float(data.get("watch_ratio"))
        if wr is not None and entry.watch_ratio != wr:
            entry.watch_ratio = wr
            changed.append("watch_ratio")

    # Always recompute score from amount/unit/activity when those change
    if any(f in changed for f in ("amount", "unit", "activity", "content_type")):
        new_score = estimate_score(entry.activity, entry.amount, entry.unit)
        if entry.tadoku_score_estimate != new_score:
            entry.tadoku_score_estimate = new_score
            changed.append("tadoku_score_estimate")
    elif "tadoku_score_estimate" in data or "score" in data:
        key = "tadoku_score_estimate" if "tadoku_score_estimate" in data else "score"
        sc = _parse_float(data.get(key))
        if sc is not None and entry.tadoku_score_estimate != sc:
            entry.tadoku_score_estimate = sc
            changed.append("tadoku_score_estimate")

    if "remote_id" in data or "tadoku_remote_id" in data:
        rid = (data.get("tadoku_remote_id") or data.get("remote_id") or "").strip()
        if rid != (entry.tadoku_remote_id or ""):
            entry.tadoku_remote_id = rid or None
            changed.append("tadoku_remote_id")

    # Never clear a known Tadoku remote id on a pushed log (empty sheet cell).
    if (status_before == "pushed" or entry.tadoku_status == "pushed") and remote_before:
        if not entry.tadoku_remote_id:
            entry.tadoku_remote_id = remote_before
            if "tadoku_remote_id" in changed:
                changed = [c for c in changed if c != "tadoku_remote_id"]

    if changed:
        entry.updated_at = utcnow()
        # silence unused
        _ = mode_before

    return changed


def row_to_dict(headers: list[str], row: list[str]) -> dict[str, str]:
    return {
        headers[j]: (row[j] if j < len(row) else "")
        for j in range(len(headers))
    }
