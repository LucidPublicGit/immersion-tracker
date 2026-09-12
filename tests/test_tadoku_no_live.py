"""Guarantees automated tests never POST to tadoku.app."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest


def test_live_submit_blocked_under_pytest():
    from app.tadoku.client import live_submit_blocked

    assert live_submit_blocked() is True


def test_client_forces_dry_run_even_with_cookie_and_live_submit(tmp_path, monkeypatch):
    """If cookie + live_submit leak into a test, client must still dry-run only."""
    from app.core.config import get_settings
    from app.db.models import LogEntry
    from app.tadoku.client import TadokuClient

    monkeypatch.setenv("TADOKU_COOKIE", "fake_session=would_post_if_live")
    settings = get_settings()
    settings.yaml_config.tadoku.live_submit = True
    settings.yaml_config.tadoku.session_cookie = "fake_session=would_post_if_live"

    # Bypass autouse __init__ patch: call real path via forced dry_run detection
    client = TadokuClient(export_dir=str(tmp_path / "exp"), dry_run=False)
    assert client.dry_run is True  # live_submit_blocked / safe_init forces this

    entry = LogEntry(
        content_type="youtube",
        title="pytest must not post this",
        amount=10,
        unit="minutes",
        activity="listening",
        language="ja",
        source="manual",
        timestamp=datetime.now(timezone.utc).replace(tzinfo=None),
    )

    posts: list = []

    class _BoomClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, *a, **k):
            posts.append((a, k))
            raise AssertionError("live HTTP post must not happen during tests")

        def get(self, *a, **k):
            posts.append((a, k))
            raise AssertionError("live HTTP get must not happen during tests")

    monkeypatch.setattr("app.tadoku.client.httpx.Client", _BoomClient)

    ok, remote_id, err = client.submit(entry)
    assert ok is True
    assert remote_id
    assert err is None
    assert posts == []
    assert list((tmp_path / "exp").glob("*.json"))


def test_approve_ready_youtube_never_hits_httpx(client, monkeypatch):
    """End-to-end: youtube pending → approve must not call tadoku.app."""
    posts: list = []

    class _BoomClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, *a, **k):
            posts.append(("post", a, k))
            raise AssertionError("live tadoku POST during test")

        def get(self, *a, **k):
            posts.append(("get", a, k))
            raise AssertionError("live tadoku GET during test")

    monkeypatch.setattr("app.tadoku.client.httpx.Client", _BoomClient)
    monkeypatch.setenv("TADOKU_COOKIE", "should_not_matter=1")
    from app.core.config import get_settings

    get_settings().yaml_config.tadoku.live_submit = True
    get_settings().yaml_config.tadoku.auto_submit_on_approve = True

    r = client.post(
        "/api/logs",
        json={
            "content_type": "youtube",
            "title": "pytest guard video",
            "amount": 5,
            "unit": "minutes",
            "source": "manual",
        },
    )
    assert r.status_code == 201
    body = r.json()
    log_id = body["id"]
    assert body["tadoku_status"] == "pending"
    # pending is not submitted by process_ready alone
    pr = client.post("/api/tadoku/process")
    assert pr.status_code == 200
    assert pr.json().get("pushed", 0) == 0
    assert posts == []

    ap = client.post(f"/api/logs/{log_id}/approve")
    assert ap.status_code == 200
    assert posts == []
