"""
Live contract checks for tadoku.app URLs/APIs this project depends on.

These are GET-only (never POST /logs). They run in the normal pytest suite so
path/API drift (e.g. contest page 404) fails with a clear error.

If tadoku.app is unreachable, tests are skipped (not failed).

Optional auth-gated probes run when a session cookie is available via:
  IMMERSION_TADOKU_UPSTREAM_COOKIE=ory_kratos_session=...
or data/tadoku_session.cookie (local Docker volume). Without a cookie those
probes skip with a warning.

Run only this module:
  python -m pytest tests/test_tadoku_upstream.py -q
"""

from __future__ import annotations

import os
import warnings
from pathlib import Path
from typing import Any, Optional

import httpx
import pytest

from app.tadoku import upstream as up

# Keep probes polite and CI-friendly
_TIMEOUT = 20.0
_UA = "immersion-tracker/upstream-check"
_HEADERS = {
    "Accept": "application/json, text/html;q=0.9,*/*;q=0.8",
    "Origin": up.TADOKU_ORIGIN,
    "Referer": f"{up.TADOKU_ORIGIN}/",
    "User-Agent": _UA,
}


def _contest_id() -> str:
    """Prefer live settings; fall back to example Deep Weeb Club 2026 UUID."""
    try:
        from app.core.config import get_settings

        cid = (get_settings().yaml_config.tadoku.contest.contest_id or "").strip()
        if cid:
            return cid
    except Exception:  # noqa: BLE001
        pass
    return "00000000-0000-0000-0000-000000000001"


def _api_base() -> str:
    try:
        from app.core.config import get_settings

        return (
            get_settings().yaml_config.tadoku.api_base or up.DEFAULT_API_BASE
        ).rstrip("/")
    except Exception:  # noqa: BLE001
        return up.DEFAULT_API_BASE


def _get(
    url: str,
    *,
    headers: Optional[dict[str, str]] = None,
    params: Optional[dict[str, Any]] = None,
    accept_statuses: tuple[int, ...] = (200,),
) -> httpx.Response:
    hdrs = dict(_HEADERS)
    if headers:
        hdrs.update(headers)
    try:
        r = httpx.get(
            url,
            headers=hdrs,
            params=params,
            timeout=_TIMEOUT,
            follow_redirects=True,
        )
    except httpx.TransportError as e:
        pytest.skip(f"tadoku.app unreachable ({url}): {e}")
    if r.status_code not in accept_statuses:
        body = (r.text or "")[:400].replace("\n", " ")
        pytest.fail(
            f"tadoku upstream broken: GET {url} → HTTP {r.status_code}\n"
            f"body: {body}"
        )
    return r


def _optional_session_cookie() -> str:
    """Cookie for auth-gated GETs (never used to POST)."""
    env = (os.environ.get("IMMERSION_TADOKU_UPSTREAM_COOKIE") or "").strip()
    if env:
        return env if "=" in env else f"ory_kratos_session={env}"
    for p in (
        Path("data/tadoku_session.cookie"),
        Path("/app/data/tadoku_session.cookie"),
    ):
        if p.is_file():
            raw = p.read_text(encoding="utf-8").strip()
            if raw:
                return raw if "=" in raw else f"ory_kratos_session={raw}"
    return ""


# ---------------------------------------------------------------------------
# Local (no network): URL builders + UI wiring
# ---------------------------------------------------------------------------


def test_leaderboard_page_url_shape():
    cid = "00000000-0000-0000-0000-000000000001"
    url = up.contest_leaderboard_page_url(cid)
    assert url == f"https://tadoku.app/contests/{cid}/leaderboard/1"
    assert "/leaderboard/" in url
    assert up.contest_bare_page_url(cid).endswith(cid)
    assert not up.contest_bare_page_url(cid).endswith("/leaderboard/1")


def test_log_page_url_shape():
    rid = "b68676fa-4446-45ef-87fa-12577659ebe5"
    assert up.log_page_url(rid) == f"https://tadoku.app/logs/{rid}"
    assert up.log_page_url("export-abc123") is None
    assert up.log_page_url("submitting:deadbeef") is None
    assert up.log_page_url("") is None
    assert up.log_page_url(None) is None  # type: ignore[arg-type]
    assert up.log_page_url("  ") is None


