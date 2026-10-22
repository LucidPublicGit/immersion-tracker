"""
Tadoku session cookie resolution + health checks + credential-driven refresh.

Saved credentials obtain a ``tadoku_session`` cookie. New session cookies can
also be supplied through a file, environment variable or configuration.
"""
from __future__ import annotations

import logging
import os
import tempfile
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional

import httpx

from app.core.config import get_settings
from app.tadoku.auth import format_session_cookie_header

logger = logging.getLogger(__name__)

_TRUTHY = frozenset({"1", "true", "yes", "on"})


def _live_submit_blocked() -> bool:
    """Same guards as TadokuClient — kept local to avoid import cycles."""
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return True
    flag = os.environ.get("IMMERSION_TADOKU_DRY_RUN", "").strip().lower()
    return flag in _TRUTHY


# A 200 identity response can still mean signed out (account: null).
_PROBE_PATH = "/identity/session"

# Avoid hammering tadoku.app from the queue UI / settings polls.
_CACHE_TTL_OK_SEC = 300.0
_CACHE_TTL_BAD_SEC = 60.0

_lock = threading.Lock()
_cache: Optional["SessionHealth"] = None
_cache_mono: float = 0.0
# Prevent concurrent auto-login storms
_login_lock = threading.Lock()
# Survives health-cache invalidations, so scheduled checks cannot retry failed
# credentials every minute. Explicit refresh and credential changes reset it.
_LOGIN_FAILURE_COOLDOWN_SEC = 15 * 60.0
_login_retry_after: float = 0.0


def cookie_file_path() -> Path:
    """Runtime cookie override (survives container restarts via ./data volume)."""
    docker = Path("/app/data/tadoku_session.cookie")
    if docker.parent.is_dir():
        return docker
    return Path("data/tadoku_session.cookie")


def _resolved_cookie() -> tuple[str, str]:
    """
    Cookie string for live Tadoku HTTP calls.

    Priority:
      1. data/tadoku_session.cookie (UI / auto-login refresh)
      2. env TADOKU_COOKIE / TADOKU_SESSION_COOKIE
      3. yaml tadoku.session_cookie (discouraged)
    """
    path = cookie_file_path()
    try:
        if path.is_file():
            text = format_session_cookie_header(path.read_text(encoding="utf-8"))
            if text:
                return text, "file"
    except OSError:
        logger.debug("could not read tadoku cookie file", exc_info=True)

    settings = get_settings()
    cfg = settings.yaml_config.tadoku
    env_name = cfg.session_cookie_env or "TADOKU_COOKIE"
    for value, source in (
        (os.environ.get(env_name, ""), "env"),
        (os.environ.get("TADOKU_SESSION_COOKIE", ""), "env"),
        (cfg.session_cookie or "", "yaml"),
    ):
        cookie = format_session_cookie_header(value)
        if cookie:
            return cookie, source
    return "", "none"


def resolve_cookie() -> str:
    """Return only a usable new session cookie, never a legacy Kratos cookie."""
    return _resolved_cookie()[0]


