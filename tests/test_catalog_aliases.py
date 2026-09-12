from __future__ import annotations


def test_plex_alias_links_to_manual_series(client):
    # Manual-style catalog entry with JP display name + English Plex alias
    r = client.post(
        "/api/catalog",
        json={
            "series_key": "anime:tensura",
            "display_title": "転スラ",
            "content_type": "anime",
            "aliases": "That Time I Got Reincarnated as a Slime",
        },
    )
    assert r.status_code == 201

    r = client.post(
        "/api/webhooks/plex",
        json={
            "rating_key": "alias-rk-1",
            "title": "Episode 1",
            "grandparent_title": "That Time I Got Reincarnated as a Slime",
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
    assert log["title"] == "転スラ"
    assert log["series_key"] == "anime:tensura"
    assert log["content_type"] == "anime"


def test_plex_display_title_from_catalog_series_key(client):
    # Same auto series_key as Plex would generate; only rename display
    client.post(
        "/api/catalog",
        json={
            "series_key": "anime:frieren",
            "display_title": "葬送のフリーレン",
            "content_type": "anime",
        },
    )
    r = client.post(
        "/api/webhooks/plex",
        json={
            "rating_key": "alias-rk-2",
            "title": "E01",
            "grandparent_title": "Frieren",
            "library_name": "Anime",
            "media_type": "episode",
            "duration_ms": 1_500_000,
            "progress_percent": 99,
            "watched": True,
        },
    )
    log = client.get(f"/api/logs/{r.json()['log_id']}").json()
    assert log["series_key"] == "anime:frieren"
    assert log["title"] == "葬送のフリーレン"


def test_catalog_link_and_relink_existing_logs(client):
    # First watch creates English title + auto key
    r = client.post(
        "/api/webhooks/plex",
        json={
            "rating_key": "pre-link-1",
            "title": "E02",
            "grandparent_title": "My Hero Academia",
            "library_name": "Anime",
            "media_type": "episode",
            "duration_ms": 1_440_000,
            "progress_percent": 100,
            "watched": True,
        },
    )
    old = client.get(f"/api/logs/{r.json()['log_id']}").json()
    assert old["title"] == "My Hero Academia"
    assert old["series_key"] == "anime:my-hero-academia"

    link = client.post(
        "/api/catalog/link",
        json={
            "series_key": "anime:bnha",
            "display_title": "僕のヒーローアカデミア",
            "content_type": "anime",
            "alias": "My Hero Academia",
            "relink_logs": True,
        },
    )
    assert link.status_code == 200
    assert link.json()["relink"]["updated"] >= 1

    fixed = client.get(f"/api/logs/{old['id']}").json()
    assert fixed["title"] == "僕のヒーローアカデミア"
    assert fixed["series_key"] == "anime:bnha"

    # New watches use alias automatically
    r2 = client.post(
        "/api/webhooks/plex",
        json={
            "rating_key": "post-link-1",
            "title": "E03",
            "grandparent_title": "My Hero Academia",
            "library_name": "Anime",
            "media_type": "episode",
            "duration_ms": 1_440_000,
            "progress_percent": 100,
            "watched": True,
        },
    )
    log2 = client.get(f"/api/logs/{r2.json()['log_id']}").json()
    assert log2["title"] == "僕のヒーローアカデミア"
    assert log2["series_key"] == "anime:bnha"


def test_relink_applies_tadoku_override(client):
    """Relink should copy catalog tadoku_override onto pipeline logs (not pushed)."""
    # Plex watch → pending by default
    r = client.post(
        "/api/webhooks/plex",
        json={
            "rating_key": "tadoku-relink-1",
            "title": "E01",
            "grandparent_title": "KONOSUBA - God's blessing on this wonderful world!",
            "library_name": "Anime",
            "media_type": "episode",
            "duration_ms": 1_440_000,
            "progress_percent": 100,
            "watched": True,
        },
    )
    log_id = r.json()["log_id"]
    old = client.get(f"/api/logs/{log_id}").json()
    assert old["tadoku_mode"] == "pending"
    assert old["tadoku_status"] == "pending"

    link = client.post(
        "/api/catalog/link",
        json={
            "series_key": "anime:konosuba",
            "display_title": "この素晴らしい世界に祝福を",
            "content_type": "anime",
            "alias": "KONOSUBA - God's blessing on this wonderful world!",
            "tadoku_override": "auto",
            "relink_logs": True,
        },
    )
    assert link.status_code == 200
    body = link.json()
    assert body["relink"]["updated"] >= 1
    assert body["relink"]["tadoku_updated"] >= 1

    fixed = client.get(f"/api/logs/{log_id}").json()
    assert fixed["title"] == "この素晴らしい世界に祝福を"
    assert fixed["series_key"] == "anime:konosuba"
    assert fixed["tadoku_mode"] == "auto"
    assert fixed["tadoku_status"] == "ready"


def test_relink_skips_pushed_and_user_skips(client):
    """Pushed logs and user skips must not be reopened by tadoku_override."""
    # Create two logs via plex
    for i, rk in enumerate(("push-rk", "skip-rk"), start=1):
        client.post(
            "/api/webhooks/plex",
            json={
                "rating_key": rk,
                "title": f"E{i:02d}",
                "grandparent_title": "Pushed Skip Show",
                "library_name": "Anime",
                "media_type": "episode",
                "duration_ms": 1_440_000,
                "progress_percent": 100,
                "watched": True,
            },
        )
    logs = client.get("/api/logs").json()
    show_logs = sorted(
        [e for e in logs if e["title"] == "Pushed Skip Show"], key=lambda e: e["id"]
    )
    assert len(show_logs) == 2
    pushed_id, skip_id = show_logs[0]["id"], show_logs[1]["id"]

    # Mark one already-submitted, one user-skipped
    from app.db.models import LogEntry
    from app.db.session import get_engine
    from sqlalchemy.orm import sessionmaker

    Session = sessionmaker(bind=get_engine())
    with Session() as db:
        pushed_row = db.get(LogEntry, pushed_id)
        assert pushed_row is not None
        pushed_row.tadoku_status = "pushed"
        pushed_row.tadoku_mode = "auto"
        pushed_row.tadoku_remote_id = "remote-test-1"
        db.commit()

    r = client.post(f"/api/logs/{skip_id}/skip")
    assert r.status_code == 200
    assert r.json()["tadoku_status"] == "skipped"

    link = client.post(
        "/api/catalog/link",
        json={
            "series_key": "anime:push-skip",
            "display_title": "PS Show JP",
            "content_type": "anime",
            "alias": "Pushed Skip Show",
            "tadoku_override": "auto",
            "relink_logs": True,
        },
    )
    assert link.status_code == 200
    # Titles/keys may update, but tadoku pipeline must not reopen
    assert link.json()["relink"]["tadoku_updated"] == 0

    pushed = client.get(f"/api/logs/{pushed_id}").json()
    skipped = client.get(f"/api/logs/{skip_id}").json()
    assert pushed["title"] == "PS Show JP"
    assert pushed["tadoku_status"] == "pushed"
    assert skipped["title"] == "PS Show JP"
    assert skipped["tadoku_status"] == "skipped"
    assert skipped["tadoku_mode"] == "never"


def test_relink_never_override_marks_pipeline_skipped(client):
    r = client.post(
        "/api/webhooks/plex",
        json={
            "rating_key": "never-rk-1",
            "title": "E01",
            "grandparent_title": "Never Export Show",
            "library_name": "Anime",
            "media_type": "episode",
            "duration_ms": 1_440_000,
            "progress_percent": 100,
            "watched": True,
        },
    )
    log_id = r.json()["log_id"]
    client.post(
        "/api/catalog/link",
        json={
            "series_key": "anime:never-show",
            "display_title": "Never JP",
            "content_type": "anime",
            "alias": "Never Export Show",
            "tadoku_override": "never",
            "relink_logs": True,
        },
    )
    log = client.get(f"/api/logs/{log_id}").json()
    assert log["tadoku_mode"] == "never"
    assert log["tadoku_status"] == "skipped"


def test_manual_and_plex_share_queue_group(client):
    client.post(
        "/api/catalog/link",
        json={
            "series_key": "anime:shared",
            "display_title": "Shared Show",
            "content_type": "anime",
            "alias": "Plex Shared Show",
            "relink_logs": False,
        },
    )
    client.post(
        "/api/logs",
        json={
            "content_type": "anime",
            "title": "Shared Show",
            "amount": 24,
            "unit": "minutes",
            "series_key": "anime:shared",
            "source": "manual",
        },
    )
    client.post(
        "/api/webhooks/plex",
        json={
            "rating_key": "share-1",
            "title": "E01",
            "grandparent_title": "Plex Shared Show",
            "library_name": "Anime",
            "media_type": "episode",
            "duration_ms": 1_440_000,
            "progress_percent": 95,
            "watched": True,
        },
    )
    logs = client.get("/api/logs").json()
    keys = {e["series_key"] for e in logs if e["series_key"] == "anime:shared"}
    assert keys == {"anime:shared"}
    titles = {e["title"] for e in logs if e["series_key"] == "anime:shared"}
    assert titles == {"Shared Show"}
