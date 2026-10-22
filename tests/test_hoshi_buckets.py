"""Hoshi reading buckets: accumulate sessions, auto/manual submit."""

from __future__ import annotations

import pytest

from app.db.models import HoshiBookBucket, HoshiSessionFragment, LogEntry
from app.db.session import get_engine
from app.ingest.hoshi import ingest_book_days, series_key_for_title
from app.ingest.hoshi_buckets import (
    add_session_fragment,
    discard_bucket,
    reading_dashboard,
    submit_bucket,
)
from app.ingest.hoshi_drive import BookFolder, parse_statistics_json
from sqlalchemy.orm import sessionmaker


def _db():
    return sessionmaker(bind=get_engine(), autoflush=False, autocommit=False)()


def test_bucket_accumulate_manual_no_auto_log(client):
    from app.core.config import get_settings

    get_settings().yaml_config.hoshi.log_mode = "manual"
    get_settings().yaml_config.hoshi.min_submit_characters = 500

    db = _db()
    try:
        b, f, entry = add_session_fragment(
            db,
            folder_id="folderX",
            title="Test Book",
            date_key="2026-07-25",
            chars=200,
            seconds=60,
            remote_total_for_day=200,
        )
        assert entry is None
        assert b.pending_chars == 200
        assert f.status == "pending"
        assert db.query(LogEntry).filter(LogEntry.source == "hoshi").count() == 0

        # Below threshold still no log
        add_session_fragment(
            db,
            folder_id="folderX",
            title="Test Book",
            date_key="2026-07-25",
            chars=100,
            remote_total_for_day=300,
        )
        b2 = db.query(HoshiBookBucket).filter_by(folder_id="folderX").one()
        assert b2.pending_chars == 300
        assert b2.session_count == 2
    finally:
        db.close()


def test_manual_submit_creates_log(client):
    from app.core.config import get_settings

    get_settings().yaml_config.hoshi.log_mode = "manual"
    db = _db()
    try:
        add_session_fragment(
            db,
            folder_id="folderY",
            title="Submit Me",
            date_key="2026-07-25",
            chars=120,
            remote_total_for_day=120,
            position_chars=900,
            book_total_chars=10000,
        )
        bucket = db.query(HoshiBookBucket).filter_by(folder_id="folderY").one()
        assert bucket.position_chars == 900
        entry = submit_bucket(db, bucket.id, force=True)
        assert entry is not None
        assert entry.amount == 120
        assert entry.unit == "characters"
        assert entry.source == "hoshi"
        db.refresh(bucket)
        assert bucket.pending_chars == 0
        assert bucket.total_logged_chars == 120
        assert bucket.last_logged_position_chars == 900
        frags = (
            db.query(HoshiSessionFragment)
            .filter_by(bucket_id=bucket.id, status="logged")
            .all()
        )
        assert len(frags) == 1
        assert frags[0].log_id == entry.id
        dash = reading_dashboard(db)
        row = next(b for b in dash["buckets"] if b["folder_id"] == "folderY")
        assert row["last_logged_position_chars"] == 900
        assert row["last_logged_percent"] == 9.0
    finally:
        db.close()


def test_auto_submit_waits_for_idle(client):
    """Threshold alone does not auto-log while still 'reading' (idle window)."""
    from datetime import timedelta

    from app.core.config import get_settings
    from app.db.models import utcnow
    from app.ingest.hoshi_buckets import process_auto_submit_idle_buckets

    get_settings().yaml_config.hoshi.log_mode = "auto"
    get_settings().yaml_config.hoshi.min_submit_characters = 250
    get_settings().yaml_config.hoshi.auto_submit_idle_minutes = 30

    db = _db()
    try:
        _b, _f, entry1 = add_session_fragment(
            db,
            folder_id="folderZ",
            title="Auto Book",
            date_key="2026-07-25",
            chars=100,
            remote_total_for_day=100,
        )
        assert entry1 is None
        _b, _f, entry2 = add_session_fragment(
            db,
            folder_id="folderZ",
            title="Auto Book",
            date_key="2026-07-25",
            chars=200,
            remote_total_for_day=300,
        )
        # Mid-session: threshold met but last fragment is "now" → no auto log
        assert entry2 is None
        bucket = db.query(HoshiBookBucket).filter_by(folder_id="folderZ").one()
        assert bucket.pending_chars == 300

        # Still idle-blocked
        assert process_auto_submit_idle_buckets(db) == []

        # Simulate quiet period after reading stopped
        bucket.last_session_at = utcnow() - timedelta(minutes=31)
        db.commit()

        submitted = process_auto_submit_idle_buckets(db)
        assert len(submitted) == 1
        assert submitted[0]["amount"] == 300
        db.refresh(bucket)
        assert bucket.pending_chars == 0
        assert bucket.total_logged_chars == 300
    finally:
        db.close()


