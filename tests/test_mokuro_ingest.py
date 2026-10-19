"""Mokuro Reader volume-data.json page deltas."""

from __future__ import annotations

from app.db.models import LogEntry
from app.db.session import get_engine
from app.ingest.mokuro import (
    _title_for,
    _volume_num,
    fetch_page_counts,
    get_progress_watermark,
    parse_series_page_counts,
    parse_volume_data,
    poll_mokuro,
    set_progress_watermark,
)
from app.ingest.service import create_log
from sqlalchemy.orm import sessionmaker


def _db():
    SessionLocal = sessionmaker(bind=get_engine(), autoflush=False, autocommit=False)
    return SessionLocal()


def _enable(*, bootstrap: bool = False) -> None:
    from app.core.config import get_settings

    cfg = get_settings().yaml_config.mokuro
    cfg.enabled = True
    cfg.bootstrap = bootstrap
    cfg.min_pages = 1
    cfg.tadoku_default = "pending"
    cfg.content_type = "manga"
    cfg.unit = "comic_pages"


SAMPLE = {
    "vol-aaa": {
        "progress": 10,
        "chars": 4000,
        "completed": False,
        "series_title": "テスト漫画",
        "volume_title": "第1巻",
        "lastProgressUpdate": "2026-04-01T12:00:00Z",
    }
}


def test_parse_skips_series_and_tombstones():
    parsed = parse_volume_data(
        {
            "series": {"x": 1},
            "keep": {"progress": 3, "series_title": "A"},
            "gone": {"progress": 9, "deletedOn": "2026-01-01T00:00:00Z"},
            "": {"progress": 1},
        }
    )
    assert set(parsed) == {"keep"}


def test_title_is_series_volume_is_episode():
    rec = {"series_title": "Vagabond", "volume_title": "vagabond_05"}
    assert _title_for(rec, "uuid") == "Vagabond"
    assert _volume_num("vagabond_05") == 5
    assert _volume_num("第1巻") == 1
    assert _volume_num("Vol. 12") == 12
    assert _volume_num("05") == 5
    assert _volume_num("ドメスティックな彼女　よりぬきカラー版 （０４） (wangson)") == 4
    assert _volume_num("Series (12)") == 12
    assert _volume_num("第１７巻") == 17
    assert _volume_num("Series (uploader)") is None
    assert _volume_num("Series (More Color Version)") is None


def test_disabled(client):
    from app.core.config import get_settings

    get_settings().yaml_config.mokuro.enabled = False
    db = _db()
    try:
        r = poll_mokuro(db, snapshot=SAMPLE)
        assert r.ok is True
        assert r.message == "disabled"
        assert r.logs_created == 0
    finally:
        db.close()


def test_baseline_then_delta_pending(client):
    _enable(bootstrap=False)
    db = _db()
    try:
        r1 = poll_mokuro(db, snapshot=SAMPLE)
        assert r1.ok
        assert r1.logs_created == 0
        assert get_progress_watermark(db, "vol-aaa") == 10

        r2 = poll_mokuro(
            db,
            snapshot={
                "vol-aaa": {**SAMPLE["vol-aaa"], "progress": 25, "completed": True}
            },
        )
        assert r2.logs_created >= 1
        entry = db.query(LogEntry).filter(LogEntry.source == "mokuro").one()
        assert entry.amount == 25
        assert entry.unit == "comic_pages"
        assert abs(float(entry.tadoku_score_estimate) - 5.0) < 0.001
        assert "pages 0→25 (+25)" in (entry.notes or "")
        assert entry.content_type == "manga"
        assert entry.tadoku_mode == "pending"
        assert entry.tadoku_status == "pending"
        assert entry.title == "テスト漫画"
        assert entry.episode == 1
        assert "completed" in (entry.notes or "")
    finally:
        db.close()


def test_completed_fills_gap_when_already_at_watermark(client):
    _enable(bootstrap=False)
    db = _db()
    try:
        poll_mokuro(db, snapshot=SAMPLE)
        poll_mokuro(
            db,
            snapshot={"vol-aaa": {**SAMPLE["vol-aaa"], "progress": 25}},
        )
        entry = db.query(LogEntry).filter(LogEntry.source == "mokuro").one()
        assert entry.amount == 15
        r = poll_mokuro(
            db,
            snapshot={
                "vol-aaa": {**SAMPLE["vol-aaa"], "progress": 25, "completed": True}
            },
        )
        assert r.logs_created >= 1
        db.refresh(entry)
        assert entry.amount == 25
        assert "pages 0→25 (+25)" in (entry.notes or "")
    finally:
        db.close()


