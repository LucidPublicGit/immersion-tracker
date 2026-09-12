"""Hoshi / ッツ Drive statistics parsing and delta ingest."""

from __future__ import annotations

import json

from app.db.models import HoshiBookBucket, LogEntry
from app.db.session import get_engine
from app.ingest.hoshi import (
    get_seen_chars,
    ingest_book_days,
    series_key_for_title,
)
from app.ingest.hoshi_buckets import submit_bucket
from app.ingest.hoshi_drive import (
    BookFolder,
    desanitize_ttu_filename,
    parse_statistics_json,
    parse_statistics_timestamp_millis,
    pick_latest_statistics_file,
    sanitize_ttu_filename,
    DriveFileInfo,
)
from sqlalchemy.orm import sessionmaker


def _db():
    SessionLocal = sessionmaker(bind=get_engine(), autoflush=False, autocommit=False)
    return SessionLocal()


SAMPLE_STATS = [
    {
        "title": "Test Novel",
        "dateKey": "2026-07-20",
        "charactersRead": 1000,
        "readingTime": 600.0,
        "minReadingSpeed": 0,
        "altMinReadingSpeed": 0,
        "lastReadingSpeed": 100,
        "maxReadingSpeed": 100,
        "lastStatisticModified": 100,
    },
    {
        "title": "Test Novel",
        "dateKey": "2026-07-21",
        "charactersRead": 2500,
        "readingTime": 1200.0,
        "lastStatisticModified": 200,
    },
]


def test_sanitize_roundtrip_special_chars():
    title = 'Book: "Part 1" / *draft*. '
    sanitized = sanitize_ttu_filename(title)
    assert "*" not in sanitized or "~ttu-star~" in sanitized
    assert desanitize_ttu_filename(sanitized) == title


def test_parse_statistics_timestamp_and_latest_file():
    assert parse_statistics_timestamp_millis(
        "statistics_1_6_999_10_1.0_0_0_0_0_0_0_0_0_0_0_na.json"
    ) == 999
    files = [
        DriveFileInfo(id="a", name="statistics_1_6_100_1_0.json", parents=[]),
        DriveFileInfo(id="b", name="statistics_1_6_500_2_0.json", parents=[]),
        DriveFileInfo(id="c", name="progress_1_6_900_0.5.json", parents=[]),
    ]
    latest = pick_latest_statistics_file(files)
    assert latest is not None
    assert latest.id == "b"


def test_parse_statistics_json_dedupes_date():
    raw = json.dumps(
        [
            {
                "title": "B",
                "dateKey": "2026-05-13",
                "charactersRead": 10,
                "lastStatisticModified": 100,
            },
            {
                "title": "B",
                "dateKey": "2026-05-13",
                "charactersRead": 20,
                "lastStatisticModified": 200,
            },
        ]
    )
    days = parse_statistics_json(raw)
    assert len(days) == 1
    assert days[0].characters_read == 20


def test_ingest_bootstrap_then_delta_buckets(client):
    """With manual log_mode, bootstrap deltas fill buckets (no formal logs yet)."""
    from app.core.config import get_settings

    get_settings().yaml_config.hoshi.log_mode = "manual"
    get_settings().yaml_config.hoshi.min_submit_characters = 99999

    db = _db()
    try:
        book = BookFolder(id="folderABC", name="Test Novel", title="Test Novel")
        days = parse_statistics_json(SAMPLE_STATS)

        r1 = ingest_book_days(db, book, days, bootstrap=True, min_characters=1)
        assert r1.ok
        assert r1.sessions_added == 2
        assert r1.chars_bucketed == 3500.0
        assert r1.logs_created == 0

        assert get_seen_chars(db, "folderABC", "2026-07-20") == 1000
        assert get_seen_chars(db, "folderABC", "2026-07-21") == 2500
        bucket = db.query(HoshiBookBucket).filter_by(folder_id="folderABC").one()
        assert bucket.pending_chars == 3500

        # Same stats again → no new sessions
        r2 = ingest_book_days(db, book, days, bootstrap=True)
        assert r2.sessions_added == 0

        # Increase day 2
        days2 = parse_statistics_json(
            [
                SAMPLE_STATS[0],
                {
                    **SAMPLE_STATS[1],
                    "charactersRead": 3000,
                    "lastStatisticModified": 300,
                },
            ]
        )
        r3 = ingest_book_days(db, book, days2, bootstrap=True)
        assert r3.sessions_added == 1
        assert r3.chars_bucketed == 500.0
        assert get_seen_chars(db, "folderABC", "2026-07-21") == 3000

        db.refresh(bucket)
        assert bucket.pending_chars == 4000
        entry = submit_bucket(db, bucket.id, force=True)
        assert entry is not None
        assert entry.amount == 4000
    finally:
        db.close()


def test_ingest_no_bootstrap_baselines_only(client):
    from app.core.config import get_settings

    get_settings().yaml_config.hoshi.log_mode = "manual"
    get_settings().yaml_config.hoshi.min_submit_characters = 99999

    db = _db()
    try:
        book = BookFolder(id="folderNoBoot", name="X", title="X")
        days = parse_statistics_json(SAMPLE_STATS)
        r1 = ingest_book_days(db, book, days, bootstrap=False)
        assert r1.sessions_added == 0
        assert r1.logs_created == 0
        assert get_seen_chars(db, "folderNoBoot", "2026-07-20") == 1000

        days_up = parse_statistics_json(
            [
                {
                    **SAMPLE_STATS[0],
                    "charactersRead": 1500,
                    "lastStatisticModified": 150,
                },
                SAMPLE_STATS[1],
            ]
        )
        r2 = ingest_book_days(db, book, days_up, bootstrap=False)
        assert r2.sessions_added == 1
        assert r2.chars_bucketed == 500.0
        assert r2.logs_created == 0
        bucket = db.query(HoshiBookBucket).filter_by(folder_id="folderNoBoot").one()
        assert bucket.pending_chars == 500
    finally:
        db.close()