def test_auto_submit_immediate_if_idle_zero(client):
    from app.core.config import get_settings

    get_settings().yaml_config.hoshi.log_mode = "auto"
    get_settings().yaml_config.hoshi.min_submit_characters = 250
    get_settings().yaml_config.hoshi.auto_submit_idle_minutes = 0

    db = _db()
    try:
        _b, _f, entry = add_session_fragment(
            db,
            folder_id="folderImmediate",
            title="Fast",
            date_key="2026-07-25",
            chars=300,
            remote_total_for_day=300,
        )
        assert entry is not None
        assert entry.amount == 300
    finally:
        db.close()


def test_discard_pending(client):
    db = _db()
    try:
        add_session_fragment(
            db,
            folder_id="folderD",
            title="Drop",
            date_key="2026-07-25",
            chars=50,
            remote_total_for_day=50,
        )
        bucket = db.query(HoshiBookBucket).filter_by(folder_id="folderD").one()
        assert discard_bucket(db, bucket.id)
        db.refresh(bucket)
        assert bucket.pending_chars == 0
        assert (
            db.query(HoshiSessionFragment)
            .filter_by(bucket_id=bucket.id, status="discarded")
            .count()
            == 1
        )
    finally:
        db.close()


def test_ingest_book_days_buckets_not_immediate_log(client):
    from app.core.config import get_settings

    get_settings().yaml_config.hoshi.log_mode = "manual"
    get_settings().yaml_config.hoshi.bootstrap = False
    get_settings().yaml_config.hoshi.min_characters = 1

    db = _db()
    try:
        book = BookFolder(id="driveFolder1", name="Novel", title="Novel")
        days = parse_statistics_json(
            [
                {
                    "title": "Novel",
                    "dateKey": "2026-07-25",
                    "charactersRead": 400,
                    "readingTime": 100,
                    "lastStatisticModified": 1,
                }
            ]
        )
        # First sight baselines (bootstrap false) — no pending
        r1 = ingest_book_days(db, book, days, bootstrap=False, min_characters=1)
        assert r1.sessions_added == 0
        assert r1.logs_created == 0

        days2 = parse_statistics_json(
            [
                {
                    "title": "Novel",
                    "dateKey": "2026-07-25",
                    "charactersRead": 750,
                    "readingTime": 200,
                    "lastStatisticModified": 2,
                }
            ]
        )
        r2 = ingest_book_days(db, book, days2, bootstrap=False, min_characters=1)
        assert r2.sessions_added == 1
        assert r2.chars_bucketed == 350
        assert r2.logs_created == 0

        bucket = db.query(HoshiBookBucket).filter_by(folder_id="driveFolder1").one()
        assert bucket.pending_chars == 350
        dash = reading_dashboard(db)
        assert dash["pending_book_count"] >= 1
        assert dash["total_pending_chars"] >= 350
        assert dash["total_unlogged_chars"] >= 350
        # Unlogged buffer is not yet in Tadoku queue
        assert dash["total_tadoku_awaiting_chars"] == 0
        row = next(b for b in dash["buckets"] if b["folder_id"] == "driveFolder1")
        assert row["lifetime_chars"] == row["total_logged_chars"]
        assert row["unlogged_chars"] == 350
        assert row["tadoku_awaiting_chars"] == 0
    finally:
        db.close()


def test_reading_api_endpoints(client):
    from app.core.config import get_settings

    get_settings().yaml_config.hoshi.log_mode = "manual"
    db = _db()
    try:
        add_session_fragment(
            db,
            folder_id="apiFolder",
            title="API Book",
            date_key="2026-07-25",
            chars=80,
            remote_total_for_day=80,
        )
        bucket = db.query(HoshiBookBucket).filter_by(folder_id="apiFolder").one()
    finally:
        db.close()

    r = client.get("/api/hoshi/reading")
    assert r.status_code == 200
    body = r.json()
    assert "buckets" in body
    assert body["log_mode"] in ("manual", "auto")

    r2 = client.post(f"/api/hoshi/buckets/{bucket.id}/submit")
    assert r2.status_code == 200
    assert r2.json()["amount"] == 80

    page = client.get("/reading")
    assert page.status_code == 200
    assert b"Reading" in page.content
    assert b"Tadoku" in page.content or b"Progress" in page.content


