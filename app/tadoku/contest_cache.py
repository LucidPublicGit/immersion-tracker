"""
Contest momentum cache — pull Tadoku leaderboard + per-user daily activity,
store locally, and derive velocity / acceleration metrics for the Race page.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import httpx

from app.core.config import get_settings
from app.tadoku.client import live_submit_blocked

logger = logging.getLogger(__name__)

# Soft palette for chart lines / avatars (paper-desk friendly, high contrast)
PALETTE = [
    "#c45c26",
    "#2a5278",
    "#2f6b3a",
    "#8b3a62",
    "#9a6b12",
    "#1a5c7a",
    "#a33a32",
    "#4a6741",
    "#5c4a8a",
    "#b85c38",
    "#2d6a6a",
    "#6b4c2a",
    "#3d5a80",
    "#7a3e48",
    "#4f6f52",
    "#8a5a2b",
    "#5a4e7a",
    "#2f4858",
    "#9c4a6e",
    "#3f5e46",
]

DEFAULT_CACHE_TTL_SECONDS = 15 * 60  # 15 minutes
_lock = threading.Lock()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _cache_root() -> Path:
    docker = Path("/app/data/contest_cache")
    if docker.parent.is_dir():
        return docker
    return Path("data/contest_cache")


def _cookie() -> str:
    """Active session cookie; auto-login once if credentials are saved."""
    from app.tadoku.session import ensure_session, resolve_cookie

    cookie = resolve_cookie()
    if cookie:
        return cookie
    try:
        return ensure_session(force_login=False)
    except Exception:  # noqa: BLE001
        return ""


def _api_base() -> str:
    cfg = get_settings().yaml_config.tadoku
    return (cfg.api_base or "https://tadoku.app/api/internal/immersion").rstrip("/")


def _headers() -> dict[str, str]:
    return {
        "Cookie": _cookie(),
        "Accept": "application/json",
        "Origin": "https://tadoku.app",
        "Referer": "https://tadoku.app/",
        "User-Agent": "immersion-tracker/contest-cache",
    }


def color_for_user(user_id: str) -> str:
    h = int(hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:8], 16)
    return PALETTE[h % len(PALETTE)]


def initials_for(name: str) -> str:
    parts = [p for p in (name or "?").replace("_", " ").split() if p]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def avatar_data_uri(name: str, user_id: str, *, size: int = 64) -> str:
    """Deterministic SVG avatar (temp stand-in for Discord pictures)."""
    color = color_for_user(user_id)
    # Darken for text contrast band
    initials = initials_for(name)
    # Escape for XML
    safe = (
        initials.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 {size} {size}">'
        f'<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
        f'<stop offset="0%" stop-color="{color}"/>'
        f'<stop offset="100%" stop-color="#1c1914"/>'
        f"</linearGradient></defs>"
        f'<rect width="{size}" height="{size}" rx="{size // 5}" fill="url(#g)"/>'
        f'<text x="50%" y="54%" dominant-baseline="middle" text-anchor="middle" '
        f'fill="#fffdf8" font-family="IBM Plex Sans,Segoe UI,system-ui,sans-serif" '
        f'font-weight="700" font-size="{size * 0.36}">{safe}</text></svg>'
    )
    import base64

    b64 = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{b64}"


@dataclass
class CachePaths:
    root: Path
    meta: Path
    leaderboard: Path
    activity_dir: Path
    snapshot: Path

    @classmethod
    def for_contest(cls, contest_id: str) -> "CachePaths":
        root = _cache_root() / contest_id
        return cls(
            root=root,
            meta=root / "meta.json",
            leaderboard=root / "leaderboard.json",
            activity_dir=root / "activity",
            snapshot=root / "snapshot.json",
        )


def _read_json(path: Path) -> Any:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def fetch_contest_meta(client: httpx.Client, contest_id: str) -> dict[str, Any]:
    r = client.get(f"{_api_base()}/contests/{contest_id}")
    r.raise_for_status()
    return r.json()


def fetch_contest_summary(client: httpx.Client, contest_id: str) -> dict[str, Any]:
    r = client.get(f"{_api_base()}/contests/{contest_id}/summary")
    r.raise_for_status()
    return r.json()


def fetch_leaderboard(client: httpx.Client, contest_id: str) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    page = 0
    while page < 50:
        r = client.get(
            f"{_api_base()}/contests/{contest_id}/leaderboard",
            params={"page": page, "page_size": 50},
        )
        r.raise_for_status()
        data = r.json()
        batch = data.get("entries") or []
        entries.extend(batch)
        if not batch or not data.get("next_page_token"):
            break
        page += 1
    return entries


def fetch_user_activity(
    client: httpx.Client, contest_id: str, user_id: str
) -> list[dict[str, Any]]:
    r = client.get(
        f"{_api_base()}/contests/{contest_id}/profile/{user_id}/activity"
    )
    r.raise_for_status()
    return r.json().get("rows") or []


def _parse_date(s: str) -> date:
    return date.fromisoformat(s[:10])


def _daterange(start: date, end: date) -> list[date]:
    if end < start:
        return []
    days = (end - start).days + 1
    return [start + timedelta(days=i) for i in range(days)]


def build_daily_map(rows: list[dict[str, Any]]) -> dict[str, float]:
    """Aggregate multi-language daily rows into date → score."""
    out: dict[str, float] = {}
    for row in rows:
        d = (row.get("date") or "")[:10]
        if not d:
            continue
        out[d] = out.get(d, 0.0) + float(row.get("score") or 0.0)
    return out


def cumulative_series(
    daily: dict[str, float],
    start: date,
    end: date,
) -> list[dict[str, Any]]:
    """Forward-filled cumulative score from contest start → end."""
    running = 0.0
    series: list[dict[str, Any]] = []
    for d in _daterange(start, end):
        key = d.isoformat()
        running += daily.get(key, 0.0)
        series.append({"date": key, "daily": daily.get(key, 0.0), "cumulative": running})
    return series


def sum_window(daily: dict[str, float], end: date, days: int) -> float:
    total = 0.0
    for i in range(days):
        d = (end - timedelta(days=i)).isoformat()
        total += daily.get(d, 0.0)
    return total


def last_active_date(daily: dict[str, float]) -> Optional[str]:
    active = [d for d, s in daily.items() if s > 0]
    if not active:
        return None
    return max(active)


def classify_momentum(
    accel: float,
    vel_7: float,
    inactive_days: int,
    *,
    accel_hot: float = 5.0,
    accel_cold: float = -5.0,
) -> str:
    """
    heating | cooling | steady | idle

    Acceleration = recent pace (7d avg) minus baseline (30d avg).
    """
    if inactive_days >= 14 and vel_7 < 0.5:
        return "idle"
    if accel >= accel_hot:
        return "heating"
    if accel <= accel_cold:
        return "cooling"
    return "steady"


def analyze_user(
    *,
    user_id: str,
    display_name: str,
    rank: int,
    score: float,
    daily: dict[str, float],
    contest_start: date,
    as_of: date,
    rank_above_score: Optional[float],
) -> dict[str, Any]:
    series = cumulative_series(daily, contest_start, as_of)
    sum_7 = sum_window(daily, as_of, 7)
    sum_14 = sum_window(daily, as_of, 14)
    sum_30 = sum_window(daily, as_of, 30)
    vel_7 = sum_7 / 7.0
    vel_14 = sum_14 / 14.0
    vel_30 = sum_30 / 30.0
    # Acceleration: how much faster (pts/day) now vs last month baseline
    acceleration = vel_7 - vel_30
    # Relative: ratio when baseline is meaningful
    if vel_30 > 1.0:
        accel_ratio = vel_7 / vel_30
    elif vel_7 > 1.0:
        accel_ratio = 2.0  # coming off idle
    else:
        accel_ratio = 1.0

    last = last_active_date(daily)
    if last:
        inactive_days = (as_of - _parse_date(last)).days
    else:
        inactive_days = (as_of - contest_start).days

    days_logged = sum(1 for s in daily.values() if s > 0)
    gap_above = None
    days_to_catch = None
    if rank_above_score is not None:
        gap_above = max(0.0, rank_above_score - score)
        # Catch-up if our 7d pace exceeds theirs — we only know our pace here;
        # gap close rate is filled later when we have neighbor velocities.
        if gap_above <= 0:
            days_to_catch = 0.0

    # Sparkline of last 28 daily scores (normalized later client-side ok)
    spark_end = as_of
    spark: list[float] = []
    for i in range(27, -1, -1):
        d = (spark_end - timedelta(days=i)).isoformat()
        spark.append(round(daily.get(d, 0.0), 2))

    band = classify_momentum(acceleration, vel_7, inactive_days)

    return {
        "user_id": user_id,
        "display_name": display_name,
        "rank": rank,
        "score": round(score, 2),
        "color": color_for_user(user_id),
        "initials": initials_for(display_name),
        "avatar_url": avatar_data_uri(display_name, user_id),
        "velocity_7d": round(vel_7, 2),
        "velocity_14d": round(vel_14, 2),
        "velocity_30d": round(vel_30, 2),
        "sum_7d": round(sum_7, 2),
        "sum_14d": round(sum_14, 2),
        "sum_30d": round(sum_30, 2),
        "acceleration": round(acceleration, 2),
        "accel_ratio": round(accel_ratio, 3),
        "momentum": band,
        "last_active": last,
        "inactive_days": inactive_days,
        "days_logged": days_logged,
        "gap_above": round(gap_above, 2) if gap_above is not None else None,
        "days_to_catch": days_to_catch,
        "series": series,
        "sparkline": spark,
    }


def _fill_catchup(users: list[dict[str, Any]]) -> None:
    """Estimate days to catch the person ranked above using relative 7d velocity."""
    by_rank = {u["rank"]: u for u in users}
    for u in users:
        gap = u.get("gap_above")
        if gap is None or gap <= 0:
            u["days_to_catch"] = 0.0 if gap == 0 else None
            continue
        above = by_rank.get(u["rank"] - 1)
        if not above:
            u["days_to_catch"] = None
            continue
        rel = u["velocity_7d"] - above["velocity_7d"]
        if rel > 0.5:
            u["days_to_catch"] = round(gap / rel, 1)
        else:
            u["days_to_catch"] = None  # not currently catching up


# Projection models for "if everyone keeps this pace for N days"
PROJECT_MODELS = ("velocity", "baseline", "accel")


def daily_rate_for_model(
    *,
    velocity_7d: float,
    velocity_30d: float,
    acceleration: float,
    model: str = "velocity",
) -> float:
    """
    Expected average points per day over a future horizon.

    - velocity: hold current 7-day pace
    - baseline: hold 30-day pace
    - accel: 7-day pace with linear drift of the recent acceleration
      (start at vel_7, end at max(0, vel_7 + accel); use the average)
    """
    v7 = float(velocity_7d or 0.0)
    v30 = float(velocity_30d or 0.0)
    acc = float(acceleration or 0.0)
    m = (model or "velocity").lower()
    if m == "baseline":
        return max(0.0, v30)
    if m == "accel":
        end_pace = max(0.0, v7 + acc)
        return max(0.0, (v7 + end_pace) / 2.0)
    # default: constant 7d velocity
    return max(0.0, v7)


def project_score(
    score: float,
    *,
    velocity_7d: float,
    velocity_30d: float = 0.0,
    acceleration: float = 0.0,
    days: float,
    model: str = "velocity",
) -> float:
    """Project a single runner's score after `days` at the chosen pace model."""
    if days <= 0:
        return float(score)
    rate = daily_rate_for_model(
        velocity_7d=velocity_7d,
        velocity_30d=velocity_30d,
        acceleration=acceleration,
        model=model,
    )
    return float(score) + rate * float(days)