def test_tool_urls_use_leaderboard_page(client):
    """UI must link to the live leaderboard path, not the bare contest 404."""
    from app.web.pages import _tool_urls

    urls = _tool_urls()
    cid = _contest_id()
    assert urls["tadoku_contest"] == up.contest_leaderboard_page_url(cid)
    assert urls["tadoku_club"] == urls["tadoku_contest"]
    assert urls["tadoku_manual"] == up.manual_log_url()
    # Served HTML also carries the path
    home = client.get("/")
    assert home.status_code == 200
    assert b"/leaderboard/1" in home.content


# ---------------------------------------------------------------------------
# Live public pages
# ---------------------------------------------------------------------------


@pytest.mark.tadoku_upstream
def test_live_manual_log_page_reachable():
    r = _get(up.manual_log_url(), accept_statuses=(200,))
    # SPA shell; just require HTML, not a Next.js 404 page
    text = r.text.lower()
    assert "<!doctype html" in text or "<html" in text
    assert "this page could not be found" not in text


@pytest.mark.tadoku_upstream
def test_live_contest_leaderboard_page_reachable():
    cid = _contest_id()
    url = up.contest_leaderboard_page_url(cid)
    r = _get(url, accept_statuses=(200,))
    text = r.text.lower()
    assert "this page could not be found" not in text, (
        f"Leaderboard page 404 for configured contest_id={cid}\n"
        f"url={url}\n"
        "Update tadoku.contest.contest_id if the club moved to a new contest."
    )


@pytest.mark.tadoku_upstream
def test_live_bare_contest_page_documents_current_behavior():
    """
    Bare /contests/{id} currently 404s; UI must not rely on it.

    If tadoku restores the bare page (200), we only warn — leaderboard path
    remains the supported link.
    """
    cid = _contest_id()
    url = up.contest_bare_page_url(cid)
    try:
        r = httpx.get(
            url,
            headers=_HEADERS,
            timeout=_TIMEOUT,
            follow_redirects=True,
        )
    except httpx.TransportError as e:
        pytest.skip(f"tadoku.app unreachable: {e}")

    if r.status_code == 404:
        return  # expected as of 2026-07
    if r.status_code == 200 and "this page could not be found" not in r.text.lower():
        warnings.warn(
            f"Bare contest URL works again (HTTP 200): {url}. "
            "Links can stay on /leaderboard/1; optional simplification.",
            UserWarning,
            stacklevel=1,
        )
        return
    warnings.warn(
        f"Unexpected bare contest page status HTTP {r.status_code} for {url}",
        UserWarning,
        stacklevel=1,
    )


# ---------------------------------------------------------------------------
# Live public immersion API (no auth)
# ---------------------------------------------------------------------------


@pytest.mark.tadoku_upstream
def test_live_api_contest_meta():
    cid = _contest_id()
    url = up.join_api(_api_base(), up.api_contest_meta_path(cid))
    r = _get(url)
    data = r.json()
    for key in ("id", "title", "contest_start", "contest_end"):
        assert key in data, f"contest meta missing '{key}': keys={list(data)[:20]}"
    assert data["id"] == cid
    title = data.get("title") or ""
    assert title.strip(), "contest meta title empty — wrong contest_id?"


@pytest.mark.tadoku_upstream
def test_live_api_contest_summary():
    cid = _contest_id()
    url = up.join_api(_api_base(), up.api_contest_summary_path(cid))
    r = _get(url)
    data = r.json()
    assert "participant_count" in data
    assert "total_score" in data
    assert int(data["participant_count"]) >= 1