def test_series_key_for_title_stable():
    assert series_key_for_title("  夜は短し  ") == series_key_for_title("夜は短し")
    assert series_key_for_title("Combine Novel") == "book:combine-novel"


def test_prefs_and_per_book_threshold(client):
    from app.core.config import get_settings
    from app.ingest.hoshi_buckets import (
        add_session_fragment,
        get_log_mode,
        effective_min_submit,
        process_auto_submit_idle_buckets,
    )
    from app.db.models import utcnow
    from datetime import timedelta

    get_settings().yaml_config.hoshi.log_mode = "manual"
    get_settings().yaml_config.hoshi.min_submit_characters = 500
    get_settings().yaml_config.hoshi.auto_submit_idle_minutes = 0

    r = client.patch("/api/hoshi/settings", json={"log_mode": "auto", "min_submit_characters": 400})
    assert r.status_code == 200
    assert r.json()["log_mode"] == "auto"
    assert r.json()["min_submit_characters"] == 400

    db = _db()
    try:
        assert get_log_mode(db) == "auto"
        add_session_fragment(
            db,
            folder_id="thrBook",
            title="Thr Book",
            date_key="2026-07-25",
            chars=100,
            remote_total_for_day=100,
        )
        bucket = db.query(HoshiBookBucket).filter_by(folder_id="thrBook").one()
        # global 400 → not ready
        assert effective_min_submit(db, bucket) == 400
        r2 = client.patch(
            f"/api/hoshi/buckets/{bucket.id}",
            json={"min_submit_characters": 80},
        )
        assert r2.status_code == 200
        assert r2.json()["bucket"]["min_submit_characters"] == 80
        db.refresh(bucket)
        assert effective_min_submit(db, bucket) == 80
        # with idle 0 and threshold 80, next process should submit
        bucket.last_session_at = utcnow() - timedelta(minutes=1)
        db.commit()
        get_settings().yaml_config.hoshi.auto_submit_idle_minutes = 0
        # prefs idle still 30 from yaml default unless we set it
        client.patch("/api/hoshi/settings", json={"auto_submit_idle_minutes": 0})
        submitted = process_auto_submit_idle_buckets(db)
        assert len(submitted) == 1
        assert submitted[0]["amount"] == 100
    finally:
        db.close()


def test_consolidate_merges_open_logs_into_one(client):
    """Log-to-Tadoku path must combine multi-day open logs into a single entry."""
    from app.ingest.hoshi_buckets import (
        get_or_create_bucket,
        consolidate_bucket_for_tadoku,
    )
    from app.ingest.service import create_log

    db = _db()
    try:
        title = "Combine Novel"
        bucket = get_or_create_bucket(db, folder_id="combineBook", title=title)
        db.commit()
        sk = bucket.series_key
        a = create_log(
            db,
            content_type="book",
            title=title,
            source="hoshi",
            amount=1000,
            unit="characters",
            activity="reading",
            series_key=sk,
            source_ref="hoshi:combine:a",
        )
        b = create_log(
            db,
            content_type="book",
            title=title,
            source="hoshi",
            amount=500,
            unit="characters",
            activity="reading",
            series_key=sk,
            source_ref="hoshi:combine:b",
        )
        assert a.series_key == b.series_key == sk
        a.tadoku_status = "failed"
        b.tadoku_status = "failed"
        db.commit()

        combined = consolidate_bucket_for_tadoku(db, bucket.id)
        assert combined is not None
        assert float(combined.amount) == 1500.0
        db.refresh(a)
        db.refresh(b)
        # Old open logs are skipped as merged
        assert a.tadoku_status == "skipped" or a.id == combined.id
        assert b.tadoku_status == "skipped" or b.id == combined.id
        open_left = (
            db.query(LogEntry)
            .filter(
                LogEntry.series_key == sk,
                LogEntry.source == "hoshi",
                LogEntry.tadoku_status.in_(["pending", "ready", "failed"]),
            )
            .all()
        )
        assert len(open_left) == 1
        assert float(open_left[0].amount) == 1500.0
    finally:
        db.close()


