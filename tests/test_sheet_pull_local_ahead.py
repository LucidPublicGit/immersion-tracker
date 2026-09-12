"""Sheet pull must not overwrite unpushed local edits (relink / catalog)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.db.models import CatalogItem, LogEntry, utcnow
from app.db.session import get_engine
from app.media.catalog_resolve import relink_logs_to_catalog
from app.sheets.state import (
    is_row_local_ahead,
    is_sheets_dirty,
    mark_sheets_dirty,
    set_last_push_at,
)
from app.sheets.sync import _pull_log_rows_from_values
from sqlalchemy.orm import sessionmaker


def _session():
    return sessionmaker(bind=get_engine(), autoflush=False, autocommit=False)()


def test_is_row_local_ahead_after_last_push(client):
    db = _session()
    try:
        past = datetime(2026, 1, 1, tzinfo=timezone.utc)
        set_last_push_at(db, "logs", past)
        assert is_row_local_ahead(db, utcnow(), scope="logs") is True
        assert is_row_local_ahead(db, past - timedelta(hours=1), scope="logs") is False
    finally:
        db.close()


def test_pull_does_not_overwrite_relinked_title(client):
    """
    Simulate: push baseline → plex log → relink JP title → sheet still has English.
    Pull must keep JP title until the next successful push.
    """
    db = _session()
    try:
        # Last push was in the past (DB and sheet were in sync)
        set_last_push_at(db, "logs", datetime(2026, 6, 1, tzinfo=timezone.utc))

        log = LogEntry(
            content_type="anime",
            title="My Hero Academia",
            series_key="anime:my-hero-academia",
            source="plex",
            source_ref="pull-test-1",
            amount=24,
            unit="minutes",
            activity="listening",
            tadoku_mode="pending",
            tadoku_status="pending",
            tadoku_score_estimate=9.6,
        )
        db.add(log)
        cat = CatalogItem(
            series_key="anime:bnha",
            display_title="僕のヒーローアカデミア",
            content_type="anime",
            aliases="My Hero Academia",
            tadoku_override="auto",
        )
        db.add(cat)
        db.commit()
        db.refresh(log)

        # Relink like the catalog UI
        result = relink_logs_to_catalog(db, cat)
        assert result["updated"] >= 1
        db.refresh(log)
        assert log.title == "僕のヒーローアカデミア"
        assert log.series_key == "anime:bnha"
        assert log.tadoku_mode == "auto"
        assert is_sheets_dirty(db)

        # Stale sheet row (still English title from before relink)
        headers = [
            "id",
            "timestamp",
            "content_type",
            "title",
            "season",
            "episode",
            "amount",
            "unit",
            "activity",
            "source",
            "series_key",
            "tadoku_mode",
            "tadoku_status",
            "notes",
        ]
        values = [
            headers,
            [
                str(log.id),
                "",
                "anime",
                "My Hero Academia",  # stale
                "",
                "",
                "24",
                "minutes",
                "listening",
                "plex",
                "anime:my-hero-academia",  # stale
                "pending",
                "pending",
                "",
            ],
        ]
        part = _pull_log_rows_from_values(db, values, allow_create=False)
        db.commit()
        db.refresh(log)

        assert part["skipped_local"] >= 1
        assert part["updated"] == 0
        assert log.title == "僕のヒーローアカデミア"
        assert log.series_key == "anime:bnha"
        assert log.tadoku_mode == "auto"
        assert log.tadoku_status == "ready"
    finally:
        db.close()


def test_pull_applies_sheet_after_push_baseline(client):
    """Once last push is after local edit, sheet edits apply again."""
    db = _session()
    try:
        log = LogEntry(
            content_type="anime",
            title="Local Title",
            series_key="anime:local",
            source="manual",
            source_ref="pull-test-2",
            amount=10,
            unit="minutes",
            activity="listening",
            tadoku_mode="pending",
            tadoku_status="pending",
            tadoku_score_estimate=4.0,
        )
        db.add(log)
        db.commit()
        db.refresh(log)

        # Simulate successful push after the local edit
        set_last_push_at(db, "logs", utcnow() + timedelta(seconds=1))

        values = [
            [
                "id",
                "title",
                "amount",
                "unit",
                "activity",
                "content_type",
                "series_key",
                "tadoku_mode",
                "tadoku_status",
            ],
            [
                str(log.id),
                "Sheet Edited Title",
                "10",
                "minutes",
                "listening",
                "anime",
                "anime:local",
                "pending",
                "pending",
            ],
        ]
        part = _pull_log_rows_from_values(db, values, allow_create=False)
        db.commit()
        db.refresh(log)

        assert part["skipped_local"] == 0
        assert part["updated"] >= 1
        assert log.title == "Sheet Edited Title"
    finally:
        db.close()


def test_catalog_link_marks_dirty(client):
    r = client.post(
        "/api/catalog/link",
        json={
            "series_key": "anime:dirtymark",
            "display_title": "Dirty JP",
            "content_type": "anime",
            "alias": "Dirty EN",
            "relink_logs": False,
        },
    )
    assert r.status_code == 200
    db = _session()
    try:
        assert is_sheets_dirty(db)
        item = (
            db.query(CatalogItem)
            .filter(CatalogItem.series_key == "anime:dirtymark")
            .one()
        )
        assert is_row_local_ahead(db, item.updated_at, scope="catalog")
    finally:
        db.close()


def test_delete_from_sheet_still_works_when_local_ahead(client):
    db = _session()
    try:
        set_last_push_at(db, "logs", datetime(2026, 1, 1, tzinfo=timezone.utc))
        log = LogEntry(
            content_type="book",
            title="Delete Me",
            source="manual",
            source_ref="pull-del-1",
            amount=1,
            unit="pages",
            activity="reading",
            tadoku_mode="never",
            tadoku_status="skipped",
            tadoku_score_estimate=0,
        )
        db.add(log)
        db.commit()
        log_id = log.id
        # Touch after last push
        log.title = "Delete Me Local"
        log.updated_at = utcnow()
        mark_sheets_dirty(db)
        db.commit()

        values = [
            ["id", "title", "amount"],
            [str(log_id), "", ""],  # delete marker
        ]
        part = _pull_log_rows_from_values(db, values, allow_create=False)
        db.commit()
        assert part["deleted"] == 1
        assert db.get(LogEntry, log_id) is None
    finally:
        db.close()
