"""
AnkiConnect → study logs (review time as minutes).

Polls Anki via the AnkiConnect HTTP API (default port 8765), sums review
durations since a stored watermark, and creates one aggregated study log when
the batch is at least ``min_delta_minutes``.

State keys (via ``app.sheets.state``):
  * ``anki:last_review_id`` — max review id already processed (epoch ms string)
  * ``anki:bootstrapped``   — set after first successful contact (skip history)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.ingest.base import PollResult
from app.ingest.service import DuplicateLogError, create_log
from app.sheets.state import get_state, set_state

logger = logging.getLogger(__name__)

SOURCE = "anki"
STATE_LAST_REVIEW_ID = "anki:last_review_id"
STATE_BOOTSTRAPPED = "anki:bootstrapped"
ANKI_CONNECT_VERSION = 6


class AnkiConnectError(RuntimeError):
    """AnkiConnect returned an error or the request failed."""


def _anki_cfg():
    return get_settings().yaml_config.anki


def anki_invoke(
    action: str,
    params: Optional[dict[str, Any]] = None,
    *,
    url: Optional[str] = None,
    timeout: Optional[float] = None,
) -> Any:
    """
    Call AnkiConnect: POST ``{"action", "version": 6, "params"?}``.

    Returns the ``result`` field. Raises ``AnkiConnectError`` on transport
    failure, non-2xx, or a non-null ``error`` in the response body.
    """
    cfg = _anki_cfg()
    base = (url if url is not None else (cfg.connect_url or "")).strip().rstrip("/")
    if not base:
        raise AnkiConnectError("anki.connect_url is empty")
    t = float(timeout if timeout is not None else (cfg.timeout_seconds or 10.0))
    payload: dict[str, Any] = {"action": action, "version": ANKI_CONNECT_VERSION}
    if params is not None:
        payload["params"] = params

    try:
        with httpx.Client(timeout=t) as client:
            resp = client.post(base, json=payload)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as exc:
        raise AnkiConnectError(f"AnkiConnect request failed: {exc}") from exc
    except ValueError as exc:
        raise AnkiConnectError(f"AnkiConnect returned non-JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise AnkiConnectError(f"AnkiConnect unexpected body type: {type(data).__name__}")
    err = data.get("error")
    if err is not None:
        raise AnkiConnectError(str(err))
    return data.get("result")


def _deck_matches(name: str, patterns: list[str]) -> bool:
    """Exact match, or prefix match when pattern ends with ``*``."""
    n = (name or "").strip()
    for raw in patterns or []:
        p = str(raw or "").strip()
        if not p:
            continue
        if p.endswith("*"):
            if n.startswith(p[:-1]):
                return True
        elif n == p:
            return True
    return False


def deck_allowed(
    name: str,
    allowlist: Optional[list[str]] = None,
    blocklist: Optional[list[str]] = None,
) -> bool:
    """Empty allowlist = all decks; blocklist applied after allowlist."""
    allow = list(allowlist or [])
    block = list(blocklist or [])
    if allow and not _deck_matches(name, allow):
        return False
    if block and _deck_matches(name, block):
        return False
    return True


def _filter_decks(
    deck_names: list[str],
    allowlist: list[str],
    blocklist: list[str],
) -> list[str]:
    return [d for d in deck_names if deck_allowed(d, allowlist, blocklist)]


def _parse_review_row(row: Any) -> Optional[tuple[int, int]]:
    """
    Parse one cardReviews row → (review_id, time_ms).

    Official AnkiConnect (9 fields)::
        [id, cardID, usn, ease, ivl, lastIvl, factor, time, type]

    Compact / alternate (8 fields)::
        [id, usn, ease, ivl, lastIvl, factor, time, type]
    """
    if not isinstance(row, (list, tuple)) or len(row) < 7:
        return None
    try:
        review_id = int(row[0])
    except (TypeError, ValueError):
        return None
    # Duration is the last numeric before type when present
    time_idx = 7 if len(row) >= 9 else 6
    try:
        time_ms = int(row[time_idx])
    except (TypeError, ValueError, IndexError):
        return None
    if time_ms < 0:
        time_ms = 0
    return review_id, time_ms


def _get_watermark(db: Session) -> int:
    raw = (get_state(db, STATE_LAST_REVIEW_ID) or "").strip()
    if not raw:
        return 0
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return 0


def _set_watermark(db: Session, review_id: int) -> None:
    set_state(db, STATE_LAST_REVIEW_ID, str(int(review_id)))


def _is_bootstrapped(db: Session) -> bool:
    return (get_state(db, STATE_BOOTSTRAPPED) or "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _set_bootstrapped(db: Session) -> None:
    set_state(db, STATE_BOOTSTRAPPED, "1")


def _list_decks() -> list[str]:
    names = anki_invoke("deckNames")
    if not isinstance(names, list):
        raise AnkiConnectError("deckNames returned non-list")
    return [str(n) for n in names if str(n).strip()]


def _card_reviews(deck: str, start_id: int) -> list[Any]:
    result = anki_invoke(
        "cardReviews",
        {"deck": deck, "startID": int(start_id)},
    )
    if result is None:
        return []
    if not isinstance(result, list):
        raise AnkiConnectError(f"cardReviews for {deck!r} returned non-list")
    return result


def _max_review_id_for_decks(decks: list[str], start_id: int = 0) -> int:
    """Highest review id across decks (optionally only after start_id)."""
    max_id = int(start_id)
    for deck in decks:
        # Prefer cheap latest-id when bootstrapping from 0
        if start_id == 0:
            try:
                latest = anki_invoke("getLatestReviewID", {"deck": deck})
                if latest is not None:
                    lid = int(latest)
                    if lid > max_id:
                        max_id = lid
                    continue
            except (AnkiConnectError, TypeError, ValueError):
                pass
        for row in _card_reviews(deck, start_id):
            parsed = _parse_review_row(row)
            if parsed and parsed[0] > max_id:
                max_id = parsed[0]
    return max_id


def _collect_reviews(
    decks: list[str],
    start_id: int,
) -> tuple[int, int, int]:
    """
    Sum review time for reviews with id > start_id across decks.

    Returns (total_ms, max_review_id, review_count).
    max_review_id is at least start_id when no newer reviews exist.
    """
    total_ms = 0
    max_id = int(start_id)
    count = 0
    for deck in decks:
        for row in _card_reviews(deck, start_id):
            parsed = _parse_review_row(row)
            if not parsed:
                continue
            rid, t_ms = parsed
            if rid <= start_id:
                continue
            total_ms += t_ms
            count += 1
            if rid > max_id:
                max_id = rid
    return total_ms, max_id, count


def poll_anki(db: Session) -> PollResult:
    """
    Scheduled / manual AnkiConnect poll.

    1. Disabled → early exit
    2. First success (not bootstrapped) → set watermark to current max, no log
    3. Else sum review time since watermark; log if ≥ min_delta_minutes
    4. Advance watermark only after a log (or duplicate); hold if below min_delta
    """
    cfg = _anki_cfg()
    if not getattr(cfg, "enabled", False):
        return PollResult(
            ok=True,
            source=SOURCE,
            message="disabled",
        )

    allowlist = list(getattr(cfg, "deck_allowlist", None) or [])
    blocklist = list(getattr(cfg, "deck_blocklist", None) or [])
    min_delta = float(getattr(cfg, "min_delta_minutes", 0.5) or 0.0)

    try:
        all_decks = _list_decks()
        decks = _filter_decks(all_decks, allowlist, blocklist)
    except AnkiConnectError as exc:
        logger.warning("anki poll: connection failed: %s", exc)
        return PollResult(
            ok=False,
            source=SOURCE,
            message=str(exc),
            errors=[str(exc)],
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("anki poll: unexpected error listing decks")
        return PollResult(
            ok=False,
            source=SOURCE,
            message=str(exc),
            errors=[str(exc)],
        )

    if not decks:
        return PollResult(
            ok=True,
            source=SOURCE,
            message="no decks match allow/block filter",
            details={
                "decks_total": len(all_decks),
                "decks_selected": 0,
            },
        )

    # Bootstrap: first contact baselines watermark without logging history
    if not _is_bootstrapped(db):
        try:
            max_id = _max_review_id_for_decks(decks, start_id=0)
        except AnkiConnectError as exc:
            return PollResult(
                ok=False,
                source=SOURCE,
                message=str(exc),
                errors=[str(exc)],
            )
        _set_watermark(db, max_id)
        _set_bootstrapped(db)
        logger.info("anki bootstrap: last_review_id=%s decks=%s", max_id, len(decks))
        return PollResult(
            ok=True,
            source=SOURCE,
            logs_created=0,
            message="bootstrapped; historical reviews skipped",
            details={
                "bootstrapped": True,
                "last_review_id": max_id,
                "decks_selected": len(decks),
                "decks_total": len(all_decks),
            },
        )

    watermark = _get_watermark(db)
    try:
        total_ms, max_id, review_count = _collect_reviews(decks, watermark)
    except AnkiConnectError as exc:
        return PollResult(
            ok=False,
            source=SOURCE,
            message=str(exc),
            errors=[str(exc)],
            details={"last_review_id": watermark},
        )

    minutes = total_ms / 60_000.0
    details: dict[str, Any] = {
        "last_review_id_before": watermark,
        "last_review_id": max_id,
        "review_count": review_count,
        "total_ms": total_ms,
        "minutes": round(minutes, 4),
        "decks_selected": len(decks),
        "decks_total": len(all_decks),
        "min_delta_minutes": min_delta,
    }

    logs_created = 0
    skipped = 0
    message = "no new reviews"

    if review_count == 0:
        return PollResult(
            ok=True,
            source=SOURCE,
            message=message,
            details=details,
        )

    if minutes + 1e-12 < min_delta:
        # Hold watermark so sub-threshold reviews accumulate across polls
        skipped = 1
        message = (
            f"below min_delta_minutes ({minutes:.3f} < {min_delta}); "
            f"holding watermark ({review_count} reviews pending)"
        )
        return PollResult(
            ok=True,
            source=SOURCE,
            skipped=skipped,
            message=message,
            details=details,
        )

    # Round to 2 decimal minutes for stable amounts
    amount = round(minutes, 2)
    if amount <= 0:
        amount = round(minutes, 4)
    source_ref = f"anki:{watermark}:{max_id}"
    title = (getattr(cfg, "title", None) or "Anki").strip() or "Anki"
    series_key = (getattr(cfg, "series_key", None) or "anki").strip() or "anki"
    content_type = (getattr(cfg, "content_type", None) or "study").strip() or "study"
    unit = (getattr(cfg, "unit", None) or "minutes").strip() or "minutes"
    activity = (getattr(cfg, "activity", None) or "study").strip() or "study"

    # Timestamp ≈ last review in batch (review id is epoch ms)
    ts: Optional[datetime] = None
    if max_id > 0:
        try:
            ts = datetime.fromtimestamp(max_id / 1000.0, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            ts = None

    notes = f"{review_count} reviews; {total_ms}ms via AnkiConnect"
    try:
        create_log(
            db,
            content_type=content_type,
            title=title,
            source=SOURCE,
            amount=float(amount),
            unit=unit,
            activity=activity,
            series_key=series_key,
            source_ref=source_ref,
            notes=notes,
            timestamp=ts,
        )
        logs_created = 1
        message = f"logged {amount} study minutes ({review_count} reviews)"
    except DuplicateLogError:
        skipped = 1
        message = f"duplicate source_ref {source_ref}"
        logger.info("anki poll: %s", message)
    except Exception as exc:  # noqa: BLE001
        logger.exception("anki poll: create_log failed")
        return PollResult(
            ok=False,
            source=SOURCE,
            message=f"create_log failed: {exc}",
            errors=[str(exc)],
            details=details,
        )

    _set_watermark(db, max_id)
    return PollResult(
        ok=True,
        source=SOURCE,
        logs_created=logs_created,
        skipped=skipped,
        message=message,
        details=details,
    )


def anki_status(db: Session) -> dict[str, Any]:
    """Health / config snapshot for GET /api/anki/status."""
    cfg = _anki_cfg()
    enabled = bool(getattr(cfg, "enabled", False))
    watermark = _get_watermark(db)
    bootstrapped = _is_bootstrapped(db)
    out: dict[str, Any] = {
        "ok": False,
        "enabled": enabled,
        "connected": False,
        "connect_url": getattr(cfg, "connect_url", "") or "",
        "poll_seconds": int(getattr(cfg, "poll_seconds", 300) or 300),
        "min_delta_minutes": float(getattr(cfg, "min_delta_minutes", 0.5) or 0.0),
        "deck_allowlist": list(getattr(cfg, "deck_allowlist", None) or []),
        "deck_blocklist": list(getattr(cfg, "deck_blocklist", None) or []),
        "content_type": getattr(cfg, "content_type", "study"),
        "unit": getattr(cfg, "unit", "minutes"),
        "activity": getattr(cfg, "activity", "study"),
        "title": getattr(cfg, "title", "Anki"),
        "series_key": getattr(cfg, "series_key", "anki"),
        "tadoku_default": getattr(cfg, "tadoku_default", "never"),
        "bootstrapped": bootstrapped,
        "last_review_id": watermark if watermark else None,
        "anki_connect_version": None,
        "decks_total": None,
        "decks_selected": None,
        "message": "",
    }

    if not enabled:
        out["message"] = "Anki integration is disabled (anki.enabled: false)."
        return out

    try:
        ver = anki_invoke("version")
        out["anki_connect_version"] = ver
        out["connected"] = True
        try:
            # Best-effort permission ping (no-op if already allowed)
            anki_invoke("requestPermission")
        except AnkiConnectError:
            pass
        all_decks = _list_decks()
        selected = _filter_decks(
            all_decks,
            list(getattr(cfg, "deck_allowlist", None) or []),
            list(getattr(cfg, "deck_blocklist", None) or []),
        )
        out["decks_total"] = len(all_decks)
        out["decks_selected"] = len(selected)
        out["ok"] = True
        out["message"] = "AnkiConnect reachable."
        if not bootstrapped:
            out["message"] = "AnkiConnect reachable; not bootstrapped yet (next poll will baseline)."
    except AnkiConnectError as exc:
        out["message"] = f"AnkiConnect unreachable: {exc}"
        out["ok"] = False
        out["connected"] = False
    except Exception as exc:  # noqa: BLE001
        out["message"] = f"AnkiConnect error: {exc}"
        out["ok"] = False

    return out
