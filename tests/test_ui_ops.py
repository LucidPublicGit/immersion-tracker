"""UI ops: basic auth, undo-last, backup."""

from __future__ import annotations

import base64

from app.core.config import reload_settings


def _basic(user: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{user}:{password}".encode()).decode("ascii")
    return {"Authorization": f"Basic {token}"}


def test_undo_last_log(client):
    r = client.post(
        "/api/logs",
        json={
            "content_type": "anime",
            "title": "Undo Me",
            "amount": 24,
            "unit": "minutes",
            "source": "manual",
        },
    )
    assert r.status_code == 201
    log_id = r.json()["id"]

    u = client.post("/api/logs/undo-last")
    assert u.status_code == 200
    body = u.json()
    assert body["ok"] is True
    assert body["deleted"]["id"] == log_id
    assert body["deleted"]["title"] == "Undo Me"

    assert client.get(f"/api/logs/{log_id}").status_code == 404
    assert client.post("/api/logs/undo-last").status_code == 404


def test_backup_sqlite(client, tmp_path, monkeypatch):
    # client fixture already uses tmp sqlite
    r = client.get("/api/backup")
    assert r.status_code == 200
    assert r.headers.get("content-type", "").startswith("application/octet-stream")
    assert r.content[:16]  # non-empty sqlite header region
    assert r.content[:15] == b"SQLite format 3" or len(r.content) > 100


def test_ui_basic_auth(client, monkeypatch):
    monkeypatch.setenv("UI_PASSWORD", "s3cret")
    monkeypatch.setenv("UI_USERNAME", "admin")
    settings = reload_settings()
    settings.ui_password = "s3cret"
    settings.ui_username = "admin"

    assert client.get("/api/health").status_code == 200
    assert client.get("/").status_code == 401
    assert client.get("/api/logs").status_code == 401

    ok = client.get("/", headers=_basic("admin", "s3cret"))
    assert ok.status_code == 200

    bad = client.get("/", headers=_basic("admin", "wrong"))
    assert bad.status_code == 401

    # Webhooks stay open to secret-based clients (no basic required)
    wh = client.post(
        "/api/webhooks/youtube",
        json={
            "video_id": "authopenvid1",
            "title": "Auth Open",
            "channel_id": "UCxxxxxxxxxxxxxxxxxxxxxx",
            "channel_title": "Ch",
            "duration_seconds": 600,
            "watched_seconds": 600,
            "ratio": 1.0,
        },
    )
    # may 200 or filter reject; must not be basic-auth 401
    assert wh.status_code != 401
