"""
Audiobookshelf listening sessions → immersion listening logs (minutes).

Polls /api/me/listening-sessions, accumulates pending minutes per item (rolling),
then creates LogEntry on:
  - manual submit (Inbox)
  - log_mode=auto when min minutes + idle met
  - daily dump at fixed local hour (idle ignored; min still applied)

Never mutates ABS. Session timeListening watermarks live in immersion state.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy.orm import Session

from app.core.config import AudiobookshelfConfig, get_settings
from app.db.models import LogEntry
from app.ingest.service import DuplicateLogError, create_log
from app.sheets.state import get_state, set_state

logger = logging.getLogger(__name__)

SOURCE = "audiobookshelf"

STATE_WATERMARKS = "abs:session_watermarks"  # {session_id: absorbed_seconds}
STATE_PROGRESS_WM = "abs:progress_watermarks"  # {bucket_key: {currentTime, lastUpdate}}
STATE_STATS_WM = "abs:stats_watermarks"  # {libraryItemId: timeListening absorbed}
STATE_ITEM_CREDITED = "abs:item_credited_seconds"  # {libraryItemId: total ever banked}
STATE_PENDING = "abs:pending_buckets"  # {bucket_key: {...}}
STATE_BOOTSTRAPPED = "abs:bootstrapped"
STATE_SEEDED = "abs:seeded_pending_v1"
STATE_CATCHUP = "abs:position_catchup_v5"  # one-shot: playhead minutes not yet banked
STATE_LAST_POLL = "abs:last_poll_at"
STATE_LAST_RESULT = "abs:last_result"
STATE_LAST_DAILY = "abs:last_daily_log_date"
STATE_LAST_SUBMIT = "abs:last_submit_at"

PREF_LOG_MODE = "abs:pref:log_mode"
PREF_MIN_SUBMIT = "abs:pref:min_submit_minutes"
PREF_IDLE = "abs:pref:auto_submit_idle_minutes"
PREF_DAILY = "abs:pref:auto_log_at_time_enabled"
PREF_HOUR = "abs:pref:auto_log_at_hour"


class AbsError(RuntimeError):
    """ABS API / config failure."""


def _cfg() -> AudiobookshelfConfig:
    return get_settings().yaml_config.audiobookshelf


def _token(cfg: Optional[AudiobookshelfConfig] = None) -> str:
    c = cfg or _cfg()
    raw = (c.api_token or "").strip()
    if not raw:
        raw = (
            os.environ.get("AUDIOBOOKSHELF_TOKEN")
            or os.environ.get("ABS_TOKEN")
            or os.environ.get("AUDIOBOOKSHELF_API_TOKEN")
            or ""
        ).strip()
    return raw


def _base_url(cfg: Optional[AudiobookshelfConfig] = None) -> str:
    c = cfg or _cfg()
    url = (c.base_url or "").strip().rstrip("/")
    if not url:
        url = (
            os.environ.get("AUDIOBOOKSHELF_URL")
            or os.environ.get("ABS_URL")
            or ""
        ).strip().rstrip("/")
    return url


def _auth_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }


def _load_json_state(db: Session, key: str, default: Any) -> Any:
    raw = get_state(db, key)
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


def _save_json_state(db: Session, key: str, value: Any) -> None:
    set_state(db, key, json.dumps(value, separators=(",", ":")))


def get_log_mode(db: Optional[Session] = None) -> str:
    if db is not None:
        v = (get_state(db, PREF_LOG_MODE) or "").strip().lower()
        if v in ("manual", "auto"):
            return v
    return (getattr(_cfg(), "log_mode", "manual") or "manual").strip().lower()


def get_min_submit_minutes(db: Optional[Session] = None) -> float:
    if db is not None:
        raw = (get_state(db, PREF_MIN_SUBMIT) or "").strip()
        if raw:
            try:
                return max(0.1, float(raw))
            except ValueError:
                pass
    return max(0.1, float(getattr(_cfg(), "min_submit_minutes", 5) or 5))


def get_idle_minutes(db: Optional[Session] = None) -> float:
    if db is not None:
        raw = (get_state(db, PREF_IDLE) or "").strip()
        if raw:
            try:
                return max(0.0, float(raw))
            except ValueError:
                pass
    return max(0.0, float(getattr(_cfg(), "auto_submit_idle_minutes", 30) or 0))


def get_auto_log_at_time_enabled(db: Optional[Session] = None) -> bool:
    if db is not None:
        raw = (get_state(db, PREF_DAILY) or "").strip().lower()
        if raw in ("1", "true", "yes", "on"):
            return True
        if raw in ("0", "false", "no", "off"):
            return False
    return bool(getattr(_cfg(), "auto_log_at_time_enabled", False))


def get_auto_log_at_hour(db: Optional[Session] = None) -> int:
    if db is not None:
        raw = (get_state(db, PREF_HOUR) or "").strip()
        if raw:
            try:
                return max(0, min(23, int(raw)))
            except ValueError:
                pass
    return max(0, min(23, int(getattr(_cfg(), "auto_log_at_hour", 4) or 4)))


def get_timezone_name() -> str:
    cfg = _cfg()
    return (
        (getattr(cfg, "timezone", None) or "").strip()
        or os.environ.get("TZ")
        or "America/Los_Angeles"
    )


def get_prefs(db: Optional[Session] = None) -> dict[str, Any]:
    return {
        "log_mode": get_log_mode(db),
        "min_submit_minutes": get_min_submit_minutes(db),
        "auto_submit_idle_minutes": get_idle_minutes(db),
        "auto_log_at_time_enabled": get_auto_log_at_time_enabled(db),
        "auto_log_at_hour": get_auto_log_at_hour(db),
        "timezone": get_timezone_name(),
    }


def set_prefs(
    db: Session,
    *,
    log_mode: Optional[str] = None,
    min_submit_minutes: Optional[float] = None,
    auto_submit_idle_minutes: Optional[float] = None,
    auto_log_at_time_enabled: Optional[bool] = None,
    auto_log_at_hour: Optional[int] = None,
) -> dict[str, Any]:
    if log_mode is not None:
        mode = str(log_mode).strip().lower()
        if mode not in ("manual", "auto"):
            raise AbsError("log_mode must be manual or auto")
        set_state(db, PREF_LOG_MODE, mode)
    if min_submit_minutes is not None:
        set_state(db, PREF_MIN_SUBMIT, str(max(0.1, float(min_submit_minutes))))
    if auto_submit_idle_minutes is not None:
        set_state(db, PREF_IDLE, str(max(0.0, float(auto_submit_idle_minutes))))
    if auto_log_at_time_enabled is not None:
        set_state(
            db,
            PREF_DAILY,
            "true" if auto_log_at_time_enabled else "false",
        )
    if auto_log_at_hour is not None:
        set_state(db, PREF_HOUR, str(max(0, min(23, int(auto_log_at_hour)))))
    db.commit()
    return get_prefs(db)


def _bucket_key(library_item_id: str, episode_id: Optional[str] = None) -> str:
    lid = (library_item_id or "").strip()
    eid = (episode_id or "").strip()
    return f"{lid}:{eid}" if eid else lid


def _last_logged_at(db: Session) -> Optional[str]:
    """ISO time of last ABS → Tadoku submit (state, else newest log)."""
    raw = (get_state(db, STATE_LAST_SUBMIT) or "").strip()
    if raw:
        return raw
    try:
        row = (
            db.query(LogEntry)
            .filter(LogEntry.source == SOURCE)
            .order_by(LogEntry.timestamp.desc())
            .first()
        )
    except Exception:  # noqa: BLE001
        return None
    if row is None or row.timestamp is None:
        return None
    ts = row.timestamp
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc).isoformat()


def fetch_cover_bytes(
    item_id: str, *, width: int = 48
) -> Optional[tuple[bytes, str]]:
    """Small ABS cover only (yaabsa same /api/items/{id}/cover). None if large/missing."""
    iid = (item_id or "").strip()
    if not iid or "/" in iid or ".." in iid:
        return None
    cfg = _cfg()
    base = _base_url(cfg)
    token = _token(cfg)
    if not base or not token:
        return None
    w = max(24, min(int(width or 48), 96))
    url = f"{base}/api/items/{iid}/cover"
    try:
        with httpx.Client(timeout=8.0, follow_redirects=True) as client:
            r = client.get(
                url,
                headers=_auth_headers(token),
                params={"width": w, "height": w},
            )
        if r.status_code != 200 or not r.content:
            return None
        # Refuse anything that isn't a small thumbnail.
        if len(r.content) > 180_000:
            return None
        ct = (r.headers.get("content-type") or "image/jpeg").split(";")[0].strip()
        if ct and not ct.startswith("image/"):
            return None
        return r.content, (ct or "image/jpeg")
    except Exception:  # noqa: BLE001
        logger.debug("abs cover fetch failed item=%s", iid, exc_info=True)
        return None


def _series_key_for(title: str, library_item_id: str) -> str:
    base = (title or "").strip() or library_item_id or "abs-unknown"
    slug = re.sub(r"[^\w\s\-]", "", base, flags=re.UNICODE)
    slug = re.sub(r"\s+", "-", slug.strip().lower())[:80] or "abs-item"
    short = (library_item_id or "")[:12]
    return f"abs:{slug}:{short}" if short else f"abs:{slug}"


def _content_type_for(media_type: str, cfg: AudiobookshelfConfig) -> str:
    mt = (media_type or "book").strip().lower()
    if mt == "podcast":
        return (cfg.podcast_content_type or "podcast").strip() or "podcast"
    return (cfg.content_type or "audiobook").strip() or "audiobook"


def _parse_iso_ms(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    try:
        if isinstance(value, (int, float)):
            # ABS uses ms epoch
            sec = float(value) / (1000.0 if float(value) > 1e12 else 1.0)
            return datetime.fromtimestamp(sec, tz=timezone.utc)
        s = str(value).strip()
        if not s:
            return None
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    except Exception:  # noqa: BLE001
        return None


def fetch_listening_sessions(
    *,
    base_url: str,
    token: str,
    timeout: float = 30.0,
    max_pages: int = 40,
    items_per_page: int = 50,
) -> list[dict[str, Any]]:
    """Paginate GET /api/me/listening-sessions."""
    headers = _auth_headers(token)
    out: list[dict[str, Any]] = []
    with httpx.Client(timeout=timeout, headers=headers) as client:
        for page in range(max(1, int(max_pages))):
            r = client.get(
                f"{base_url}/api/me/listening-sessions",
                params={"itemsPerPage": items_per_page, "page": page},
            )
            if r.status_code == 401:
                raise AbsError("ABS auth failed (check api_token)")
            if r.status_code >= 400:
                raise AbsError(f"ABS sessions HTTP {r.status_code}: {r.text[:200]}")
            data = r.json() if r.content else {}
            sessions = data.get("sessions") or data.get("items") or []
            if not isinstance(sessions, list):
                break
            out.extend(s for s in sessions if isinstance(s, dict))
            total = data.get("total")
            num_pages = data.get("numPages")
            if num_pages is not None and page + 1 >= int(num_pages):
                break
            if total is not None and len(out) >= int(total):
                break
            if len(sessions) < items_per_page:
                break
    return out


def _session_allowed(session: dict[str, Any], cfg: AudiobookshelfConfig) -> bool:
    mt = (session.get("mediaType") or "book").strip().lower()
    if mt == "podcast" and not bool(getattr(cfg, "include_podcasts", True)):
        return False
    if mt != "podcast" and not bool(getattr(cfg, "include_books", True)):
        return False
    libs = list(getattr(cfg, "library_ids", None) or [])
    if libs:
        lid = str(session.get("libraryId") or "").strip()
        if lid and lid not in {str(x).strip() for x in libs}:
            return False
    return True


def _credit_pending(
    pending: dict[str, Any],
    *,
    key: str,
    item_id: str,
    ep_id: Optional[str],
    title: str,
    author: str,
    media_type: str,
    delta: float,
    activity_at: datetime,
    source_tag: str,
    item_credited: Optional[dict[str, float]] = None,
) -> None:
    if delta <= 0:
        return
    row = pending.get(key) or {
        "key": key,
        "library_item_id": item_id,
        "episode_id": ep_id,
        "title": title,
        "author": author,
        "media_type": media_type,
        "pending_seconds": 0.0,
        "last_activity_at": None,
        "sources": {},
    }
    row["title"] = title or row.get("title")
    row["author"] = author or row.get("author")
    row["media_type"] = media_type or row.get("media_type")
    row["pending_seconds"] = float(row.get("pending_seconds") or 0) + delta
    row["last_activity_at"] = activity_at.astimezone(timezone.utc).isoformat()
    sources = dict(row.get("sources") or {})
    sources[source_tag] = float(sources.get(source_tag) or 0) + delta
    row["sources"] = sources
    pending[key] = row
    if item_credited is not None and item_id:
        item_credited[str(item_id)] = float(item_credited.get(str(item_id)) or 0) + delta


def _absorb_sessions(
    db: Session,
    sessions: list[dict[str, Any]],
    *,
    bootstrap: bool = False,
    credit: bool = True,
    pending: Optional[dict[str, Any]] = None,
    watermarks: Optional[dict[str, float]] = None,
    persist: bool = True,
) -> dict[str, Any]:
    """
    Update session watermarks and optionally pending from ABS sessions.

    When listening-stats is enabled, pass credit=False so session rows only track
    watermarks (stats + position own pending — avoids triple-counting).
    """
    cfg = _cfg()
    # Dust only — never drop real multi-second sync chunks (old min_session_seconds
    # advanced the watermark without banking; live listens vanished).
    min_sec = max(0.0, float(getattr(cfg, "min_session_seconds", 0) or 0))
    if watermarks is None:
        watermarks = {
            str(k): float(v)
            for k, v in (_load_json_state(db, STATE_WATERMARKS, {}) or {}).items()
        }
    if pending is None:
        pending = dict(_load_json_state(db, STATE_PENDING, {}) or {})

    absorbed = 0.0
    touched = 0
    new_sessions = 0
    credited_keys: set[str] = set()

    for s in sessions:
        if not _session_allowed(s, cfg):
            continue
        sid = str(s.get("id") or "").strip()
        item_id = str(s.get("libraryItemId") or "").strip()
        if not sid or not item_id:
            continue
        try:
            tl = float(s.get("timeListening") or 0)
        except (TypeError, ValueError):
            continue
        if tl < 0:
            continue

        prev = float(watermarks.get(sid, 0.0) or 0.0)
        if sid not in watermarks:
            new_sessions += 1

        if (bootstrap or not credit) and sid not in watermarks:
            watermarks[sid] = tl
            continue

        if bootstrap and sid not in watermarks:
            watermarks[sid] = tl
            continue

        if tl <= prev + 1e-6:
            watermarks[sid] = max(prev, tl)
            continue

        delta = tl - prev
        watermarks[sid] = tl
        if bootstrap or not credit:
            continue
        if delta < max(0.5, min_sec):
            # Keep watermark (already raised); ignore sub-second dust only.
            continue

        ep = s.get("episodeId")
        ep_id = str(ep).strip() if ep else None
        key = _bucket_key(item_id, ep_id)
        title = (s.get("displayTitle") or "").strip() or item_id
        author = (s.get("displayAuthor") or "").strip()
        media_type = (s.get("mediaType") or "book").strip().lower()
        activity_at = (
            _parse_iso_ms(s.get("updatedAt"))
            or _parse_iso_ms(s.get("startedAt"))
            or datetime.now(timezone.utc)
        )
        _credit_pending(
            pending,
            key=key,
            item_id=item_id,
            ep_id=ep_id,
            title=title,
            author=author,
            media_type=media_type,
            delta=delta,
            activity_at=activity_at,
            source_tag="session",
        )
        absorbed += delta
        touched += 1
        credited_keys.add(key)

    if persist:
        _save_json_state(db, STATE_WATERMARKS, watermarks)
        _save_json_state(db, STATE_PENDING, pending)
        db.commit()
    return {
        "absorbed_seconds": absorbed,
        "buckets_touched": touched,
        "new_sessions": new_sessions,
        "pending_buckets": len([b for b in pending.values() if float(b.get("pending_seconds") or 0) > 0]),
        "pending_seconds": sum(float(b.get("pending_seconds") or 0) for b in pending.values()),
        "bootstrapped": bootstrap,
        "watermarks": watermarks,
        "pending": pending,
        "credited_keys": credited_keys,
    }


def fetch_media_progress(
    *,
    base_url: str,
    token: str,
    timeout: float = 30.0,
) -> list[dict[str, Any]]:
    """GET /api/me mediaProgress (yaabsa + ABS clients update this while playing)."""
    headers = _auth_headers(token)
    with httpx.Client(timeout=timeout, headers=headers) as client:
        r = client.get(f"{base_url}/api/me")
        if r.status_code == 401:
            raise AbsError("ABS auth failed (check api_token)")
        if r.status_code >= 400:
            raise AbsError(f"ABS /api/me HTTP {r.status_code}: {r.text[:200]}")
        data = r.json() if r.content else {}
    mp = data.get("mediaProgress") or data.get("mediaProgresses") or []
    return [p for p in mp if isinstance(p, dict)] if isinstance(mp, list) else []


def fetch_listening_stats(
    *,
    base_url: str,
    token: str,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """GET /api/me/listening-stats — lifetime timeListening per library item."""
    headers = _auth_headers(token)
    with httpx.Client(timeout=timeout, headers=headers) as client:
        r = client.get(f"{base_url}/api/me/listening-stats")
        if r.status_code == 401:
            raise AbsError("ABS auth failed (check api_token)")
        if r.status_code >= 400:
            raise AbsError(f"ABS listening-stats HTTP {r.status_code}: {r.text[:200]}")
        data = r.json() if r.content else {}
    return data if isinstance(data, dict) else {}


def _ms(value: Any) -> float:
    try:
        v = float(value) if value is not None else 0.0
    except (TypeError, ValueError):
        return 0.0
    if 0 < v < 1e12:
        v *= 1000.0
    return v


def _item_meta_from_sessions(
    sessions: list[dict[str, Any]], item_id: str, ep_id: Optional[str]
) -> tuple[str, str, str]:
    for s in sessions:
        if str(s.get("libraryItemId") or "") != item_id:
            continue
        sep = s.get("episodeId")
        sep_id = str(sep).strip() if sep else None
        if (ep_id or None) != (sep_id or None):
            continue
        return (
            (s.get("displayTitle") or "").strip() or item_id,
            (s.get("displayAuthor") or "").strip(),
            (s.get("mediaType") or "book").strip().lower(),
        )
    return item_id, "", "book"


def _meta_from_stats_item(item: dict[str, Any], item_id: str) -> tuple[str, str, str]:
    md = item.get("mediaMetadata") or {}
    title = (md.get("title") or "").strip() or item_id
    authors = md.get("authors") or []
    author = ""
    if isinstance(authors, list) and authors:
        names = []
        for a in authors:
            if isinstance(a, dict) and a.get("name"):
                names.append(str(a["name"]))
            elif isinstance(a, str):
                names.append(a)
        author = ", ".join(names)
    return title, author, "book"


def _absorb_progress(
    db: Session,
    progress_rows: list[dict[str, Any]],
    *,
    sessions: Optional[list[dict[str, Any]]] = None,
    pending: Optional[dict[str, Any]] = None,
    item_credited: Optional[dict[str, float]] = None,
    bootstrap: bool = False,
    skip_keys: Optional[set[str]] = None,
    persist: bool = True,
) -> dict[str, Any]:
    """
    Credit playhead advances (currentTime), capped by wall clock × max_play_speed.

    This is what catches yaabsa/ABS when they move the bookmark but under-report
    session timeListening (seek-safe via wall-clock cap).
    """
    cfg = _cfg()
    if not bool(getattr(cfg, "use_position", True)):
        return {"absorbed_seconds": 0.0, "buckets_touched": 0, "baselined": 0, "pending": pending}

    speed = max(1.0, float(getattr(cfg, "max_play_speed", 2.5) or 2.5))
    wm: dict[str, Any] = dict(_load_json_state(db, STATE_PROGRESS_WM, {}) or {})
    if pending is None:
        pending = dict(_load_json_state(db, STATE_PENDING, {}) or {})
    if item_credited is None:
        item_credited = {
            str(k): float(v)
            for k, v in (_load_json_state(db, STATE_ITEM_CREDITED, {}) or {}).items()
        }
    sessions = sessions or []
    skip_keys = skip_keys or set()

    absorbed = 0.0
    touched = 0
    baselined = 0
    now_ms = datetime.now(timezone.utc).timestamp() * 1000.0
    last_poll = _parse_iso_ms(get_state(db, STATE_LAST_POLL) or "")
    poll_wall = (
        (datetime.now(timezone.utc) - last_poll).total_seconds()
        if last_poll
        else float(getattr(cfg, "poll_seconds", 120) or 120)
    )
    poll_wall = max(5.0, min(poll_wall, 3600.0))

    for p in progress_rows:
        item_id = str(p.get("libraryItemId") or "").strip()
        if not item_id:
            # newer ABS may only put libraryItemId in extraData
            extra = p.get("extraData")
            if isinstance(extra, str):
                try:
                    extra = json.loads(extra)
                except json.JSONDecodeError:
                    extra = {}
            if isinstance(extra, dict):
                item_id = str(extra.get("libraryItemId") or "").strip()
        if not item_id:
            continue
        ep = p.get("episodeId")
        ep_id = str(ep).strip() if ep else None
        key = _bucket_key(item_id, ep_id)
        try:
            ct = float(p.get("currentTime") or 0)
        except (TypeError, ValueError):
            continue
        lu = _ms(p.get("lastUpdate") or p.get("updatedAt"))
        if lu <= 0:
            lu = now_ms

        prev = wm.get(key)
        title, author, media_type = _item_meta_from_sessions(sessions, item_id, ep_id)

        if not prev or bootstrap:
            wm[key] = {"currentTime": ct, "lastUpdate": lu}
            baselined += 1
            continue

        try:
            prev_ct = float(prev.get("currentTime") or 0)
            prev_lu = float(prev.get("lastUpdate") or 0)
        except (TypeError, ValueError, AttributeError):
            wm[key] = {"currentTime": ct, "lastUpdate": lu}
            baselined += 1
            continue

        d_pos = ct - prev_ct
        d_wall = (lu - prev_lu) / 1000.0 if lu and prev_lu else 0.0
        # If ABS only bumps currentTime and lastUpdate stalls, fall back to poll gap
        if d_pos > 0.5 and d_wall < 0.5:
            d_wall = poll_wall
        wm[key] = {"currentTime": ct, "lastUpdate": lu}

        if key in skip_keys:
            continue
        if d_pos <= 0.5:
            continue
        if d_wall <= 0:
            continue
        credit = min(d_pos, d_wall * speed)
        if credit < 0.5:
            continue

        activity_at = _parse_iso_ms(lu) or datetime.now(timezone.utc)
        _credit_pending(
            pending,
            key=key,
            item_id=item_id,
            ep_id=ep_id,
            title=title,
            author=author,
            media_type=media_type,
            delta=credit,
            activity_at=activity_at,
            source_tag="position",
            item_credited=item_credited,
        )
        # stash bookmark + duration on row for UI progress bar
        row = pending.get(key) or {}
        row["bookmark_seconds"] = ct
        try:
            dur = float(p.get("duration") or 0)
        except (TypeError, ValueError):
            dur = 0.0
        if dur > 0:
            row["duration_seconds"] = dur
        pending[key] = row
        absorbed += credit
        touched += 1

    if persist:
        _save_json_state(db, STATE_PROGRESS_WM, wm)
        _save_json_state(db, STATE_ITEM_CREDITED, item_credited)
        _save_json_state(db, STATE_PENDING, pending)
        db.commit()
    return {
        "absorbed_seconds": absorbed,
        "buckets_touched": touched,
        "baselined": baselined,
        "pending": pending,
        "item_credited": item_credited,
    }


def _absorb_listening_stats(
    db: Session,
    stats: dict[str, Any],
    *,
    sessions: Optional[list[dict[str, Any]]] = None,
    pending: Optional[dict[str, Any]] = None,
    item_credited: Optional[dict[str, float]] = None,
    bootstrap: bool = False,
    persist: bool = True,
) -> dict[str, Any]:
    """
    Raise pending so each item is at least ABS lifetime timeListening.

    Uses item_credited totals so position credits already banked are not repeated.
    """
    cfg = _cfg()
    if not bool(getattr(cfg, "use_listening_stats", True)):
        return {"absorbed_seconds": 0.0, "buckets_touched": 0, "pending": pending}

    items = stats.get("items") or {}
    if not isinstance(items, dict):
        return {"absorbed_seconds": 0.0, "buckets_touched": 0, "pending": pending}

    if item_credited is None:
        item_credited = {
            str(k): float(v)
            for k, v in (_load_json_state(db, STATE_ITEM_CREDITED, {}) or {}).items()
        }
    if pending is None:
        pending = dict(_load_json_state(db, STATE_PENDING, {}) or {})
    sessions = sessions or []

    absorbed = 0.0
    touched = 0
    for item_id, raw in items.items():
        if not isinstance(raw, dict):
            continue
        iid = str(item_id).strip()
        try:
            tl = float(raw.get("timeListening") or 0)
        except (TypeError, ValueError):
            continue
        if tl < 0:
            continue
        already = float(item_credited.get(iid) or 0)
        key = _bucket_key(iid, None)
        pending_s = float((pending.get(key) or {}).get("pending_seconds") or 0)
        floor = max(already, pending_s)
        # Bootstrap: do not dump lifetime totals into pending (catch-up pass owns backfill).
        if bootstrap:
            continue
        if tl <= floor + 0.5:
            continue
        delta = tl - floor
        title, author, media_type = _meta_from_stats_item(raw, iid)
        st, sa, sm = _item_meta_from_sessions(sessions, iid, None)
        if st and st != iid:
            title, author, media_type = st, sa or author, sm or media_type
        key = _bucket_key(iid, None)
        _credit_pending(
            pending,
            key=key,
            item_id=iid,
            ep_id=None,
            title=title,
            author=author,
            media_type=media_type,
            delta=delta,
            activity_at=datetime.now(timezone.utc),
            source_tag="stats",
            item_credited=item_credited,
        )
        absorbed += delta
        touched += 1

    if persist:
        _save_json_state(db, STATE_ITEM_CREDITED, item_credited)
        _save_json_state(db, STATE_PENDING, pending)
        db.commit()
    return {
        "absorbed_seconds": absorbed,
        "buckets_touched": touched,
        "pending": pending,
        "item_credited": item_credited,
    }


def _position_catchup(
    db: Session,
    progress_rows: list[dict[str, Any]],
    stats: dict[str, Any],
    sessions: list[dict[str, Any]],
    pending: dict[str, Any],
) -> dict[str, Any]:
    """
    One-shot: when playhead >> ABS reported timeListening, credit the gap.

    Happens when clients update bookmark/progress without full session TL
    (yaabsa/ABS mix, offline sync, etc.). Seek-forward still possible; UI shows
    bookmark vs pending so the user can discard.
    """
    items = stats.get("items") if isinstance(stats.get("items"), dict) else {}
    absorbed = 0.0
    touched = 0
    item_credited = {
        str(k): float(v)
        for k, v in (_load_json_state(db, STATE_ITEM_CREDITED, {}) or {}).items()
    }

    for p in progress_rows:
        item_id = str(p.get("libraryItemId") or "").strip()
        if not item_id:
            extra = p.get("extraData")
            if isinstance(extra, str):
                try:
                    extra = json.loads(extra)
                except json.JSONDecodeError:
                    extra = {}
            if isinstance(extra, dict):
                item_id = str(extra.get("libraryItemId") or "").strip()
        if not item_id:
            continue
        ep = p.get("episodeId")
        ep_id = str(ep).strip() if ep else None
        # books only for catch-up (podcasts are episode-scoped)
        if ep_id:
            continue
        try:
            ct = float(p.get("currentTime") or 0)
        except (TypeError, ValueError):
            continue
        key = _bucket_key(item_id, None)
        stats_tl = 0.0
        st_item = items.get(item_id) if isinstance(items.get(item_id), dict) else {}
        try:
            stats_tl = float((st_item or {}).get("timeListening") or 0)
        except (TypeError, ValueError):
            stats_tl = 0.0
        pending_s = float((pending.get(key) or {}).get("pending_seconds") or 0)
        already = float(item_credited.get(item_id) or 0)
        # Only subtract what WE already banked (pending / credited) — ABS stats TL
        # is often under-reported vs playhead and is NOT already in pending.
        accounted = max(already, pending_s)
        gap = ct - accounted
        if gap < 60:  # ignore tiny bookmark noise
            # still store bookmark for UI
            row = pending.get(key)
            if row is not None:
                row["bookmark_seconds"] = ct
            continue

        title, author, media_type = _item_meta_from_sessions(sessions, item_id, None)
        if title == item_id and st_item:
            title, author, media_type = _meta_from_stats_item(st_item, item_id)
        _credit_pending(
            pending,
            key=key,
            item_id=item_id,
            ep_id=None,
            title=title,
            author=author,
            media_type=media_type,
            delta=gap,
            activity_at=datetime.now(timezone.utc),
            source_tag="position_catchup",
            item_credited=item_credited,
        )
        row = pending.get(key) or {}
        row["bookmark_seconds"] = ct
        row["catchup_seconds"] = gap
        pending[key] = row
        absorbed += gap
        touched += 1

    # Align progress watermarks to current playhead so ongoing caps work cleanly
    wm: dict[str, Any] = dict(_load_json_state(db, STATE_PROGRESS_WM, {}) or {})
    now_ms = datetime.now(timezone.utc).timestamp() * 1000.0
    for p in progress_rows:
        item_id = str(p.get("libraryItemId") or "").strip()
        if not item_id:
            extra = p.get("extraData")
            if isinstance(extra, str):
                try:
                    extra = json.loads(extra)
                except json.JSONDecodeError:
                    extra = {}
            if isinstance(extra, dict):
                item_id = str(extra.get("libraryItemId") or "").strip()
        if not item_id:
            continue
        ep = p.get("episodeId")
        ep_id = str(ep).strip() if ep else None
        key = _bucket_key(item_id, ep_id)
        try:
            ct = float(p.get("currentTime") or 0)
        except (TypeError, ValueError):
            continue
        lu = _ms(p.get("lastUpdate") or p.get("updatedAt")) or now_ms
        wm[key] = {"currentTime": ct, "lastUpdate": lu}
    # Items with ABS listen time but no current progress row (e.g. finished books)
    for item_id, raw in items.items():
        if not isinstance(raw, dict):
            continue
        iid = str(item_id).strip()
        key = _bucket_key(iid, None)
        if float((pending.get(key) or {}).get("pending_seconds") or 0) > 0:
            continue
        try:
            tl = float(raw.get("timeListening") or 0)
        except (TypeError, ValueError):
            continue
        already = float(item_credited.get(iid) or 0)
        if tl <= already + 60:
            continue
        delta = tl - already
        title, author, media_type = _meta_from_stats_item(raw, iid)
        st, sa, sm = _item_meta_from_sessions(sessions, iid, None)
        if st and st != iid:
            title, author, media_type = st, sa or author, sm or media_type
        _credit_pending(
            pending,
            key=key,
            item_id=iid,
            ep_id=None,
            title=title,
            author=author,
            media_type=media_type,
            delta=delta,
            activity_at=datetime.now(timezone.utc),
            source_tag="stats_catchup",
            item_credited=item_credited,
        )
        absorbed += delta
        touched += 1

    _save_json_state(db, STATE_PROGRESS_WM, wm)
    _save_json_state(db, STATE_ITEM_CREDITED, item_credited)
    _save_json_state(db, STATE_PENDING, pending)
    db.commit()
    return {"absorbed_seconds": absorbed, "buckets_touched": touched, "pending": pending}


def poll_sessions(db: Session) -> dict[str, Any]:
    """Fetch ABS sessions + stats + progress; fold listen into pending buckets."""
    cfg = _cfg()
    if not getattr(cfg, "enabled", False):
        return {"ok": True, "skipped": True, "reason": "disabled"}

    base = _base_url(cfg)
    token = _token(cfg)
    if not base or not token:
        return {
            "ok": False,
            "skipped": True,
            "reason": "missing_url_or_token",
            "message": "Set audiobookshelf.base_url and api_token (or ABS_URL / ABS_TOKEN)",
        }

    timeout = float(getattr(cfg, "timeout_seconds", 30) or 30)
    try:
        sessions = fetch_listening_sessions(
            base_url=base, token=token, timeout=timeout
        )
        try:
            progress_rows = fetch_media_progress(
                base_url=base, token=token, timeout=timeout
            )
        except AbsError:
            progress_rows = []
        try:
            stats = fetch_listening_stats(
                base_url=base, token=token, timeout=timeout
            )
        except AbsError:
            stats = {}
    except AbsError as exc:
        set_state(db, STATE_LAST_POLL, datetime.now(timezone.utc).isoformat())
        set_state(db, STATE_LAST_RESULT, json.dumps({"ok": False, "error": str(exc)}))
        db.commit()
        return {"ok": False, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        logger.exception("abs poll failed")
        return {"ok": False, "error": str(exc)}

    bootstrapped = (get_state(db, STATE_BOOTSTRAPPED) or "").strip() in (
        "1",
        "true",
        "yes",
    )
    seeded = (get_state(db, STATE_SEEDED) or "").strip() in ("1", "true", "yes")
    catchup_done = (get_state(db, STATE_CATCHUP) or "").strip() in ("1", "true", "yes")
    do_bootstrap = (not bootstrapped) and bool(getattr(cfg, "bootstrap", True))

    messages: list[str] = []
    absorbed = 0.0
    touched = 0

    # Prefer stats+position for pending when stats enabled (session rows ⊆ stats).
    credit_sessions = not bool(getattr(cfg, "use_listening_stats", True))

    # One-shot session reimport after original empty-bootstrap bug
    if bootstrapped and not seeded and not do_bootstrap:
        _save_json_state(db, STATE_WATERMARKS, {})
        set_state(db, STATE_SEEDED, "true")
        db.commit()
        sess_part = _absorb_sessions(
            db, sessions, bootstrap=False, credit=True, persist=True
        )
        absorbed += float(sess_part.get("absorbed_seconds") or 0)
        touched += int(sess_part.get("buckets_touched") or 0)
        messages.append(
            f"imported {float(sess_part.get('absorbed_seconds') or 0):.0f}s from sessions"
        )
        pending = sess_part.get("pending") or dict(
            _load_json_state(db, STATE_PENDING, {}) or {}
        )
    else:
        sess_part = _absorb_sessions(
            db,
            sessions,
            bootstrap=do_bootstrap,
            credit=credit_sessions,
            persist=True,
        )
        absorbed += float(sess_part.get("absorbed_seconds") or 0)
        touched += int(sess_part.get("buckets_touched") or 0)
        pending = sess_part.get("pending") or dict(
            _load_json_state(db, STATE_PENDING, {}) or {}
        )
        if do_bootstrap:
            set_state(db, STATE_BOOTSTRAPPED, "true")
            set_state(db, STATE_SEEDED, "true")
            messages.append("bootstrapped; historical listening skipped")

    # listening-stats floor (lifetime TL per item)
    stats_part = _absorb_listening_stats(
        db,
        stats,
        sessions=sessions,
        pending=pending,
        bootstrap=do_bootstrap,
        persist=True,
    )
    absorbed += float(stats_part.get("absorbed_seconds") or 0)
    touched += int(stats_part.get("buckets_touched") or 0)
    pending = stats_part.get("pending") or pending

    # Playhead deltas (yaabsa/ABS bookmark), wall-clock capped
    prog_part = _absorb_progress(
        db,
        progress_rows,
        sessions=sessions,
        pending=pending,
        bootstrap=do_bootstrap,
        skip_keys=set(),  # max-with-stats handled by separate sources; small overlap ok
        persist=True,
    )
    # Avoid double-count when stats already covered same seconds this poll:
    # position credits are still valuable when stats lag; keep both but that's rare.
    absorbed += float(prog_part.get("absorbed_seconds") or 0)
    touched += int(prog_part.get("buckets_touched") or 0)
    pending = prog_part.get("pending") or pending

    # One-shot: playhead ahead of ABS timeListening (your medium ~84m vs ~9m TL case)
    if not catchup_done and not do_bootstrap:
        cup = _position_catchup(db, progress_rows, stats, sessions, pending)
        set_state(db, STATE_CATCHUP, "true")
        db.commit()
        cup_s = float(cup.get("absorbed_seconds") or 0)
        absorbed += cup_s
        touched += int(cup.get("buckets_touched") or 0)
        pending = cup.get("pending") or pending
        if cup_s > 0:
            messages.append(
                f"catch-up {cup_s / 60.0:.0f}m from playhead ahead of ABS listen time"
            )

    # Annotate bookmarks + duration on pending rows for UI progress bar
    prog_by_key: dict[str, tuple[float, float]] = {}
    for p in progress_rows:
        item_id = str(p.get("libraryItemId") or "").strip()
        if not item_id:
            extra = p.get("extraData")
            if isinstance(extra, str):
                try:
                    extra = json.loads(extra)
                except json.JSONDecodeError:
                    extra = {}
            if isinstance(extra, dict):
                item_id = str(extra.get("libraryItemId") or "").strip()
        if not item_id:
            continue
        ep = p.get("episodeId")
        ep_id = str(ep).strip() if ep else None
        key = _bucket_key(item_id, ep_id)
        try:
            ct = float(p.get("currentTime") or 0)
        except (TypeError, ValueError):
            continue
        try:
            dur = float(p.get("duration") or 0)
        except (TypeError, ValueError):
            dur = 0.0
        prog_by_key[key] = (ct, dur)
        # also index by item for book rows without episode key mismatch
        if not ep_id:
            prog_by_key[item_id] = (ct, dur)
    for key, row in list(pending.items()):
        hit = prog_by_key.get(key)
        if hit is None:
            iid = str(row.get("library_item_id") or "")
            hit = prog_by_key.get(iid)
        if hit is None:
            continue
        ct, dur = hit
        row["bookmark_seconds"] = ct
        if dur > 0:
            row["duration_seconds"] = dur
        pending[key] = row
    _save_json_state(db, STATE_PENDING, pending)

    pending_final = dict(_load_json_state(db, STATE_PENDING, {}) or {})
    result = {
        "ok": True,
        "absorbed_seconds": absorbed,
        "session_absorbed_seconds": float(sess_part.get("absorbed_seconds") or 0),
        "stats_absorbed_seconds": float(stats_part.get("absorbed_seconds") or 0),
        "progress_absorbed_seconds": float(prog_part.get("absorbed_seconds") or 0),
        "buckets_touched": touched,
        "new_sessions": int(sess_part.get("new_sessions") or 0),
        "pending_buckets": len(
            [b for b in pending_final.values() if float(b.get("pending_seconds") or 0) > 0]
        ),
        "pending_seconds": sum(
            float(b.get("pending_seconds") or 0) for b in pending_final.values()
        ),
        "sessions_seen": len(sessions),
        "progress_seen": len(progress_rows),
        "bootstrapped": do_bootstrap,
        "message": "; ".join(messages) if messages else None,
    }

    set_state(db, STATE_LAST_POLL, datetime.now(timezone.utc).isoformat())
    set_state(
        db,
        STATE_LAST_RESULT,
        json.dumps(
            {
                k: result[k]
                for k in result
                if k not in ("pending", "watermarks")
            }
        ),
    )
    db.commit()
    return result


def _bar_segments(
    *,
    logged_s: float,
    pending_s: float,
    duration_s: float,
    bookmark_s: float = 0.0,
) -> dict[str, float]:
    """logged | unlogged | empty as % of total duration (sum ≈ 100)."""
    logged_s = max(0.0, float(logged_s or 0))
    pending_s = max(0.0, float(pending_s or 0))
    bookmark_s = max(0.0, float(bookmark_s or 0))
    duration_s = max(0.0, float(duration_s or 0))
    # Prefer ABS duration; else at least cover known listen position/time.
    total = max(duration_s, bookmark_s, logged_s + pending_s, 1.0)
    # Cap logged+pending into total so empty stays non-negative.
    used = logged_s + pending_s
    if used > total and used > 0:
        scale = total / used
        logged_s *= scale
        pending_s *= scale
        used = total
    empty_s = max(0.0, total - used)
    return {
        "duration_seconds": round(total, 2),
        "logged_seconds": round(logged_s, 2),
        "pending_seconds": round(pending_s, 2),
        "empty_seconds": round(empty_s, 2),
        "logged_pct": round(100.0 * logged_s / total, 2),
        "pending_pct": round(100.0 * pending_s / total, 2),
        "empty_pct": round(100.0 * empty_s / total, 2),
    }


def _pending_entries(db: Session) -> list[dict[str, Any]]:
    pending: dict[str, Any] = dict(_load_json_state(db, STATE_PENDING, {}) or {})
    item_credited = {
        str(k): float(v)
        for k, v in (_load_json_state(db, STATE_ITEM_CREDITED, {}) or {}).items()
    }
    min_m = get_min_submit_minutes(db)
    idle_m = get_idle_minutes(db)
    now = datetime.now(timezone.utc)
    rows: list[dict[str, Any]] = []
    for key, raw in pending.items():
        secs = float(raw.get("pending_seconds") or 0)
        if secs <= 0:
            continue
        mins = secs / 60.0
        last = _parse_iso_ms(raw.get("last_activity_at"))
        idle_sec = (now - last).total_seconds() if last else None
        idle_ok = idle_sec is None or idle_sec >= idle_m * 60.0
        try:
            bookmark_s = float(raw.get("bookmark_seconds") or 0)
        except (TypeError, ValueError):
            bookmark_s = 0.0
        try:
            duration_s = float(raw.get("duration_seconds") or 0)
        except (TypeError, ValueError):
            duration_s = 0.0
        item_id = str(raw.get("library_item_id") or "").strip()
        # item_credited includes still-pending time → logged = credited − pending
        credited = float(item_credited.get(item_id) or 0)
        logged_s = max(0.0, credited - secs)
        bar = _bar_segments(
            logged_s=logged_s,
            pending_s=secs,
            duration_s=duration_s,
            bookmark_s=bookmark_s,
        )
        rows.append(
            {
                "key": key,
                "title": raw.get("title") or key,
                "author": raw.get("author") or "",
                "media_type": raw.get("media_type") or "book",
                "library_item_id": item_id or raw.get("library_item_id"),
                "episode_id": raw.get("episode_id"),
                "pending_seconds": secs,
                "pending_minutes": round(mins, 2),
                "logged_seconds": bar["logged_seconds"],
                "logged_minutes": round(bar["logged_seconds"] / 60.0, 2),
                "empty_seconds": bar["empty_seconds"],
                "duration_seconds": bar["duration_seconds"],
                "duration_minutes": round(bar["duration_seconds"] / 60.0, 2),
                "logged_pct": bar["logged_pct"],
                "pending_pct": bar["pending_pct"],
                "empty_pct": bar["empty_pct"],
                "bookmark_seconds": bookmark_s,
                "bookmark_minutes": round(bookmark_s / 60.0, 2) if bookmark_s else None,
                "last_activity_at": raw.get("last_activity_at"),
                "idle_seconds": idle_sec,
                "meets_min": mins + 1e-9 >= min_m,
                "idle_ok": idle_ok,
                "auto_ready": (mins + 1e-9 >= min_m) and idle_ok,
                "sources": raw.get("sources") or {},
                # Small ABS/yaabsa cover via local proxy (resized server-side).
                "cover_url": (f"/api/abs/cover/{item_id}?w=48" if item_id else None),
            }
        )
    rows.sort(key=lambda r: (-float(r["pending_minutes"]), str(r["title"])))
    return rows


def build_preview(db: Session, *, refresh: bool = True) -> dict[str, Any]:
    if refresh and getattr(_cfg(), "enabled", False):
        poll = poll_sessions(db)
    else:
        poll = {"ok": True, "skipped": True, "reason": "no_refresh"}
    entries = _pending_entries(db)
    prefs = get_prefs(db)
    total_m = sum(float(e["pending_minutes"]) for e in entries)
    ready_m = sum(float(e["pending_minutes"]) for e in entries if e["meets_min"])
    return {
        "ok": bool(poll.get("ok", True)),
        "poll": poll,
        "prefs": prefs,
        "entries": entries,
        "total_pending_minutes": round(total_m, 2),
        "ready_minutes": round(ready_m, 2),
        "ready_count": sum(1 for e in entries if e["meets_min"]),
        "auto_ready_count": sum(1 for e in entries if e["auto_ready"]),
        "last_logged_at": _last_logged_at(db),
        "server_now": datetime.now(timezone.utc).isoformat(),
        "message": poll.get("message") or poll.get("error"),
    }


def submit_pending(
    db: Session,
    *,
    keys: Optional[list[str]] = None,
    only_min: bool = False,
    only_auto_ready: bool = False,
    min_minutes: Optional[float] = None,
) -> dict[str, Any]:
    """Create logs from pending buckets; clear submitted time."""
    cfg = _cfg()
    pending: dict[str, Any] = dict(_load_json_state(db, STATE_PENDING, {}) or {})
    if not pending:
        return {"ok": True, "created": [], "message": "nothing pending"}

    min_m = float(min_minutes) if min_minutes is not None else get_min_submit_minutes(db)
    idle_m = get_idle_minutes(db)
    now = datetime.now(timezone.utc)
    key_filter = {str(k) for k in keys} if keys is not None else None

    created: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for key, raw in list(pending.items()):
        if key_filter is not None and key not in key_filter:
            continue
        secs = float(raw.get("pending_seconds") or 0)
        mins = secs / 60.0
        if secs <= 0 or mins < 0.05:
            skipped.append({"key": key, "reason": "empty"})
            continue
        if only_min or only_auto_ready:
            if mins + 1e-9 < min_m:
                skipped.append({"key": key, "reason": "below_min", "minutes": mins})
                continue
        if only_auto_ready:
            last = _parse_iso_ms(raw.get("last_activity_at"))
            if last is not None:
                idle_sec = (now - last).total_seconds()
                if idle_sec < idle_m * 60.0:
                    skipped.append({"key": key, "reason": "not_idle", "idle_seconds": idle_sec})
                    continue

        title = (raw.get("title") or key).strip()
        author = (raw.get("author") or "").strip()
        media_type = (raw.get("media_type") or "book").strip().lower()
        content_type = _content_type_for(media_type, cfg)
        item_id = str(raw.get("library_item_id") or key)
        series_key = _series_key_for(title, item_id)
        notes_parts = ["Audiobookshelf listening"]
        if author:
            notes_parts.append(author)
        source_ref = f"abs:{key}:{int(now.timestamp())}:{int(secs)}"
        amount = round(mins, 2)
        try:
            entry = create_log(
                db,
                content_type=content_type,
                title=title,
                source=SOURCE,
                amount=amount,
                unit=(cfg.unit or "minutes_high_density"),
                activity=(cfg.activity or "listening"),
                series_key=series_key,
                source_ref=source_ref,
                notes=" · ".join(notes_parts),
                tadoku_mode_override=(cfg.tadoku_default or None) or None,
                timestamp=now,
            )
            created.append(
                {
                    "id": entry.id,
                    "title": title,
                    "amount": amount,
                    "key": key,
                    "source_ref": source_ref,
                }
            )
            # clear bucket
            del pending[key]
        except DuplicateLogError as exc:
            skipped.append({"key": key, "reason": "duplicate", "existing_id": exc.existing.id})
            del pending[key]
        except Exception as exc:  # noqa: BLE001
            logger.exception("abs submit failed key=%s", key)
            skipped.append({"key": key, "reason": "error", "error": str(exc)})

    _save_json_state(db, STATE_PENDING, pending)
    db.commit()

    # Inbox approve already reviewed the listen — push Tadoku same as GSM submit.
    submitted = None
    if created:
        from app.tadoku.queue import approve_many

        submitted = approve_many(db, [c["id"] for c in created])
        set_state(db, STATE_LAST_SUBMIT, datetime.now(timezone.utc).isoformat())
        db.commit()

    return {
        "ok": True,
        "created": created,
        "skipped": skipped,
        "created_count": len(created),
        "submitted": submitted,
        "last_logged_at": _last_logged_at(db),
        "message": f"logged {len(created)} item(s)",
    }


def process_auto_export(db: Session) -> dict[str, Any]:
    """Scheduler: poll sessions, then auto-submit ready buckets when mode=auto."""
    cfg = _cfg()
    if not getattr(cfg, "enabled", False):
        return {"ok": True, "skipped": True, "reason": "disabled"}

    poll = poll_sessions(db)
    if get_log_mode(db) != "auto":
        return {
            "ok": True,
            "skipped": True,
            "reason": "manual_mode",
            "poll": poll,
        }
    result = submit_pending(db, only_auto_ready=True)
    result["poll"] = poll
    if result.get("created"):
        logger.info(
            "abs auto-export: created=%s",
            len(result["created"]),
        )
    return result


def process_daily_time_export(db: Session, *, force: bool = False) -> dict[str, Any]:
    """
    Once per local day at configured hour: poll + submit all buckets ≥ min minutes.
    Idle is ignored (same idea as GSM daily dump).
    """
    cfg = _cfg()
    if not getattr(cfg, "enabled", False):
        return {"ok": True, "skipped": True, "reason": "disabled"}

    poll = poll_sessions(db)

    if not force and not get_auto_log_at_time_enabled(db):
        return {
            "ok": True,
            "skipped": True,
            "reason": "auto_log_at_time_off",
            "poll": poll,
        }

    try:
        tz = ZoneInfo(get_timezone_name())
    except Exception:  # noqa: BLE001
        tz = ZoneInfo("America/Los_Angeles")
    now = datetime.now(tz)
    hour = get_auto_log_at_hour(db)
    today = now.date().isoformat()

    if not force:
        if now.hour != hour:
            return {
                "ok": True,
                "skipped": True,
                "reason": "wrong_hour",
                "local_hour": now.hour,
                "target_hour": hour,
                "timezone": str(tz),
                "poll": poll,
            }
        if now.minute > 5:
            return {
                "ok": True,
                "skipped": True,
                "reason": "past_window",
                "poll": poll,
            }
        last = (get_state(db, STATE_LAST_DAILY) or "").strip()
        if last == today:
            return {
                "ok": True,
                "skipped": True,
                "reason": "already_ran_today",
                "date": today,
                "poll": poll,
            }

    result = submit_pending(db, only_min=True)
    result["poll"] = poll
    result["daily"] = True
    result["local_date"] = today
    result["timezone"] = str(tz)
    result["target_hour"] = hour
    if result.get("ok") is not False:
        set_state(db, STATE_LAST_DAILY, today)
        db.commit()
    if result.get("created"):
        logger.info(
            "abs daily time-export: hour=%s tz=%s created=%s",
            hour,
            tz,
            len(result["created"]),
        )
    return result


def get_status(db: Optional[Session] = None) -> dict[str, Any]:
    cfg = _cfg()
    base = _base_url(cfg)
    token = _token(cfg)
    prefs = get_prefs(db) if db is not None else get_prefs(None)
    pending_m = 0.0
    pending_n = 0
    last_poll = None
    bootstrapped = False
    if db is not None:
        entries = _pending_entries(db)
        pending_n = len(entries)
        pending_m = round(sum(float(e["pending_minutes"]) for e in entries), 2)
        last_poll = get_state(db, STATE_LAST_POLL) or None
        bootstrapped = (get_state(db, STATE_BOOTSTRAPPED) or "").strip() in (
            "1",
            "true",
            "yes",
        )
    last_logged = _last_logged_at(db) if db is not None else None
    return {
        "ok": bool(getattr(cfg, "enabled", False) and base and token),
        "enabled": bool(getattr(cfg, "enabled", False)),
        "configured": bool(base and token),
        "base_url": base or None,
        "has_token": bool(token),
        "prefs": prefs,
        "pending_minutes": pending_m,
        "pending_items": pending_n,
        "last_poll_at": last_poll,
        "last_logged_at": last_logged,
        "server_now": datetime.now(timezone.utc).isoformat(),
        "bootstrapped": bootstrapped,
        "poll_seconds": int(getattr(cfg, "poll_seconds", 120) or 120),
        "include_books": bool(getattr(cfg, "include_books", True)),
        "include_podcasts": bool(getattr(cfg, "include_podcasts", True)),
        "message": (
            None
            if (getattr(cfg, "enabled", False) and base and token)
            else (
                "disabled"
                if not getattr(cfg, "enabled", False)
                else "missing base_url or api_token"
            )
        ),
    }
