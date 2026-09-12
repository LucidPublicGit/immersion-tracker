"""mpv history poll + event ingest tests."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import sessionmaker

from app.db.models import LogEntry
from app.db.session import get_engine
from app.ingest.mpv import (
    MpvWatchEvent,
    event_from_dict,
    ingest_mpv_event,
    load_history_entries,
    make_source_ref,
    map_content_type,
    mpv_status,
    poll_mpv,
    resolve_history_path,
)


def _db():
    SessionLocal = sessionmaker(bind=get_engine(), autoflush=False, autocommit=False)
    return SessionLocal()


def _enable_mpv(history_path: str = "", **overrides):
    from app.core.config import get_settings

    cfg = get_settings().yaml_config.mpv
    cfg.enabled = True
    cfg.history_path = history_path
    cfg.completion_threshold = 0.90
    cfg.min_watched_seconds = 60.0
    cfg.content_type = "anime"
    cfg.unit = "minutes"
    cfg.activity = "listening"
    cfg.tadoku_default = "pending"
    cfg.show_path_markers = ["jdrama", "drama", "live-action", "shows"]
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


def _event(**overrides) -> MpvWatchEvent:
    base = {
        "path": r"D:/Anime/Frieren/S01E02.mkv",
        "title": "Frieren S01E02",
        "duration_seconds": 1420.0,
        "watched_seconds": 1400.0,
        "ratio": 0.98,
        "finished_at": datetime(2026, 7, 30, 12, 0, 0, tzinfo=timezone.utc),
        "event": "end-file",
    }
    base.update(overrides)
    return MpvWatchEvent(**base)


def test_map_content_type_show_markers(client):
    _enable_mpv()
    assert map_content_type(r"D:/Media/Anime/Show/ep.mkv") == "anime"
    assert map_content_type(r"D:/Media/JDrama/Show/ep.mkv") == "show"
    assert map_content_type(r"E:/live-action/Movie.mkv") == "show"
    assert map_content_type(r"E:/shows/Something/ep.mkv") == "show"


def test_make_source_ref_stable(client):
    finished = datetime(2026, 7, 30, 12, 0, 0, tzinfo=timezone.utc)
    a = make_source_ref(r"D:\Anime\A.mkv", finished_at=finished)
    b = make_source_ref(r"D:/Anime/A.mkv", finished_at=finished)
    assert a == b
    assert a.startswith("mpv:")
    c = make_source_ref(r"D:/Anime/A.mkv", finished_at=finished.replace(hour=13))
    assert a != c


def test_event_from_dict_jsonl_shape(client):
    ev = event_from_dict(
        {
            "path": "D:/Anime/Show/S01E02.mkv",
            "title": "Show S01E02",
            "duration_seconds": 1420,
            "watched_seconds": 1400,
            "ratio": 0.98,
            "finished_at": "2026-07-30T12:00:00+00:00",
            "event": "end-file",
        }
    )
    assert ev is not None
    assert ev.path.endswith("S01E02.mkv")
    assert abs(ev.computed_ratio() - 0.98) < 1e-6


def test_event_from_dict_skips_no_duration(client):
    # Classic watch_history: path + timestamp only
    assert (
        event_from_dict(
            {"path": "D:/x.mkv", "time": 1720000000, "title": "X"}
        )
        is None
    )


def test_event_from_dict_watch_history_with_duration(client):
    ev = event_from_dict(
        {
            "path": "D:/Anime/X/ep.mkv",
            "title": "X",
            "duration": 1200,
            "position": 1190,
            "time": 1720000000,
        }
    )
    assert ev is not None
    assert ev.duration_seconds == 1200
    assert ev.watched_seconds == 1190
    assert ev.finished_at is not None


def test_load_history_jsonl(client, tmp_path: Path):
    p = tmp_path / "hist.jsonl"
    lines = [
        {
            "path": "D:/a.mkv",
            "title": "A",
            "duration_seconds": 100,
            "watched_seconds": 99,
            "ratio": 0.99,
            "finished_at": "2026-07-30T10:00:00Z",
        },
        {
            "path": "D:/b.mkv",
            "title": "B",
            "duration_seconds": 200,
            "watched_seconds": 190,
            "ratio": 0.95,
            "finished_at": "2026-07-30T11:00:00Z",
        },
    ]
    p.write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")
    loaded = load_history_entries(p)
    assert len(loaded) == 2
    assert loaded[0]["path"] == "D:/a.mkv"


def test_load_history_json_array(client, tmp_path: Path):
    p = tmp_path / "hist.json"
    data = [
        {
            "path": "D:/c.mkv",
            "title": "C",
            "duration_seconds": 300,
            "watched_seconds": 300,
            "ratio": 1.0,
        }
    ]
    p.write_text(json.dumps(data), encoding="utf-8")
    loaded = load_history_entries(p)
    assert len(loaded) == 1


def test_ingest_rejects_below_threshold(client):
    _enable_mpv()
    db = _db()
    try:
        result = ingest_mpv_event(
            db,
            _event(watched_seconds=500, ratio=0.4, path="D:/Anime/Low/ep.mkv"),
        )
        assert result.accepted is False
        assert "below_threshold" in result.reason
    finally:
        db.close()


def test_ingest_rejects_below_min_watched(client):
    _enable_mpv(min_watched_seconds=60.0)
    db = _db()
    try:
        # Short clip finished fully but under min_watched
        result = ingest_mpv_event(
            db,
            _event(
                path="D:/Anime/Short/clip.mkv",
                title="clip",
                duration_seconds=40,
                watched_seconds=40,
                ratio=1.0,
            ),
        )
        assert result.accepted is False
        assert "below_min_watched" in result.reason
    finally:
        db.close()


def test_ingest_accepts_completed_anime(client):
    _enable_mpv()
    db = _db()
    try:
        result = ingest_mpv_event(db, _event())
        assert result.accepted is True
        assert result.log_id is not None
        entry = db.query(LogEntry).filter(LogEntry.id == result.log_id).one()
        assert entry.source == "mpv"
        assert entry.content_type == "anime"
        assert entry.unit == "minutes"
        # full duration minutes like YouTube
        assert entry.amount == round(1420 / 60.0, 3)
        assert entry.watch_ratio is not None and entry.watch_ratio >= 0.9
        assert entry.season == 1
        assert entry.episode == 2
        assert entry.series_key
        assert entry.source_ref.startswith("mpv:")
    finally:
        db.close()


def test_ingest_show_path_marker(client):
    _enable_mpv()
    db = _db()
    try:
        result = ingest_mpv_event(
            db,
            _event(
                path=r"D:/Media/JDrama/Midnight Diner/S01E01.mkv",
                title="Midnight Diner S01E01",
            ),
        )
        assert result.accepted is True
        entry = db.query(LogEntry).filter(LogEntry.id == result.log_id).one()
        assert entry.content_type == "show"
    finally:
        db.close()


def test_ingest_dedupe(client):
    _enable_mpv()
    db = _db()
    try:
        ev = _event(path="D:/Anime/Dup/S01E01.mkv", title="Dup S01E01")
        r1 = ingest_mpv_event(db, ev)
        r2 = ingest_mpv_event(db, ev)
        assert r1.accepted is True
        assert r2.accepted is False
        assert r2.reason == "duplicate"
        assert r2.log_id == r1.log_id
        count = (
            db.query(LogEntry)
            .filter(LogEntry.source == "mpv", LogEntry.title == r1.log["title"])
            .count()
        )
        assert count == 1
    finally:
        db.close()


def test_poll_mpv_jsonl(client, tmp_path: Path):
    hist = tmp_path / "watch_history.jsonl"
    rows = [
        {
            "path": "D:/Anime/PollShow/S01E01.mkv",
            "title": "PollShow S01E01",
            "duration_seconds": 1440,
            "watched_seconds": 1400,
            "ratio": 0.97,
            "finished_at": "2026-07-30T08:00:00+00:00",
            "event": "end-file",
        },
        {
            # incomplete — skip
            "path": "D:/Anime/PollShow/S01E02.mkv",
            "title": "PollShow S01E02",
            "duration_seconds": 1440,
            "watched_seconds": 200,
            "ratio": 0.1,
            "finished_at": "2026-07-30T09:00:00+00:00",
        },
        {
            # no duration — skip
            "path": "D:/Anime/PollShow/S01E03.mkv",
            "time": 1720000000,
        },
    ]
    hist.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    _enable_mpv(history_path=str(hist))

    db = _db()
    try:
        result = poll_mpv(db)
        assert result.ok is True
        assert result.source == "mpv"
        assert result.logs_created == 1
        assert result.skipped >= 2
        logs = db.query(LogEntry).filter(LogEntry.source == "mpv").all()
        assert len(logs) == 1
        assert logs[0].amount == round(1440 / 60.0, 3)

        # second poll is all duplicates / skips
        result2 = poll_mpv(db)
        assert result2.logs_created == 0
        assert db.query(LogEntry).filter(LogEntry.source == "mpv").count() == 1
    finally:
        db.close()


def test_poll_mpv_json_array(client, tmp_path: Path):
    hist = tmp_path / "history.json"
    hist.write_text(
        json.dumps(
            [
                {
                    "path": "D:/Anime/ArrayShow/ep1.mkv",
                    "title": "ArrayShow",
                    "duration": 900,
                    "position": 890,
                    "time": "2026-07-30T14:00:00+00:00",
                }
            ]
        ),
        encoding="utf-8",
    )
    _enable_mpv(history_path=str(hist))
    db = _db()
    try:
        result = poll_mpv(db)
        assert result.logs_created == 1
    finally:
        db.close()


def test_poll_mpv_disabled(client, tmp_path: Path):
    hist = tmp_path / "x.jsonl"
    hist.write_text("{}\n", encoding="utf-8")
    _enable_mpv(history_path=str(hist), enabled=False)
    db = _db()
    try:
        result = poll_mpv(db)
        assert result.ok is True
        assert result.logs_created == 0
        assert "disabled" in result.message
    finally:
        db.close()


def test_poll_mpv_missing_file(client):
    _enable_mpv(history_path=r"C:/definitely/not/here/mpv-history.jsonl")
    db = _db()
    try:
        result = poll_mpv(db)
        assert result.ok is True
        assert result.logs_created == 0
        assert "not found" in result.message
    finally:
        db.close()


def test_resolve_history_path_env(client, tmp_path: Path, monkeypatch):
    p = tmp_path / "env_hist.jsonl"
    p.write_text("", encoding="utf-8")
    monkeypatch.setenv("MPV_HISTORY_PATH", str(p))
    found = resolve_history_path("")
    assert found is not None
    assert found.resolve() == p.resolve()


def test_ingest_accepts_raw_dict_webhook_body(client):
    """Routes pass raw JSON dict into ingest_mpv_event."""
    _enable_mpv()
    db = _db()
    try:
        result = ingest_mpv_event(
            db,
            {
                "path": "D:/Anime/WebhookShow/S01E03.mkv",
                "title": "WebhookShow S01E03",
                "duration_seconds": 1200,
                "watched_seconds": 1150,
                "ratio": 0.96,
                "finished_at": "2026-07-30T16:00:00+00:00",
                "event": "end-file",
            },
        )
        assert result.accepted is True
        assert result.log_id is not None
        assert result.source == "mpv"
    finally:
        db.close()


def test_mpv_status(client, tmp_path: Path):
    hist = tmp_path / "status_hist.jsonl"
    hist.write_text("", encoding="utf-8")
    _enable_mpv(history_path=str(hist))
    db = _db()
    try:
        status = mpv_status(db)
        assert status["enabled"] is True
        assert status["history_exists"] is True
        assert status["webhook"] == "/api/webhooks/mpv"
        assert status["completion_threshold"] == 0.9
    finally:
        db.close()