@pytest.mark.parametrize("bucket_key", ["hoshi:Legacy Novel", "book:legacy-novel"])
@pytest.mark.parametrize("log_keys", [
    ("book:legacy-novel", "book:legacy-novel"),
    ("hoshi:Legacy Novel", "hoshi:Legacy Novel"),
    ("hoshi:Legacy Novel", "book:legacy-novel"),
])
def test_consolidate_legacy_key_variants(client, monkeypatch, bucket_key, log_keys):
    from app.core.config import get_settings
    from app.ingest.hoshi_buckets import (
        backfill_logged_totals_from_logs, bucket_to_dict,
        consolidate_bucket_for_tadoku, log_all_to_tadoku,
    )
    from app.ingest.service import create_log

    get_settings().yaml_config.hoshi.log_mode = "manual"
    db = _db()
    try:
        bucket, fragment, _ = add_session_fragment(
            db, folder_id="legacy", title="Legacy Novel",
            date_key="2026-07-25", chars=25,
        )
        bucket.series_key = bucket_key
        db.commit()
        originals = []
        for i, (key, amount) in enumerate(zip(log_keys, (100, 50))):
            entry = create_log(
                db, content_type="book", title=bucket.title, source="hoshi",
                amount=amount, unit="characters", activity="reading",
                series_key=key, source_ref=f"hoshi:legacy:{i}",
            )
            # Simulate persisted logs from before identity normalization.
            entry.series_key = key
            entry.tadoku_status = "failed"
            originals.append(entry)
        db.commit()

        before = reading_dashboard(db)
        before_row = next(b for b in before["buckets"] if b["id"] == bucket.id)
        assert before_row["total_logged_chars"] == before_row["lifetime_chars"] == 150
        assert before_row["submit_count"] == 2
        assert before_row["last_log_id"] == originals[-1].id
        assert backfill_logged_totals_from_logs(db) == 0
        row = bucket_to_dict(db, bucket)
        assert row["tadoku_awaiting_chars"] == 150
        assert {log["id"] for log in row["logs"]} == {entry.id for entry in originals}
        # Bulk eligibility must also find these logs without a pending buffer.
        pending = bucket.pending_chars
        bucket.pending_chars = 0
        calls = []
        monkeypatch.setattr(
            "app.ingest.hoshi_buckets.log_bucket_to_tadoku",
            lambda db, bucket_id: calls.append(bucket_id) or {},
        )
        assert log_all_to_tadoku(db)["books"] == 1
        assert calls == [bucket.id]
        bucket.pending_chars = pending
        combined = consolidate_bucket_for_tadoku(db, bucket.id)
        assert combined.amount == 175
        assert combined.unit == "characters"
        assert combined.series_key == "book:legacy-novel"
        assert bucket.series_key == bucket_key  # No historical key migration.
        assert bucket.pending_chars == 0
        assert bucket.total_logged_chars == 175  # Consolidation adds no credit.
        assert fragment.status == "logged"
        for entry, key in zip(originals, log_keys):
            db.refresh(entry)
            assert entry.series_key == key
            assert entry.tadoku_status == "skipped"
        count = db.query(LogEntry).count()
        snapshots = [(e.id, e.series_key, e.amount, e.notes, e.tadoku_status)
                     for e in db.query(LogEntry).order_by(LogEntry.id).all()]
        for _ in range(2):
            after = reading_dashboard(db)
            after_row = next(b for b in after["buckets"] if b["id"] == bucket.id)
            assert after_row["total_logged_chars"] == after_row["lifetime_chars"] == 175
            assert after_row["tadoku_awaiting_chars"] == 175
            assert after_row["submit_count"] == 3
            assert after_row["last_log_id"] == combined.id
            assert backfill_logged_totals_from_logs(db) == 0
        assert [(e.id, e.series_key, e.amount, e.notes, e.tadoku_status)
                for e in db.query(LogEntry).order_by(LogEntry.id).all()] == snapshots
        assert consolidate_bucket_for_tadoku(db, bucket.id).id == combined.id
        assert submit_bucket(db, bucket.id, force=True) is None
        assert db.query(LogEntry).count() == count
    finally:
        db.close()


