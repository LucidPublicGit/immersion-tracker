"""
Pull Tadoku logs for the signed-in user and import anything missing locally.

Remote API: GET {api_base}/users/{user_id}/logs?page=&page_size=

Matching strategy:
  - source_ref = tadoku:{remote_id}
  - tadoku_remote_id = remote_id
  - also skip if any local log already has that tadoku_remote_id
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import LogEntry, TadokuStatus, utcnow
from app.ingest.service import DuplicateLogError, create_log
from app.media.catalog_resolve import resolve_series
from app.media.title_format import suggest_series_key
from app.tadoku.client import live_submit_blocked
from app.tadoku.session import ensure_session, resolve_cookie

logger = logging.getLogger(__name__)

# "Show Name S01E04" / "Show Name S1E4" / trailing E12
_SE_RE = re.compile(
    r"^(?P<title>.+?)\s+[Ss](?P<season>\d{1,2})[Ee](?P<episode>\d{1,3})\s*$"
)
_E_RE = re.compile(r"^(?P<title>.+?)\s+[Ee](?P<episode>\d{1,3})\s*$")
# Bulk multi-season: "Arcane S1+S2 (740min half)" / "Show S1-S2"
_S_RANGE_RE = re.compile(
    r"^(?P<title>.+?)\s+[Ss](?P<a>\d{1,2})\s*(?:[+&]|[-–])\s*[Ss]?(?P<b>\d{1,2})\b"
    r"(?P<rest>.*)$",
    re.I,
)
# Contest noise tails after season range
_BULK_TAIL_RE = re.compile(
    r"\s*[\(（]?\s*\d+(?:\.\d+)?\s*(?:min|mins|minutes|時間)?\s*"
    r"(?:half|double|x\s*2|½)?\s*[\)）]?\s*$",
    re.I,
)
# Any S1+S2 / S1-S2 span inside a description (for progress expansion)
_S_RANGE_ANY_RE = re.compile(
    r"[Ss](?P<a>\d{1,2})\s*[+&]\s*[Ss]?(?P<b>\d{1,2})"
    r"|[Ss](?P<c>\d{1,2})\s*[-–]\s*[Ss]?(?P<d>\d{1,2})",
    re.I,
)
# Manga volume + page range (must run before bare Vol / trailing numbers)
# "ダンダダン vol 1 page 50-100" / "Title vol 1 page 0-50"
_VOL_PAGE_RE = re.compile(
    r"^(?P<title>.+?)\s+(?:Vol\.?|Volume|v|第)\s*(?P<volume>\d{1,4})\s+"
    r"(?:pages?\s*)?(?P<p0>\d{1,5})\s*[-–~～to]+\s*(?P<p1>\d{1,5})\s*$",
    re.I,
)
# "ダンダダン vol 1 (100 to 216)"
_VOL_PAREN_RANGE_RE = re.compile(
    r"^(?P<title>.+?)\s+(?:Vol\.?|Volume|v|第)\s*(?P<volume>\d{1,4})\s*"
    r"[\(（]\s*(?P<p0>\d{1,5})\s*(?:to|[-–~～]|–)\s*(?P<p1>\d{1,5})\s*[\)）]\s*$",
    re.I,
)
_VOL_RE = re.compile(
    r"^(?P<title>.+?)\s+(?:Vol\.?|Volume|v)\s*(?P<volume>\d{1,4})\s*$",
    re.I,
)

_UNIT_MAP = {
    "minute": "minutes",
    "minutes": "minutes",
    "minute (high density)": "minutes_high_density",
    "page": "pages",
    "pages": "pages",
    "2 column page": "two_column_pages",
    "comic page": "comic_pages",
    "character": "characters",
    "characters": "characters",
    "sentence": "sentences",
    "sentences": "sentences",
}

_ACTIVITY_MAP = {
    "reading": "reading",
    "listening": "listening",
    "writing": "writing",
    "speaking": "speaking",
    "study": "study",
}

_TAG_CONTENT_TYPE = {
    "youtube": "youtube",
    "youtube:video": "youtube",
    "anime": "anime",
    "manga": "manga",
    "book": "book",
    "audiobook": "audiobook",
    "vn": "visual_novel",
    "visual novel": "visual_novel",
    "visual_novel": "visual_novel",
    "show": "show",
    "drama": "show",
    "game": "game",
    "podcast": "podcast",
}


def _api_base() -> str:
    cfg = get_settings().yaml_config.tadoku
    return (cfg.api_base or "https://tadoku.app/api/internal/immersion").rstrip("/")


def _cookie() -> str:
    cookie = resolve_cookie()
    if cookie:
        return cookie
    try:
        return ensure_session(force_login=False)
    except Exception:  # noqa: BLE001
        return ""


def discover_user_id() -> Optional[str]:
    """
    Find Tadoku user UUID from config, then local export payloads.
    """
    cfg_uid = (get_settings().yaml_config.tadoku.user_id or "").strip()
    if cfg_uid:
        return cfg_uid

    roots = [Path("data/tadoku_export"), Path("/app/data/tadoku_export")]
    for root in roots:
        if not root.is_dir():
            continue
        for path in sorted(root.glob("export-*.json"), reverse=True)[:40]:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            api = data.get("api") or {}
            resp = api.get("response") or {}
            uid = resp.get("user_id")
            if uid:
                return str(uid)

    # Contest cache leaderboard — match display name if known
    contest_id = (
        get_settings().yaml_config.tadoku.contest.contest_id
        if get_settings().yaml_config.tadoku.contest
        else ""
    )
    if contest_id:
        for base in (Path("data/contest_cache"), Path("/app/data/contest_cache")):
            lb = base / contest_id / "leaderboard.json"
            if not lb.is_file():
                continue
            try:
                entries = json.loads(lb.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            # Prefer exact "Lucid" style names from exports if any later
            if isinstance(entries, list) and entries:
                # can't know which is us without name — skip
                pass
    return None


def parse_season_range(text: str) -> list[int]:
    """
    Extract inclusive season numbers from bulk titles like ``S1+S2`` / ``S1-S3``.

    Returns [] when no range is found.
    """
    m = _S_RANGE_ANY_RE.search(text or "")
    if not m:
        return []
    if m.groupdict().get("a") is not None and m.group("a") is not None:
        a, b = int(m.group("a")), int(m.group("b"))
    else:
        a, b = int(m.group("c")), int(m.group("d"))
    lo, hi = (a, b) if a <= b else (b, a)
    if hi - lo > 30:
        return []
    return list(range(lo, hi + 1))


def parse_description(description: str) -> dict[str, Any]:
    """Extract base title + season/episode/volume from Tadoku description."""
    raw = (description or "").strip()
    # Strip legacy Youtube: prefix (older submits; no longer added)
    if raw.lower().startswith("youtube:"):
        raw = raw.split(":", 1)[1].strip()

    m = _SE_RE.match(raw)
    if m:
        return {
            "title": m.group("title").strip(),
            "season": int(m.group("season")),
            "episode": int(m.group("episode")),
            "volume": None,
            "kind": "episode",
        }
    # Bulk multi-season logs: "Arcane S1+S2 (740min half)"
    m = _S_RANGE_RE.match(raw)
    if m:
        title = m.group("title").strip()
        a, b = int(m.group("a")), int(m.group("b"))
        lo, hi = (a, b) if a <= b else (b, a)
        seasons = list(range(lo, hi + 1)) if hi - lo <= 30 else [lo, hi]
        rest = (m.group("rest") or "").strip()
        # half/double in rest is Tadoku score credit, not incomplete watching
        return {
            "title": title,
            "season": hi,  # highest season reached
            "episode": None,
            "volume": None,
            "kind": "season_range",
            "seasons": seasons,
            "season_lo": lo,
            "season_hi": hi,
            "bulk_rest": rest,
        }
    # Volume + page range BEFORE bare volume / E-number
    # Page numbers must never become episode (E50/E100 from "page 50-100")
    m = _VOL_PAGE_RE.match(raw) or _VOL_PAREN_RANGE_RE.match(raw)
    if m:
        vol = int(m.group("volume"))
        return {
            "title": m.group("title").strip(),
            "season": None,
            "episode": vol,  # volume stored in episode field for shelf position
            "volume": vol,
            "page_start": int(m.group("p0")),
            "page_end": int(m.group("p1")),
            "kind": "volume",
        }
    m = _VOL_RE.match(raw)
    if m:
        vol = int(m.group("volume"))
        return {
            "title": m.group("title").strip(),
            "season": None,
            "episode": vol,
            "volume": vol,
            "kind": "volume",
        }
    m = _E_RE.match(raw)
    if m:
        return {
            "title": m.group("title").strip(),
            "season": None,
            "episode": int(m.group("episode")),
            "volume": None,
            "kind": "episode",
        }
    # "Title 1" alone is ambiguous — leave episode unset (identity peel may set it)
    cleaned = _BULK_TAIL_RE.sub("", raw).strip() or raw
    return {
        "title": cleaned or "Unknown",
        "season": None,
        "episode": None,
        "volume": None,
        "kind": "plain",
    }


def _content_type_from_tags(tags: list[str], description: str) -> str:
    for t in tags or []:
        key = (t or "").strip().lower()
        if key in _TAG_CONTENT_TYPE:
            return _TAG_CONTENT_TYPE[key]
        # Platform:Medium style
        if ":" in key:
            parts = key.split(":")
            for p in parts:
                if p in _TAG_CONTENT_TYPE:
                    return _TAG_CONTENT_TYPE[p]
    if (description or "").lower().startswith("youtube:"):
        return "youtube"
    return "other"


def refine_content_type_from_activity(
    content_type: str,
    *,
    unit: str = "",
    activity: str = "",
    description: str = "",
) -> str:
    """
    Split reading vs listening into different media kinds.

    Tadoku often tags poorly or uses "other"; unit/activity are the ground truth:
      pages + reading  → manga (not anime)
      minutes + listening → anime (not manga), unless already show/podcast/…
    """
    ct = (content_type or "other").strip().lower() or "other"
    unit_l = (unit or "").strip().lower()
    act = (activity or "").strip().lower()
    desc = (description or "").lower()

    reading_units = {
        "pages",
        "comic_pages",
        "two_column_pages",
        "characters",
        "sentences",
    }
    listening_units = {"minutes", "minutes_high_density"}

    looks_volume = bool(
        re.search(r"\bvol(?:ume)?\.?\b|\bpage\b|巻|頁", desc, re.I)
    )

    # Explicit strong types we never override
    if ct in ("youtube", "podcast", "game", "visual_novel", "study", "audiobook"):
        return ct

    if unit_l in reading_units or act == "reading" or looks_volume:
        if ct in ("other", "anime", "show", "movie", ""):
            return "manga"
        return ct

    if unit_l in listening_units or act == "listening":
        if ct in ("other", "manga", "book", ""):
            return "anime"
        return ct

    return ct


def _unit_from_remote(unit_name: Optional[str], activity: str) -> str:
    name = (unit_name or "").strip().lower()
    if name in _UNIT_MAP:
        return _UNIT_MAP[name]
    if "minute" in name and "high" in name:
        return "minutes_high_density"
    if "minute" in name:
        return "minutes"
    if "comic" in name:
        return "comic_pages"
    if "column" in name:
        return "two_column_pages"
    if "page" in name:
        return "pages"
    if "char" in name:
        return "characters"
    if "sentence" in name:
        return "sentences"
    # activity fallbacks
    if activity == "listening":
        return "minutes"
    if activity == "reading":
        return "characters"
    return "minutes"


def _activity_from_remote(log: dict[str, Any]) -> str:
    act = log.get("activity") or {}
    name = (act.get("name") or "").strip().lower()
    if name in _ACTIVITY_MAP:
        return _ACTIVITY_MAP[name]
    aid = act.get("id")
    return {1: "reading", 2: "listening", 3: "writing", 4: "speaking", 5: "study"}.get(
        aid, "listening"
    )


def _parse_ts(value: Any) -> datetime:
    if not value:
        return utcnow()
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    s = str(value).replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return utcnow()


def fetch_remote_logs(
    user_id: str,
    *,
    page_size: int = 50,
    max_pages: int = 100,
) -> list[dict[str, Any]]:
    """Paginate all user logs from Tadoku."""
    cookie = _cookie()
    headers = {
        "Accept": "application/json",
        "Origin": "https://tadoku.app",
        "Referer": "https://tadoku.app/",
        "User-Agent": "immersion-tracker/tadoku-pull",
    }
    if cookie:
        headers["Cookie"] = cookie

    logs: list[dict[str, Any]] = []
    page = 0
    with httpx.Client(timeout=40.0, headers=headers, follow_redirects=True) as client:
        while page < max_pages:
            r = client.get(
                f"{_api_base()}/users/{user_id}/logs",
                params={"page": page, "page_size": page_size},
            )
            if r.status_code in (401, 403):
                # Public list sometimes works without auth; if blocked, re-login once
                try:
                    new_cookie = ensure_session(force_login=True)
                except Exception:  # noqa: BLE001
                    new_cookie = ""
                if new_cookie:
                    headers["Cookie"] = new_cookie
                    r = client.get(
                        f"{_api_base()}/users/{user_id}/logs",
                        params={"page": page, "page_size": page_size},
                        headers=headers,
                    )
            r.raise_for_status()
            data = r.json()
            batch = data.get("logs") or []
            logs.extend(batch)
            next_tok = data.get("next_page_token")
            if not batch or next_tok is None or next_tok == "":
                # Also stop when short page
                if len(batch) < page_size:
                    break
            page += 1
    return logs


def existing_remote_ids(db: Session) -> set[str]:
    rows = (
        db.query(LogEntry.tadoku_remote_id)
        .filter(LogEntry.tadoku_remote_id.isnot(None))
        .all()
    )
    out = {str(r[0]) for r in rows if r[0]}
    # source_ref tadoku:uuid
    refs = (
        db.query(LogEntry.source_ref)
        .filter(LogEntry.source == "tadoku")
        .all()
    )
    for (ref,) in refs:
        if ref and str(ref).startswith("tadoku:"):
            out.add(str(ref).split(":", 1)[1])
        elif ref:
            out.add(str(ref))
    return out


def import_remote_log(db: Session, remote: dict[str, Any]) -> Optional[LogEntry]:
    """Create a local log from a Tadoku remote payload. Returns entry or None if skip."""
    rid = str(remote.get("id") or "").strip()
    if not rid:
        return None
    if remote.get("deleted"):
        return None

    description = remote.get("description") or ""
    parsed = parse_description(description)
    title = parsed["title"] or description or "Tadoku log"
    tags = list(remote.get("tags") or [])
    content_type = _content_type_from_tags(tags, description)
    activity = _activity_from_remote(remote)
    unit = _unit_from_remote(remote.get("unit_name"), activity)
    # Reading (pages) vs listening (minutes) must not share an anime key
    content_type = refine_content_type_from_activity(
        content_type,
        unit=unit,
        activity=activity,
        description=description,
    )
    amount = float(remote.get("amount") or 0.0)
    if amount <= 0:
        # duration-only edge case — skip zero
        return None

    lang = (remote.get("language") or {}).get("code") or "jpn"
    if lang == "jpn":
        lang = "ja"

    resolved = resolve_series(db, content_type, title)
    series_key = resolved.series_key or suggest_series_key(content_type, title)
    display_title = resolved.display_title or title

    # Volume logs: episode holds volume number only (never page end 50/100)
    season = parsed.get("season")
    episode = parsed.get("episode")
    if parsed.get("kind") == "volume":
        season = None
        episode = parsed.get("volume") or episode

    # Identity cleanup (Arcane → show, film red → movie, …)
    try:
        from app.media.work_identity import prepare_log_identity

        ident = prepare_log_identity(
            content_type=content_type,
            title=display_title,
            series_key=series_key,
            season=season,
            episode=episode,
            unit=unit,
            activity=activity,
            source="tadoku",
        )
        content_type = ident.get("content_type") or content_type
        display_title = ident.get("title") or display_title
        series_key = ident.get("series_key") or series_key
        if ident.get("season") is not None:
            season = ident.get("season")
        if ident.get("episode") is not None:
            episode = ident.get("episode")
    except Exception:  # noqa: BLE001
        pass

    # Keep bulk range in notes so Progress can expand S1+S2 → full seasons
    note_bits = [f"Imported from Tadoku · {description}"]
    if parsed.get("kind") == "season_range" and parsed.get("seasons"):
        lo = parsed.get("season_lo")
        hi = parsed.get("season_hi")
        note_bits.append(f"seasons {lo}-{hi}")

    source_ref = f"tadoku:{rid}"
    try:
        entry = create_log(
            db,
            content_type=content_type,
            title=display_title,
            source="tadoku",
            amount=amount,
            unit=unit,
            activity=activity,
            series_key=series_key,
            source_ref=source_ref,
            language=lang,
            notes=" · ".join(note_bits)[:500],
            tags=",".join(tags)[:500] if tags else None,
            timestamp=_parse_ts(remote.get("created_at")),
            tadoku_mode_override="never",
            season=season,
            episode=episode,
        )
    except DuplicateLogError:
        return None

    # Mark as already on Tadoku. Preserve remote create time on updated_at so
    # bulk progress imports do not look "just submitted" in the UI.
    entry.tadoku_status = TadokuStatus.PUSHED.value
    entry.tadoku_remote_id = rid
    score = remote.get("score")
    if score is not None:
        try:
            entry.tadoku_score_estimate = float(score)
        except (TypeError, ValueError):
            pass
    entry.updated_at = entry.timestamp or _parse_ts(remote.get("created_at"))
    db.commit()
    db.refresh(entry)
    return entry


def _normalize_match_text(value: str) -> str:
    s = (value or "").strip().lower()
    s = re.sub(r"[^\w\s\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]+", " ", s, flags=re.U)
    return re.sub(r"\s+", " ", s).strip()


def remote_matches_title_query(remote: dict[str, Any], query: str) -> bool:
    """True when a remote Tadoku log description/tags match a title filter."""
    q = _normalize_match_text(query)
    if not q:
        return True
    desc = remote.get("description") or ""
    tags = " ".join(str(t) for t in (remote.get("tags") or []))
    blob = _normalize_match_text(f"{desc} {tags}")
    if not blob:
        return False
    if q in blob:
        return True
    # All tokens present (order-independent) for multi-word titles
    tokens = [t for t in q.split() if len(t) >= 2]
    if tokens and all(t in blob for t in tokens):
        return True
    return False


def pull_missing_logs(
    db: Session,
    *,
    user_id: Optional[str] = None,
    dry_run: bool = False,
    title_query: Optional[str] = None,
    series_key: Optional[str] = None,
) -> dict[str, Any]:
    """
    Fetch Tadoku logs and import those not already in the local DB.

    dry_run: count only, no writes.
    title_query: only import remote logs whose description matches this title
      (used for per-work "Resync from Tadoku").
    series_key: optional Progress key — resolves catalog/log title as the query
      when title_query is empty.
    """
    uid = (user_id or "").strip() or discover_user_id()
    if not uid:
        return {
            "ok": False,
            "error": (
                "Could not determine Tadoku user_id. Submit at least one log from "
                "this tracker first (so exports contain user_id), or pass user_id."
            ),
            "imported": 0,
            "skipped": 0,
            "remote_total": 0,
            "matched": 0,
            "query": title_query or "",
        }

    q = (title_query or "").strip()
    sk = (series_key or "").strip()
    if not q and sk:
        # Prefer catalog display title, else any local log title for this key
        from app.db.models import CatalogItem

        cat = (
            db.query(CatalogItem)
            .filter(CatalogItem.series_key == sk)
            .one_or_none()
        )
        if cat and cat.display_title:
            q = str(cat.display_title).strip()
        if not q:
            row = (
                db.query(LogEntry.title)
                .filter(LogEntry.series_key == sk)
                .order_by(LogEntry.timestamp.desc())
                .first()
            )
            if row and row[0]:
                q = str(row[0]).strip()
        if not q and ":" in sk:
            # slug fallback: show:arcane → Arcane
            q = sk.split(":", 1)[1].replace("-", " ").strip()

    try:
        remote_logs = fetch_remote_logs(uid)
    except Exception as exc:  # noqa: BLE001
        logger.exception("tadoku pull failed")
        return {
            "ok": False,
            "error": f"Failed to fetch Tadoku logs: {exc}",
            "imported": 0,
            "skipped": 0,
            "remote_total": 0,
            "matched": 0,
            "user_id": uid,
            "query": q,
        }

    known = existing_remote_ids(db)
    imported = 0
    skipped = 0
    matched = 0
    already_local = 0
    samples: list[str] = []
    matched_samples: list[str] = []

    for remote in remote_logs:
        rid = str(remote.get("id") or "")
        if not rid or remote.get("deleted"):
            skipped += 1
            continue
        if q and not remote_matches_title_query(remote, q):
            skipped += 1
            continue
        matched += 1
        desc = (remote.get("description") or rid).strip()
        if len(matched_samples) < 12:
            matched_samples.append(desc)
        if rid in known:
            already_local += 1
            skipped += 1
            continue
        if dry_run:
            imported += 1
            if len(samples) < 8:
                samples.append(desc)
            continue
        entry = import_remote_log(db, remote)
        if entry:
            imported += 1
            known.add(rid)
            if len(samples) < 8:
                samples.append(entry.title)
        else:
            skipped += 1

    return {
        "ok": True,
        "user_id": uid,
        "remote_total": len(remote_logs),
        "matched": matched,
        "already_local": already_local,
        "imported": imported,
        "skipped": skipped,
        "query": q,
        "series_key": sk or None,
        "matched_samples": matched_samples,
        "dry_run": dry_run,
        "blocked_live": live_submit_blocked(),
        "samples": samples,
    }
