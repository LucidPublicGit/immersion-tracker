from __future__ import annotations


def test_manual_book_pending(client):
    r = client.post(
        "/api/logs",
        json={
            "content_type": "book",
            "title": "こころ",
            "amount": 12,
            "unit": "pages",
            "series_key": "book:kokoro",
        },
    )
    assert r.status_code == 201
    data = r.json()
    assert data["tadoku_mode"] == "pending"
    assert data["tadoku_status"] == "pending"
    assert data["tadoku_score_estimate"] == 12.0


def test_catalog_override_to_never(client):
    client.post(
        "/api/catalog",
        json={
            "series_key": "book:skipme",
            "display_title": "Skip Book",
            "content_type": "book",
            "tadoku_override": "never",
        },
    )
    r = client.post(
        "/api/logs",
        json={
            "content_type": "book",
            "title": "Skip Book ch1",
            "amount": 5,
            "series_key": "book:skipme",
        },
    )
    assert r.status_code == 201
    assert r.json()["tadoku_status"] == "skipped"


def test_approve_and_process_queue(client, tmp_path, monkeypatch):
    from app.tadoku.client import TadokuClient

    export = tmp_path / "export"
    export.mkdir()
    monkeypatch.setattr(
        "app.tadoku.queue.TadokuClient",
        lambda: TadokuClient(export_dir=str(export), dry_run=True),
    )

    r = client.post(
        "/api/logs",
        json={
            "content_type": "anime",
            "title": "Show S01E01",
            "amount": 24,
            "series_key": "anime:show",
        },
    )
    log_id = r.json()["id"]
    assert r.json()["tadoku_status"] == "pending"

    # Approve auto-submits when auto_submit_on_approve is true (dry_run export)
    ap = client.post(f"/api/logs/{log_id}/approve")
    assert ap.json()["tadoku_status"] == "pushed"
    assert ap.json()["tadoku_remote_id"]
    assert list(export.glob("*.json"))


def test_recent_tadoku_logs_local_only(client, tmp_path, monkeypatch):
    """GET /api/tadoku/recent lists pushed logs from local DB (no tadoku.app)."""
    from app.tadoku.client import TadokuClient

    export = tmp_path / "export"
    export.mkdir()
    monkeypatch.setattr(
        "app.tadoku.queue.TadokuClient",
        lambda: TadokuClient(export_dir=str(export), dry_run=True),
    )

    empty = client.get("/api/tadoku/recent").json()
    assert empty == []

    # Pending only — must not appear in recent
    pending = client.post(
        "/api/logs",
        json={
            "content_type": "book",
            "title": "Still pending",
            "amount": 5,
            "unit": "pages",
            "series_key": "book:pending-recent",
        },
    ).json()
    assert pending["tadoku_status"] == "pending"

    pushed = client.post(
        "/api/logs",
        json={
            "content_type": "anime",
            "title": "Recent Show",
            "amount": 22,
            "series_key": "anime:recent-show",
            "season": 1,
            "episode": 3,
        },
    ).json()
    log_id = pushed["id"]
    ap = client.post(f"/api/logs/{log_id}/approve")
    assert ap.json()["tadoku_status"] == "pushed"
    remote = ap.json()["tadoku_remote_id"]

    recent = client.get("/api/tadoku/recent?limit=10").json()
    ids = [row["id"] for row in recent]
    assert log_id in ids
    assert pending["id"] not in ids
    row = next(r for r in recent if r["id"] == log_id)
    assert row["tadoku_status"] == "pushed"
    assert row["tadoku_remote_id"] == remote
    assert row.get("updated_at")
    assert "Recent Show" in (row.get("tadoku_title") or row["title"])


