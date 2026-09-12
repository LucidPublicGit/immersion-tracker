"""
Spotify recently-played podcast episodes → immersion listening logs.

OAuth refresh tokens live in a JSON file written by scripts/spotify_oauth_setup.py.
Poll path is registered as app.ingest.spotify:poll_spotify.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx
from sqlalchemy.orm import Session

from app.core.config import SpotifyConfig, get_settings
from app.db.models import LogEntry, utcnow
from app.ingest.base import PollResult
from app.ingest.service import DuplicateLogError, create_log, ensure_catalog
from app.sheets.state import get_state, set_state

logger = logging.getLogger(__name__)

SOURCE = "spotify"
TOKEN_URL = "https://accounts.spotify.com/api/token"
RECENTLY_PLAYED_URL = "https://api.spotify.com/v1/me/player/recently-played"
CURRENTLY_PLAYING_URL = "https://api.spotify.com/v1/me/player/currently-playing"

LAST_POLL_KEY = "spotify:last_poll_at"
LAST_RESULT_KEY = "spotify:last_result"
WATERMARK_KEY = "spotify:last_played_at_ms"

# Refresh a minute before expiry
_TOKEN_SKEW_SECONDS = 60


class SpotifyAuthError(RuntimeError):
    """Token load / refresh failure."""


def _cfg() -> SpotifyConfig:
    return get_settings().yaml_config.spotify


def resolve_token_path(configured: Optional[str] = None) -> Path:
    """Resolve token file path (Docker /app/data vs host data/)."""
    raw = (configured if configured is not None else _cfg().token_file) or ""
    raw = raw.strip() or "/app/data/spotify-oauth-token.json"
    primary = Path(raw)
    if primary.is_file():
        return primary
    name = primary.name or "spotify-oauth-token.json"
    for candidate in (
        primary,
        Path("data") / name,
        Path("/app/data") / name,
    ):
        if candidate.is_file():
            return candidate
    return primary


def _client_credentials(cfg: Optional[SpotifyConfig] = None) -> tuple[str, str]:
    cfg = cfg or _cfg()
    client_id = (cfg.client_id or "").strip() or (os.environ.get("SPOTIFY_CLIENT_ID") or "").strip()
    client_secret = (
        (cfg.client_secret or "").strip()
        or (os.environ.get("SPOTIFY_CLIENT_SECRET") or "").strip()
    )
    return client_id, client_secret


def load_token_file(path: Optional[Path] = None) -> dict[str, Any]:
    token_path = path or resolve_token_path()
    if not token_path.is_file():
        raise SpotifyAuthError(f"token file missing: {token_path}")
    try:
        data = json.loads(token_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise SpotifyAuthError(f"token file unreadable: {token_path}: {e}") from e
    if not isinstance(data, dict):
        raise SpotifyAuthError("token file must be a JSON object")
    if not (data.get("refresh_token") or "").strip():
        raise SpotifyAuthError("token file missing refresh_token")
    return data


def save_token_file(data: dict[str, Any], path: Optional[Path] = None) -> Path:
    token_path = path or resolve_token_path()
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return token_path


def _basic_auth_header(client_id: str, client_secret: str) -> str:
    raw = f"{client_id}:{client_secret}".encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("ascii")


def refresh_access_token(
    *,
    token_data: Optional[dict[str, Any]] = None,
    token_path: Optional[Path] = None,
    client: Optional[httpx.Client] = None,
    force: bool = False,
) -> dict[str, Any]:
    """
    Ensure access_token is valid; refresh via refresh_token grant if needed.

    Updates token file on successful refresh. Returns the (possibly updated) token dict.
    """
    cfg = _cfg()
    path = token_path or resolve_token_path()
    data = dict(token_data) if token_data is not None else load_token_file(path)
    client_id, client_secret = _client_credentials(cfg)
    if not client_id or not client_secret:
        raise SpotifyAuthError(
            "Spotify client_id/client_secret missing "
            "(config.spotify or SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET)"
        )

    now = int(time.time())
    expires_at = int(data.get("expires_at") or 0)
    access = (data.get("access_token") or "").strip()
    if not force and access and expires_at > now + _TOKEN_SKEW_SECONDS:
        return data

    refresh = (data.get("refresh_token") or "").strip()
    if not refresh:
        raise SpotifyAuthError("no refresh_token to refresh access token")

    owns_client = client is None
    client = client or httpx.Client(timeout=30.0)
    try:
        r = client.post(
            TOKEN_URL,
            headers={
                "Authorization": _basic_auth_header(client_id, client_secret),
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh,
            },
        )
        if r.status_code >= 400:
            # Do not include response body — may echo request metadata
            raise SpotifyAuthError(
                f"token refresh failed HTTP {r.status_code}"
            )
        body = r.json()
    finally:
        if owns_client:
            client.close()

    new_access = (body.get("access_token") or "").strip()
    if not new_access:
        raise SpotifyAuthError("token refresh response missing access_token")
    data["access_token"] = new_access
    expires_in = int(body.get("expires_in") or 3600)
    data["expires_at"] = int(time.time()) + expires_in
    # Spotify may rotate refresh tokens
    if body.get("refresh_token"):
        data["refresh_token"] = body["refresh_token"]
    save_token_file(data, path)
    return data


def get_access_token(
    *,
    client: Optional[httpx.Client] = None,
    token_path: Optional[Path] = None,
) -> str:
    data = refresh_access_token(client=client, token_path=token_path)
    return str(data["access_token"])


def _auth_headers(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


def fetch_recently_played(
    access_token: str,
    *,
    limit: int = 50,
    after_ms: Optional[int] = None,
    client: Optional[httpx.Client] = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {"limit": max(1, min(50, int(limit)))}
    if after_ms is not None and after_ms > 0:
        params["after"] = int(after_ms)
    owns = client is None
    client = client or httpx.Client(timeout=30.0)
    try:
        r = client.get(
            RECENTLY_PLAYED_URL,
            headers=_auth_headers(access_token),
            params=params,
        )
        if r.status_code >= 400:
            raise RuntimeError(f"recently-played HTTP {r.status_code}")
        return r.json()
    finally:
        if owns:
            client.close()


def fetch_currently_playing(
    access_token: str,
    *,
    market: str = "US",
    client: Optional[httpx.Client] = None,
) -> Optional[dict[str, Any]]:
    """Return currently-playing payload, or None if nothing / 204."""
    owns = client is None
    client = client or httpx.Client(timeout=30.0)
    try:
        r = client.get(
            CURRENTLY_PLAYING_URL,
            headers=_auth_headers(access_token),
            params={"market": market or "US", "additional_types": "episode"},
        )
        if r.status_code == 204 or r.status_code == 202:
            return None
        if r.status_code >= 400:
            logger.debug("currently-playing HTTP %s", r.status_code)
            return None
        if not r.content:
            return None
        return r.json()
    finally:
        if owns:
            client.close()


def _strip_spotify_id(value: str) -> str:
    """Accept bare id, spotify:show:id, or open.spotify.com URL tail."""
    s = (value or "").strip()
    if not s:
        return ""
    if "spotify.com/" in s:
        s = s.rstrip("/").split("/")[-1].split("?")[0]
    if ":" in s:
        s = s.split(":")[-1]
    return s.strip()


def _is_episode_item(track: dict[str, Any], context: Optional[dict[str, Any]]) -> bool:
    if not track:
        return False
    t = str(track.get("type") or "").lower()
    if t == "episode":
        return True
    if track.get("show") and isinstance(track.get("show"), dict):
        return True
    uri = str(track.get("uri") or "")
    if uri.startswith("spotify:episode:"):
        return True
    if context and str(context.get("type") or "").lower() == "show":
        return True
    return False


def _extract_show(track: dict[str, Any], context: Optional[dict[str, Any]]) -> tuple[str, str]:
    """Return (show_id, show_name)."""
    show = track.get("show") if isinstance(track.get("show"), dict) else {}
    show_id = _strip_spotify_id(str(show.get("id") or ""))
    show_name = str(show.get("name") or "").strip()
    if not show_id and context:
        uri = str(context.get("uri") or "")
        if uri.startswith("spotify:show:"):
            show_id = uri.split(":")[-1]
    return show_id, show_name


def parse_play_item(item: dict[str, Any]) -> Optional[dict[str, Any]]:
    """
    Normalize a recently-played (or currently-playing item) entry.

    Returns dict with keys:
      kind: episode|track
      id, name, duration_ms, played_at, show_id, show_name, source_ref, series_key
    """
    if not item:
        return None
    # recently-played uses "track"; currently-playing uses "item"
    track = item.get("track") or item.get("item")
    if not isinstance(track, dict):
        return None
    context = item.get("context") if isinstance(item.get("context"), dict) else None
    is_ep = _is_episode_item(track, context)
    obj_id = _strip_spotify_id(str(track.get("id") or ""))
    if not obj_id:
        uri = str(track.get("uri") or "")
        if ":" in uri:
            obj_id = uri.split(":")[-1]
    if not obj_id:
        return None

    name = str(track.get("name") or "").strip() or "Unknown"
    try:
        duration_ms = int(track.get("duration_ms") or 0)
    except (TypeError, ValueError):
        duration_ms = 0

    played_at_raw = item.get("played_at")
    played_at: Optional[datetime] = None
    if played_at_raw:
        try:
            played_at = datetime.fromisoformat(
                str(played_at_raw).replace("Z", "+00:00")
            )
            if played_at.tzinfo is None:
                played_at = played_at.replace(tzinfo=timezone.utc)
        except ValueError:
            played_at = None

    if is_ep:
        show_id, show_name = _extract_show(track, context)
        return {
            "kind": "episode",
            "id": obj_id,
            "name": name,
            "duration_ms": duration_ms,
            "played_at": played_at,
            "show_id": show_id,
            "show_name": show_name,
            "source_ref": f"spotify:episode:{obj_id}",
            "series_key": f"spotify:show:{show_id}" if show_id else f"spotify:episode:{obj_id}",
        }

    # music track
    artists = track.get("artists") if isinstance(track.get("artists"), list) else []
    artist_name = ""
    artist_id = ""
    if artists and isinstance(artists[0], dict):
        artist_name = str(artists[0].get("name") or "").strip()
        artist_id = _strip_spotify_id(str(artists[0].get("id") or ""))
    album = track.get("album") if isinstance(track.get("album"), dict) else {}
    album_name = str(album.get("name") or "").strip()
    return {
        "kind": "track",
        "id": obj_id,
        "name": name,
        "duration_ms": duration_ms,
        "played_at": played_at,
        "show_id": artist_id,  # reuse filter fields loosely
        "show_name": artist_name or album_name,
        "source_ref": f"spotify:track:{obj_id}",
        "series_key": (
            f"spotify:artist:{artist_id}" if artist_id else f"spotify:track:{obj_id}"
        ),
        "artist_name": artist_name,
        "album_name": album_name,
    }


def show_allowed(
    show_id: str,
    show_name: str,
    *,
    cfg: Optional[SpotifyConfig] = None,
) -> tuple[bool, str]:
    """Apply show_blocklist then show_allowlist. Empty allowlist = allow all."""
    cfg = cfg or _cfg()
    sid = _strip_spotify_id(show_id)
    sname = (show_name or "").strip()
    sname_l = sname.lower()

    for entry in cfg.show_blocklist or []:
        token = str(entry or "").strip()
        if not token:
            continue
        tid = _strip_spotify_id(token)
        if tid and sid and tid.lower() == sid.lower():
            return False, "show_blocked"
        if token.lower() in sname_l and sname_l:
            return False, "show_blocked"

    allow = [str(x).strip() for x in (cfg.show_allowlist or []) if str(x).strip()]
    if not allow:
        return True, "ok"

    for token in allow:
        tid = _strip_spotify_id(token)
        if tid and sid and tid.lower() == sid.lower():
            return True, "ok"
        # name substring (also match raw token against name)
        if token.lower() in sname_l and sname_l:
            return True, "ok"
    return False, "show_not_allowlisted"


def find_existing_spotify_log(db: Session, source_ref: str) -> Optional[LogEntry]:
    ref = (source_ref or "").strip()
    if not ref:
        return None
    return (
        db.query(LogEntry)
        .filter(LogEntry.source == SOURCE, LogEntry.source_ref == ref)
        .one_or_none()
    )


def _played_at_ms(played_at: Optional[datetime]) -> Optional[int]:
    if played_at is None:
        return None
    return int(played_at.timestamp() * 1000)


def _ingest_play(
    db: Session,
    play: dict[str, Any],
    cfg: SpotifyConfig,
) -> tuple[str, Optional[int]]:
    """
    Attempt to log one play. Returns (reason, log_id|None).
    reason is logged | duplicate | skipped_* | rejected_*.
    """
    kind = play.get("kind")
    if kind == "track" and cfg.podcasts_only:
        return "skipped_music", None
    if kind not in ("episode", "track"):
        return "skipped_unknown", None

    show_id = str(play.get("show_id") or "")
    show_name = str(play.get("show_name") or "")
    if kind == "episode":
        ok, why = show_allowed(show_id, show_name, cfg=cfg)
        if not ok:
            return why, None

    source_ref = str(play.get("source_ref") or "")
    existing = find_existing_spotify_log(db, source_ref)
    if existing:
        return "duplicate", existing.id

    duration_ms = int(play.get("duration_ms") or 0)
    amount = round(duration_ms / 60_000.0, 3) if duration_ms > 0 else 0.0
    # completion_threshold is reserved; recently-played has no progress ratio
    _ = float(cfg.completion_threshold or 0.0)

    title = str(play.get("name") or "Unknown")
    series_key = str(play.get("series_key") or "")
    content_type = (cfg.content_type or "podcast").strip() or "podcast"
    unit = (cfg.unit or "minutes").strip() or "minutes"
    activity = (cfg.activity or "listening").strip() or "listening"

    if kind == "episode":
        notes_parts = [
            f"episode_id={play.get('id')}",
            f"duration_ms={duration_ms}",
        ]
        if show_name:
            notes_parts.append(f"show={show_name}")
        if show_id:
            notes_parts.append(f"show_id={show_id}")
        notes = "; ".join(notes_parts)
        # Catalog display = show name when known
        if series_key and show_name:
            ensure_catalog(
                db,
                series_key,
                show_name,
                content_type,
                default_unit=unit,
            )
    else:
        artist = str(play.get("artist_name") or show_name or "")
        album = str(play.get("album_name") or "")
        notes = f"track_id={play.get('id')}; duration_ms={duration_ms}"
        if artist:
            notes += f"; artist={artist}"
        if album:
            notes += f"; album={album}"
        if series_key and artist:
            ensure_catalog(
                db,
                series_key,
                artist,
                content_type,
                default_unit=unit,
            )

    try:
        entry = create_log(
            db,
            content_type=content_type,
            title=title,
            source=SOURCE,
            amount=amount,
            unit=unit,
            activity=activity,
            series_key=series_key or None,
            source_ref=source_ref,
            notes=notes,
            timestamp=play.get("played_at"),
            watch_ratio=1.0 if duration_ms > 0 else None,
        )
    except DuplicateLogError as dup:
        return "duplicate", dup.existing.id

    return "logged", entry.id


def poll_spotify(db: Session) -> PollResult:
    """Scheduler entrypoint: pull recently-played and create logs."""
    cfg = _cfg()
    if not cfg.enabled:
        result = PollResult(
            ok=True,
            source=SOURCE,
            message="disabled",
            details={"enabled": False},
        )
        _save_poll_meta(db, result)
        return result

    client_id, client_secret = _client_credentials(cfg)
    if not client_id or not client_secret:
        result = PollResult(
            ok=False,
            source=SOURCE,
            message="missing client credentials",
            errors=["Set spotify.client_id/client_secret or SPOTIFY_CLIENT_* env"],
        )
        _save_poll_meta(db, result)
        return result

    token_path = resolve_token_path(cfg.token_file)
    if not token_path.is_file():
        result = PollResult(
            ok=False,
            source=SOURCE,
            message=f"token file missing: {token_path}",
            errors=["Run scripts/spotify_oauth_setup.py once"],
        )
        _save_poll_meta(db, result)
        return result

    created = 0
    skipped = 0
    errors: list[str] = []
    details: dict[str, Any] = {
        "items_seen": 0,
        "episodes": 0,
        "tracks": 0,
        "duplicates": 0,
        "filtered": 0,
        "music_skipped": 0,
    }

    try:
        with httpx.Client(timeout=30.0) as client:
            token_data = refresh_access_token(token_path=token_path, client=client)
            access = str(token_data["access_token"])

            after_raw = (get_state(db, WATERMARK_KEY) or "").strip()
            after_ms: Optional[int] = None
            if after_raw:
                try:
                    after_ms = int(after_raw)
                except ValueError:
                    after_ms = None

            payload = fetch_recently_played(
                access,
                limit=50,
                after_ms=after_ms,
                client=client,
            )
            items = list(payload.get("items") or [])
            details["items_seen"] = len(items)

            # Also peek currently-playing (status + optional late episode not yet in history)
            current = fetch_currently_playing(
                access,
                market=cfg.market or "US",
                client=client,
            )
            if current and isinstance(current.get("item"), dict):
                # Only append if it looks finished-ish is unknown; we log from history primarily.
                # Include current item only when progress >= 0.99 if progress fields exist.
                progress = current.get("progress_ms")
                item_obj = current.get("item") or {}
                dur = item_obj.get("duration_ms")
                try:
                    if (
                        progress is not None
                        and dur
                        and int(dur) > 0
                        and int(progress) / int(dur) >= 0.99
                    ):
                        items.append(
                            {
                                "track": item_obj,
                                "played_at": utcnow().isoformat().replace("+00:00", "Z"),
                                "context": current.get("context"),
                            }
                        )
                        details["from_currently_playing"] = True
                except (TypeError, ValueError):
                    pass
                details["currently_playing"] = {
                    "type": item_obj.get("type"),
                    "name": item_obj.get("name"),
                    "id": item_obj.get("id"),
                }

            # Process oldest → newest so watermark advances cleanly
            plays: list[dict[str, Any]] = []
            for raw in items:
                play = parse_play_item(raw if isinstance(raw, dict) else {})
                if play:
                    plays.append(play)
            plays.sort(
                key=lambda p: p.get("played_at") or datetime.min.replace(tzinfo=timezone.utc)
            )

            max_played_ms = after_ms or 0
            for play in plays:
                kind = play.get("kind")
                if kind == "episode":
                    details["episodes"] += 1
                elif kind == "track":
                    details["tracks"] += 1

                reason, log_id = _ingest_play(db, play, cfg)
                if reason == "logged":
                    created += 1
                elif reason == "duplicate":
                    skipped += 1
                    details["duplicates"] += 1
                elif reason == "skipped_music":
                    skipped += 1
                    details["music_skipped"] += 1
                elif reason in ("show_blocked", "show_not_allowlisted"):
                    skipped += 1
                    details["filtered"] += 1
                else:
                    skipped += 1

                pms = _played_at_ms(play.get("played_at"))
                if pms is not None and pms > max_played_ms:
                    max_played_ms = pms

            if max_played_ms and max_played_ms > (after_ms or 0):
                set_state(db, WATERMARK_KEY, str(max_played_ms))
                details["watermark_ms"] = max_played_ms

    except SpotifyAuthError as e:
        result = PollResult(
            ok=False,
            source=SOURCE,
            message=str(e),
            errors=[str(e)],
            logs_created=created,
            skipped=skipped,
            details=details,
        )
        _save_poll_meta(db, result)
        return result
    except Exception as e:  # noqa: BLE001
        logger.exception("spotify poll failed")
        errors.append(str(e))
        result = PollResult(
            ok=False,
            source=SOURCE,
            message=str(e),
            errors=errors,
            logs_created=created,
            skipped=skipped,
            details=details,
        )
        _save_poll_meta(db, result)
        return result

    result = PollResult(
        ok=True,
        source=SOURCE,
        logs_created=created,
        skipped=skipped,
        message=f"created={created} skipped={skipped}",
        details=details,
    )
    _save_poll_meta(db, result)
    return result


def _save_poll_meta(db: Session, result: PollResult) -> None:
    try:
        set_state(db, LAST_POLL_KEY, utcnow().isoformat().replace("+00:00", "Z"))
        set_state(
            db,
            LAST_RESULT_KEY,
            json.dumps(result.to_dict(), ensure_ascii=False, default=str),
        )
    except Exception:  # noqa: BLE001
        logger.debug("spotify poll meta save failed", exc_info=True)


def spotify_status(db: Session) -> dict[str, Any]:
    """Status blob for API / UI (never returns tokens or client secret)."""
    from app.ingest.privacy import redact_id, scrub_mapping

    cfg = _cfg()
    last_raw = get_state(db, LAST_RESULT_KEY)
    last: Any = None
    if last_raw:
        try:
            last = scrub_mapping(json.loads(last_raw))
        except json.JSONDecodeError:
            last = {"raw": "(unparseable)"}

    token_path = resolve_token_path(cfg.token_file)
    token_ok = False
    token_has_refresh = False
    expires_at = None
    if token_path.is_file():
        try:
            data = load_token_file(token_path)
            token_has_refresh = bool(data.get("refresh_token"))
            token_ok = token_has_refresh
            expires_at = data.get("expires_at")
            # Never retain token material in locals beyond flags
            data = {}
        except SpotifyAuthError:
            token_ok = False

    client_id, client_secret = _client_credentials(cfg)
    return {
        "enabled": bool(cfg.enabled),
        "poll_seconds": int(cfg.poll_seconds or 300),
        "podcasts_only": bool(cfg.podcasts_only),
        "content_type": cfg.content_type,
        "unit": cfg.unit,
        "activity": cfg.activity,
        "tadoku_default": cfg.tadoku_default,
        "show_allowlist": list(cfg.show_allowlist or []),
        "show_blocklist": list(cfg.show_blocklist or []),
        "market": cfg.market,
        # Path basename only — avoid leaking host username in absolute paths
        "token_file": token_path.name,
        "token_file_exists": token_path.is_file(),
        "token_ok": token_ok,
        "token_has_refresh": token_has_refresh,
        "token_expires_at": expires_at,
        "has_client_id": bool(client_id),
        "has_client_secret": bool(client_secret),
        "client_id_redacted": redact_id(client_id, keep_tail=4),
        "last_poll_at": get_state(db, LAST_POLL_KEY) or None,
        "watermark_ms": get_state(db, WATERMARK_KEY) or None,
        "last_result": last,
    }
