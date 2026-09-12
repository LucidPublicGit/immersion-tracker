"""Progress fixup: merge, rename, category, episode peel, catalog redirects."""

from __future__ import annotations

import pytest

from app.db.models import CatalogItem, LogEntry
from app.ingest.service import create_log
from app.media.progress import aggregate_progress
from app.media.progress_fixup import (
    build_catalog_key_redirects,
    merge_works,
    rename_works,
    set_content_type,
    split_embedded_episode,
)


@pytest.fixture()
def db(client):
    from app.db.session import _SessionLocal

    assert _SessionLocal is not None
    session = _SessionLocal()
    try:
        yield session
    finally:
        session.close()


def test_split_embedded_episode():
    assert split_embedded_episode("GTO 11")["title"] == "GTO"
    assert split_embedded_episode("GTO 11")["episode"] == 11
    assert split_embedded_episode("GTO 12-14")["episode"] == 14
    assert split_embedded_episode("GTO 5,6")["episode"] == 6
    p = split_embedded_episode("Yugi 0-13 (double pts)")
    assert p["title"] == "Yugi"
    assert p["episode"] == 13
    assert split_embedded_episode("Show 2024")["matched"] is False


def test_set_content_type_rewrites_key_prefix(db, monkeypatch):
    """manga→show rewrites series_key prefix and force-refetches metadata."""
    from app.db.models import MediaMetadata, utcnow
    from app.media import progress_fixup as fixup

    create_log(
        db,
        content_type="manga",
        title="Type Change Show",
        source="manual",
        amount=20,
        unit="pages",
        series_key="manga:type-change-show",
        source_ref="tcs-1",
    )
    db.add(
        MediaMetadata(
            series_key="manga:type-change-show",
            content_type="manga",
            title="Type Change Show",
            source="anilist",
            total_units=10,
            total_units_label="volumes",
            fetched_at=utcnow(),
        )
    )
    db.commit()

    def fake_ensure(db, *, series_key, title, content_type, force=False, **kwargs):
        assert force is True
        assert content_type == "show"
        assert series_key == "show:type-change-show"
        row = (
            db.query(MediaMetadata)
            .filter(MediaMetadata.series_key == series_key)
            .one_or_none()
        )
        if not row:
            row = MediaMetadata(series_key=series_key)
            db.add(row)
        row.content_type = "show"
        row.title = title
        row.source = "tvmaze"
        row.total_units = 11
        row.total_units_label = "episodes"
        row.cover_url = "https://example.com/show.jpg"
        row.cover_local_path = "covers/show_test.jpg"
        row.fetched_at = utcnow()
        row.updated_at = utcnow()
        db.commit()
        db.refresh(row)
        return row

    monkeypatch.setattr(fixup, "ensure_metadata", fake_ensure, raising=False)
    # patch where ensure_metadata is imported inside the function
    import app.media.metadata_cache as mc

    monkeypatch.setattr(mc, "ensure_metadata", fake_ensure)

    result = set_content_type(
        db, ["manga:type-change-show"], "show", refetch_meta=True
    )
    assert result["ok"] is True
    assert result["key_rewrites"].get("manga:type-change-show") == "show:type-change-show"
    logs = (
        db.query(LogEntry)
        .filter(LogEntry.source_ref == "tcs-1")
        .all()
    )
    assert logs[0].content_type == "show"
    assert logs[0].series_key == "show:type-change-show"
    meta = (
        db.query(MediaMetadata)
        .filter(MediaMetadata.series_key == "show:type-change-show")
        .one()
    )
    assert meta.source == "tvmaze"
    assert meta.total_units_label == "episodes"
    assert meta.total_units == 11


