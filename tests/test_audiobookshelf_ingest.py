"""Audiobookshelf session → pending minutes → log (no live ABS)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings, reload_settings
from app.db.models import LogEntry
from app.db.session import get_engine, init_db
from app.ingest import audiobookshelf as abs_mod
from app.ingest.audiobookshelf import (
    STATE_BOOTSTRAPPED,
    STATE_PENDING,
    STATE_WATERMARKS,
    _absorb_sessions,
    build_preview,
    get_prefs,
    process_auto_export,
    process_daily_time_export,
    set_prefs,
    submit_pending,
)
from app.sheets.state import get_state, set_state


def _db():
    init_db()
    SessionLocal = sessionmaker(bind=get_engine(), autoflush=False, autocommit=False)
    return SessionLocal()


@pytest.fixture()
def db(monkeypatch):
    reload_settings()
    settings = get_settings()
    settings.yaml_config.audiobookshelf.enabled = True
    settings.yaml_config.audiobookshelf.bootstrap = True
    settings.yaml_config.audiobookshelf.min_session_seconds = 1
    settings.yaml_config.audiobookshelf.min_submit_minutes = 1
    settings.yaml_config.audiobookshelf.auto_submit_idle_minutes = 0
    settings.yaml_config.audiobookshelf.log_mode = "manual"
    settings.yaml_config.tadoku.live_submit = False
    monkeypatch.setattr(abs_mod, "poll_sessions", lambda db: {"ok": True, "skipped": True})
    session = _db()
    # Isolate ABS state on the shared test DB
    for key in (
        STATE_WATERMARKS,
        STATE_PENDING,
        STATE_BOOTSTRAPPED,
        abs_mod.STATE_SEEDED,
        abs_mod.STATE_PROGRESS_WM,
        abs_mod.STATE_LAST_DAILY,
        abs_mod.PREF_LOG_MODE,
        abs_mod.PREF_MIN_SUBMIT,
        abs_mod.PREF_IDLE,
        abs_mod.PREF_DAILY,
        abs_mod.PREF_HOUR,
    ):
        set_state(session, key, "")
    session.query(LogEntry).filter(LogEntry.source == "audiobookshelf").delete()
    session.commit()
    yield session
    session.close()


def _session(
    sid: str,
    item: str,
    seconds: float,
    *,
    title: str = "Test Book",
    media_type: str = "book",
    updated_at: int | None = None,
) -> dict:
    return {
        "id": sid,
        "libraryItemId": item,
        "libraryId": "lib1",
        "displayTitle": title,
        "displayAuthor": "Author",
        "mediaType": media_type,
        "timeListening": seconds,
        "updatedAt": updated_at or int(datetime.now(timezone.utc).timestamp() * 1000),
    }


def test_bootstrap_skips_history(db):
    s = _session("s1", "li1", 3600)
    out = _absorb_sessions(db, [s], bootstrap=True)
    assert out["bootstrapped"] is True
    assert out["absorbed_seconds"] == 0
    assert get_state(db, STATE_PENDING) in ("{}", None) or get_state(db, STATE_PENDING) == "{}"
    # watermarks stored
    assert "s1" in (get_state(db, STATE_WATERMARKS) or "")


def test_delta_then_submit(db):
    set_state(db, STATE_BOOTSTRAPPED, "true")
    _absorb_sessions(db, [_session("s1", "li1", 100)], bootstrap=True)
    out = _absorb_sessions(
        db,
        [_session("s1", "li1", 100 + 600)],  # +10 min
        bootstrap=False,
    )
    assert out["absorbed_seconds"] == pytest.approx(600)
    prev = build_preview(db, refresh=False)
    assert prev["total_pending_minutes"] == pytest.approx(10.0)
    assert prev["entries"][0]["meets_min"] is True

    result = submit_pending(db, keys=None)
    assert result["created_count"] == 1
    assert result.get("submitted") is not None
    logs = db.query(LogEntry).filter(LogEntry.source == "audiobookshelf").all()
    assert len(logs) == 1
    assert logs[0].amount == pytest.approx(10.0)
    assert logs[0].unit == "minutes_high_density"
    # ABS inbox approve auto-pushes (tadoku.auto_submit_on_approve)
    assert logs[0].tadoku_status == "pushed"
    # pending cleared
    assert build_preview(db, refresh=False)["total_pending_minutes"] == 0


def test_auto_export_respects_mode(db):
    set_state(db, STATE_BOOTSTRAPPED, "true")
    _absorb_sessions(db, [_session("s1", "li1", 0)], bootstrap=True)
    _absorb_sessions(db, [_session("s1", "li1", 600)], bootstrap=False)

    set_prefs(db, log_mode="manual")
    r = process_auto_export(db)
    assert r.get("reason") == "manual_mode"
    assert (
        db.query(LogEntry).filter(LogEntry.source == "audiobookshelf").count() == 0
    )

    set_prefs(db, log_mode="auto", min_submit_minutes=1, auto_submit_idle_minutes=0)
    r2 = process_auto_export(db)
    assert r2.get("created_count", 0) == 1


def test_daily_force(db):
    set_state(db, STATE_BOOTSTRAPPED, "true")
    _absorb_sessions(db, [_session("s1", "li1", 0)], bootstrap=True)
    _absorb_sessions(db, [_session("s1", "li1", 300)], bootstrap=False)  # 5 min
    set_prefs(db, min_submit_minutes=1, auto_log_at_time_enabled=False)
    r = process_daily_time_export(db, force=True)
    assert r.get("created_count") == 1
    assert r.get("daily") is True


def test_prefs_roundtrip(db):
    p = set_prefs(
        db,
        log_mode="auto",
        min_submit_minutes=12.5,
        auto_submit_idle_minutes=15,
        auto_log_at_time_enabled=True,
        auto_log_at_hour=6,
    )
    assert p["log_mode"] == "auto"
    assert p["min_submit_minutes"] == 12.5
    assert get_prefs(db)["auto_log_at_hour"] == 6