def days_until_contest_end(as_of: date, contest_end: date) -> int:
    """Whole days from as_of to contest_end (0 if already past end)."""
    return max(0, (contest_end - as_of).days)


def project_standings(
    users: list[dict[str, Any]],
    *,
    days: float,
    model: str = "velocity",
) -> list[dict[str, Any]]:
    """
    Re-rank everyone after projecting each score forward `days`.

    Returns a new list of dicts (shallow copies) with:
      projected_score, projected_rank, rank_delta (current - projected; + = climbing),
      projected_daily_rate, project_days, project_model
    Sorted by projected_rank ascending.
    """
    days = max(0.0, float(days))
    model = (model or "velocity").lower()
    if model not in PROJECT_MODELS:
        model = "velocity"

    projected: list[dict[str, Any]] = []
    for u in users:
        rate = daily_rate_for_model(
            velocity_7d=float(u.get("velocity_7d") or 0),
            velocity_30d=float(u.get("velocity_30d") or 0),
            acceleration=float(u.get("acceleration") or 0),
            model=model,
        )
        pscore = float(u.get("score") or 0) + rate * days
        row = dict(u)
        row["projected_score"] = round(pscore, 2)
        row["projected_daily_rate"] = round(rate, 2)
        row["project_days"] = days
        row["project_model"] = model
        projected.append(row)

    # Stable rank: higher score wins; ties keep original rank as tie-breaker
    projected.sort(
        key=lambda r: (-r["projected_score"], r.get("rank") or 9999, r.get("display_name") or "")
    )
    for i, row in enumerate(projected, start=1):
        row["projected_rank"] = i
        cur = int(row.get("rank") or i)
        row["rank_delta"] = cur - i  # positive = moved up

    return projected