def test_rewind_resets_baseline(client):
    _enable(bootstrap=False)
    db = _db()
    try:
        poll_mokuro(db, snapshot=SAMPLE)
        poll_mokuro(
            db,
            snapshot={"vol-aaa": {**SAMPLE["vol-aaa"], "progress": 2}},
        )
        assert get_progress_watermark(db, "vol-aaa") == 2
        r = poll_mokuro(
            db,
            snapshot={"vol-aaa": {**SAMPLE["vol-aaa"], "progress": 8}},
        )
        assert r.logs_created == 1
        entry = db.query(LogEntry).filter(LogEntry.source == "mokuro").one()
        assert entry.amount == 6
    finally:
        db.close()


def test_pending_deltas_fold_same_volume(client):
    _enable(bootstrap=False)
    db = _db()
    try:
        poll_mokuro(db, snapshot=SAMPLE)
        poll_mokuro(
            db,
            snapshot={"vol-aaa": {**SAMPLE["vol-aaa"], "progress": 25}},
        )
        r = poll_mokuro(
            db,
            snapshot={"vol-aaa": {**SAMPLE["vol-aaa"], "progress": 40}},
        )
        assert r.logs_created == 1
        entry = db.query(LogEntry).filter(LogEntry.source == "mokuro").one()
        assert entry.amount == 30
        assert entry.source_ref == "mokuro:vol-aaa:40"
        assert entry.tadoku_status == "pending"
        assert "pages 10→40 (+30)" in (entry.notes or "")
    finally:
        db.close()


def test_new_log_after_push(client):
    _enable(bootstrap=False)
    db = _db()
    try:
        poll_mokuro(db, snapshot=SAMPLE)
        poll_mokuro(
            db,
            snapshot={"vol-aaa": {**SAMPLE["vol-aaa"], "progress": 25}},
        )
        entry = db.query(LogEntry).filter(LogEntry.source == "mokuro").one()
        entry.tadoku_status = "pushed"
        db.commit()
        r = poll_mokuro(
            db,
            snapshot={"vol-aaa": {**SAMPLE["vol-aaa"], "progress": 40}},
        )
        assert r.logs_created == 1
        logs = db.query(LogEntry).filter(LogEntry.source == "mokuro").all()
        assert len(logs) == 2
        by_status = {e.tadoku_status: e for e in logs}
        assert by_status["pushed"].amount == 15
        assert by_status["pending"].amount == 15
        assert by_status["pending"].source_ref == "mokuro:vol-aaa:40"
    finally:
        db.close()


def test_coalesce_existing_pending_same_volume(client):
    _enable(bootstrap=False)
    db = _db()
    try:
        poll_mokuro(db, snapshot=SAMPLE)
        create_log(
            db,
            content_type="manga",
            title="テスト漫画 第1巻",
            source="mokuro",
            amount=10,
            unit="comic_pages",
            activity="reading",
            source_ref="mokuro:vol-aaa:20",
            tadoku_mode_override="pending",
        )
        create_log(
            db,
            content_type="manga",
            title="テスト漫画 第1巻",
            source="mokuro",
            amount=15,
            unit="comic_pages",
            activity="reading",
            source_ref="mokuro:vol-aaa:35",
            tadoku_mode_override="pending",
        )
        set_progress_watermark(db, "vol-aaa", 35)
        r = poll_mokuro(
            db,
            snapshot={"vol-aaa": {**SAMPLE["vol-aaa"], "progress": 35}},
        )
        assert r.logs_created == 0
        entry = db.query(LogEntry).filter(LogEntry.source == "mokuro").one()
        assert entry.amount == 25
        assert entry.source_ref == "mokuro:vol-aaa:35"
        assert entry.title == "テスト漫画"
        assert entry.episode == 1
    finally:
        db.close()


def test_folder_slug_not_in_title(client):
    _enable(bootstrap=False)
    db = _db()
    snap = {
        "vol-aaa": {
            "progress": 10,
            "chars": 0,
            "series_title": "Vagabond",
            "volume_title": "vagabond_05",
            "lastProgressUpdate": "2026-04-01T12:00:00Z",
        }
    }
    try:
        poll_mokuro(db, snapshot=snap)
        poll_mokuro(
            db,
            snapshot={"vol-aaa": {**snap["vol-aaa"], "progress": 20}},
        )
        entry = db.query(LogEntry).filter(LogEntry.source == "mokuro").one()
        assert entry.title == "Vagabond"
        assert entry.episode == 5
        assert "vagabond_05" not in (entry.title or "").lower()
    finally:
        db.close()


