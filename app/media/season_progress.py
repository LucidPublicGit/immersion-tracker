"""
Season-aware progress helpers.

Storage (MediaMetadata.raw_json):
  season_totals: { "1": 12, "2": 13 }   # episodes (or volumes) per season number
  seasons_locked: true                   # user set totals — don't clobber on auto fetch

Logs use log_entries.season + episode (nullable). Missing season = "unscoped"
bucket (common for manga volumes / bulk anime logs without Sxx).
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional

from app.media.catalog_resolve import normalize_title

# Known multi-season franchises when providers only return S1 deck totals.
# Keys: normalized title aliases + series_key slug suffixes.
# Values: season number → episode count (main TV seasons; movies tracked separately).
_KNOWN_FRANCHISE_SEASON_TOTALS: dict[str, dict[int, int]] = {
    # KonoSuba: S1=10, S2=10, S3=11 (theatrical film is its own movie work)
    "konosuba": {1: 10, 2: 10, 3: 11},
    "kono subarashii sekai ni shukufuku wo": {1: 10, 2: 10, 3: 11},
    "この素晴らしい世界に祝福を": {1: 10, 2: 10, 3: 11},
    "この素晴らしい世界に祝福を!": {1: 10, 2: 10, 3: 11},
    "この素晴らしい世界に祝福を！": {1: 10, 2: 10, 3: 11},
    # Yowamushi Pedal main TV seasons (movies/OVAs tracked separately)
    # S1=38, Grande Road=24, New Generation=25, Glory Line=25, Limit Break=25
    "yowamushi pedal": {1: 38, 2: 24, 3: 25, 4: 25, 5: 25},
    "弱虫ペダル": {1: 38, 2: 24, 3: 25, 4: 25, 5: 25},
}


def known_franchise_season_totals(
    *,
    series_key: str = "",
    title: str = "",
) -> dict[int, int]:
    """
    Built-in season episode maps for multi-season works.

    Used when metadata only has a single-season deck total (e.g. jiten S1)
    so Progress can show S1 green + unfinished franchise % correctly.
    """
    candidates: list[str] = []
    sk = (series_key or "").strip().lower()
    if ":" in sk:
        candidates.append(sk.split(":", 1)[1].replace("-", " "))
    if title:
        candidates.append(normalize_title(title))
        # Also try without trailing bang / punctuation noise
        candidates.append(normalize_title(re.sub(r"[!！?？]+$", "", title)))
    for c in candidates:
        c = (c or "").strip()
        if not c:
            continue
        if c in _KNOWN_FRANCHISE_SEASON_TOTALS:
            return dict(_KNOWN_FRANCHISE_SEASON_TOTALS[c])
        compact = re.sub(r"[\s\-_]+", " ", c).strip()
        if compact in _KNOWN_FRANCHISE_SEASON_TOTALS:
            return dict(_KNOWN_FRANCHISE_SEASON_TOTALS[compact])
        # slug-style without spaces
        nospace = re.sub(r"[\s\-_]+", "", compact)
        for k, v in _KNOWN_FRANCHISE_SEASON_TOTALS.items():
            if re.sub(r"[\s\-_]+", "", k) == nospace:
                return dict(v)
    return {}


def parse_season_totals_map(raw: Any) -> dict[int, int]:
    """
    Normalize season → count map from JSON / form input.

    Accepts:
      {"1": 12, "2": 13}
      [{"season": 1, "episodes": 12}, ...]
      "1:12, 2:13" / "S1=12; S2=13"
    """
    if raw is None or raw == "":
        return {}
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return {}
        # try JSON first
        if s[0] in "{[":
            try:
                return parse_season_totals_map(json.loads(s))
            except Exception:  # noqa: BLE001
                pass
        out: dict[int, int] = {}
        for part in re.split(r"[,;\n]+", s):
            part = part.strip()
            if not part:
                continue
            m = re.match(
                r"^[Ss]?(?:eason\s*)?(\d+)\s*[:=\-–]\s*(\d+)\s*[eEvV]?[pP]?s?\.?$",
                part,
            )
            if not m:
                m = re.match(r"^(\d+)\s+(\d+)$", part)
            if m:
                try:
                    sn, cnt = int(m.group(1)), int(m.group(2))
                    if sn >= 0 and cnt > 0:
                        out[sn] = cnt
                except ValueError:
                    continue
        return out
    if isinstance(raw, dict):
        out = {}
        for k, v in raw.items():
            try:
                sn = int(str(k).lstrip("Ss"))
                cnt = int(v)
            except (TypeError, ValueError):
                continue
            if sn >= 0 and cnt > 0:
                out[sn] = cnt
        return out
    if isinstance(raw, list):
        out = {}
        for item in raw:
            if not isinstance(item, dict):
                continue
            try:
                sn = int(item.get("season"))
                cnt = int(
                    item.get("episodes")
                    or item.get("total")
                    or item.get("count")
                    or item.get("volumes")
                    or 0
                )
            except (TypeError, ValueError):
                continue
            if sn >= 0 and cnt > 0:
                out[sn] = cnt
        return out
    return {}


def format_season_totals_map(totals: dict[int, int]) -> str:
    if not totals:
        return ""
    return ", ".join(f"{s}:{totals[s]}" for s in sorted(totals))


def season_totals_from_metadata(meta: Any) -> dict[int, int]:
    """Read season_totals from MediaMetadata row (raw_json)."""
    if meta is None:
        return {}
    raw_txt = getattr(meta, "raw_json", None) or ""
    if not raw_txt:
        return {}
    try:
        raw = json.loads(raw_txt)
    except Exception:  # noqa: BLE001
        return {}
    if not isinstance(raw, dict):
        return {}
    return parse_season_totals_map(raw.get("season_totals"))


def seasons_locked_from_metadata(meta: Any) -> bool:
    if meta is None:
        return False
    raw_txt = getattr(meta, "raw_json", None) or ""
    if not raw_txt:
        return False
    try:
        raw = json.loads(raw_txt)
    except Exception:  # noqa: BLE001
        return False
    return bool(isinstance(raw, dict) and raw.get("seasons_locked"))


def merge_season_totals_into_raw(
    raw_json: Optional[str],
    season_totals: dict[int, int],
    *,
    locked: bool = True,
) -> str:
    try:
        raw = json.loads(raw_json) if raw_json else {}
    except Exception:  # noqa: BLE001
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    if season_totals:
        raw["season_totals"] = {str(k): int(v) for k, v in sorted(season_totals.items())}
        raw["seasons_locked"] = bool(locked)
    elif "season_totals" in raw and not season_totals:
        # explicit clear
        raw.pop("season_totals", None)
        raw.pop("seasons_locked", None)
    return json.dumps(raw, ensure_ascii=False)[:50000]


def season_totals_from_tvmaze_episodes(episodes: list[dict[str, Any]]) -> dict[int, int]:
    """Count episodes per season from TVMaze episode list."""
    counts: dict[int, int] = {}
    for ep in episodes or []:
        try:
            sn = int(ep.get("season") or 0)
        except (TypeError, ValueError):
            continue
        if sn <= 0:
            continue
        counts[sn] = counts.get(sn, 0) + 1
    return counts


def build_season_rows(
    *,
    episode_tags: set[str],
    log_seasons: list[tuple[Optional[int], Optional[int], float]],
    season_totals: dict[int, int],
    total_units: Optional[int] = None,
    total_units_label: Optional[str] = None,
) -> dict[str, Any]:
    """
    Build season breakdown for a progress item.

    log_seasons: list of (season, episode, minutes) from each log contribution
    (minutes optional — pass 0 if unused).
    """
    # Per-season episode tags + max episode + counts
    by: dict[Optional[int], dict[str, Any]] = {}

    def _bucket(sn: Optional[int]) -> dict[str, Any]:
        if sn not in by:
            by[sn] = {
                "season": sn,
                "episode_keys": set(),
                "max_episode": None,
                "log_count": 0,
                "minutes": 0.0,
            }
        return by[sn]

    for sn, ep, mins in log_seasons:
        b = _bucket(sn)
        b["log_count"] += 1
        b["minutes"] += float(mins or 0)
        if ep is not None:
            b["max_episode"] = (
                ep if b["max_episode"] is None else max(int(b["max_episode"]), int(ep))
            )
            if sn is not None:
                b["episode_keys"].add(f"S{int(sn):02d}E{int(ep):02d}")
            else:
                b["episode_keys"].add(f"E{int(ep):02d}")

    # Also fold any tags we already collected (in case log list incomplete)
    for tag in episode_tags or set():
        m = re.fullmatch(r"S(\d{1,2})E(\d{1,3})", tag or "", re.I)
        if m:
            sn, ep = int(m.group(1)), int(m.group(2))
            b = _bucket(sn)
            b["episode_keys"].add(f"S{sn:02d}E{ep:02d}")
            b["max_episode"] = (
                ep if b["max_episode"] is None else max(int(b["max_episode"]), ep)
            )
            continue
        m = re.fullmatch(r"E(\d{1,3})", tag or "", re.I)
        if m:
            ep = int(m.group(1))
            b = _bucket(None)
            b["episode_keys"].add(f"E{ep:02d}")
            b["max_episode"] = (
                ep if b["max_episode"] is None else max(int(b["max_episode"]), ep)
            )

    # Ensure seasons that only exist in totals still appear
    for sn in season_totals:
        _bucket(sn)

    numbered = sorted(k for k in by if k is not None)
    has_unscoped = None in by and (
        by[None]["log_count"] > 0
        or bool(by[None]["episode_keys"])
        or by[None]["max_episode"] is not None
    )
    multi = len(numbered) > 1
    # Unscoped-only noise alongside a real season (e.g. one log missing S) is mixed
    if multi:
        mode = "multi"
    elif len(numbered) == 1 and has_unscoped:
        mode = "mixed"
    elif len(numbered) == 1:
        mode = "single"
    elif has_unscoped and not numbered:
        mode = "unscoped"
    else:
        mode = "none"

    rows: list[dict[str, Any]] = []
    for sn in sorted(by.keys(), key=lambda x: (x is None, x or 0)):
        b = by[sn]
        eps_logged = len(b["episode_keys"])
        # Prefer distinct keys; fall back to max episode as lower bound of progress
        progress_eps = eps_logged
        if progress_eps == 0 and b["max_episode"] is not None:
            progress_eps = 0  # don't invent count from max alone without keys
        total_eps = season_totals.get(sn) if sn is not None else None
        numbered_exist = any(k is not None for k in by)
        flat_ok = bool(
            total_units
            and (total_units_label or "").lower()
            in ("episodes", "volumes", "chapters", "parts", "")
        )
        # Flat total → unscoped only when there are no numbered seasons
        if sn is None and not season_totals and not numbered_exist and flat_ok:
            total_eps = int(total_units)
        # Flat total → the single numbered season (Konosuba S1 + 12 eps metadata)
        if (
            sn is not None
            and not season_totals
            and len(numbered) == 1
            and flat_ok
        ):
            total_eps = int(total_units)
        pct = None
        if total_eps and total_eps > 0 and progress_eps > 0:
            # Cap at season length (S1E11 on a 10-ep season → full S1, not 110%)
            progress_eps = min(int(progress_eps), int(total_eps))
            pct = min(100.0, round(100.0 * progress_eps / total_eps, 1))
        elif total_eps and total_eps > 0 and b["max_episode"] is not None:
            # max-episode fill only when we have a season total (common for S1E11 of 12)
            filled = min(int(total_eps), int(b["max_episode"]))
            if filled > 0:
                pct = min(100.0, round(100.0 * filled / total_eps, 1))
                progress_eps = max(progress_eps, filled)
                progress_eps = min(int(progress_eps), int(total_eps))
        elif total_eps and total_eps > 0 and progress_eps > total_eps:
            progress_eps = int(total_eps)

        # Season is complete when fill ≥ total (green chip even if franchise unfinished)
        is_done = bool(
            total_eps and total_eps > 0 and progress_eps >= int(total_eps)
        )
        if is_done and pct is None:
            pct = 100.0

        if sn is not None:
            label = f"S{int(sn)}"
        else:
            label = "Eps" if (total_units_label or "").lower() in ("", "episodes") else "Items"

        rows.append(
            {
                "season": sn,
                "label": label,
                "episodes_logged": eps_logged,
                "progress_episodes": progress_eps,
                "max_episode": b["max_episode"],
                "total_episodes": total_eps,
                "percent_complete": pct,
                "is_done": is_done,
                "log_count": b["log_count"],
                "minutes": round(b["minutes"], 1) if b["minutes"] else None,
            }
        )

    # Franchise / work totals from season map
    franchise_total = sum(season_totals.values()) if season_totals else None
    franchise_done = None
    franchise_pct = None
    if season_totals:
        done = 0
        for sn, tot in season_totals.items():
            match = next((r for r in rows if r["season"] == sn), None)
            if not match:
                continue
            pe = match["progress_episodes"] or 0
            done += min(int(tot), int(pe))
        franchise_done = done
        if franchise_total:
            franchise_pct = min(100.0, round(100.0 * done / franchise_total, 1))

    # Compact display strings
    if mode in ("multi", "mixed", "single"):
        parts = []
        for r in rows:
            # Skip empty unscoped noise when numbered seasons exist
            if r["season"] is None and numbered and not (
                r["episodes_logged"] or r["max_episode"] or r["log_count"]
            ):
                continue
            if r["season"] is None and numbered and not r["episodes_logged"]:
                continue
            if r["total_episodes"]:
                parts.append(
                    f"{r['label']} {r['progress_episodes'] or 0}/{r['total_episodes']}"
                )
            elif r["episodes_logged"] or r["max_episode"]:
                pe = r["episodes_logged"] or 0
                if pe:
                    parts.append(f"{r['label']} {pe} ep")
                elif r["max_episode"]:
                    parts.append(f"{r['label']} →{r['max_episode']}")
        seasons_summary = " · ".join(parts) if parts else None
    else:
        seasons_summary = None

    return {
        "season_mode": mode,
        "seasons": rows,
        "season_totals": {str(k): v for k, v in sorted(season_totals.items())},
        "franchise_total_episodes": franchise_total,
        "franchise_done_episodes": franchise_done,
        "franchise_percent": franchise_pct,
        "seasons_summary": seasons_summary,
        "is_multi_season": mode in ("multi", "mixed"),
    }
