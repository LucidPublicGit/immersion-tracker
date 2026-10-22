"""Tadoku identity sign-in and cookie-based API requests.

Reuse ``tadoku_session`` and retry an API request once after a 401. Credentials
and response bodies/cookies are never included in logs or public errors.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

AUTH_BASE_URL = "https://tadoku.app/api/internal/identity/"
IMMERSION_BASE_URL = "https://tadoku.app/api/internal/immersion/"
TIMEOUT_SECONDS = 20.0
SESSION_COOKIE_NAME = "tadoku_session"
TADOKU_ORIGIN = "https://tadoku.app"

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
    """Accept a raw token or extract the new cookie from a Cookie header.

    Named legacy/unknown cookies are rejected, never relabeled as new sessions.
    """
    text = (cookie_header or "").strip()
    if text.lower().startswith("cookie:"):
        text = text[7:].strip()
    if not text or any(ord(char) < 32 or ord(char) == 127 for char in text):
        return ""
    if "=" not in text and ";" not in text:
        return text
    for part in text.split(";"):
        name, sep, value = part.strip().partition("=")
        if sep and name.strip() == SESSION_COOKIE_NAME:
            return value.strip()
    return ""


def format_session_cookie_header(value: str) -> str:
    token = extract_session_cookie_value(value)
    return f"{SESSION_COOKIE_NAME}={token}" if token else ""


def _get_session_cookie_from_client(client: httpx.Client) -> str:
    for cookie in client.cookies.jar:
        if cookie.name == SESSION_COOKIE_NAME and cookie.value:
            return str(cookie.value)
    return ""


def _clear_session_cookie(client: httpx.Client) -> None:
    for cookie in list(client.cookies.jar):
        if cookie.name in (SESSION_COOKIE_NAME, "ory_kratos_session"):
            client.cookies.jar.clear(cookie.domain, cookie.path, cookie.name)


def _seed_session_cookie(client: httpx.Client, session_cookie: str) -> None:
    value = extract_session_cookie_value(session_cookie)
    if value:
        client.cookies.set(SESSION_COOKIE_NAME, value, domain=".tadoku.app", path="/")


class TadokuAuthClient:
    """Cookie-aware HTTP client for identity sign-in and immersion API calls."""

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
        # Preserve the public username argument; the identity API calls it email.
        self.username = (username or "").strip()
        self.password = password or ""
        if not self.username or not self.password:
            raise TadokuAuthenticationError(
                "Tadoku username and password are not configured"
            )
        self.auth_base = auth_base.rstrip("/") + "/"
        self.immersion_base = immersion_base.rstrip("/") + "/"
        self.timeout = timeout
        self.client = httpx.Client(
            timeout=timeout,
            follow_redirects=False,
            headers={
                "User-Agent": "immersion-tracker/tadoku-auth",
                "Accept": "application/json",
            },
        )
        _seed_session_cookie(self.client, session_cookie)

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> "TadokuAuthClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def has_session_cookie(self) -> bool:
        return bool(_get_session_cookie_from_client(self.client))

    def session_cookie_header(self) -> str:
        return format_session_cookie_header(_get_session_cookie_from_client(self.client))

    def _clear_session_cookie(self) -> None:
        _clear_session_cookie(self.client)

    def login(self) -> str:
        """Sign in once with JSON and return the new session Cookie header."""
        if live_auth_blocked():
            raise TadokuAuthenticationError(
                "Tadoku live authentication is blocked in test/dry-run mode"
            )
        # An old cookie must not make a cookie-less login response look successful.
        self._clear_session_cookie()
        try:
            response = self.client.post(
                f"{self.auth_base}login",
                json={"email": self.username, "password": self.password},
                headers={
                    "Content-Type": "application/json",
                    "Origin": TADOKU_ORIGIN,
                },
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("tadoku login request failed: %s", type(exc).__name__)
            raise TadokuAuthenticationError(
                "Tadoku login request failed; check network connectivity"
            ) from None

        if response.status_code != 200:
            self._clear_session_cookie()
            messages = {
                401: "Tadoku login failed; check the saved email and password",
                403: "Tadoku login failed; sign-in origin was rejected",
                429: "Tadoku login is rate limited; wait 15 minutes before trying again",
                503: "Tadoku sign-in is temporarily unavailable; try again later",
            }
            raise TadokuAuthenticationError(messages.get(
                response.status_code, "Tadoku login failed; try again later"
            ))
        if not self.has_session_cookie():
            raise TadokuAuthenticationError(
                "Tadoku login did not return a tadoku_session cookie"
            )
        logger.info("tadoku login succeeded (session cookie obtained)")
        return self.session_cookie_header()

    def refresh_session(self) -> str:
        """Force sign-in even if a prior cookie is present."""
        return self.login()

    def request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        """Immersion API request with automatic login and one 401 retry."""
        if not self.has_session_cookie():
            self.login()
        url = f"{self.immersion_base}{path.lstrip('/')}"
        headers = dict(kwargs.pop("headers", None) or {})
        headers.setdefault("Origin", TADOKU_ORIGIN)
        headers.setdefault("Referer", "https://tadoku.app/logs/new")
        response = self.client.request(method, url, headers=headers, **kwargs)
        if response.status_code == 401:
            self.login()
            response = self.client.request(method, url, headers=headers, **kwargs)
        return response


def login_and_get_cookie(username: str, password: str) -> str:
    """Sign in and return a session Cookie header string."""
    with TadokuAuthClient(username, password) as auth:
        return auth.login()


def ensure_session_cookie(
    *,
    force_login: bool = False,
    existing_cookie: Optional[str] = None,
) -> str:
    """Reuse a new session cookie, otherwise sign in with saved credentials."""
    cookie = format_session_cookie_header(existing_cookie or "")
    if cookie and not force_login:
        return cookie

    from app.tadoku.credentials import load_credentials

    username, password = load_credentials()
    if not username or not password:
        raise TadokuAuthenticationError(
            "Tadoku username and password are not configured"
        )
    return login_and_get_cookie(username, password)