def test_recent_tadoku_logs_order_by_timestamp(client, tmp_path, monkeypatch):
    """Recent list is by immersion timestamp, not updated_at (progress imports)."""
    from datetime import datetime, timedelta, timezone

    from sqlalchemy.orm import sessionmaker

    from app.db.models import LogEntry, TadokuStatus, utcnow
    from app.db.session import get_engine
    from app.tadoku.client import TadokuClient

    export = tmp_path / "export"
    export.mkdir()
    monkeypatch.setattr(
        "app.tadoku.queue.TadokuClient",
        lambda: TadokuClient(export_dir=str(export), dry_run=True),
    )

    # Fresh approve → recent immersion
    fresh = client.post(
        "/api/logs",
        json={
            "content_type": "anime",
            "title": "Fresh Show",
            "amount": 24,
            "series_key": "anime:fresh-show",
            "season": 1,
            "episode": 1,
        },
    ).json()
    client.post(f"/api/logs/{fresh['id']}/approve")

    # Simulate a progress-import: old timestamp, but updated_at just now
    old_ts = datetime(2020, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
    SessionLocal = sessionmaker(bind=get_engine(), autoflush=False, autocommit=False)
    db = SessionLocal()
    try:
        old = LogEntry(
            content_type="anime",
            title="Ancient Progress Import",
            amount=24,
            unit="minutes",
            source="tadoku",
            source_ref="tadoku:import-old-1",
            series_key="anime:ancient",
            activity="listening",
            tadoku_mode="never",
            tadoku_status=TadokuStatus.PUSHED.value,
            tadoku_remote_id="import-old-1",
            tadoku_score_estimate=1.0,
            timestamp=old_ts,
            created_at=utcnow(),
            updated_at=utcnow() + timedelta(hours=1),  # newer than fresh submit
        )
        db.add(old)
        db.commit()
        db.refresh(old)
        old_id = old.id
    finally:
        db.close()

    recent = client.get("/api/tadoku/recent?limit=20").json()
    ids = [row["id"] for row in recent]
    assert fresh["id"] in ids
    assert old_id in ids
    # Fresh immersion must rank above the old imported log
    assert ids.index(fresh["id"]) < ids.index(old_id)
    # Strict timestamp order among these two
    by_id = {row["id"]: row for row in recent}
    assert by_id[fresh["id"]]["timestamp"] > by_id[old_id]["timestamp"]


def test_metrics(client):
    client.post(
        "/api/logs",
        json={"content_type": "youtube", "title": "a", "amount": 10, "source": "manual"},
    )
    m = client.get("/api/metrics").json()
    assert m["total_logs"] >= 1
    assert m["total_minutes"] >= 10
    assert m["total_hours"] == round(m["total_minutes"] / 60.0, 2)
    assert "by_unit" in m
    assert "by_activity" in m
    assert m["by_unit"].get("minutes", 0) >= 10 or any(
        k in m["by_unit"] for k in ("minutes", "minutes_high_density")
    )


def test_metrics_timeline(client):
    client.post(
        "/api/logs",
        json={
            "content_type": "youtube",
            "title": "timeline-yt",
            "amount": 30,
            "source": "manual",
            "unit": "minutes",
            "activity": "listening",
        },
    )
    client.post(
        "/api/logs",
        json={
            "content_type": "book",
            "title": "timeline-book",
            "amount": 5000,
            "source": "manual",
            "unit": "characters",
            "activity": "reading",
        },
    )
    t = client.get("/api/metrics/timeline").json()
    assert "year" in t
    assert "days" in t
    assert "totals" in t
    assert t["totals"]["hours"] >= 0.5
    assert t["totals"]["characters"] >= 5000
    assert any(d["hours"] > 0 or d["characters"] > 0 for d in t["days"])


def test_process_ready_promotes_auto_pending_then_submits(client, tmp_path, monkeypatch):
    from app.db.session import get_db
    from app.tadoku.client import TadokuClient
    from app.tadoku import queue as tadoku_queue

    export = tmp_path / "export"
    export.mkdir()
    monkeypatch.setattr(
        "app.tadoku.queue.TadokuClient",
        lambda: TadokuClient(export_dir=str(export), dry_run=True),
    )

    r = client.post(
        "/api/logs",
        json={
            "content_type": "anime",
            "title": "Auto Show",
            "amount": 24,
            "series_key": "anime:autoshow",
            "tadoku_mode": "pending",
        },
    )
    log_id = r.json()["id"]
    # Simulate sheet edit: mode=auto but status left as pending
    db = next(get_db())
    try:
        from app.db.models import LogEntry

        e = db.get(LogEntry, log_id)
        e.tadoku_mode = "auto"
        e.tadoku_status = "pending"
        db.commit()
        result = tadoku_queue.process_ready(db)
    finally:
        db.close()

    assert result["promoted_auto"] >= 1
    assert result["pushed"] >= 1
    check = client.get(f"/api/logs/{log_id}").json()
    assert check["tadoku_status"] == "pushed"
    assert check["tadoku_remote_id"]


def test_no_double_submit_approve_then_process_ready(client, tmp_path, monkeypatch):
    """Approve auto-submit + process_ready must not POST twice."""
    from app.db.session import get_db
    from app.tadoku.client import TadokuClient
    from app.tadoku import queue as tadoku_queue

    export = tmp_path / "export"
    export.mkdir()
    monkeypatch.setattr(
        "app.tadoku.queue.TadokuClient",
        lambda: TadokuClient(export_dir=str(export), dry_run=True),
    )

    r = client.post(
        "/api/logs",
        json={
            "content_type": "youtube",
            "title": "Double-check YT",
            "amount": 10,
            "source": "youtube",
            "series_key": "yt:double",
        },
    )
    log_id = r.json()["id"]

    ap = client.post(f"/api/logs/{log_id}/approve")
    assert ap.json()["tadoku_status"] == "pushed"
    remote = ap.json()["tadoku_remote_id"]
    assert remote
    first_exports = list(export.glob("*.json"))
    assert len(first_exports) == 1

    db = next(get_db())
    try:
        # Second path that used to double-log: scheduler process_ready
        result = tadoku_queue.process_ready(db)
        # May count as pushed with already_submitted note, or skipped — never new POST
        assert result["failed"] == 0
    finally:
        db.close()

    # Still only one export file (one Tadoku create)
    assert len(list(export.glob("*.json"))) == 1
    check = client.get(f"/api/logs/{log_id}").json()
    assert check["tadoku_status"] == "pushed"
    assert check["tadoku_remote_id"] == remote


def test_no_double_submit_when_remote_id_already_set(client, tmp_path, monkeypatch):
    """If remote_id is set, never POST again even if status drifted to ready."""
    from app.db.session import get_db
    from app.tadoku.client import TadokuClient
    from app.tadoku import queue as tadoku_queue

    export = tmp_path / "export"
    export.mkdir()
    monkeypatch.setattr(
        "app.tadoku.queue.TadokuClient",
        lambda: TadokuClient(export_dir=str(export), dry_run=True),
    )

    r = client.post(
        "/api/logs",
        json={
            "content_type": "youtube",
            "title": "Already on Tadoku",
            "amount": 5,
            "source": "youtube",
        },
    )
    log_id = r.json()["id"]
    db = next(get_db())
    try:
        from app.db.models import LogEntry

        e = db.get(LogEntry, log_id)
        e.tadoku_status = "ready"
        e.tadoku_remote_id = "existing-remote-abc"
        db.commit()
        result = tadoku_queue.process_ready(db)
    finally:
        db.close()

    assert len(list(export.glob("*.json"))) == 0
    check = client.get(f"/api/logs/{log_id}").json()
    assert check["tadoku_status"] == "pushed"
    assert check["tadoku_remote_id"] == "existing-remote-abc"
    assert result["failed"] == 0
