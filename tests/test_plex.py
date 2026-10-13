from __future__ import annotations

from datetime import datetime, timedelta, timezone


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


def test_plex_duplicate_within_week(client):
    payload = {
        "rating_key": "rk-dup",
        "title": "E03",
        "grandparent_title": "Dup Show",
        "library_name": "Anime",
        "media_type": "episode",
        "duration_ms": 1_440_000,
        "progress_percent": 95,
        "watched": True,
        "season_num": 1,
        "episode_num": 3,
    }
    first = client.post("/api/webhooks/plex", json=payload).json()
    assert first["accepted"] is True
    again = client.post("/api/webhooks/plex", json=payload).json()
    assert again == {"accepted": False, "reason": "duplicate", "log_id": first["log_id"]}


def test_plex_jellyfin_same_episode_deduped(client):
    plex = client.post(
        "/api/webhooks/plex",
        json={
            "rating_key": "rk-cross",
            "title": "E07",
            "grandparent_title": "Cross Show",
            "library_name": "Anime",
            "media_type": "episode",
            "duration_ms": 1_440_000,
            "progress_percent": 99,
            "watched": True,
            "season_num": 1,
            "episode_num": 7,
        },
    ).json()
    assert plex["accepted"] is True
    jelly = client.post(
        "/api/webhooks/jellyfin",
        json={
            "NotificationType": "PlaybackStop",
            "ItemId": "jf-cross",
            "Name": "E07",
            "SeriesName": "Cross Show",
            "LibraryName": "Anime",
            "ItemType": "Episode",
            "RunTimeTicks": 24 * 60 * 10_000_000,
            "PlayedToCompletion": True,
            "SeasonNumber": 1,
            "EpisodeNumber": 7,
        },
    ).json()
    assert jelly == {"accepted": False, "reason": "duplicate", "log_id": plex["log_id"]}


def test_plex_rewatch_after_week_allowed(client):
    from app.db.session import get_db
    from app.ingest.plex import PlexWatchEvent, ingest_plex_watch

    now = datetime.now(timezone.utc)
    event = PlexWatchEvent(
        rating_key="rk-week",
        title="E04",
        grandparent_title="Week Show",
        library_name="Anime",
        media_type="episode",
        duration_ms=1_440_000,
        progress_percent=95,
        watched=True,
        finished_at=now - timedelta(days=8),
        season_num=1,
        episode_num=4,
    )
    db = next(get_db())
    try:
        first = ingest_plex_watch(db, event)
        assert first.accepted is True
        later = event.model_copy(update={"finished_at": now})
        again = ingest_plex_watch(db, later)
        assert again.accepted is True
        assert again.log_id != first.log_id
    finally:
        db.close()
