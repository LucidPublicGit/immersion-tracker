"""
mpv local video → anime/show minutes.

Primary: poll a watch-history JSON/JSONL written by mpv or our lua helper.
Secondary: ingest_mpv_event() for POST /api/webhooks/mpv (routes wired separately).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.ingest.base import IngestResult, PollResult
from app.ingest.service import DuplicateLogError, create_log
from app.media.catalog_resolve import resolve_series
from app.media.title_format import suggest_series_key

logger = logging.getLogger(__name__)

SOURCE = "mpv"

# Default history locations when config.history_path is empty
_DEFAULT_HISTORY_CANDIDATES = (
    "/mpv/watch_history.jsonl",
    "/mpv/immersion-tracker.jsonl",
)

_SE_RE = re.compile(r"[Ss](?P<season>\d{1,2})[Ee](?P<episode>\d{1,3})")
_SEASON_DIR_RE = re.compile(
    r"^(season|series|s)\s*0*\d+$",
    re.IGNORECASE,
)


class MpvWatchEvent(BaseModel):
    """Normalized mpv end-of-file / history entry."""

    path: str = Field(..., min_length=1)
    title: str = ""
    duration_seconds: float = Field(..., gt=0)
    watched_seconds: float = Field(..., ge=0)
    ratio: Optional[float] = None
    finished_at: Optional[datetime] = None
    event: Optional[str] = None

    @field_validator("path")
    @classmethod
    def strip_path(cls, v: str) -> str:
        return (v or "").strip()

    @field_validator("title")
    @classmethod
    def strip_title(cls, v: str) -> str:
        return (v or "").strip()

    def computed_ratio(self) -> float:
        if self.ratio is not None:
            return max(0.0, min(1.0, float(self.ratio)))
        if self.duration_seconds > 0:
            return max(
                0.0,
                min(1.0, float(self.watched_seconds) / float(self.duration_seconds)),
            )
        return 0.0


def _log_dict(entry: Any) -> dict[str, Any]:
    return {
        "id": entry.id,
        "title": entry.title,
        "amount": entry.amount,
        "unit": entry.unit,
        "content_type": entry.content_type,
        "series_key": entry.series_key,
        "tadoku_status": entry.tadoku_status,
        "tadoku_mode": entry.tadoku_mode,
        "tadoku_score_estimate": entry.tadoku_score_estimate,
        "watch_ratio": entry.watch_ratio,
        "source_ref": entry.source_ref,
    }


def resolve_history_path(explicit: str = "") -> Optional[Path]:
    """
    Resolve the mpv history file path.

    Order: config/explicit → env MPV_HISTORY_PATH → common container defaults.
    """
    candidates: list[str] = []
    if explicit and str(explicit).strip():
        candidates.append(str(explicit).strip())
    env_path = (os.environ.get("MPV_HISTORY_PATH") or "").strip()
    if env_path:
        candidates.append(env_path)
    candidates.extend(_DEFAULT_HISTORY_CANDIDATES)

    seen: set[str] = set()
    for raw in candidates:
        if not raw or raw in seen:
            continue
        seen.add(raw)
        p = Path(raw)
        if p.is_file():
            return p
    return None


def _parse_finished_at(val: Any) -> Optional[datetime]:
    if val is None or val == "":
        return None
    if isinstance(val, datetime):
        dt = val
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt
    if isinstance(val, (int, float)):
        # unix seconds (or ms if huge)
        ts = float(val)
        if ts > 1e12:
            ts = ts / 1000.0
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    s = str(val).strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        pass
    try:
        return datetime.fromtimestamp(float(s), tz=timezone.utc)
    except (TypeError, ValueError):
        return None


def _as_float(val: Any) -> Optional[float]:
    if val is None or val == "":
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _filename_stem(path: str) -> str:
    try:
        return Path(path).stem
    except Exception:  # noqa: BLE001
        base = path.replace("\\", "/").rsplit("/", 1)[-1]
        if "." in base:
            return base.rsplit(".", 1)[0]
        return base


def _parent_folder_name(path: str) -> str:
    """
    Series-ish folder name: skip Season N / S01 dirs, use parent or grandparent.
    """
    try:
        p = Path(path)
        parent = p.parent
        if not parent or str(parent) in (".", "", "/"):
            return ""
        name = parent.name
        if name and _SEASON_DIR_RE.match(name.strip()):
            gp = parent.parent
            if gp and gp.name:
                return gp.name
        return name or ""
    except Exception:  # noqa: BLE001
        return ""


def _parse_season_episode(text: str) -> tuple[Optional[int], Optional[int]]:
    m = _SE_RE.search(text or "")
    if not m:
        return None, None
    return int(m.group("season")), int(m.group("episode"))


def _series_name_from_title(title: str) -> str:
    """Strip SxxExx / trailing episode tags for a series display name."""
    t = (title or "").strip()
    if not t:
        return ""
    t = _SE_RE.sub(" ", t)
    t = re.sub(r"\s+", " ", t).strip(" -_.")
    return t


def map_content_type(path: str, cfg: Any = None) -> str:
    cfg = cfg or get_settings().yaml_config.mpv
    default_ct = (getattr(cfg, "content_type", None) or "anime").strip() or "anime"
    markers = list(getattr(cfg, "show_path_markers", None) or [])
    pl = (path or "").lower().replace("\\", "/")
    for marker in markers:
        m = str(marker or "").strip().lower()
        if m and m in pl:
            return "show"
    return default_ct


def make_source_ref(
    path: str,
    *,
    finished_at: Optional[datetime] = None,
    duration_seconds: Optional[float] = None,
) -> str:
    """
    Stable dedupe key: mpv:{sha1(path|finished_at)} or path|duration fallback.
    """
    path_n = (path or "").strip().replace("\\", "/")
    if finished_at is not None:
        if finished_at.tzinfo is None:
            finished_at = finished_at.replace(tzinfo=timezone.utc)
        stamp = finished_at.astimezone(timezone.utc).isoformat()
        raw = f"{path_n}|{stamp}"
    elif duration_seconds is not None and float(duration_seconds) > 0:
        raw = f"{path_n}|dur:{float(duration_seconds):.3f}"
    else:
        raw = path_n
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]
    return f"mpv:{digest}"


def event_from_dict(raw: dict[str, Any]) -> Optional[MpvWatchEvent]:
    """
    Best-effort normalize a history/webhook dict into MpvWatchEvent.

    Supports our lua JSONL shape and common mpv watch_history fields.
    Skips entries that lack path + duration (cannot compute completion).
    """
    if not isinstance(raw, dict):
        return None

    path = (
        raw.get("path")
        or raw.get("filename")
        or raw.get("file")
        or raw.get("filepath")
        or ""
    )
    path = str(path).strip()
    if not path:
        return None

    title = str(raw.get("title") or raw.get("media_title") or raw.get("name") or "").strip()

    duration = _as_float(
        raw.get("duration_seconds")
        or raw.get("duration")
        or raw.get("length")
        or raw.get("total")
    )
    # Some plugins store duration in ms
    if duration is not None and duration > 10_000 and "duration_seconds" not in raw:
        # Heuristic: values > 10000 without explicit duration_seconds are likely ms
        # unless already huge runtime hours; treat as ms when path-like media
        if duration > 86_400:  # > 24h in seconds is unlikely; treat as ms
            duration = duration / 1000.0
        elif "duration_ms" in raw or "length_ms" in raw:
            duration = duration / 1000.0

    duration_ms = _as_float(raw.get("duration_ms") or raw.get("length_ms"))
    if (duration is None or duration <= 0) and duration_ms and duration_ms > 0:
        duration = duration_ms / 1000.0

    watched = _as_float(
        raw.get("watched_seconds")
        or raw.get("watched")
        or raw.get("position")
        or raw.get("time-pos")
        or raw.get("time_pos")
        or raw.get("pos")
    )
    watched_ms = _as_float(raw.get("watched_ms") or raw.get("position_ms"))
    if (watched is None or watched < 0) and watched_ms is not None:
        watched = watched_ms / 1000.0

    ratio = _as_float(raw.get("ratio") or raw.get("progress") or raw.get("percent"))
    if ratio is not None and ratio > 1.0:
        # percent 0-100
        ratio = ratio / 100.0

    finished_at = _parse_finished_at(
        raw.get("finished_at")
        or raw.get("timestamp")
        or raw.get("time")
        or raw.get("date")
        or raw.get("played_at")
    )

    # watch_history sometimes only has path + time — skip unless duration known
    if duration is None or duration <= 0:
        return None

    if watched is None:
        if ratio is not None:
            watched = float(duration) * max(0.0, min(1.0, float(ratio)))
        else:
            # no progress info — cannot verify completion; leave 0 (will fail thresholds)
            watched = 0.0

    if not title:
        title = _filename_stem(path)

    event_name = raw.get("event")
    if event_name is not None:
        event_name = str(event_name)

    try:
        return MpvWatchEvent(
            path=path,
            title=title,
            duration_seconds=float(duration),
            watched_seconds=float(watched),
            ratio=ratio,
            finished_at=finished_at,
            event=event_name,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("mpv event_from_dict skip: %s (%s)", exc, raw)
        return None


def load_history_entries(path: Path) -> list[dict[str, Any]]:
    """
    Load history file as list of raw dicts.

    Auto-detect:
      1. JSONL (one object per non-empty line)
      2. JSON array of objects
      3. JSON object with list under common keys (entries/history/items/…)
    """
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    if not text:
        return []

    # Prefer JSONL when multiple lines look like objects
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if len(lines) > 1 and all(
        ln.startswith("{") and ln.endswith("}") for ln in lines[: min(5, len(lines))]
    ):
        out: list[dict[str, Any]] = []
        for ln in lines:
            try:
                obj = json.loads(ln)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                out.append(obj)
        if out:
            return out

    # Whole-file JSON
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Fall back to line-by-line best effort
        out = []
        for ln in lines:
            try:
                obj = json.loads(ln)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                out.append(obj)
        return out

    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for key in ("entries", "history", "items", "files", "watches", "data"):
            nested = data.get(key)
            if isinstance(nested, list):
                return [x for x in nested if isinstance(x, dict)]
        # single object file
        return [data]
    return []


def _coerce_event(event: MpvWatchEvent | dict[str, Any]) -> tuple[Optional[MpvWatchEvent], str]:
    """Normalize webhook body or typed event. Returns (event, error_reason)."""
    if isinstance(event, MpvWatchEvent):
        return event, ""
    if not isinstance(event, dict):
        return None, "invalid_payload"
    parsed = event_from_dict(event)
    if parsed is None:
        # Prefer structured validation errors when fields are present
        try:
            return MpvWatchEvent.model_validate(event), ""
        except Exception as exc:  # noqa: BLE001
            return None, f"invalid_payload:{exc}"
    return parsed, ""


def ingest_mpv_event(
    db: Session, event: MpvWatchEvent | dict[str, Any]
) -> IngestResult:
    """
    Ingest a single mpv watch event (webhook dict or poll-normalized model).

    Routes call this with a raw JSON body; poll_mpv passes MpvWatchEvent.
    """
    coerced, err = _coerce_event(event)
    if coerced is None:
        return IngestResult(
            accepted=False,
            reason=err or "invalid_payload",
            source=SOURCE,
        )
    event = coerced

    cfg = get_settings().yaml_config.mpv
    ratio = event.computed_ratio()

    if ratio < float(cfg.completion_threshold):
        return IngestResult(
            accepted=False,
            reason=f"below_threshold:{ratio:.3f}<{cfg.completion_threshold}",
            source=SOURCE,
        )

    min_watched = float(cfg.min_watched_seconds or 0)
    effective_watched = max(
        float(event.watched_seconds or 0),
        float(event.duration_seconds or 0) * ratio,
    )
    if min_watched > 0 and effective_watched < min_watched:
        return IngestResult(
            accepted=False,
            reason=f"below_min_watched:{effective_watched:.1f}<{min_watched:.0f}",
            source=SOURCE,
        )

    content_type = map_content_type(event.path, cfg)
    # Full media duration in minutes (Tadoku-friendly; matches YouTube completed logs)
    amount_minutes = round(float(event.duration_seconds) / 60.0, 3)

    raw_title = (event.title or "").strip() or _filename_stem(event.path)
    season, episode = _parse_season_episode(raw_title)
    if season is None and episode is None:
        season, episode = _parse_season_episode(event.path)

    series_guess = (
        _series_name_from_title(raw_title)
        or _parent_folder_name(event.path)
        or raw_title
    )
    # Catalog resolve: anime alias matching still works for shows mapped to anime keys
    key_ct = content_type if content_type != "show" else "anime"
    resolved = resolve_series(db, key_ct, series_guess)
    if resolved.catalog and resolved.catalog.content_type:
        content_type = resolved.catalog.content_type
    series_key = resolved.series_key or suggest_series_key(content_type, series_guess)
    title = resolved.display_title or series_guess

    source_ref = make_source_ref(
        event.path,
        finished_at=event.finished_at,
        duration_seconds=event.duration_seconds,
    )

    notes = (
        f"path={event.path}; ratio={ratio:.3f}; "
        f"duration_s={event.duration_seconds}; watched_s={effective_watched:.1f}"
    )
    if event.event:
        notes += f"; event={event.event}"
    if raw_title and raw_title != title:
        notes += f"; media_title={raw_title}"

    try:
        entry = create_log(
            db,
            content_type=content_type,
            title=title,
            source=SOURCE,
            amount=amount_minutes,
            unit=cfg.unit or "minutes",
            activity=cfg.activity or None,
            series_key=series_key,
            source_ref=source_ref,
            notes=notes,
            timestamp=event.finished_at,
            watch_ratio=ratio,
            season=season,
            episode=episode,
        )
    except DuplicateLogError as dup:
        return IngestResult(
            accepted=False,
            reason="duplicate",
            log_id=dup.existing.id,
            log=_log_dict(dup.existing),
            source=SOURCE,
        )

    return IngestResult(
        accepted=True,
        reason="logged",
        log_id=entry.id,
        log=_log_dict(entry),
        source=SOURCE,
    )


def mpv_status(db: Session) -> dict[str, Any]:
    """Health / config snapshot for GET /api/mpv/status."""
    cfg = get_settings().yaml_config.mpv
    history = resolve_history_path(cfg.history_path or "")
    return {
        "ok": True,
        "enabled": bool(cfg.enabled),
        "history_path": cfg.history_path or "",
        "history_resolved": str(history) if history else None,
        "history_exists": bool(history and history.is_file()),
        "poll_seconds": int(cfg.poll_seconds or 120),
        "completion_threshold": float(cfg.completion_threshold),
        "min_watched_seconds": float(cfg.min_watched_seconds or 0),
        "content_type": cfg.content_type,
        "unit": cfg.unit,
        "activity": cfg.activity,
        "tadoku_default": cfg.tadoku_default,
        "show_path_markers": list(cfg.show_path_markers or []),
        "webhook": "/api/webhooks/mpv",
        "sync": "/api/mpv/sync",
        "env_history_set": bool((os.environ.get("MPV_HISTORY_PATH") or "").strip()),
    }


def poll_mpv(db: Session) -> PollResult:
    """
    Poll configured (or default) mpv history file and log completed watches.
    """
    cfg = get_settings().yaml_config.mpv
    if not cfg.enabled:
        return PollResult(
            ok=True,
            source=SOURCE,
            message="mpv disabled",
            details={"enabled": False},
        )

    history = resolve_history_path(cfg.history_path or "")
    if history is None:
        return PollResult(
            ok=True,
            source=SOURCE,
            message="history file not found",
            details={
                "history_path": cfg.history_path or "",
                "tried_defaults": list(_DEFAULT_HISTORY_CANDIDATES),
                "env": bool((os.environ.get("MPV_HISTORY_PATH") or "").strip()),
            },
        )

    try:
        raw_entries = load_history_entries(history)
    except OSError as exc:
        logger.warning("mpv history read failed: %s", exc)
        return PollResult(
            ok=False,
            source=SOURCE,
            message=f"read error: {exc}",
            errors=[str(exc)],
            details={"history_path": str(history)},
        )

    created = 0
    skipped = 0
    errors: list[str] = []
    reasons: dict[str, int] = {}

    for raw in raw_entries:
        event = event_from_dict(raw)
        if event is None:
            skipped += 1
            reasons["unparseable_or_no_duration"] = (
                reasons.get("unparseable_or_no_duration", 0) + 1
            )
            continue
        try:
            result = ingest_mpv_event(db, event)
        except Exception as exc:  # noqa: BLE001
            errors.append(str(exc))
            skipped += 1
            reasons["error"] = reasons.get("error", 0) + 1
            logger.exception("mpv ingest failed for %s", event.path)
            continue
        if result.accepted:
            created += 1
            reasons["logged"] = reasons.get("logged", 0) + 1
        else:
            skipped += 1
            # bucket by reason prefix
            key = (result.reason or "skipped").split(":", 1)[0]
            reasons[key] = reasons.get(key, 0) + 1

    return PollResult(
        ok=len(errors) == 0,
        source=SOURCE,
        logs_created=created,
        skipped=skipped,
        message=f"processed {len(raw_entries)} entries from {history.name}",
        errors=errors,
        details={
            "history_path": str(history),
            "entries": len(raw_entries),
            "reasons": reasons,
        },
    )