def test_position_gates_reread_stats(client):
    """Day-stat increases without bookmark advance must not inflate pending."""
    from app.core.config import get_settings
    from app.db.models import HoshiBookBucket

    get_settings().yaml_config.hoshi.log_mode = "manual"
    get_settings().yaml_config.hoshi.min_submit_characters = 99999

    db = _db()
    try:
        book = BookFolder(id="folderPos", name="Pos Book", title="Pos Book")
        # First sight at position 1000 with 1000 day chars
        days1 = parse_statistics_json(
            [
                {
                    "title": "Pos Book",
                    "dateKey": "2026-07-25",
                    "charactersRead": 1000,
                    "readingTime": 10,
                    "lastStatisticModified": 1,
                }
            ]
        )
        r1 = ingest_book_days(
            db,
            book,
            days1,
            bootstrap=True,
            min_characters=1,
            position_chars=1000,
            book_total_chars=50000,
        )
        assert r1.sessions_added == 1
        assert r1.chars_bucketed == 1000.0
        bucket = db.query(HoshiBookBucket).filter_by(folder_id="folderPos").one()
        assert bucket.pending_chars == 1000
        assert bucket.credited_position_chars == 1000

        # Re-read: day chars jump, position stays put → no new pending
        days2 = parse_statistics_json(
            [
                {
                    "title": "Pos Book",
                    "dateKey": "2026-07-25",
                    "charactersRead": 2500,
                    "readingTime": 40,
                    "lastStatisticModified": 2,
                }
            ]
        )
        r2 = ingest_book_days(
            db,
            book,
            days2,
            bootstrap=True,
            min_characters=1,
            position_chars=1000,
            book_total_chars=50000,
        )
        assert r2.sessions_added == 0
        assert r2.chars_bucketed == 0.0
        assert r2.skipped_reread >= 1
        db.refresh(bucket)
        assert bucket.pending_chars == 1000

        # Real progress: position advances 400 → only +400, not full day delta
        days3 = parse_statistics_json(
            [
                {
                    "title": "Pos Book",
                    "dateKey": "2026-07-25",
                    "charactersRead": 3000,
                    "readingTime": 50,
                    "lastStatisticModified": 3,
                }
            ]
        )
        r3 = ingest_book_days(
            db,
            book,
            days3,
            bootstrap=True,
            min_characters=1,
            position_chars=1400,
            book_total_chars=50000,
        )
        assert r3.sessions_added == 1
        assert r3.chars_bucketed == 400.0
        db.refresh(bucket)
        assert bucket.pending_chars == 1400
        assert bucket.credited_position_chars == 1400
    finally:
        db.close()


def test_series_key_for_title():
    assert series_key_for_title("  夜は短し歩けよ乙女  ") == "hoshi:夜は短し歩けよ乙女"


def test_hoshi_status_endpoint(client):
    r = client.get("/api/hoshi/status")
    assert r.status_code == 200
    body = r.json()
    assert "enabled" in body
    assert body.get("source") in ("adb", "drive")
    assert "adb" in body


def test_hoshi_sync_disabled_without_creds(client):
    """When disabled, poll reports not enabled (no network call required)."""
    from app.core.config import get_settings

    get_settings().yaml_config.hoshi.enabled = False
    r = client.post("/api/hoshi/sync")
    assert r.status_code == 503
    body = r.json()
    assert body.get("ok") is False
    assert "enabled" in (body.get("reason") or "").lower()


def test_hoshi_ingest_stats_api(client, monkeypatch):
    from app.core.config import get_settings

    get_settings().yaml_config.hoshi.enabled = True
    get_settings().yaml_config.hoshi.log_mode = "manual"
    get_settings().yaml_config.hoshi.bootstrap = True
    get_settings().yaml_config.hoshi.min_submit_characters = 99999
    body = {
        "books": [
            {
                "folder_id": "TestNovel",
                "title": "Test Novel",
                "statistics": [
                    {
                        "title": "Test Novel",
                        "dateKey": "2026-07-22",
                        "charactersRead": 800,
                        "readingTime": 100.0,
                        "lastStatisticModified": 1,
                    }
                ],
            }
        ]
    }
    r = client.post("/api/hoshi/ingest-stats", json=body)
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data.get("sessions_added", 0) == 1 or data.get("chars_bucketed", 0) == 800
    assert data["logs_created"] == 0

    # second push same total → no new sessions
    r2 = client.post("/api/hoshi/ingest-stats", json=body)
    assert r2.status_code == 200
    assert r2.json().get("sessions_added", 0) == 0


def test_adb_book_folder_id():
    from app.ingest.hoshi_adb import AdbDeviceBook, adb_book_to_folder

    b = AdbDeviceBook(
        folder="夜は短し",
        title="夜は短し歩けよ乙女",
        days=[],
        access_mode="run-as",
    )
    f = adb_book_to_folder(b)
    assert f.id.startswith("adb:")
    assert f.title == "夜は短し歩けよ乙女"