def project_series(
    last_score: float,
    last_date: date,
    *,
    daily_rate: float,
    days: int,
) -> list[dict[str, Any]]:
    """Build cumulative score points for a dashed chart extension."""
    days = max(0, int(days))
    out: list[dict[str, Any]] = []
    running = float(last_score)
    rate = max(0.0, float(daily_rate))
    for i in range(1, days + 1):
        d = last_date + timedelta(days=i)
        running += rate
        out.append(
            {
                "date": d.isoformat(),
                "cumulative": round(running, 2),
                "projected": True,
            }
        )
    return out


def build_snapshot(
    *,
    contest_id: str,
    contest_meta: dict[str, Any],
    summary: dict[str, Any],
    leaderboard: list[dict[str, Any]],
    activities: dict[str, list[dict[str, Any]]],
    fetched_at: str,
    as_of: Optional[date] = None,
) -> dict[str, Any]:
    start_s = (contest_meta.get("contest_start") or "2026-01-01")[:10]
    end_s = (contest_meta.get("contest_end") or "2026-12-31")[:10]
    contest_start = _parse_date(start_s)
    contest_end = _parse_date(end_s)
    as_of = min(as_of or _utc_now().date(), contest_end)

    # Sort leaderboard by rank for gap calculation
    ordered = sorted(
        leaderboard,
        key=lambda e: (e.get("rank") or 9999, -(float(e.get("score") or 0))),
    )

    users: list[dict[str, Any]] = []
    for i, entry in enumerate(ordered):
        uid = entry.get("user_id") or ""
        if not uid:
            continue
        name = entry.get("user_display_name") or "Unknown"
        rank = int(entry.get("rank") or (i + 1))
        score = float(entry.get("score") or 0.0)
        daily = build_daily_map(activities.get(uid) or [])
        above_score = None
        if i > 0:
            above_score = float(ordered[i - 1].get("score") or 0.0)
        users.append(
            analyze_user(
                user_id=uid,
                display_name=name,
                rank=rank,
                score=score,
                daily=daily,
                contest_start=contest_start,
                as_of=as_of,
                rank_above_score=above_score,
            )
        )

    _fill_catchup(users)

    # Chart: dense daily series can be huge — downsample to weekly if long
    chart_users = []
    for u in users:
        series = u["series"]
        if len(series) > 120:
            # keep every 3rd point + last
            thin = series[::3]
            if thin[-1]["date"] != series[-1]["date"]:
                thin.append(series[-1])
            chart_series = thin
        else:
            chart_series = series
        chart_users.append(
            {
                "user_id": u["user_id"],
                "display_name": u["display_name"],
                "color": u["color"],
                "rank": u["rank"],
                "score": u["score"],
                "series": [
                    {"date": p["date"], "cumulative": round(p["cumulative"], 2)}
                    for p in chart_series
                ],
            }
        )

    heating = sorted(
        [u for u in users if u["momentum"] == "heating"],
        key=lambda x: -x["acceleration"],
    )
    cooling = sorted(
        [u for u in users if u["momentum"] in ("cooling", "idle")],
        key=lambda x: x["acceleration"],
    )
    catching = sorted(
        [u for u in users if u.get("days_to_catch") is not None and u["days_to_catch"] > 0],
        key=lambda x: x["days_to_catch"],
    )[:8]

    # Strip heavy series from table payload (keep sparkline)
    table_users = []
    for u in users:
        row = {k: v for k, v in u.items() if k != "series"}
        table_users.append(row)

    return {
        "contest": {
            "id": contest_id,
            "title": contest_meta.get("title") or contest_meta.get("name") or "",
            "start": start_s,
            "end": end_s,
            "description": (contest_meta.get("description") or "")[:400],
            "official": bool(contest_meta.get("official")),
        },
        "summary": {
            "participant_count": summary.get("participant_count")
            or len([u for u in users if u["score"] > 0]),
            "total_score": round(float(summary.get("total_score") or 0), 2),
            "language_count": summary.get("language_count"),
            "as_of": as_of.isoformat(),
        },
        "fetched_at": fetched_at,
        "users": table_users,
        "chart": chart_users,
        "highlights": {
            "heating": [
                {
                    "user_id": u["user_id"],
                    "display_name": u["display_name"],
                    "avatar_url": u["avatar_url"],
                    "color": u["color"],
                    "acceleration": u["acceleration"],
                    "velocity_7d": u["velocity_7d"],
                    "rank": u["rank"],
                    "score": u["score"],
                }
                for u in heating[:6]
            ],
            "cooling": [
                {
                    "user_id": u["user_id"],
                    "display_name": u["display_name"],
                    "avatar_url": u["avatar_url"],
                    "color": u["color"],
                    "acceleration": u["acceleration"],
                    "velocity_7d": u["velocity_7d"],
                    "rank": u["rank"],
                    "score": u["score"],
                    "inactive_days": u["inactive_days"],
                    "momentum": u["momentum"],
                }
                for u in cooling[:6]
            ],
            "catching_up": [
                {
                    "user_id": u["user_id"],
                    "display_name": u["display_name"],
                    "avatar_url": u["avatar_url"],
                    "color": u["color"],
                    "days_to_catch": u["days_to_catch"],
                    "gap_above": u["gap_above"],
                    "rank": u["rank"],
                    "velocity_7d": u["velocity_7d"],
                }
                for u in catching
            ],
        },
    }