def test_consolidate_excludes_submitted_inflight_and_unrelated_logs(client):
    from app.ingest.hoshi_buckets import get_or_create_bucket, consolidate_bucket_for_tadoku
    from app.ingest.service import create_log

    db = _db()
    try:
        bucket = get_or_create_bucket(db, folder_id="safe", title="Safe Novel")
        db.commit()
        excluded = []
        variants = [
            ("hoshi", "characters", bucket.series_key, "pushed", None),
            ("hoshi", "characters", bucket.series_key, "failed", "remote-123"),
            ("hoshi", "characters", bucket.series_key, "ready", "inflight:abc"),
            ("hoshi", "characters", bucket.series_key, "skipped", None),
            ("hoshi", "characters", "book:another-novel", "pending", None),
            ("hoshi", "characters", "custom:catalog-work", "pending", None),
            ("manual", "characters", bucket.series_key, "pending", None),
            ("hoshi", "minutes", bucket.series_key, "pending", None),
        ]
        for i, (source, unit, key, status, remote) in enumerate(variants):
            entry = create_log(
                db, content_type="book", title=bucket.title, source=source,
                amount=1000, unit=unit, activity="reading", series_key=key,
                source_ref=f"hoshi:excluded:{i}",
            )
            entry.series_key = key
            entry.tadoku_status = status
            entry.tadoku_remote_id = remote
            excluded.append(entry)
        db.commit()
        # With only excluded rows, even single-log failure reset must not run.
        assert consolidate_bucket_for_tadoku(db, bucket.id) is None
        for i, amount in enumerate((100, 50)):
            entry = create_log(
                db, content_type="book", title=bucket.title, source="hoshi",
                amount=amount, unit="characters", activity="reading",
                series_key=bucket.series_key, source_ref=f"hoshi:safe:{i}",
            )
            entry.tadoku_remote_id = "" if i else None
        db.commit()
        combined = consolidate_bucket_for_tadoku(db, bucket.id)
        assert combined.amount == 150
        for entry, (_, unit, key, status, remote) in zip(excluded, variants):
            db.refresh(entry)
            assert (entry.unit, entry.series_key, entry.tadoku_status, entry.tadoku_remote_id) == (
                unit, key, status, remote,
            )
    finally:
        db.close()


def test_catalog_link_survives_title_changes_and_consolidation(client):
    from app.core.config import get_settings
    from app.ingest.hoshi_buckets import (
        get_or_create_bucket, update_bucket_settings, consolidate_bucket_for_tadoku,
    )
    from app.ingest.service import create_log

    get_settings().yaml_config.hoshi.log_mode = "manual"
    db = _db()
    try:
        bucket = get_or_create_bucket(db, folder_id="linked", title="Old Title")
        bucket.series_key = "book:catalog-linked-work"
        db.commit()
        get_or_create_bucket(db, folder_id="linked", title="Poll Title")
        assert bucket.series_key == "book:catalog-linked-work"
        update_bucket_settings(db, bucket.id, title="UI Title")
        assert bucket.series_key == "book:catalog-linked-work"
        unrelated = create_log(
            db, content_type="book", title=bucket.title, source="hoshi",
            amount=1000, unit="characters", activity="reading",
            series_key=series_key_for_title(bucket.title), source_ref="hoshi:unlinked",
        )
        for i, chars in enumerate((100, 50)):
            add_session_fragment(
                db, folder_id=bucket.folder_id, title=bucket.title,
                date_key=f"2026-07-{25 + i}", chars=chars,
            )
            assert submit_bucket(db, bucket.id, force=True).series_key == bucket.series_key
        combined = consolidate_bucket_for_tadoku(db, bucket.id)
        assert combined.amount == 150
        assert combined.series_key == bucket.series_key
        db.refresh(unrelated)
        assert unrelated.tadoku_status == "pending"
    finally:
        db.close()


