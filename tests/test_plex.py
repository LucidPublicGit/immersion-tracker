from __future__ import annotations


def test_plex_below_threshold(client):
    r = client.post(
        "/api/webhooks/plex",
        json={
            "rating_key": "rk1",
            "title": "E01",
            "grandparent_title": "Anime X",
            "library_name": "Anime",
            "media_type": "episode",
            "duration_ms": 1_440_000,
            "progress_percent": 50,
            "watched": False,
        },
    )
    assert r.json()["accepted"] is False


def test_plex_watched_logs_pending(client):
    r = client.post(
        "/api/webhooks/plex",
        json={
            "rating_key": "rk2",
            "title": "E02",
            "grandparent_title": "Anime X",
            "library_name": "Anime",
            "media_type": "episode",
            "duration_ms": 1_440_000,
            "progress_percent": 95,
            "watched": True,
        },
    )
    body = r.json()
    assert body["accepted"] is True
    log = client.get(f"/api/logs/{body['log_id']}").json()
    assert log["content_type"] == "anime"
    assert log["tadoku_status"] == "pending"
    assert log["amount"] == 24.0
