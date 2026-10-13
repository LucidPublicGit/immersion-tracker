from __future__ import annotations

import io
import json

import pytest

# 24 minutes in .NET ticks
EP_TICKS = 24 * 60 * 10_000_000


def test_jellyfin_below_threshold(client):
    r = client.post(
        "/api/webhooks/jellyfin",
        json={
            "NotificationType": "PlaybackStop",
            "ItemId": "jf1",
            "Name": "E01",
            "SeriesName": "Anime X",
            "LibraryName": "Anime",
            "ItemType": "Episode",
            "RunTimeTicks": EP_TICKS,
            "PlaybackPositionTicks": int(EP_TICKS * 0.5),
            "PlayedToCompletion": False,
        },
    )
    assert r.json()["accepted"] is False


def test_jellyfin_playback_stop_logs(client):
    r = client.post(
        "/api/webhooks/jellyfin",
        json={
            "NotificationType": "PlaybackStop",
            "ItemId": "jf2",
            "Name": "E02",
            "SeriesName": "Anime X",
            "LibraryName": "Anime",
            "ItemType": "Episode",
            "RunTimeTicks": EP_TICKS,
            "PlaybackPositionTicks": int(EP_TICKS * 0.95),
            "PlayedToCompletion": True,
            "SeasonNumber": 1,
            "EpisodeNumber": 2,
        },
    )
    body = r.json()
    assert body["accepted"] is True
    log = client.get(f"/api/logs/{body['log_id']}").json()
    assert log["content_type"] == "anime"
    assert log["source"] == "jellyfin"
    assert log["tadoku_mode"] == "auto"
    assert log["tadoku_status"] == "ready"
    assert log["amount"] == 24.0
    assert log["season"] == 1
    assert log["episode"] == 2


def test_jellyfin_movie_drops_index(client):
    r = client.post(
        "/api/webhooks/jellyfin",
        json={
            "NotificationType": "PlaybackStop",
            "ItemId": "jf-movie",
            "Name": "Die Hard",
            "LibraryName": "Movies",
            "ItemType": "Movie",
            "RunTimeTicks": 90 * 60 * 10_000_000,
            "PlayedToCompletion": True,
            "SeasonNumber": 0,
            "EpisodeNumber": 0,
        },
    )
    body = r.json()
    assert body["accepted"] is True
    log = client.get(f"/api/logs/{body['log_id']}").json()
    assert log["season"] is None
    assert log["episode"] is None
    assert log["tadoku_status"] == "pending"


def test_jellyfin_ignores_item_added(client):
    r = client.post(
        "/api/webhooks/jellyfin",
        json={
            "NotificationType": "ItemAdded",
            "ItemId": "jf-lib",
            "Name": "E99",
            "SeriesName": "Anime X",
            "LibraryName": "Anime",
            "ItemType": "Episode",
            "PlayedToCompletion": True,
        },
    )
    assert r.json()["accepted"] is False
    assert "ignored_event" in r.json()["reason"]


@pytest.mark.parametrize(
    ("library", "folder", "language"),
    [("JPDrama", "drama", "ja"), ("Shows", "tv", "en")],
)
def test_jellyfin_resolves_library_from_item_path(client, monkeypatch, library, folder, language):
    from app.core.config import get_settings

    settings = get_settings()
    settings.jellyfin_url = "http://jellyfin:8096"
    settings.jellyfin_api_key = "test-key"
    settings.yaml_config.jellyfin.library_map[library] = "show"
    settings.yaml_config.jellyfin.library_language[library] = language

    def fake_urlopen(request, timeout):
        assert request.get_header("X-emby-token") == "test-key"
        assert timeout == 5
        body = (
            {"Items": [{"Path": f"/data/media/{folder}/Series/S01E01.mkv"}]}
            if "/Items?" in request.full_url
            else [{"Name": library, "Locations": [f"/data/media/{folder}"]}]
        )
        return io.BytesIO(json.dumps(body).encode())

    monkeypatch.setattr("app.ingest.jellyfin.urlopen", fake_urlopen)
    r = client.post(
        "/api/webhooks/jellyfin",
        json={
            "NotificationType": "PlaybackStop",
            "ItemId": "jf-drama",
            "Name": "Episode 1",
            "SeriesName": "Drama",
            "ItemType": "Episode",
            "RunTimeTicks": EP_TICKS,
            "PlayedToCompletion": True,
        },
    )
    assert r.json()["accepted"] is True
    log = client.get(f"/api/logs/{r.json()['log_id']}").json()
    assert (log["content_type"], log["language"], log["source"]) == ("show", language, "jellyfin")
    assert log["tadoku_mode"] == ("auto" if language == "ja" else "pending")


def test_jellyfin_auto_japanese_setting_and_show_override(client):
    assert client.get("/api/jellyfin/preferences").json() == {"auto_japanese": True}
    assert client.patch("/api/jellyfin/preferences", json={"auto_japanese": False}).json() == {
        "auto_japanese": False
    }

    def watch(item_id, series):
        response = client.post(
            "/api/webhooks/jellyfin",
            json={
                "NotificationType": "PlaybackStop",
                "ItemId": item_id,
                "Name": "Episode 1",
                "SeriesName": series,
                "LibraryName": "Anime",
                "ItemType": "Episode",
                "PlayedToCompletion": True,
            },
        ).json()
        assert response["accepted"]
        return client.get(f"/api/logs/{response['log_id']}").json()

    assert watch("jf-off", "Off Show")["tadoku_mode"] == "pending"
    client.patch("/api/jellyfin/preferences", json={"auto_japanese": True})
    catalog = client.get("/api/catalog").json()
    show = next(row for row in catalog if row["display_title"] == "Off Show")
    client.patch(f"/api/catalog/{show['series_key']}", json={"tadoku_override": "never"})
    assert watch("jf-override", "Off Show")["tadoku_mode"] == "never"
    assert watch("jf-on", "On Show")["tadoku_mode"] == "auto"


def test_jellyfin_unknown_library_does_not_log(client, monkeypatch):
    from app.core.config import get_settings

    get_settings().jellyfin_url = "http://jellyfin:8096"
    get_settings().jellyfin_api_key = "test-key"
    monkeypatch.setattr(
        "app.ingest.jellyfin.urlopen",
        lambda request, timeout: io.BytesIO(
            json.dumps(
                {"Items": [{"Path": "/unmapped/episode.mkv"}]}
                if "/Items?" in request.full_url
                else [{"Name": "Anime", "Locations": ["/data/media/anime"]}]
            ).encode()
        ),
    )
    r = client.post(
        "/api/webhooks/jellyfin",
        json={"NotificationType": "PlaybackStop", "ItemId": "unknown", "Name": "E1", "PlayedToCompletion": True},
    )
    assert r.json() == {"accepted": False, "reason": "library_not_found", "log_id": None}