def load_cached_snapshot(contest_id: str) -> Optional[dict[str, Any]]:
    paths = CachePaths.for_contest(contest_id)
    return _read_json(paths.snapshot)


def cache_age_seconds(contest_id: str) -> Optional[float]:
    paths = CachePaths.for_contest(contest_id)
    meta = _read_json(paths.meta)
    if not meta or not meta.get("fetched_at"):
        return None
    try:
        ts = datetime.fromisoformat(meta["fetched_at"].replace("Z", "+00:00"))
        return max(0.0, (_utc_now() - ts).total_seconds())
    except (TypeError, ValueError):
        return None


def refresh_contest_cache(
    contest_id: Optional[str] = None,
    *,
    force: bool = False,
    ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
) -> dict[str, Any]:
    """
    Fetch (or reuse cache) leaderboard + activity and rebuild snapshot.

    Skips remote fetches when cache is fresh unless force=True.
    Reuses per-user activity files when that user's total score is unchanged.
    """
    settings = get_settings()
    cfg = settings.yaml_config.tadoku
    contest_id = contest_id or (cfg.contest.contest_id if cfg.contest else "")
    if not contest_id:
        raise ValueError("No contest_id configured")

    with _lock:
        paths = CachePaths.for_contest(contest_id)
        paths.root.mkdir(parents=True, exist_ok=True)
        paths.activity_dir.mkdir(parents=True, exist_ok=True)

        age = cache_age_seconds(contest_id)
        if not force and age is not None and age < ttl_seconds:
            snap = load_cached_snapshot(contest_id)
            if snap:
                snap["cache"] = {
                    "hit": True,
                    "age_seconds": round(age),
                    "ttl_seconds": ttl_seconds,
                }
                return snap

        cookie = _cookie()
        if not cookie or live_submit_blocked():
            # Offline / test: serve stale cache if any
            snap = load_cached_snapshot(contest_id)
            if snap:
                snap["cache"] = {
                    "hit": True,
                    "stale": True,
                    "reason": "no_cookie_or_dry_run",
                    "age_seconds": round(age) if age is not None else None,
                }
                return snap
            raise RuntimeError(
                "TADOKU_COOKIE not set (or dry-run) and no local contest cache yet"
            )

        fetched_at = _utc_now().isoformat().replace("+00:00", "Z")
        with httpx.Client(headers=_headers(), timeout=45.0, follow_redirects=True) as client:
            contest_meta = fetch_contest_meta(client, contest_id)
            try:
                summary = fetch_contest_summary(client, contest_id)
            except httpx.HTTPError:
                summary = {}
            leaderboard = fetch_leaderboard(client, contest_id)

            old_lb = _read_json(paths.leaderboard) or []
            old_scores = {
                e.get("user_id"): float(e.get("score") or 0)
                for e in old_lb
                if e.get("user_id")
            }

            activities: dict[str, list[dict[str, Any]]] = {}
            refreshed = 0
            reused = 0
            for entry in leaderboard:
                uid = entry.get("user_id")
                if not uid:
                    continue
                score = float(entry.get("score") or 0)
                act_path = paths.activity_dir / f"{uid}.json"
                cached_act = _read_json(act_path)
                if (
                    not force
                    and cached_act is not None
                    and old_scores.get(uid) == score
                    and isinstance(cached_act, dict)
                    and "rows" in cached_act
                ):
                    activities[uid] = cached_act["rows"]
                    reused += 1
                    continue
                rows = fetch_user_activity(client, contest_id, uid)
                activities[uid] = rows
                _write_json(
                    act_path,
                    {
                        "user_id": uid,
                        "score": score,
                        "fetched_at": fetched_at,
                        "rows": rows,
                    },
                )
                refreshed += 1
                # Be polite to tadoku.app
                time.sleep(0.05)

        _write_json(paths.leaderboard, leaderboard)
        _write_json(
            paths.meta,
            {
                "contest_id": contest_id,
                "fetched_at": fetched_at,
                "user_count": len(leaderboard),
                "activity_refreshed": refreshed,
                "activity_reused": reused,
            },
        )

        snapshot = build_snapshot(
            contest_id=contest_id,
            contest_meta=contest_meta,
            summary=summary,
            leaderboard=leaderboard,
            activities=activities,
            fetched_at=fetched_at,
        )
        snapshot["cache"] = {
            "hit": False,
            "age_seconds": 0,
            "ttl_seconds": ttl_seconds,
            "activity_refreshed": refreshed,
            "activity_reused": reused,
        }
        _write_json(paths.snapshot, snapshot)
        logger.info(
            "contest cache refreshed contest=%s users=%s refreshed=%s reused=%s",
            contest_id,
            len(leaderboard),
            refreshed,
            reused,
        )
        return snapshot


def get_contest_momentum(
    *,
    force: bool = False,
    contest_id: Optional[str] = None,
) -> dict[str, Any]:
    """Public entry: return momentum snapshot (refresh if needed)."""
    return refresh_contest_cache(contest_id=contest_id, force=force)
