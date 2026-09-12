"""HTTP smoke tests for new integration routes (webhooks + status)."""

from __future__ import annotations


def test_integrations_overview(client):
    r = client.get("/api/integrations")
    assert r.status_code == 200
    body = r.json()
    names = {p["name"] for p in body["poll"]}
    assert {"steam", "anki", "spotify", "mpv"} <= names
    wh = {w["name"] for w in body["webhooks"]}
    assert "asbplayer" in wh and "mpv" in wh


def test_steam_status_disabled(client):
    r = client.get("/api/steam/status")
    assert r.status_code == 200
    assert "enabled" in r.json()


def test_asbplayer_webhook_accepts(client):
    r = client.post(
        "/api/webhooks/asbplayer",
        json={
            "media_id": "ep-api-1",
            "title": "Test Show Ep1",
            "duration_seconds": 1400,
            "watched_seconds": 1350,
            "ratio": 0.96,
        },
    )
    assert r.status_code in (200, 201)
    body = r.json()
    assert body["accepted"] is True
    assert body["log_id"] is not None


def test_asbplayer_webhook_duplicate(client):
    payload = {
        "media_id": "ep-api-dup",
        "title": "Dup",
        "duration_seconds": 600,
        "watched_seconds": 600,
        "ratio": 1.0,
    }
    r1 = client.post("/api/webhooks/asbplayer", json=payload)
    r2 = client.post("/api/webhooks/asbplayer", json=payload)
    assert r1.json()["accepted"] is True
    assert r2.json()["accepted"] is False


def test_mpv_webhook_accepts(client):
    r = client.post(
        "/api/webhooks/mpv",
        json={
            "path": "D:/Anime/MyShow/S01E01.mkv",
            "title": "MyShow S01E01",
            "duration_seconds": 1440,
            "watched_seconds": 1400,
            "ratio": 0.97,
            "finished_at": "2026-07-30T12:00:00+00:00",
        },
    )
    assert r.status_code in (200, 201)
    body = r.json()
    assert body["accepted"] is True