@pytest.mark.tadoku_upstream
def test_live_api_contest_leaderboard():
    cid = _contest_id()
    url = up.join_api(_api_base(), up.api_contest_leaderboard_path(cid))
    r = _get(url, params={"page": 0, "page_size": 5})
    data = r.json()
    assert "entries" in data, f"leaderboard missing entries: {list(data)[:20]}"
    entries = data["entries"]
    assert isinstance(entries, list) and len(entries) >= 1, (
        f"empty leaderboard for contest_id={cid} — contest ended or id wrong?"
    )
    row = entries[0]
    for key in ("rank", "score", "user_id", "user_display_name"):
        assert key in row, f"leaderboard entry missing '{key}': {row!r}"


@pytest.mark.tadoku_upstream
def test_live_api_user_activity():
    """Activity series used by contest momentum cache."""
    cid = _contest_id()
    lb_url = up.join_api(_api_base(), up.api_contest_leaderboard_path(cid))
    lb = _get(lb_url, params={"page": 0, "page_size": 1}).json()
    entries = lb.get("entries") or []
    if not entries:
        pytest.fail(f"no leaderboard entries to probe activity (contest={cid})")
    uid = entries[0]["user_id"]
    act_url = up.join_api(_api_base(), up.api_user_activity_path(cid, uid))
    r = _get(act_url)
    data = r.json()
    assert "rows" in data, f"activity missing 'rows': {list(data)[:20]}"
    assert isinstance(data["rows"], list)


@pytest.mark.tadoku_upstream
def test_live_kratos_login_browser_reachable():
    """Auth bootstrap endpoint used by app.tadoku.auth."""
    r = _get(
        up.kratos_login_browser_url(),
        accept_statuses=(200, 303, 422),  # Kratos may return flow JSON or redirect
    )
    # 422 can still mean "flow created" depending on Accept; 200 with flow id is ideal
    if r.status_code == 200:
        try:
            data = r.json()
            assert "id" in data or "ui" in data or "error" in data
        except ValueError:
            # HTML login page is also fine
            assert len(r.content) > 100


# ---------------------------------------------------------------------------
# Auth-gated API (optional)
# ---------------------------------------------------------------------------


@pytest.mark.tadoku_upstream
def test_live_api_configuration_options_when_cookie():
    cookie = _optional_session_cookie()
    if not cookie:
        warnings.warn(
            "Skipping auth-gated configuration-options probe "
            "(set IMMERSION_TADOKU_UPSTREAM_COOKIE or data/tadoku_session.cookie)",
            UserWarning,
            stacklevel=1,
        )
        pytest.skip("no Tadoku session cookie for auth-gated probe")

    url = up.join_api(_api_base(), up.api_configuration_options_path())
    r = _get(url, headers={"Cookie": cookie}, accept_statuses=(200, 401, 403))
    if r.status_code in (401, 403):
        warnings.warn(
            f"configuration-options rejected cookie (HTTP {r.status_code}) — "
            "session may be expired; Queue UI → Refresh Tadoku login",
            UserWarning,
            stacklevel=1,
        )
        pytest.fail(
            "Auth-gated configuration-options failed with configured session cookie. "
            "Live submit will fail until login is refreshed."
        )
    data = r.json()
    assert "units" in data or "activities" in data, (
        f"configuration-options unexpected shape: {list(data)[:30]}"
    )


@pytest.mark.tadoku_upstream
def test_live_api_ongoing_registrations_when_cookie():
    cookie = _optional_session_cookie()
    if not cookie:
        warnings.warn(
            "Skipping auth-gated ongoing-registrations probe "
            "(set IMMERSION_TADOKU_UPSTREAM_COOKIE or data/tadoku_session.cookie)",
            UserWarning,
            stacklevel=1,
        )
        pytest.skip("no Tadoku session cookie for auth-gated probe")

    url = up.join_api(_api_base(), up.api_ongoing_registrations_path())
    r = _get(url, headers={"Cookie": cookie}, accept_statuses=(200, 401, 403))
    if r.status_code in (401, 403):
        warnings.warn(
            f"ongoing-registrations rejected cookie (HTTP {r.status_code})",
            UserWarning,
            stacklevel=1,
        )
        pytest.fail(
            "Auth-gated ongoing-registrations failed with configured session cookie. "
            "Session probe / registration_id discovery will break."
        )
    # Response is typically a list or object with registrations
    data = r.json()
    assert data is not None