def save_cookie(cookie: str) -> Path:
    """Persist session cookie for live submit (never log the value)."""
    cleaned = format_session_cookie_header(cookie)
    if not cleaned:
        raise ValueError("A tadoku_session cookie is required; sign in again on tadoku.app")
    path = cookie_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # Create with private permissions before writing any secret; replace atomically
    # so failures preserve the previous cookie, including on an existing 0644 file.
    fd, temporary = tempfile.mkstemp(prefix=".tadoku-session-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            os.fchmod(handle.fileno(), 0o600)
            handle.write(cleaned + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    invalidate_session_cache()
    logger.info("tadoku session cookie saved")
    return path


def clear_cookie_file() -> bool:
    """Remove runtime cookie file (falls back to env). Returns True if removed."""
    path = cookie_file_path()
    try:
        if path.is_file():
            path.unlink()
            invalidate_session_cache()
            return True
    except OSError:
        logger.debug("could not remove tadoku cookie file", exc_info=True)
    return False


def cookie_source() -> str:
    """Where the active cookie came from (never returns secret value)."""
    return _resolved_cookie()[1]


def invalidate_saved_session() -> None:
    """
    Drop the persisted session cookie so the next request must re-login.
    Used when credentials change or login is cleared.
    """
    clear_cookie_file()
    invalidate_session_cache()
    global _login_retry_after
    with _login_lock:
        _login_retry_after = 0.0


def ensure_session(*, force_login: bool = False) -> str:
    """
    Return a session cookie, logging in with saved credentials when needed.

    - force_login=False: reuse saved cookie if present; otherwise login
    - force_login=True: sign in again and replace cookie only on success
    Automatic calls respect a cooldown after failed sign-in, including 401 retries.
    """
    from app.tadoku.auth import TadokuAuthenticationError, ensure_session_cookie
    from app.tadoku.credentials import credentials_configured

    global _login_retry_after

    existing = resolve_cookie()
    if existing and not force_login:
        return existing

    if not credentials_configured():
        raise TadokuAuthenticationError(
            "Tadoku username and password are not configured"
        )

    with _login_lock:
        # Another thread may have refreshed while we waited
        existing = resolve_cookie()
        if existing and not force_login:
            return existing

        if time.monotonic() < _login_retry_after:
            raise TadokuAuthenticationError(
                "Tadoku automatic login paused after a failed attempt; wait 15 minutes "
                "or check credentials and use Refresh Tadoku login"
            )
        try:
            cookie = ensure_session_cookie(
                force_login=True,
                existing_cookie="" if force_login else existing,
            )
        except TadokuAuthenticationError:
            _login_retry_after = time.monotonic() + _LOGIN_FAILURE_COOLDOWN_SEC
            raise
        save_cookie(cookie)
        _login_retry_after = 0.0
        return cookie


def refresh_login() -> dict[str, Any]:
    """
    Force sign-in with saved credentials; persist replacement cookie.
    Does not clear the previous cookie until login succeeds.
    Returns a safe public dict (no secrets).
    """
    from app.tadoku.auth import TadokuAuthenticationError, login_and_get_cookie
    from app.tadoku.credentials import load_credentials

    global _login_retry_after

    username, password = load_credentials()
    if not username or not password:
        raise TadokuAuthenticationError(
            "Tadoku username and password are not configured"
        )

    with _login_lock:
        # Keep previous cookie file intact until new login succeeds
        try:
            new_cookie = login_and_get_cookie(username, password)
        except TadokuAuthenticationError:
            _login_retry_after = time.monotonic() + _LOGIN_FAILURE_COOLDOWN_SEC
            raise
        save_cookie(new_cookie)
        _login_retry_after = 0.0

    health = check_session(force=True)
    return {
        "authenticated": health.status == "ok" or (
            health.status in ("skipped", "disabled") and bool(resolve_cookie())
        ),
        **session_public_dict(force_check=False),
    }


@dataclass
class SessionHealth:
    """Safe (no secret) session status for UI / API."""

    status: str  # ok | missing | expired | error | skipped | disabled
    configured: bool
    source: str  # file | env | yaml | none
    checked_at: Optional[str] = None  # ISO UTC when we last probed
    detail: str = ""
    http_status: Optional[int] = None
    live_submit: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def invalidate_session_cache() -> None:
    global _cache, _cache_mono
    with _lock:
        _cache = None
        _cache_mono = 0.0


def mark_session_invalid(
    reason: str = "unauthorized",
    *,
    http_status: int = 401,
) -> SessionHealth:
    """Call when a live submit/API call returns 401/403 so UI updates immediately."""
    from datetime import datetime, timezone

    from app.tadoku.credentials import credentials_configured

    health = SessionHealth(
        status="expired",
        configured=bool(resolve_cookie()) or credentials_configured(),
        source=cookie_source(),
        checked_at=datetime.now(timezone.utc).isoformat(),
        detail=reason or "session rejected by tadoku.app",
        http_status=http_status,
        live_submit=bool(get_settings().yaml_config.tadoku.live_submit),
    )
    with _lock:
        global _cache, _cache_mono
        _cache = health
        _cache_mono = time.monotonic()
    logger.warning("tadoku session marked expired: %s", reason)
    return health


def _ttl_for(status: str) -> float:
    if status == "ok":
        return _CACHE_TTL_OK_SEC
    if status in ("expired", "error", "missing"):
        return _CACHE_TTL_BAD_SEC
    return _CACHE_TTL_OK_SEC


def get_cached_session_health() -> Optional[SessionHealth]:
    with _lock:
        if _cache is None:
            return None
        age = time.monotonic() - _cache_mono
        if age > _ttl_for(_cache.status):
            return None
        return _cache


def check_session(*, force: bool = False) -> SessionHealth:
    """
    Probe tadoku.app with the configured cookie.

    Cached to keep queue UI polls cheap. Use force=True after paste/refresh.
    Does not auto-login (avoids surprise network during settings polls).
    """
    from datetime import datetime, timezone

    from app.tadoku.credentials import credentials_configured

    settings = get_settings()
    cfg = settings.yaml_config.tadoku
    live = bool(cfg.live_submit)
    source = cookie_source()
    cookie = resolve_cookie()
    creds_ok = credentials_configured()
    now_iso = datetime.now(timezone.utc).isoformat()
    configured = bool(cookie) or creds_ok

    if not force:
        cached = get_cached_session_health()
        if cached is not None:
            if cached.configured == configured and cached.source == source:
                return cached

    if not live:
        health = SessionHealth(
            status="disabled",
            configured=configured,
            source=source,
            checked_at=now_iso,
            detail="live_submit is false (export-only)",
            live_submit=False,
        )
        _store_cache(health)
        return health

    if _live_submit_blocked():
        health = SessionHealth(
            status="skipped",
            configured=configured,
            source=source,
            checked_at=now_iso,
            detail="dry-run / test mode — live probe skipped",
            live_submit=live,
        )
        _store_cache(health)
        return health

    if not cookie:
        if creds_ok:
            health = SessionHealth(
                status="missing",
                configured=True,
                source="none",
                checked_at=now_iso,
                detail=(
                    "Credentials saved — session will be created on next sync "
                    "or use Refresh Tadoku login"
                ),
                live_submit=live,
            )
        else:
            health = SessionHealth(
                status="missing",
                configured=False,
                source="none",
                checked_at=now_iso,
                detail=(
                    "Save Tadoku username and password to enable live submit "
                    "(automatic sign-in)"
                ),
                live_submit=live,
            )
        _store_cache(health)
        return health

    api_base = (cfg.api_base or "https://tadoku.app/api/internal/immersion").rstrip("/")
    if api_base.endswith("/immersion"):
        api_base = api_base[:-len("/immersion")]
    url = f"{api_base}{_PROBE_PATH}"
    headers = {
        "Cookie": cookie,
        "Accept": "application/json",
        "Origin": "https://tadoku.app",
        "Referer": "https://tadoku.app/logs/new",
        "User-Agent": "immersion-tracker/session-check",
    }
    try:
        with httpx.Client(timeout=15.0, follow_redirects=False) as client:
            r = client.get(url, headers=headers)
        signed_out = False
        if r.status_code == 200:
            payload = r.json()
            if not isinstance(payload, dict) or "account" not in payload:
                raise ValueError("invalid identity session response")
            account = payload["account"]
            if account is not None and (not isinstance(account, dict) or not account.get("id")):
                raise ValueError("invalid identity session account")
            signed_out = account is None
        if r.status_code == 401 or signed_out:
            detail = "Session cookie rejected (expired)."
            if creds_ok:
                detail += " Will re-login automatically on next sync, or use Refresh Tadoku login."
            else:
                detail += " Save username/password so the app can sign in again."
            health = SessionHealth(
                status="expired",
                configured=True,
                source=source,
                checked_at=now_iso,
                detail=detail,
                http_status=r.status_code,
                live_submit=live,
            )
        elif r.status_code != 200:
            health = SessionHealth(
                status="error",
                configured=True,
                source=source,
                checked_at=now_iso,
                detail=f"Probe HTTP {r.status_code}",
                http_status=r.status_code,
                live_submit=live,
            )
        else:
            health = SessionHealth(
                status="ok",
                configured=True,
                source=source,
                checked_at=now_iso,
                detail="Session accepted by tadoku.app",
                http_status=r.status_code,
                live_submit=live,
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("tadoku session probe failed: %s", type(exc).__name__)
        health = SessionHealth(
            status="error",
            configured=True,
            source=source,
            checked_at=now_iso,
            detail=f"Probe failed: {type(exc).__name__}",
            live_submit=live,
        )

    _store_cache(health)
    return health


def _store_cache(health: SessionHealth) -> None:
    global _cache, _cache_mono
    with _lock:
        _cache = health
        _cache_mono = time.monotonic()


def session_public_dict(*, force_check: bool = False) -> dict[str, Any]:
    """Payload for /api/tadoku/settings (no secrets)."""
    from app.tadoku.credentials import credentials_public_dict

    health = check_session(force=force_check)
    return {
        "session_cookie_configured": bool(resolve_cookie()),
        "session_cookie_source": health.source,
        "session_status": health.status,
        "session_detail": health.detail,
        "session_checked_at": health.checked_at,
        "session_http_status": health.http_status,
        "session_file": str(cookie_file_path()),
        **credentials_public_dict(),
    }
