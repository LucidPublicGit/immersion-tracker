from __future__ import annotations

import base64
import secrets
from typing import Optional

from fastapi import Header, HTTPException, Query, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response

from app.core.config import get_settings


def verify_webhook_secret(
    x_webhook_secret: str | None = Header(default=None),
    secret: Optional[str] = Query(
        default=None,
        description="Same as X-Webhook-Secret; query form is easier for Tautulli webhooks",
    ),
) -> None:
    expected = get_settings().webhook_secret
    if not expected:
        # Dev mode: open webhooks when no secret configured
        return
    provided = x_webhook_secret or secret
    if not provided or provided != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing webhook secret (header X-Webhook-Secret or ?secret=)",
        )


def _const_eq(a: str, b: str) -> bool:
    aa, bb = a.encode("utf-8"), b.encode("utf-8")
    if len(aa) != len(bb):
        return False
    return secrets.compare_digest(aa, bb)


def _ui_auth_open_path(path: str) -> bool:
    """Paths that skip UI basic auth (webhooks/extension use WEBHOOK_SECRET)."""
    if path == "/api/health":
        return True
    if path.startswith("/api/webhooks/"):
        return True
    if path.startswith("/api/youtube/"):
        return True
    if path.startswith("/static/") or path.startswith("/media-cache/"):
        return True
    return False


class UiBasicAuthMiddleware(BaseHTTPMiddleware):
    """Optional HTTP Basic Auth when Settings.ui_password is set."""

    async def dispatch(self, request: Request, call_next) -> Response:
        settings = get_settings()
        password = (settings.ui_password or "").strip()
        if not password:
            return await call_next(request)

        path = request.url.path or "/"
        if _ui_auth_open_path(path):
            return await call_next(request)

        username = (settings.ui_username or "admin").strip() or "admin"
        header = request.headers.get("authorization") or ""
        if header.lower().startswith("basic "):
            try:
                raw = base64.b64decode(header.split(" ", 1)[1].strip()).decode("utf-8")
                user, _, pw = raw.partition(":")
                if _const_eq(user, username) and _const_eq(pw, password):
                    return await call_next(request)
            except Exception:  # noqa: BLE001
                pass

        return PlainTextResponse(
            "Unauthorized",
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="Immersion Tracker"'},
        )
