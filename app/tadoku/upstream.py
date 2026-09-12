"""
Public tadoku.app URLs and API paths this app depends on.

UI links and live contract probes (tests/test_tadoku_upstream.py) share these
helpers so path drift is caught in one place.

Rules:
  - GET-only probes in tests (never POST /logs from the suite).
  - Bare /contests/{id} currently 404s on tadoku.app; use leaderboard page.
"""

from __future__ import annotations

from typing import Any

TADOKU_ORIGIN = "https://tadoku.app"
DEFAULT_API_BASE = f"{TADOKU_ORIGIN}/api/internal/immersion"
ACCOUNT_ORIGIN = "https://account.tadoku.app"


def manual_log_url() -> str:
    """Manual log form (browser)."""
    return f"{TADOKU_ORIGIN}/logs/new"


def log_page_url(remote_id: str) -> str | None:
    """
    Browser page for a single submitted log on tadoku.app.

    Remote IDs are UUIDs returned by POST /api/internal/immersion/logs.
    Dry-run export-* / claim submitting:* IDs are not real pages → None.
    """
    rid = (remote_id or "").strip()
    if not rid:
        return None
    # UUID shape only (live API response id)
    if len(rid) != 36 or rid.count("-") != 4:
        return None
    for part in rid.split("-"):
        if not part or any(c not in "0123456789abcdefABCDEF" for c in part):
            return None
    return f"{TADOKU_ORIGIN}/logs/{rid}"


def contest_leaderboard_page_url(contest_id: str, *, page: int = 1) -> str:
    """
    Public contest leaderboard HTML page.

    tadoku.app serves this under /contests/{id}/leaderboard/{page};
    bare /contests/{id} returns 404 (as of 2026-07).
    """
    cid = (contest_id or "").strip()
    if not cid:
        return TADOKU_ORIGIN
    return f"{TADOKU_ORIGIN}/contests/{cid}/leaderboard/{int(page)}"


def contest_bare_page_url(contest_id: str) -> str:
    """Bare contest path — historically linked; currently 404 on tadoku.app."""
    cid = (contest_id or "").strip()
    if not cid:
        return TADOKU_ORIGIN
    return f"{TADOKU_ORIGIN}/contests/{cid}"


def api_contest_meta_path(contest_id: str) -> str:
    return f"/contests/{contest_id}"


def api_contest_summary_path(contest_id: str) -> str:
    return f"/contests/{contest_id}/summary"


def api_contest_leaderboard_path(contest_id: str) -> str:
    return f"/contests/{contest_id}/leaderboard"


def api_user_activity_path(contest_id: str, user_id: str) -> str:
    return f"/contests/{contest_id}/profile/{user_id}/activity"


def api_configuration_options_path() -> str:
    """Auth-gated: unit/activity IDs for live submit."""
    return "/logs/configuration-options"


def api_ongoing_registrations_path() -> str:
    """Auth-gated: session probe + registration_id discovery."""
    return "/contests/ongoing-registrations"


def kratos_login_browser_url() -> str:
    """Ory Kratos browser login bootstrap (auth flow)."""
    return f"{ACCOUNT_ORIGIN}/kratos/self-service/login/browser"


def join_api(api_base: str, path: str) -> str:
    base = (api_base or DEFAULT_API_BASE).rstrip("/")
    if not path.startswith("/"):
        path = "/" + path
    return base + path


# Expected JSON keys for public contract checks (minimal, stable fields).
PUBLIC_API_CONTRACTS: list[dict[str, Any]] = [
    {
        "name": "contest_meta",
        "path_fn": "api_contest_meta_path",
        "needs_contest": True,
        "required_keys": ("id", "title", "contest_start", "contest_end"),
    },
    {
        "name": "contest_summary",
        "path_fn": "api_contest_summary_path",
        "needs_contest": True,
        "required_keys": ("participant_count", "total_score"),
    },
    {
        "name": "contest_leaderboard",
        "path_fn": "api_contest_leaderboard_path",
        "needs_contest": True,
        "query": {"page": 0, "page_size": 5},
        "required_keys": ("entries",),
        "entry_keys": ("rank", "score", "user_id", "user_display_name"),
    },
]
