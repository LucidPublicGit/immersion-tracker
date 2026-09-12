"""
Tadoku browser (Ory Kratos) username/password login.

Immersion API requires the browser `ory_kratos_session` cookie — the native
Kratos session_token is NOT accepted. This module performs the browser login
flow, extracts the session cookie, and supports one-shot 401 relogin.

Secrets (password, CSRF, session cookie values) are never logged.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

AUTH_BASE_URL = "https://account.tadoku.app/kratos/"
IMMERSION_BASE_URL = "https://tadoku.app/api/internal/immersion/"
LOGIN_ACTION_PREFIX = f"{AUTH_BASE_URL}self-service/login?"
TIMEOUT_SECONDS = 20.0
SESSION_COOKIE_NAME = "ory_kratos_session"

_TRUTHY = frozenset({"1", "true", "yes", "on"})


class TadokuAuthenticationError(RuntimeError):
    """Safe auth error for callers/UI (no secrets)."""


def live_auth_blocked() -> bool:
    """Same guards as TadokuClient — no live network during tests/dry-run."""
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return True
    flag = os.environ.get("IMMERSION_TADOKU_DRY_RUN", "").strip().lower()
    return flag in _TRUTHY


def extract_session_cookie_value(cookie_header: str) -> str:
    """
    Pull ory_kratos_session value from a Cookie header string.
    Accepts raw token or `name=value; other=...`.
    """
    text = (cookie_header or "").strip()
    if text.lower().startswith("cookie:"):
        text = text[7:].strip()
    if not text:
        return ""
    # Already just the token (no '=') — rare but allow
    if "=" not in text and ";" not in text:
        return text
    for part in text.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, _, value = part.partition("=")
        if name.strip() == SESSION_COOKIE_NAME:
            return value.strip()
    return ""


def format_session_cookie_header(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    if value.startswith(f"{SESSION_COOKIE_NAME}="):
        return value
    return f"{SESSION_COOKIE_NAME}={value}"


def _cookie_jar_has_session(client: httpx.Client) -> bool:
    for cookie in client.cookies.jar:
        if cookie.name == SESSION_COOKIE_NAME and cookie.value:
            return True
    return False


def _get_session_cookie_from_client(client: httpx.Client) -> str:
    for cookie in client.cookies.jar:
        if cookie.name == SESSION_COOKIE_NAME and cookie.value:
            return str(cookie.value)
    return ""


def _clear_session_cookie(client: httpx.Client) -> None:
    # httpx Cookies: clear by rebuilding without the session cookie
    to_keep: list[tuple[str, str]] = []
    for cookie in list(client.cookies.jar):
        if cookie.name != SESSION_COOKIE_NAME:
            to_keep.append((cookie.name, cookie.value))
    client.cookies.clear()
    for name, value in to_keep:
        client.cookies.set(name, value)


def _seed_session_cookie(client: httpx.Client, session_cookie: str) -> None:
    value = extract_session_cookie_value(session_cookie)
    if not value:
        # Maybe the whole string is already name=value for multiple cookies
        raw = (session_cookie or "").strip()
        if raw.lower().startswith("cookie:"):
            raw = raw[7:].strip()
        if raw and SESSION_COOKIE_NAME not in raw and "=" not in raw:
            value = raw
        elif raw:
            # Seed full cookie header pieces when possible
            for part in raw.split(";"):
                part = part.strip()
                if "=" not in part:
                    continue
                name, _, val = part.partition("=")
                name = name.strip()
                val = val.strip()
                if name and val:
                    client.cookies.set(name, val, domain=".tadoku.app", path="/")
            return
    if value:
        client.cookies.set(
            SESSION_COOKIE_NAME,
            value,
            domain=".tadoku.app",
            path="/",
        )


def _extract_csrf_token(ui: dict[str, Any]) -> str:
    for node in ui.get("nodes") or []:
        attrs = (node or {}).get("attributes") or {}
        if attrs.get("name") == "csrf_token":
            return str(attrs.get("value") or "")
    return ""


def _validate_login_action(action: str) -> str:
    action = str(action or "").strip()
    if not action.startswith(LOGIN_ACTION_PREFIX):
        raise TadokuAuthenticationError("Tadoku returned an invalid login flow")
    # Extra host check against open redirect / credential exfiltration
    parsed = urlparse(action)
    if parsed.scheme != "https" or parsed.netloc != "account.tadoku.app":
        raise TadokuAuthenticationError("Tadoku returned an invalid login flow")
    return action


class TadokuAuthClient:
    """
    Cookie-aware HTTP client for Tadoku browser login + immersion API calls.
    """

    def __init__(
        self,
        username: str,
        password: str,
        session_cookie: str = "",
        *,
        auth_base: str = AUTH_BASE_URL,
        immersion_base: str = IMMERSION_BASE_URL,
        timeout: float = TIMEOUT_SECONDS,
    ):
        self.username = (username or "").strip()
        self.password = password or ""
        self.auth_base = auth_base if auth_base.endswith("/") else auth_base + "/"
        self.immersion_base = (
            immersion_base if immersion_base.endswith("/") else immersion_base + "/"
        )
        self.timeout = timeout
        self.client = httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={
                "User-Agent": "immersion-tracker/tadoku-auth",
                "Accept": "application/json",
            },
        )
        if session_cookie:
            _seed_session_cookie(self.client, session_cookie)

        if not self.username or not self.password:
            raise TadokuAuthenticationError(
                "Tadoku username and password are not configured"
            )

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> "TadokuAuthClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def has_session_cookie(self) -> bool:
        return _cookie_jar_has_session(self.client)

    def session_cookie_header(self) -> str:
        value = _get_session_cookie_from_client(self.client)
        return format_session_cookie_header(value)

    def _clear_session_cookie(self) -> None:
        _clear_session_cookie(self.client)

    def login(self) -> str:
        """
        Perform browser login flow. Returns Cookie header string for persistence.
        Does not log credentials or the session value.
        """
        if live_auth_blocked():
            raise TadokuAuthenticationError(
                "Tadoku live authentication is blocked in test/dry-run mode"
            )

        try:
            flow_response = self.client.get(
                f"{self.auth_base}self-service/login/browser",
                headers={"Accept": "application/json"},
            )
            flow_response.raise_for_status()
            flow = flow_response.json()
        except TadokuAuthenticationError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("tadoku login flow start failed: %s", type(exc).__name__)
            raise TadokuAuthenticationError(
                "Could not start Tadoku login; check network connectivity"
            ) from exc

        ui = flow.get("ui") or {}
        action = _validate_login_action(str(ui.get("action") or ""))
        csrf_token = _extract_csrf_token(ui)
        if not csrf_token:
            raise TadokuAuthenticationError("Tadoku did not return a CSRF token")

        try:
            login_response = self.client.post(
                action,
                data={
                    "identifier": self.username,
                    "password": self.password,
                    "method": "password",
                    "csrf_token": csrf_token,
                },
                headers={"Accept": "application/json"},
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("tadoku login submit failed: %s", type(exc).__name__)
            raise TadokuAuthenticationError(
                "Tadoku login request failed; check network connectivity"
            ) from exc

        if not login_response.is_success:
            # Generic message — do not include body (may echo identifier)
            raise TadokuAuthenticationError(
                "Tadoku login failed; check the saved username and password"
            )
        if not self.has_session_cookie():
            raise TadokuAuthenticationError(
                "Tadoku login did not return a browser session cookie"
            )

        header = self.session_cookie_header()
        logger.info("tadoku browser login succeeded (session cookie obtained)")
        return header

    def refresh_session(self) -> str:
        """Force a full browser login even if a prior cookie is present."""
        self._clear_session_cookie()
        return self.login()

    def request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        """
        Immersion API request with automatic login / one-shot 401 retry.
        """
        if not self.has_session_cookie():
            self.login()

        url = f"{self.immersion_base}{path.lstrip('/')}"
        headers = dict(kwargs.pop("headers", None) or {})
        headers.setdefault("Origin", "https://tadoku.app")
        headers.setdefault("Referer", "https://tadoku.app/logs/new")

        response = self.client.request(method, url, headers=headers, **kwargs)
        if response.status_code == 401:
            self._clear_session_cookie()
            self.login()
            response = self.client.request(method, url, headers=headers, **kwargs)
        return response


def login_and_get_cookie(username: str, password: str) -> str:
    """Convenience: browser login → session Cookie header string."""
    with TadokuAuthClient(username, password, session_cookie="") as auth:
        return auth.login()


def ensure_session_cookie(
    *,
    force_login: bool = False,
    existing_cookie: Optional[str] = None,
) -> str:
    """
    Ensure a usable session cookie is available.

    Loads credentials from the secure store. When force_login is False and
    existing_cookie is non-empty, returns it without contacting Tadoku.
    When force_login is True, always performs browser login.
    """
    from app.tadoku.credentials import load_credentials

    username, password = load_credentials()
    if not username or not password:
        raise TadokuAuthenticationError(
            "Tadoku username and password are not configured"
        )

    cookie = (existing_cookie or "").strip()
    if cookie and not force_login:
        return cookie

    return login_and_get_cookie(username, password)