@pytest.mark.parametrize("bucket_key", ["hoshi:History Novel", "book:history-novel"])
def test_backfill_mixed_keys_preserves_latest_metadata(client, bucket_key):
    from datetime import datetime, timezone

    from app.ingest.hoshi_buckets import (
        backfill_logged_totals_from_logs, get_or_create_bucket,
    )
    from app.ingest.service import create_log

    db = _db()
    try:
        bucket = get_or_create_bucket(db, folder_id="history", title="History Novel")
        bucket.series_key = bucket_key
        entries = []
        for i, (key, notes, status) in enumerate([
            ("hoshi:History Novel", "pos 900/1000", "pushed"),
            ("book:history-novel", "pos 400/1000", "skipped"),
            ("hoshi:History Novel", None, "failed"),
        ]):
            entry = create_log(
                db, content_type="book", title=bucket.title, source="hoshi",
                amount=100, unit="characters", activity="reading",
                series_key=key, source_ref=f"hoshi:history:{i}", notes=notes,
                # Reading dates run backward; insertion order still determines
                # the latest log and latest available position across keys.
                timestamp=datetime(2026, 7, 25 - i, tzinfo=timezone.utc),
            )
            entry.series_key = key
            entry.tadoku_status = status
            entries.append(entry)
        # Total is already correct: metadata must still reconcile independently.
        bucket.total_logged_chars = 300
        bucket.submit_count = 1
        bucket.last_log_id = entries[0].id
        bucket.last_logged_position_chars = 900
        db.commit()

        assert backfill_logged_totals_from_logs(db) == 1
        db.refresh(bucket)
        assert bucket.total_logged_chars == 300  # Ordinary skipped logs count.
        assert bucket.submit_count == 3
        assert bucket.last_log_id == entries[-1].id
        assert bucket.last_logged_position_chars == 400
        assert bucket.series_key == bucket_key
        assert backfill_logged_totals_from_logs(db) == 0
        row = next(b for b in reading_dashboard(db)["buckets"] if b["id"] == bucket.id)
        assert row["last_log_id"] == entries[-1].id
        assert row["last_logged_position_chars"] == 400
    finally:
        db.close()


def test_backfill_custom_link_requires_exact_key(client):
    from app.ingest.hoshi_buckets import (
        backfill_logged_totals_from_logs, get_or_create_bucket,
    )
    from app.ingest.service import create_log

    db = _db()
    try:
        bucket = get_or_create_bucket(db, folder_id="custom", title="Shared Title")
        bucket.series_key = "book:catalog-linked-work"
        bucket.last_logged_position_chars = 77
        db.commit()
        for i, key in enumerate(["book:shared-title", "hoshi:Shared Title", None]):
            entry = create_log(
                db, content_type="book", title=bucket.title, source="hoshi",
                amount=1000, unit="characters", activity="reading",
                series_key=key, source_ref=f"hoshi:custom-unrelated:{i}", notes="pos 900",
            )
            entry.series_key = key
        db.commit()
        assert backfill_logged_totals_from_logs(db) == 0
        row = next(b for b in reading_dashboard(db)["buckets"] if b["id"] == bucket.id)
        assert row["total_logged_chars"] == row["submit_count"] == 0
        assert row["last_log_id"] is None
        assert row["last_logged_position_chars"] == 77

        exact = create_log(
            db, content_type="book", title="Different Catalog Title", source="hoshi",
            amount=75, unit="characters", activity="reading",
            series_key=bucket.series_key, source_ref="hoshi:custom-exact",
        )
        assert backfill_logged_totals_from_logs(db) == 1
        db.refresh(bucket)
        assert bucket.total_logged_chars == 75
        assert bucket.submit_count == 1
        assert bucket.last_log_id == exact.id
        assert bucket.last_logged_position_chars == 77  # No new position in notes.
        assert backfill_logged_totals_from_logs(db) == 0
    finally:
        db.close()


def test_backfill_logged_from_existing_log(client):
    from app.ingest.hoshi_buckets import (
        get_or_create_bucket,
        backfill_logged_totals_from_logs,
        reading_dashboard,
    )
    from app.ingest.service import create_log

    db = _db()
    try:
        title = "斬魔大聖デモンベイン 機神胎動 (角川スニーカー文庫)"
        bucket = get_or_create_bucket(db, folder_id="demBook", title=title)
        db.commit()
        create_log(
            db,
            content_type="book",
            title=title,
            source="hoshi",
            amount=2846,
            unit="characters",
            activity="reading",
            series_key=bucket.series_key,
            source_ref="hoshi:legacy:2846",
        )
        n = backfill_logged_totals_from_logs(db)
        assert n >= 1
        db.refresh(bucket)
        assert bucket.total_logged_chars == 2846
        dash = reading_dashboard(db)
        row = next(b for b in dash["buckets"] if b["folder_id"] == "demBook")
        assert row["total_logged_chars"] == 2846
        assert row["lifetime_chars"] == 2846
        # Formal log is in Tadoku queue, not Hoshi buffer
        assert row["tadoku_awaiting_chars"] == 2846
        assert row["tadoku_pushed_chars"] == 0
        assert row.get("unlogged_chars", 0) == 0
        assert row["tadoku_awaiting_score"] > 0
        assert row["tadoku_pushed_score"] == 0
        assert isinstance(row.get("logs"), list)
        assert len(row["logs"]) >= 1
        assert row["logs"][0]["chars"] == 2846
    finally:
        db.close()
