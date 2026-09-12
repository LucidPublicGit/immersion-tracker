"""asbplayer webhook ingest (direct function calls; route may be wired separately)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import sessionmaker

from app.db.session import get_engine, init_db
from app.ingest.asbplayer import (
    AsbplayerWatchEvent,
    find_existing_asbplayer_log,
    ingest_asbplayer_watch,
)


def _db():
    init_db()
    SessionLocal = sessionmaker(bind=get_engine(), autoflush=False, autocommit=False)
    return SessionLocal()


def _ok_event(**overrides) -> AsbplayerWatchEvent:
    """Payload that meets default ≥90% and ≥60s watched."""
    base = {
        "media_id": "ep01-file.mkv",
        "title": "Frieren S01E01",
        "series_title": "Frieren",
        "duration_seconds": 1440.0,
        "watched_seconds": 1300.0,
        "ratio": 0.95,
    }
    base.update(overrides)
    return AsbplayerWatchEvent(**base)


@pytest.fixture()
def db(client):
    """Reuse client fixture isolation (fresh SQLite + settings)."""
    session = _db()
    try:
        yield session
    finally:
        session.close()


def test_asbplayer_rejects_below_threshold(db):
    event = _ok_event(
        media_id="partial1",
        duration_seconds=600,
        watched_seconds=300,
        ratio=0.5,
    )
    result = ingest_asbplayer_watch(db, event)
    assert result.accepted is False
    assert "below_threshold" in result.reason


def test_asbplayer_rejects_below_min_watched(db, monkeypatch):
    """≥90% alone is not enough when watched progress is under min_watched_seconds."""
    from app.core.config import get_settings

    cfg = get_settings().yaml_config.asbplayer
    cfg.min_watched_seconds = 60.0
    cfg.completion_threshold = 0.90

    event = _ok_event(
        media_id="short1",
        duration_seconds=40.0,
        watched_seconds=40.0,
        ratio=1.0,
    )
    result = ingest_asbplayer_watch(db, event)
    assert result.accepted is False
    assert "below_min_watched" in result.reason


def test_asbplayer_accepts_at_threshold(db):
    from app.core.config import get_settings

    cfg = get_settings().yaml_config.asbplayer
    cfg.completion_threshold = 0.90
    cfg.min_watched_seconds = 60.0
    cfg.tadoku_default = "pending"

    event = _ok_event(media_id="ok1")
    result = ingest_asbplayer_watch(db, event)
    assert result.accepted is True
    assert result.reason == "logged"
    assert result.log_id is not None
    assert result.log is not None
    assert result.log["amount"] == 24.0  # 1440s → 24 min
    assert result.log["unit"] == "minutes"
    assert result.log["content_type"] == "anime"
    assert result.log["source_ref"] == "asbplayer:ok1"
    assert result.log["series_key"] == "asb:frieren"
    assert result.log["tadoku_mode"] in ("auto", "pending")
    assert result.log["tadoku_status"] in ("ready", "pending")


def test_asbplayer_duplicate(db):
    event = _ok_event(
        media_id="dup1",
        finished_at=datetime(2026, 7, 11, 12, 0, tzinfo=timezone.utc),
    )
    r1 = ingest_asbplayer_watch(db, event)
    r2 = ingest_asbplayer_watch(db, event)
    assert r1.accepted is True
    assert r2.accepted is False
    assert r2.reason == "duplicate"
    assert r2.log_id == r1.log_id


def test_asbplayer_path_as_media_id(db):
    event = AsbplayerWatchEvent(
        path=r"D:\Anime\Frieren\S01E02.mkv",
        title="Frieren S01E02",
        series_title="Frieren",
        duration_seconds=1440,
        watched_seconds=1440,
        ratio=1.0,
    )
    result = ingest_asbplayer_watch(db, event)
    assert result.accepted is True
    assert result.log["source_ref"] == r"asbplayer:D:\Anime\Frieren\S01E02.mkv"
    found = find_existing_asbplayer_log(db, r"D:\Anime\Frieren\S01E02.mkv")
    assert found is not None


def test_asbplayer_requires_media_id_or_path():
    with pytest.raises(ValidationError):
        AsbplayerWatchEvent(title="No id", duration_seconds=100, watched_seconds=100)


def test_asbplayer_missing_duration(db):
    event = AsbplayerWatchEvent(
        media_id="nodur",
        title="Unknown length",
        ratio=1.0,
        watched_seconds=100,
    )
    result = ingest_asbplayer_watch(db, event)
    assert result.accepted is False
    assert result.reason == "missing_duration"


def test_asbplayer_content_type_override(db):
    event = _ok_event(media_id="show1", content_type="show", series_title="JDrama")
    result = ingest_asbplayer_watch(db, event)
    assert result.accepted is True
    assert result.log["content_type"] == "show"
    assert result.log["series_key"] == "asb:jdrama"


def test_asbplayer_ratio_from_watched(db):
    """When ratio omitted, compute from watched/duration."""
    event = AsbplayerWatchEvent(
        media_id="ratio-compute",
        title="Ep",
        series_title="Show",
        duration_seconds=1000,
        watched_seconds=950,
    )
    result = ingest_asbplayer_watch(db, event)
    assert result.accepted is True
    assert result.log["watch_ratio"] == pytest.approx(0.95)
