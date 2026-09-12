from __future__ import annotations


def _ok_payload(**overrides):
    """Payload that meets default ≥90% and ≥300s watched."""
    base = {
        "video_id": "vid90",
        "title": "Comprehensible Japanese",
        "channel_id": "UCjp",
        "channel_title": "CI Channel",
        "duration_seconds": 1200,
        "watched_seconds": 1080,
        "ratio": 0.9,
    }
    base.update(overrides)
    return base


def test_youtube_rejects_below_threshold(client):
    r = client.post(
        "/api/webhooks/youtube",
        json=_ok_payload(
            video_id="abc123",
            title="JLPT N3 Listening",
            channel_id="UCtest",
            duration_seconds=600,
            watched_seconds=300,
            ratio=0.5,
        ),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["accepted"] is False
    assert "below_threshold" in body["reason"]


def test_youtube_rejects_below_min_watched(client):
    """≥90% alone is not enough when watched progress is under 5 minutes."""
    r = client.post(
        "/api/webhooks/youtube",
        json={
            "video_id": "shortwatch",
            "title": "Short clip finish",
            "channel_id": "UCjp",
            "duration_seconds": 200,
            "watched_seconds": 200,
            "ratio": 1.0,
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["accepted"] is False
    assert "below_min_watched" in body["reason"]


def test_youtube_history_import_skips_min_watched(client):
    """User-approved log-from-history may log full watches under the auto min-watch floor."""
    r = client.post(
        "/api/webhooks/youtube",
        json={
            "video_id": "histimport1",
            "title": "Phone watch under 5 min",
            "channel_id": "UCjp",
            "channel_title": "CI",
            "duration_seconds": 180,
            "watched_seconds": 180,
            "ratio": 1.0,
            "import_source": "history",
            "finished_at": "2026-07-12T15:00:00+00:00",
        },
    )
    assert r.status_code in (200, 201)
    body = r.json()
    assert body["accepted"] is True
    assert body["log_id"] is not None
    assert body["log"]["amount"] == 3.0


def test_youtube_history_import_still_requires_threshold(client):
    r = client.post(
        "/api/webhooks/youtube",
        json={
            "video_id": "histimport2",
            "title": "Partial",
            "channel_id": "UCjp",
            "duration_seconds": 600,
            "watched_seconds": 100,
            "ratio": 0.2,
            "import_source": "history",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["accepted"] is False
    assert "below_threshold" in body["reason"]


def test_youtube_check_ids(client):
    client.post("/api/webhooks/youtube", json=_ok_payload(video_id="knownvid1"))
    r = client.post(
        "/api/youtube/check-ids",
        json={"video_ids": ["knownvid1", "unknownvid9", "knownvid1"]},
    )
    assert r.status_code == 200
    body = r.json()
    assert "knownvid1" in body["known"]
    assert "unknownvid9" in body["unknown"]
    assert body["checked"] == 2


def test_youtube_extension_config(client, monkeypatch):
    from app.core.config import get_settings

    cfg = get_settings().yaml_config
    cfg.youtube.viewer_allowlist = ["@TestViewer", "UCxxxxxxxxxxxxxxxxxxxxxx"]
    cfg.youtube.channel_allowlist = ["@ComprehensibleJapanese"]
    cfg.youtube.channel_blocklist = ["@EnglishOnly"]
    cfg.youtube.completion_threshold = 0.9
    cfg.youtube.min_watched_seconds = 300.0

    r = client.get("/api/youtube/extension-config")
    assert r.status_code == 200
    body = r.json()
    assert body["viewer_allowlist"] == ["@TestViewer", "UCxxxxxxxxxxxxxxxxxxxxxx"]
    assert body["channel_allowlist"] == ["@ComprehensibleJapanese"]
    assert body["channel_blocklist"] == ["@EnglishOnly"]
    assert body["completion_threshold"] == 0.9
    assert body["min_watched_seconds"] == 300.0
    assert "tadoku_default" in body


def test_youtube_accepts_at_threshold(client):
    r = client.post("/api/webhooks/youtube", json=_ok_payload())
    assert r.status_code in (200, 201)
    body = r.json()
    assert body["accepted"] is True
    assert body["log_id"] is not None
    # tadoku_default comes from settings.yaml (auto → ready, or pending)
    assert body["log"]["tadoku_mode"] in ("auto", "pending")
    assert body["log"]["tadoku_status"] in ("ready", "pending")
    assert body["log"]["amount"] == 20.0  # 1200s -> 20 min


def test_youtube_dedupe(client):
    payload = _ok_payload(
        video_id="dup1",
        title="Same video",
        channel_id="UCx",
        finished_at="2026-07-11T12:00:00+00:00",
    )
    r1 = client.post("/api/webhooks/youtube", json=payload)
    r2 = client.post("/api/webhooks/youtube", json=payload)
    assert r1.json()["accepted"] is True
    assert r2.json()["accepted"] is False
    assert r2.json()["reason"] == "duplicate"


def test_youtube_rewatch_next_day_rejected(client):
    """Same video_id must never log twice, even on a later calendar day."""
    base = _ok_payload(
        video_id="dup2",
        title="Same video again",
        channel_id="UCx",
    )
    r1 = client.post(
        "/api/webhooks/youtube",
        json={**base, "finished_at": "2026-07-10T12:00:00+00:00"},
    )
    r2 = client.post(
        "/api/webhooks/youtube",
        json={**base, "finished_at": "2026-07-11T12:00:00+00:00"},
    )
    assert r1.json()["accepted"] is True
    assert r2.json()["accepted"] is False
    assert r2.json()["reason"] == "duplicate"


def test_youtube_legacy_day_source_ref_still_duplicates(client):
    """Older rows used video_id:YYYY-MM-DD; those still block a rewatch."""
    from app.db.models import LogEntry
    from app.db.session import get_db
    from app.ingest.youtube import find_existing_youtube_log

    db = next(get_db())
    try:
        legacy = LogEntry(
            content_type="youtube",
            title="Old shape",
            source="youtube",
            source_ref="legacyvid:2026-07-01",
            amount=10.0,
            unit="minutes",
            activity="listening",
            language="ja",
            tadoku_mode="pending",
            tadoku_status="pending",
        )
        db.add(legacy)
        db.commit()
        found = find_existing_youtube_log(db, "legacyvid")
        assert found is not None
        assert found.source_ref == "legacyvid:2026-07-01"
    finally:
        db.close()

    r = client.post(
        "/api/webhooks/youtube",
        json=_ok_payload(
            video_id="legacyvid",
            title="Rewatch attempt",
            channel_id="UCx",
            finished_at="2026-07-12T12:00:00+00:00",
        ),
    )
    assert r.json()["accepted"] is False
    assert r.json()["reason"] == "duplicate"


def test_youtube_status_code_created(client):
    r = client.post(
        "/api/webhooks/youtube",
        json=_ok_payload(video_id="st1", title="Status", channel_id="UCx"),
    )
    assert r.status_code == 201


def test_youtube_blocklist(client, monkeypatch):
    from app.core.config import get_settings

    cfg = get_settings().yaml_config
    cfg.youtube.channel_blocklist = ["UCbad"]
    r = client.post(
        "/api/webhooks/youtube",
        json=_ok_payload(
            video_id="blocked1",
            title="Nope",
            channel_id="UCbad",
        ),
    )
    assert r.json()["accepted"] is False
    assert r.json()["reason"] == "channel_blocked"


def test_youtube_viewer_allowlist_rejects_unknown(client, monkeypatch):
    from app.core.config import get_settings

    cfg = get_settings().yaml_config
    cfg.youtube.viewer_allowlist = ["@immersion", "UCimmersionxxxxxxxxxxxxxxxx"]
    r = client.post(
        "/api/webhooks/youtube",
        json=_ok_payload(
            video_id="viewer_unknown",
            title="JP vid",
            channel_id="UCcreator",
        ),
    )
    assert r.json()["accepted"] is False
    assert r.json()["reason"] == "viewer_unknown_with_allowlist"


def test_youtube_viewer_allowlist_rejects_wrong_account(client, monkeypatch):
    from app.core.config import get_settings

    cfg = get_settings().yaml_config
    cfg.youtube.viewer_allowlist = ["@immersion"]
    r = client.post(
        "/api/webhooks/youtube",
        json=_ok_payload(
            video_id="viewer_wrong",
            title="JP vid",
            channel_id="UCcreator",
            viewer_channel_id="UCenglishaccountxxxxxxxxxxx",
            viewer_handle="@englishmain",
        ),
    )
    assert r.json()["accepted"] is False
    assert r.json()["reason"] == "viewer_not_allowlisted"


def test_youtube_viewer_allowlist_accepts_handle(client, monkeypatch):
    from app.core.config import get_settings

    cfg = get_settings().yaml_config
    cfg.youtube.viewer_allowlist = ["@immersion"]
    r = client.post(
        "/api/webhooks/youtube",
        json=_ok_payload(
            video_id="viewer_ok",
            title="JP vid",
            channel_id="UCcreator",
            viewer_channel_id="UCimmersionxxxxxxxxxxxxxxxx",
            viewer_handle="@Immersion",
        ),
    )
    assert r.status_code in (200, 201)
    assert r.json()["accepted"] is True


def test_youtube_viewer_allowlist_accepts_url_encoded_handle(client, monkeypatch):
    """YouTube hrefs encode non-ASCII handles; server must unquote before match."""
    from app.core.config import get_settings

    cfg = get_settings().yaml_config
    # Generic non-ASCII handle so URL-decoding is exercised without personal data.
    cfg.youtube.viewer_allowlist = ["@テスト-handle"]
    r = client.post(
        "/api/webhooks/youtube",
        json=_ok_payload(
            video_id="viewer_encoded",
            title="JP vid",
            channel_id="UCcreator",
            viewer_handle="@%E3%83%86%E3%82%B9%E3%83%88-handle",
        ),
    )
    assert r.status_code in (200, 201)
    assert r.json()["accepted"] is True
