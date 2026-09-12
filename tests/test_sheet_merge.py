from app.db.models import LogEntry
from app.sheets.merge import apply_log_fields, is_delete_row


def _entry(**kwargs):
    e = LogEntry(
        content_type="book",
        title="Old",
        source="manual",
        amount=10,
        unit="pages",
        activity="reading",
        tadoku_mode="pending",
        tadoku_status="pending",
        tadoku_score_estimate=10.0,
    )
    for k, v in kwargs.items():
        setattr(e, k, v)
    return e


def test_apply_updates_title_and_amount():
    e = _entry()
    changed = apply_log_fields(
        e,
        {"title": "New title", "amount": "20", "unit": "pages", "activity": "reading"},
    )
    assert e.title == "New title"
    assert e.amount == 20.0
    assert e.tadoku_score_estimate == 20.0
    assert "title" in changed
    assert "amount" in changed


def test_timestamp_roundtrip_tz_not_a_change():
    """Sheet may return +00:00 while SQLite stores naive UTC — not a real edit."""
    from datetime import datetime, timezone

    e = _entry(timestamp=datetime(2026, 7, 12, 22, 13, 37))
    changed = apply_log_fields(
        e, {"timestamp": "2026-07-12T22:13:37+00:00"}
    )
    assert "timestamp" not in changed

    e2 = _entry(timestamp=datetime(2026, 7, 12, 22, 13, 37, tzinfo=timezone.utc))
    changed2 = apply_log_fields(e2, {"timestamp": "2026-07-12T22:13:37"})
    assert "timestamp" not in changed2


def test_mode_auto_sets_ready_when_status_omitted():
    e = _entry()
    apply_log_fields(e, {"tadoku_mode": "auto"})
    assert e.tadoku_mode == "auto"
    assert e.tadoku_status == "ready"


def test_mode_auto_promotes_stale_pending_status_from_sheet():
    """Sheets always send both columns; stale pending must not block auto."""
    e = _entry(tadoku_mode="pending", tadoku_status="pending")
    apply_log_fields(e, {"tadoku_mode": "auto", "tadoku_status": "pending"})
    assert e.tadoku_mode == "auto"
    assert e.tadoku_status == "ready"


def test_status_skipped_sets_never():
    e = _entry()
    apply_log_fields(e, {"tadoku_status": "skipped"})
    assert e.tadoku_status == "skipped"
    assert e.tadoku_mode == "never"


def test_delete_row_detection():
    assert is_delete_row({"action": "delete", "title": "x", "amount": "1"})
    assert is_delete_row({"id": "1", "title": "", "amount": ""})
    assert not is_delete_row({"id": "1", "title": "x", "amount": "1"})


def test_never_downgrade_pushed_status_from_sheet():
    e = _entry(
        tadoku_status="pushed",
        tadoku_mode="pending",
        tadoku_remote_id="tadoku-abc",
    )
    changed = apply_log_fields(
        e,
        {
            "tadoku_status": "pending",
            "tadoku_mode": "pending",
            "tadoku_remote_id": "",
            "title": "Still pushed",
        },
    )
    assert e.tadoku_status == "pushed"
    assert e.tadoku_remote_id == "tadoku-abc"
    assert e.title == "Still pushed"
    assert "tadoku_status" not in changed
    assert "tadoku_remote_id" not in changed


def test_mode_change_does_not_unpush():
    e = _entry(tadoku_status="pushed", tadoku_mode="pending", tadoku_remote_id="x")
    apply_log_fields(e, {"tadoku_mode": "auto"})
    assert e.tadoku_status == "pushed"
    assert e.tadoku_remote_id == "x"


def test_upgrade_pending_to_pushed_from_sheet_allowed():
    e = _entry(tadoku_status="pending", tadoku_remote_id=None)
    changed = apply_log_fields(
        e, {"tadoku_status": "pushed", "tadoku_remote_id": "remote-1"}
    )
    assert e.tadoku_status == "pushed"
    assert e.tadoku_remote_id == "remote-1"
    assert "tadoku_status" in changed