def test_merge_gto_style_logs(db):
    # Ingest already peels GTO N → work GTO + episode; use distinct raw keys
    # then merge (and also verify aggregate groups fragments).
    create_log(
        db,
        content_type="other",
        title="GTO 1",
        source="manual",
        amount=20,
        unit="minutes",
        series_key="other:gto-1",
        source_ref="gto-a",
    )
    create_log(
        db,
        content_type="anime",
        title="GTO 2",
        source="manual",
        amount=20,
        unit="minutes",
        series_key="anime:gto-2",
        source_ref="gto-b",
    )
    create_log(
        db,
        content_type="anime",
        title="GTO 11",
        source="manual",
        amount=20,
        unit="minutes",
        series_key="anime:gto-11",
        source_ref="gto-c",
    )

    # create_log may already collapse keys; merge remaining into anime:gto
    keys = list(
        {
            log.series_key
            for log in db.query(LogEntry).filter(LogEntry.source_ref.like("gto-%")).all()
            if log.series_key
        }
    )
    if "anime:gto" not in keys:
        keys.append("anime:gto")
    result = merge_works(
        db,
        keys,
        target_series_key="anime:gto",
        title="GTO",
        content_type="anime",
        parse_episodes=True,
        refetch_meta=False,
    )
    assert result["ok"]

    logs = db.query(LogEntry).filter(LogEntry.series_key == "anime:gto").all()
    assert len(logs) == 3
    assert all(l.content_type == "anime" for l in logs)
    eps = sorted(l.episode for l in logs if l.episode is not None)
    assert eps == [1, 2, 11]

    rows = aggregate_progress(db)
    gto = next(r for r in rows if r["series_key"] == "anime:gto")
    assert gto["log_count"] == 3
    assert gto["progress_episode"] == 11
    assert gto["content_type"] == "anime"


def test_set_type_and_rename(db):
    create_log(
        db,
        content_type="other",
        title="Yugi 0-13 (Double pts)",
        source="manual",
        amount=40,
        unit="minutes",
        series_key="other:yugi-0-13-double-pts",
        source_ref="yugi-ren",
    )
    log0 = db.query(LogEntry).filter(LogEntry.source_ref == "yugi-ren").one()
    key = log0.series_key
    set_content_type(db, [key], "anime")
    rename_works(
        db,
        [key],
        "Yu-Gi-Oh!",
        also_parse_episodes=True,
    )
    log = db.query(LogEntry).filter(LogEntry.source_ref == "yugi-ren").one()
    assert log.content_type == "anime"
    assert log.title == "Yu-Gi-Oh!"
    assert log.episode == 13


def test_catalog_redirect_groups_relinked_keys(db):
    """Old auto key should group under catalog canonical after alias setup."""
    create_log(
        db,
        content_type="anime",
        title="yanki neko",
        source="manual",
        amount=20,
        unit="minutes",
        series_key="anime:yanki-neko",
        season=1,
        episode=1,
    )
    create_log(
        db,
        content_type="anime",
        title="yanineko",
        source="manual",
        amount=20,
        unit="minutes",
        series_key="anime:yanineko",
        season=1,
        episode=2,
    )
    # create_log already seeded catalog rows — attach aliases on the canonical key
    cat = (
        db.query(CatalogItem)
        .filter(CatalogItem.series_key == "anime:yanineko")
        .one()
    )
    cat.display_title = "yanineko"
    cat.aliases = "yanki neko | anime:yanki-neko"
    db.commit()

    redirects = build_catalog_key_redirects(db)
    assert redirects.get("anime:yanki-neko") == "anime:yanineko"

    rows = aggregate_progress(db)
    keys = [r["series_key"] for r in rows]
    assert "anime:yanineko" in keys
    # Old key should not appear as a separate work when redirected
    assert "anime:yanki-neko" not in keys
    y = next(r for r in rows if r["series_key"] == "anime:yanineko")
    assert y["log_count"] == 2


def test_fixup_api_merge(client, db):
    create_log(
        db,
        content_type="other",
        title="GTO 1",
        source="manual",
        amount=20,
        unit="minutes",
        series_key="other:gto-1",
    )
    create_log(
        db,
        content_type="anime",
        title="GTO 3",
        source="manual",
        amount=20,
        unit="minutes",
        series_key="anime:gto-3",
    )
    r = client.post(
        "/api/progress/fixup",
        json={
            "action": "merge",
            "series_keys": ["other:gto-1", "anime:gto-3"],
            "title": "GTO",
            "content_type": "anime",
            "target_series_key": "anime:gto",
            "refetch_meta": False,
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["target_series_key"] == "anime:gto"
    assert body["progress"]["total"] >= 1
    keys = [i["series_key"] for i in body["progress"]["items"]]
    assert "anime:gto" in keys