def test_retitles_existing_folder_slug_log(client):
    _enable(bootstrap=False)
    db = _db()
    try:
        ugly = create_log(
            db,
            content_type="manga",
            title="Vagabond vagabond_05",
            source="mokuro",
            amount=10,
            unit="comic_pages",
            activity="reading",
            source_ref="mokuro:vol-aaa:20",
            tadoku_mode_override="pending",
            episode=None,
        )
        poll_mokuro(
            db,
            snapshot={
                "vol-aaa": {
                    "progress": 20,
                    "series_title": "Vagabond",
                    "volume_title": "vagabond_05",
                }
            },
        )
        db.refresh(ugly)
        assert ugly.title == "Vagabond"
        assert ugly.episode == 5
    finally:
        db.close()


def test_parse_series_page_counts():
    raw = {
        "volumes": [
            {"volume_uuid": "vol-aaa", "page_count": 196},
            {"volume_uuid": "zero", "page_count": 0},
            {"volume_title": "no-id", "page_count": 10},
        ]
    }
    assert parse_series_page_counts(raw) == {"vol-aaa": 196}
    assert parse_series_page_counts("{") == {}


class _DriveFile:
    def __init__(self, file_id: str, name: str, parents: list[str]):
        self.id = file_id
        self.name = name
        self.parents = parents


class _PageCountDrive:
    def find_root_folder(self, *, folder_id: str = "", folder_name: str = ""):
        return "root-1"

    def list_files(self, query: str, *, fields: str = ""):
        if "mimeType" in query:
            return [_DriveFile("folder-vagabond", "Vagabond", ["root-1"])]
        if "series.json" in query:
            return [
                _DriveFile("good", "series.json", ["folder-vagabond"]),
                _DriveFile("bad", "series.json", ["folder-vagabond"]),
                _DriveFile("other", "series.json", ["somewhere-else"]),
            ]
        return []

    def download_file_text(self, file_id: str) -> str:
        if file_id == "bad":
            raise RuntimeError("unreadable")
        return (
            '{"volumes":[{"volume_uuid":"vol-aaa","page_count":196},'
            '{"volume_uuid":"other-vol","page_count":50}]}'
        )


def test_fetch_page_counts_uses_series_json_under_mokuro_root():
    counts = fetch_page_counts(client=_PageCountDrive(), folder_name="mokuro-reader")
    assert counts == {"vol-aaa": 196, "other-vol": 50}


def test_page_count_in_notes_and_stamp_without_new_pages(client):
    _enable(bootstrap=False)
    db = _db()
    rec = {
        "progress": 38,
        "chars": 100,
        "completed": False,
        "series_title": "Vagabond",
        "volume_title": "vagabond_17",
        "lastProgressUpdate": "2026-04-01T12:00:00Z",
    }
    try:
        poll_mokuro(db, snapshot={"vol-aaa": rec})
        poll_mokuro(db, snapshot={"vol-aaa": {**rec, "progress": 107, "chars": 1863}})
        entry = db.query(LogEntry).filter(LogEntry.source == "mokuro").one()
        assert entry.amount == 69
        assert "total=" not in (entry.notes or "")
        r = poll_mokuro(
            db,
            snapshot={"vol-aaa": {**rec, "progress": 107, "chars": 1863, "page_count": 196}},
        )
        assert r.logs_created == 0
        db.refresh(entry)
        assert entry.amount == 69
        assert "pages 38→107 (+69)" in (entry.notes or "")
        assert "total=196" in (entry.notes or "")
        assert "completed" not in (entry.notes or "")
    finally:
        db.close()


def test_completion_after_pushed_partial_does_not_double_count(client):
    _enable(bootstrap=False)
    db = _db()
    rec = {
        "progress": 38,
        "chars": 100,
        "completed": False,
        "page_count": 196,
        "series_title": "Vagabond",
        "volume_title": "vagabond_17",
        "lastProgressUpdate": "2026-04-01T12:00:00Z",
    }
    try:
        poll_mokuro(db, snapshot={"vol-aaa": rec})
        poll_mokuro(db, snapshot={"vol-aaa": {**rec, "progress": 107}})
        partial = db.query(LogEntry).filter(LogEntry.source == "mokuro").one()
        assert partial.amount == 69
        partial.tadoku_status = "pushed"
        db.commit()
        r = poll_mokuro(
            db,
            snapshot={"vol-aaa": {**rec, "progress": 196, "completed": True}},
        )
        assert r.logs_created >= 1
        logs = db.query(LogEntry).filter(LogEntry.source == "mokuro").all()
        assert len(logs) == 2
        by_status = {e.tadoku_status: e for e in logs}
        assert by_status["pushed"].amount == 69
        opened = by_status["pending"]
        assert opened.amount == 127
        assert opened.source_ref == "mokuro:vol-aaa:196"
        assert "pages 69→196 (+127)" in (opened.notes or "")
        assert "total=196" in (opened.notes or "")
        assert "completed" in (opened.notes or "")
    finally:
        db.close()
