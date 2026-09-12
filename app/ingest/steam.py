"""
Steam Web API playtime → immersion logs (minute deltas).

Polls IPlayerService/GetOwnedGames, compares playtime_forever to per-app
watermarks, and creates logs for positive deltas ≥ min_delta_minutes.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

import httpx
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import utcnow
from app.ingest.base import PollResult
from app.ingest.service import DuplicateLogError, create_log
from app.sheets.state import get_state, set_state

logger = logging.getLogger(__name__)

SOURCE = "steam"
OWNED_GAMES_URL = "https://api.steampowered.com/IPlayerService/GetOwnedGames/v1/"
STATE_PREFIX = "steam:playtime:"
LAST_POLL_KEY = "steam:last_poll"
LAST_RESULT_KEY = "steam:last_result"
LAST_ERROR_KEY = "steam:last_error"


def _watermark_key(appid: int) -> str:
    return f"{STATE_PREFIX}{int(appid)}"


def resolve_credentials(
    api_key: str = "",
    steam_id: str = "",
) -> tuple[str, str]:
    """Resolve API key and SteamID64 from args, config, or env."""
    cfg = get_settings().yaml_config.steam
    key = (api_key or cfg.api_key or os.environ.get("STEAM_API_KEY") or "").strip()
    sid = (steam_id or cfg.steam_id or os.environ.get("STEAM_ID") or "").strip()
    return key, sid


def get_playtime_watermark(db: Session, appid: int) -> Optional[int]:
    """Return previous playtime_forever minutes, or None if never seen."""
    raw = get_state(db, _watermark_key(appid))
    if raw == "":
        return None
    try:
        return max(0, int(raw))
    except ValueError:
        return None


def set_playtime_watermark(db: Session, appid: int, minutes: int) -> None:
    set_state(db, _watermark_key(appid), str(max(0, int(minutes))))


def game_allowed(
    appid: int,
    name: str,
    *,
    app_allowlist: list[int],
    app_blocklist: list[int],
    name_allowlist: list[str],
    name_blocklist: list[str],
) -> bool:
    """Return True if this game passes allow/block filters."""
    aid = int(appid)
    if app_blocklist and aid in {int(x) for x in app_blocklist}:
        return False
    if app_allowlist and aid not in {int(x) for x in app_allowlist}:
        return False

    name_l = (name or "").lower()
    for frag in name_blocklist or []:
        f = (frag or "").strip().lower()
        if f and f in name_l:
            return False

    # name_allowlist: when non-empty, name must match at least one substring.
    # When app_allowlist already restricted the set, still apply if configured.
    allow_names = [((n or "").strip().lower()) for n in (name_allowlist or []) if (n or "").strip()]
    if allow_names:
        if not any(f in name_l for f in allow_names):
            return False
    return True


def fetch_owned_games(
    api_key: str,
    steam_id: str,
    *,
    include_appinfo: bool = True,
    include_played_free_games: bool = True,
    timeout: float = 30.0,
) -> list[dict[str, Any]]:
    """
    GET GetOwnedGames. Returns list of game dicts with appid, name, playtime_forever.
    Raises httpx.HTTPError / ValueError on failure.
    """
    params = {
        "key": api_key,
        "steamid": steam_id,
        "include_appinfo": 1 if include_appinfo else 0,
        "include_played_free_games": 1 if include_played_free_games else 0,
        "format": "json",
    }
    with httpx.Client(timeout=timeout) as client:
        resp = client.get(OWNED_GAMES_URL, params=params)
        resp.raise_for_status()
        data = resp.json()

    response = data.get("response") if isinstance(data, dict) else None
    if not isinstance(response, dict):
        raise ValueError("Steam API: missing response object")
    games = response.get("games") or []
    if not isinstance(games, list):
        raise ValueError("Steam API: games is not a list")
    return games


def _save_poll_meta(db: Session, result: PollResult) -> None:
    set_state(db, LAST_POLL_KEY, utcnow().isoformat().replace("+00:00", "Z"))
    set_state(db, LAST_RESULT_KEY, json.dumps(result.to_dict(), ensure_ascii=False))
    if result.errors:
        set_state(db, LAST_ERROR_KEY, "; ".join(result.errors[:5]))
    elif not result.ok and result.message:
        set_state(db, LAST_ERROR_KEY, result.message)
    else:
        set_state(db, LAST_ERROR_KEY, "")


def poll_steam(db: Session) -> PollResult:
    """
    Poll Steam owned games and log playtime deltas.

    Never raises — errors are captured on PollResult.
    """
    cfg = get_settings().yaml_config.steam
    result = PollResult(ok=True, source=SOURCE)

    if not cfg.enabled:
        result.message = "disabled"
        return result

    api_key, steam_id = resolve_credentials()
    if not api_key or not steam_id:
        result.ok = False
        missing = []
        if not api_key:
            missing.append("api_key / STEAM_API_KEY")
        if not steam_id:
            missing.append("steam_id / STEAM_ID")
        result.message = f"missing credentials: {', '.join(missing)}"
        result.errors.append(result.message)
        try:
            _save_poll_meta(db, result)
        except Exception:  # noqa: BLE001
            logger.debug("steam: failed to save poll meta", exc_info=True)
        return result

    try:
        games = fetch_owned_games(
            api_key,
            steam_id,
            include_appinfo=bool(cfg.include_appinfo),
            include_played_free_games=bool(cfg.include_played_free_games),
        )
    except httpx.HTTPError as exc:
        logger.warning("steam: HTTP error fetching owned games: %s", exc)
        result.ok = False
        result.message = f"http_error: {exc}"
        result.errors.append(result.message)
        try:
            _save_poll_meta(db, result)
        except Exception:  # noqa: BLE001
            pass
        return result
    except Exception as exc:  # noqa: BLE001
        logger.exception("steam: failed to fetch owned games")
        result.ok = False
        result.message = f"fetch_error: {exc}"
        result.errors.append(result.message)
        try:
            _save_poll_meta(db, result)
        except Exception:  # noqa: BLE001
            pass
        return result

    min_delta = float(cfg.min_delta_minutes or 0)
    bootstrap = bool(cfg.bootstrap)
    content_type = (cfg.content_type or "game").strip() or "game"
    unit = (cfg.unit or "minutes").strip() or "minutes"
    activity = (cfg.activity or "reading").strip() or "reading"

    filtered = 0
    baselined = 0
    tracked = 0

    for g in games:
        try:
            appid = int(g.get("appid"))
        except (TypeError, ValueError):
            result.skipped += 1
            continue

        name = str(g.get("name") or f"App {appid}").strip() or f"App {appid}"
        try:
            playtime = max(0, int(g.get("playtime_forever") or 0))
        except (TypeError, ValueError):
            playtime = 0

        if not game_allowed(
            appid,
            name,
            app_allowlist=list(cfg.app_allowlist or []),
            app_blocklist=list(cfg.app_blocklist or []),
            name_allowlist=list(cfg.name_allowlist or []),
            name_blocklist=list(cfg.name_blocklist or []),
        ):
            filtered += 1
            result.skipped += 1
            continue

        tracked += 1
        prev = get_playtime_watermark(db, appid)

        if prev is None:
            # First sight
            if bootstrap and playtime >= min_delta and playtime > 0:
                delta = float(playtime)
                try:
                    create_log(
                        db,
                        content_type=content_type,
                        title=name,
                        source=SOURCE,
                        amount=delta,
                        unit=unit,
                        activity=activity,
                        series_key=f"steam:{appid}",
                        source_ref=f"steam:{appid}:{playtime}",
                        notes=f"bootstrap; playtime_forever={playtime}",
                    )
                    result.logs_created += 1
                    set_playtime_watermark(db, appid, playtime)
                except DuplicateLogError:
                    result.skipped += 1
                    set_playtime_watermark(db, appid, playtime)
                except Exception as exc:  # noqa: BLE001
                    logger.exception("steam: create_log failed appid=%s", appid)
                    result.errors.append(f"{appid}: {exc}")
                    # No watermark — retry bootstrap log next poll
            else:
                baselined += 1
                result.skipped += 1
                set_playtime_watermark(db, appid, playtime)
            continue

        if playtime <= prev:
            # No increase (or clock reset / refund edge) — keep watermark at max
            if playtime < prev:
                # Lifetime total should not shrink; keep higher watermark
                result.skipped += 1
            else:
                result.skipped += 1
            continue

        delta_mins = playtime - prev
        if delta_mins < min_delta:
            # Hold watermark so small sessions accumulate across polls
            result.skipped += 1
            continue

        try:
            create_log(
                db,
                content_type=content_type,
                title=name,
                source=SOURCE,
                amount=float(delta_mins),
                unit=unit,
                activity=activity,
                series_key=f"steam:{appid}",
                source_ref=f"steam:{appid}:{playtime}",
                notes=f"playtime {prev}→{playtime} (+{delta_mins}m)",
            )
            result.logs_created += 1
            set_playtime_watermark(db, appid, playtime)
        except DuplicateLogError:
            # Same total already logged — advance so we do not retry forever
            result.skipped += 1
            set_playtime_watermark(db, appid, playtime)
        except Exception as exc:  # noqa: BLE001
            logger.exception("steam: create_log failed appid=%s", appid)
            result.errors.append(f"{appid}: {exc}")
            # Leave watermark so a later poll can retry this delta

    result.details = {
        "games_returned": len(games),
        "tracked": tracked,
        "filtered": filtered,
        "baselined": baselined,
        "steam_id": steam_id,
    }
    if result.logs_created:
        result.message = f"created {result.logs_created} log(s)"
        try:
            from app.sheets.state import mark_sheets_dirty

            mark_sheets_dirty(db)
        except Exception:  # noqa: BLE001
            pass
    elif not result.message:
        result.message = "ok"

    if result.errors and result.logs_created == 0:
        result.ok = False
        if not result.message or result.message == "ok":
            result.message = "; ".join(result.errors[:3])

    try:
        _save_poll_meta(db, result)
    except Exception:  # noqa: BLE001
        logger.debug("steam: failed to save poll meta", exc_info=True)

    return result


def steam_status(db: Session) -> dict[str, Any]:
    """Status blob for API / UI (no raw API key or full SteamID)."""
    from app.ingest.privacy import redact_id, scrub_mapping

    cfg = get_settings().yaml_config.steam
    api_key, steam_id = resolve_credentials()
    last_raw = get_state(db, LAST_RESULT_KEY)
    last: Any = None
    if last_raw:
        try:
            last = scrub_mapping(json.loads(last_raw))
        except json.JSONDecodeError:
            last = {"raw": "(unparseable)"}

    # Count watermarks currently stored
    tracked_count = 0
    try:
        from app.db.models import SheetSyncState

        rows = (
            db.query(SheetSyncState)
            .filter(SheetSyncState.key.like(f"{STATE_PREFIX}%"))
            .all()
        )
        tracked_count = len(rows)
    except Exception:  # noqa: BLE001
        tracked_count = 0

    return {
        "enabled": bool(cfg.enabled),
        "configured": bool(api_key and steam_id),
        "has_api_key": bool(api_key),
        "has_steam_id": bool(steam_id),
        # Never return raw key or full SteamID64 over the API
        "steam_id_redacted": redact_id(steam_id, keep_tail=4),
        "poll_seconds": int(cfg.poll_seconds),
        "min_delta_minutes": float(cfg.min_delta_minutes),
        "bootstrap": bool(cfg.bootstrap),
        "content_type": cfg.content_type,
        "unit": cfg.unit,
        "activity": cfg.activity,
        "tadoku_default": cfg.tadoku_default,
        "app_allowlist": list(cfg.app_allowlist or []),
        "app_blocklist": list(cfg.app_blocklist or []),
        "name_allowlist": list(cfg.name_allowlist or []),
        "name_blocklist": list(cfg.name_blocklist or []),
        "tracked_apps": tracked_count,
        "last_poll_at": get_state(db, LAST_POLL_KEY) or None,
        "last_error": get_state(db, LAST_ERROR_KEY) or None,
        "last_result": last,
    }
