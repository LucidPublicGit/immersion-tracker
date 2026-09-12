"""Content progress aggregation, Tadoku description parse, metadata cache."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.db.models import LogEntry, MediaMetadata
from app.db.session import get_engine, init_db
from app.ingest.service import create_log
from app.media.progress import aggregate_progress
from app.tadoku.pull import parse_description


@pytest.fixture()
def db(client):
    """Reuse test client fixture's DB (initialized)."""
    from app.db.session import _SessionLocal

    assert _SessionLocal is not None
    session = _SessionLocal()
    try:
        yield session
    finally:
        session.close()


def test_parse_description_season_episode():
    p = parse_description("The Great Escape S01E04")
    assert p["title"] == "The Great Escape"
    assert p["season"] == 1
    assert p["episode"] == 4


def test_parse_description_bulk_season_range():
    from app.tadoku.pull import parse_season_range

    p = parse_description("Arcane S1+S2 (740min half)")
    assert p["title"] == "Arcane"
    assert p["kind"] == "season_range"
    assert p["seasons"] == [1, 2]
    assert parse_season_range("Imported from Tadoku · Arcane S1+S2 (740min half)") == [
        1,
        2,
    ]
    assert parse_season_range("Show S1-S3") == [1, 2, 3]


def test_parse_description_youtube_prefix():
    p = parse_description("Youtube: Some Video Title")
    assert p["title"] == "Some Video Title"
    assert p["season"] is None


def test_parse_description_volume():
    p = parse_description("Spy x Family Vol. 3")
    assert p["title"] == "Spy x Family"
    assert p["volume"] == 3
    assert p["episode"] == 3


def test_parse_description_vol_page_not_episode():
    """Page ranges must never become E50/E100."""
    from app.tadoku.pull import refine_content_type_from_activity

    p = parse_description("ダンダダン vol 1 page 50-100")
    assert "ダンダダン" in p["title"]
    assert p["volume"] == 1
    assert p["episode"] == 1  # volume number, not page 100
    assert p.get("page_start") == 50
    assert p.get("page_end") == 100
    assert p["kind"] == "volume"

    p2 = parse_description("ダンダダン vol 1 (100 to 216)")
    assert p2["volume"] == 1
    assert p2["episode"] == 1
    assert p2.get("page_end") == 216

    assert (
        refine_content_type_from_activity(
            "anime", unit="pages", activity="reading", description="ダンダダン vol 1"
        )
        == "manga"
    )
    assert (
        refine_content_type_from_activity(
            "manga", unit="minutes", activity="listening", description="dandadan 1"
        )
        == "anime"
    )


def test_prepare_identity_splits_reading_listening():
    from app.media.work_identity import prepare_log_identity

    manga = prepare_log_identity(
        content_type="anime",
        title="ダンダダン vol 1 page 0-50",
        unit="pages",
        activity="reading",
        series_key="anime:dandadan",
    )
    assert manga["content_type"] == "manga"
    assert manga["series_key"].startswith("manga:")
    assert manga["episode"] == 1  # vol 1

    anime = prepare_log_identity(
        content_type="other",
        title="ダンダダン",
        unit="minutes",
        activity="listening",
        series_key="manga:dandadan",
    )
    assert anime["content_type"] == "anime"
    assert anime["series_key"].startswith("anime:")


def test_aggregate_progress_groups_by_series(db):
    create_log(
        db,
        content_type="anime",
        title="KonoSuba",
        source="manual",
        amount=24,
        unit="minutes",
        series_key="anime:konosuba",
        season=1,
        episode=1,
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    create_log(
        db,
        content_type="anime",
        title="KonoSuba",
        source="manual",
        amount=24,
        unit="minutes",
        series_key="anime:konosuba",
        season=1,
        episode=3,
        timestamp=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )
    create_log(
        db,
        content_type="manga",
        title="Yotsuba",
        source="manual",
        amount=40,
        unit="pages",
        series_key="manga:yotsuba",
        episode=2,
    )

    rows = aggregate_progress(db)
    by_key = {r["series_key"]: r for r in rows}
    assert "anime:konosuba" in by_key
    k = by_key["anime:konosuba"]
    assert k["log_count"] == 2
    assert k["progress_season"] == 1
    assert k["progress_episode"] == 3
    assert k["progress_label"] == "S01E03"
    assert k["episodes_logged"] == 2
    assert by_key["manga:yotsuba"]["content_type"] == "manga"


def test_single_season_gets_flat_total():
    """S1 logs + flat 12-episode metadata → season chip can show 3/12."""
    from app.media.season_progress import build_season_rows

    info = build_season_rows(
        episode_tags={"S01E01", "S01E02", "S01E03"},
        log_seasons=[(1, 1, 24.0), (1, 2, 24.0), (1, 3, 24.0)],
        season_totals={},
        total_units=12,
        total_units_label="episodes",
    )
    assert info["season_mode"] == "single"
    s1 = next(s for s in info["seasons"] if s["season"] == 1)
    assert s1["total_episodes"] == 12
    assert s1["progress_episodes"] >= 3


def test_multi_season_progress(db):
    """Franchise % uses per-season totals; max-episode does not leap seasons."""
    from app.db.models import MediaMetadata, utcnow
    import json

    for se, ep in [(1, 1), (1, 2), (1, 12), (2, 1), (2, 3)]:
        create_log(
            db,
            content_type="anime",
            title="Multi Season Show",
            source="manual",
            amount=24,
            unit="minutes",
            series_key="anime:multi-season-show",
            season=se,
            episode=ep,
            source_ref=f"mss-{se}-{ep}",
        )
    meta = MediaMetadata(
        series_key="anime:multi-season-show",
        content_type="anime",
        title="Multi Season Show",
        source="manual",
        total_units=25,
        total_units_label="episodes",
        raw_json=json.dumps(
            {"season_totals": {"1": 12, "2": 13}, "seasons_locked": True}
        ),
        fetched_at=utcnow(),
    )
    db.add(meta)
    db.commit()

    rows = aggregate_progress(db, auto_finish=False)
    hit = next(r for r in rows if r["series_key"] == "anime:multi-season-show")
    assert hit["is_multi_season"] is True
    assert hit["progress_season"] == 2
    assert hit["progress_episode"] == 3
    assert hit["progress_label"] == "S02E03"
    assert hit["season_mode"] == "multi"
    assert len(hit["seasons"]) >= 2
    s1 = next(s for s in hit["seasons"] if s["season"] == 1)
    s2 = next(s for s in hit["seasons"] if s["season"] == 2)
    assert s1["total_episodes"] == 12
    assert s2["total_episodes"] == 13
    # S1: 3 distinct eps of 12, S2: 2 of 13 → 5/25 = 20%
    assert hit["franchise_total_episodes"] == 25
    assert hit["franchise_done_episodes"] == 5
    assert hit["percent_complete"] == 20.0
    assert hit["seasons_summary"]
    assert "S1" in hit["seasons_summary"]


def test_arcane_bulk_s1_s2_counts_as_franchise(db):
    """Bulk Tadoku 'Arcane S1+S2' minutes credit both seasons when totals known."""
    from app.db.models import MediaMetadata, utcnow
    import json

    create_log(
        db,
        content_type="show",
        title="Arcane",
        source="tadoku",
        amount=370,
        unit="minutes",
        series_key="show:arcane",
        source_ref="tadoku:arcane-bulk-test",
        notes="Imported from Tadoku · Arcane S1+S2 (740min half)",
        language="ja",
    )
    db.add(
        MediaMetadata(
            series_key="show:arcane",
            content_type="show",
            title="Arcane: League of Legends",
            source="tvmaze",
            total_units=18,
            total_units_label="episodes",
            raw_json=json.dumps(
                {"season_totals": {"1": 9, "2": 9}, "seasons_locked": True}
            ),
            fetched_at=utcnow(),
        )
    )
    db.commit()

    rows = aggregate_progress(db, auto_finish=False)
    hit = next(
        r
        for r in rows
        if "arcane" in (r["series_key"] or "").lower()
        or (r.get("title") or "").lower() == "arcane"
    )
    assert hit["is_multi_season"] is True
    assert hit["percent_complete"] == 100.0
    s1 = next(s for s in hit["seasons"] if s["season"] == 1)
    s2 = next(s for s in hit["seasons"] if s["season"] == 2)
    assert s1.get("is_done") is True or s1["progress_episodes"] >= 9
    assert s2.get("is_done") is True or s2["progress_episodes"] >= 9


def test_audiobook_ignores_anime_jiten_deck(db):
    """Audiobook logs must not show anime episode/runtime totals."""
    from app.db.models import MediaMetadata, utcnow
    import json

    create_log(
        db,
        content_type="audiobook",
        title="無職転生",
        source="tadoku",
        amount=886,
        unit="minutes",
        series_key="audiobook:mushoku-tensei",
        source_ref="mt-audio-1",
        notes="Imported from Tadoku · [1巻] 無職転生 (double)",
    )
    db.add(
        MediaMetadata(
            series_key="audiobook:mushoku-tensei",
            content_type="audiobook",
            title="無職転生 ～異世界行ったら本気だす～",
            source="jiten",
            total_units=11,
            total_units_label="episodes",
            total_minutes=148,
            total_characters=46306,
            raw_json=json.dumps(
                {"match": {"mediaType": 1}, "detail_main": {"mediaType": 1}}
            ),
            fetched_at=utcnow(),
        )
    )
    db.commit()

    rows = aggregate_progress(db, auto_finish=False)
    hit = next(r for r in rows if "mushoku" in r["series_key"])
    td = (hit.get("total_display") or "").lower()
    assert "11" not in td
    assert "eps" not in td
    assert "148" not in td
    assert hit["current_display"] and "886" in hit["current_display"]


def test_yowamushi_pedal_known_multi_season(db):
    """jiten flat 38-ep deck must not hide the multi-season franchise map."""
    from app.db.models import MediaMetadata, utcnow
    from app.media.season_progress import known_franchise_season_totals

    known = known_franchise_season_totals(
        series_key="anime:yowamushi-pedal", title="Yowamushi Pedal"
    )
    assert known.get(1) == 38
    assert len(known) >= 4

    create_log(
        db,
        content_type="anime",
        title="Yowamushi Pedal",
        source="plex",
        amount=24,
        unit="minutes",
        series_key="anime:yowamushi-pedal",
        season=1,
        episode=20,
        source_ref="yp-s1e20",
    )
    db.add(
        MediaMetadata(
            series_key="anime:yowamushi-pedal",
            content_type="anime",
            title="Yowamushi Pedal",
            source="jiten",
            total_units=38,
            total_units_label="episodes",
            total_minutes=563,
            fetched_at=utcnow(),
        )
    )
    db.commit()

    rows = aggregate_progress(db, auto_finish=False)
    hit = next(r for r in rows if "yowamushi" in r["series_key"])
    assert hit["is_multi_season"] is True
    assert hit["franchise_total_episodes"] == sum(known.values())
    assert hit["season_totals"]
    assert int(hit["season_totals"].get("1") or 0) == 38
    assert int(hit["season_totals"].get("2") or 0) == 24
    s1 = next(s for s in hit["seasons"] if s["season"] == 1)
    assert s1["total_episodes"] == 38
    # Flat jiten total must not claim the whole franchise is 38 eps of S1 only
    assert hit["total_units"] == sum(known.values())


def test_konosuba_s1_done_franchise_unfinished(db):
    """S1 complete → green S1 chip, but franchise % unfinished (known multi-season)."""
    from app.db.models import MediaMetadata, utcnow
    from app.ingest.service import ensure_catalog

    for ep in range(1, 11):
        create_log(
            db,
            content_type="anime",
            title="この素晴らしい世界に祝福を!",
            source="manual",
            amount=24,
            unit="minutes",
            series_key="anime:konosuba",
            season=1,
            episode=ep,
            source_ref=f"ks-s1-{ep}",
        )
    # jiten-style S1-only deck (the bug that auto-finished the franchise)
    db.add(
        MediaMetadata(
            series_key="anime:konosuba",
            content_type="anime",
            title="KonoSuba",
            source="jiten",
            total_units=10,
            total_units_label="episodes",
            total_minutes=152,
            fetched_at=utcnow(),
        )
    )
    cat = ensure_catalog(db, "anime:konosuba", "この素晴らしい世界に祝福を!", "anime")
    cat.progress_status = "finished"
    cat.progress_status_locked = False
    db.commit()

    rows = aggregate_progress(db, auto_finish=False)
    hit = next(r for r in rows if r["series_key"] == "anime:konosuba")
    assert hit["is_multi_season"] is True
    assert hit["progress_status"] == "active"  # not finished — S2/S3 remain
    s1 = next(s for s in hit["seasons"] if s["season"] == 1)
    assert s1["total_episodes"] == 10
    assert s1["progress_episodes"] >= 10
    assert s1.get("is_done") is True or s1["percent_complete"] == 100.0
    # Franchise: 10 / (10+10+11) ≈ 32.3%
    assert hit["franchise_total_episodes"] == 31
    assert hit["percent_complete"] is not None
    assert hit["percent_complete"] < 50.0
    assert hit["percent_complete"] > 20.0
    s2 = next(s for s in hit["seasons"] if s["season"] == 2)
    assert s2["total_episodes"] == 10
    assert (s2["progress_episodes"] or 0) == 0


def test_total_display_listening_vs_reading_extras(db):
    """Anime shows duration, not characters; manga shows characters, not minutes."""
    from app.db.models import MediaMetadata, utcnow

    create_log(
        db,
        content_type="anime",
        title="Solo Leveling Display",
        source="manual",
        amount=24,
        unit="minutes",
        series_key="anime:solo-leveling-display",
        season=1,
        episode=5,
        source_ref="sl-disp-1",
    )
    db.add(
        MediaMetadata(
            series_key="anime:solo-leveling-display",
            content_type="anime",
            title="Solo Leveling Display",
            source="jiten",
            total_units=12,
            total_units_label="episodes",
            total_characters=47026,
            total_minutes=156,
            fetched_at=utcnow(),
        )
    )
    create_log(
        db,
        content_type="manga",
        title="Manga Display Work",
        source="manual",
        amount=40,
        unit="pages",
        series_key="manga:display-work",
        episode=2,
        source_ref="mg-disp-1",
    )
    db.add(
        MediaMetadata(
            series_key="manga:display-work",
            content_type="manga",
            title="Manga Display Work",
            source="jiten",
            total_units=10,
            total_units_label="volumes",
            total_characters=120000,
            total_minutes=400,
            fetched_at=utcnow(),
        )
    )
    db.commit()

    rows = aggregate_progress(db, auto_finish=False)
    anime = next(r for r in rows if r["series_key"] == "anime:solo-leveling-display")
    manga = next(r for r in rows if r["series_key"] == "manga:display-work")
    anime_td = anime.get("total_display") or ""
    manga_td = manga.get("total_display") or ""
    assert "12 eps" in anime_td or "12 episodes" in anime_td
    assert "156 min" in anime_td
    assert "chars" not in anime_td.lower()
    assert "10 vols" in manga_td or "10 volumes" in manga_td
    assert "120" in manga_td and "chars" in manga_td
    assert "min" not in manga_td.lower()


def test_one_piece_red_is_movie_not_tv_series(db):
    """One Piece Red must not pick up the 1088-ep TV anime metadata."""
    from app.db.models import MediaMetadata, utcnow

    create_log(
        db,
        content_type="anime",
        title="One Piece Red",
        source="manual",
        amount=115,
        unit="minutes",
        series_key="anime:onepiecered",
        source_ref="op-red-1",
    )
    # Wrong TV series metadata under film-red key (the live bug)
    db.add(
        MediaMetadata(
            series_key="anime:one-piece-film-red",
            content_type="anime",
            title="ONE PIECE",
            source="jiten",
            total_units=1088,
            total_units_label="episodes",
            total_minutes=14908,
            fetched_at=utcnow(),
        )
    )
    # Correct film deck under alternate key
    db.add(
        MediaMetadata(
            series_key="anime:onepiecered",
            content_type="anime",
            title="One Piece Film: Red",
            source="jiten",
            total_units=0,
            total_units_label="episodes",
            total_minutes=81,
            total_characters=21640,
            fetched_at=utcnow(),
        )
    )
    db.commit()

    rows = aggregate_progress(db, auto_finish=False)
    hits = [
        r
        for r in rows
        if "film-red" in r["series_key"]
        or "onepiecered" in r["series_key"]
        or "red" in (r["title"] or "").lower()
    ]
    assert hits, "expected One Piece Red progress row"
    hit = hits[0]
    assert hit["content_type"] == "movie"
    assert hit["series_key"].startswith("movie:")
    # Must not show 1088 episodes
    assert hit["total_units"] != 1088
    td = (hit.get("total_display") or "").lower()
    assert "1088" not in td
    assert hit["percent_complete"] is not None
    assert hit["percent_complete"] >= 90.0


def test_parse_season_totals_form():
    from app.media.season_progress import parse_season_totals_map

    assert parse_season_totals_map("1:12, 2:13") == {1: 12, 2: 13}
    assert parse_season_totals_map("S1=12; S2=13") == {1: 12, 2: 13}
    assert parse_season_totals_map({"1": 12, "2": 13}) == {1: 12, 2: 13}


def test_progress_api(client, db):
    create_log(
        db,
        content_type="anime",
        title="Frieren",
        source="manual",
        amount=22,
        unit="minutes",
        series_key="anime:frieren",
        season=1,
        episode=5,
    )
    # Attach cached metadata
    db.add(
        MediaMetadata(
            series_key="anime:frieren",
            content_type="anime",
            title="Frieren",
            source="jiten",
            external_id="1",
            cover_url="https://cdn.jiten.moe/1/cover.jpg",
            total_units=28,
            total_units_label="episodes",
        )
    )
    db.commit()

    r = client.get("/api/progress")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] >= 1
    item = next(i for i in data["items"] if i["series_key"] == "anime:frieren")
    assert item["progress_label"] == "S01E05"
    assert item["total_units"] == 28
    assert item["has_metadata"] is True
    assert "anime" in data["content_types"]


def test_progress_page_renders(client):
    r = client.get("/progress")
    assert r.status_code == 200
    assert b"Pull from Tadoku" in r.content
    assert b"prog-items" in r.content
    assert b"btn-refresh" not in r.content
    assert b"EXCLUDE_FROM_ALL" in r.content
    assert b"logsHref" in r.content or b"series_key=" in r.content
    assert b"btn-toast-finished" in r.content
    assert b"prog-sort" in r.content
    assert b"bulkSetStatus" in r.content


def test_bulk_set_status_via_fixup(client, db):
    from app.db.models import CatalogItem
    from app.ingest.service import create_log

    for key in ("anime:bulk-a", "anime:bulk-b"):
        create_log(
            db,
            content_type="anime",
            title=key,
            source="manual",
            amount=20,
            unit="minutes",
            series_key=key,
            season=1,
            episode=1,
            source_ref=f"{key}-e1",
        )
    r = client.post(
        "/api/progress/fixup",
        json={
            "action": "set_status",
            "series_keys": ["anime:bulk-a", "anime:bulk-b"],
            "progress_status": "dropped",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    for key in ("anime:bulk-a", "anime:bulk-b"):
        item = next(i for i in body["progress"]["items"] if i["series_key"] == key)
        assert item["progress_status"] == "dropped"
        cat = db.query(CatalogItem).filter(CatalogItem.series_key == key).one()
        assert cat.progress_status_locked is True


def test_enrich_returns_progress_snapshot(client, db):
    create_log(
        db,
        content_type="anime",
        title="Solo Work",
        source="manual",
        amount=20,
        unit="minutes",
        series_key="anime:solo-work",
        season=1,
        episode=1,
    )
    # Pretend already cached so enrich skips network
    db.add(
        MediaMetadata(
            series_key="anime:solo-work",
            content_type="anime",
            title="Solo Work",
            source="jiten",
            external_id="99",
            cover_url="https://cdn.jiten.moe/99/cover.jpg",
            cover_local_path="covers/jiten_99.jpg",
            total_units=12,
            total_units_label="episodes",
        )
    )
    db.commit()
    r = client.post(
        "/api/progress/enrich",
        json={"force": False, "limit": 5, "only_missing": True},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "progress" in body
    assert body["progress"]["total"] >= 1


def test_home_has_club_link(client):
    r = client.get("/")
    assert r.status_code == 200
    assert b"Tadoku contest" in r.content
    # tadoku.app 404s bare /contests/{id}; UI must link to leaderboard page
    assert b"/leaderboard/1" in r.content


def test_set_progress_status(client, db):
    from app.ingest.service import create_log

    create_log(
        db,
        content_type="anime",
        title="Test Show",
        source="manual",
        amount=20,
        unit="minutes",
        series_key="anime:test-show",
        season=1,
        episode=1,
    )
    r = client.post(
        "/api/progress/fixup",
        json={
            "action": "set_status",
            "series_keys": ["anime:test-show"],
            "progress_status": "finished",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    item = next(i for i in body["progress"]["items"] if i["series_key"] == "anime:test-show")
    assert item["progress_status"] == "finished"
    assert body["progress"]["status_counts"]["finished"] >= 1


def test_set_progress_status_ignored(client, db):
    """Ignored hides stub/junk works from the shelf without deleting logs."""
    from app.db.models import CatalogItem
    from app.ingest.service import create_log

    create_log(
        db,
        content_type="visual_novel",
        title="Mahoyo (stub log)",
        source="manual",
        amount=1,
        unit="characters",
        series_key="vn:mahoyo-stub-log",
        source_ref="stub-1",
    )
    r = client.post(
        "/api/progress/fixup",
        json={
            "action": "set_status",
            "series_keys": ["vn:mahoyo-stub-log"],
            "progress_status": "ignored",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    item = next(
        i for i in body["progress"]["items"] if i["series_key"] == "vn:mahoyo-stub-log"
    )
    assert item["progress_status"] == "ignored"
    assert body["progress"]["status_counts"].get("ignored", 0) >= 1

    cat = (
        db.query(CatalogItem)
        .filter(CatalogItem.series_key == "vn:mahoyo-stub-log")
        .one()
    )
    assert cat.progress_status == "ignored"
    assert cat.progress_status_locked is True

    # Status filter returns only ignored works
    r2 = client.get("/api/progress", params={"status": "ignored"})
    assert r2.status_code == 200
    keys = {i["series_key"] for i in r2.json()["items"]}
    assert "vn:mahoyo-stub-log" in keys

    # Progress page exposes Ignore UI
    page = client.get("/progress")
    assert page.status_code == 200
    assert b"btn-toast-ignored" in page.content
    assert b"Ignored" in page.content


def _seed_complete_show(db, *, series_key="anime:complete-show", title="Complete Show"):
    from app.db.models import MediaMetadata
    from app.ingest.service import create_log

    for ep in (3, 1, 2):
        create_log(
            db,
            content_type="anime",
            title=title,
            source="manual",
            amount=20,
            unit="minutes",
            series_key=series_key,
            season=1,
            episode=ep,
            source_ref=f"{series_key}-e{ep}",
        )
    db.add(
        MediaMetadata(
            series_key=series_key,
            content_type="anime",
            title=title,
            source="jiten",
            external_id="1",
            total_units=3,
            total_units_label="episodes",
        )
    )
    db.commit()


def test_get_progress_does_not_auto_finish(client, db):
    """GET is a pure read — 100% works stay active until a write path auto-finishes."""
    from app.db.models import CatalogItem

    _seed_complete_show(db)
    r = client.get("/api/progress")
    assert r.status_code == 200
    item = next(
        i for i in r.json()["items"] if i["series_key"] == "anime:complete-show"
    )
    assert item["percent_complete"] == 100.0
    assert item["progress_status"] == "active"
    cat = (
        db.query(CatalogItem)
        .filter(CatalogItem.series_key == "anime:complete-show")
        .one()
    )
    assert cat.progress_status == "active"


def test_auto_finished_on_write_snapshot(client, db):
    """Pull/enrich/fixup snapshots promote unlocked active@100% → finished."""
    from app.db.models import CatalogItem
    from app.media.progress import aggregate_progress

    _seed_complete_show(db)
    rows = aggregate_progress(db, auto_finish=True)
    item = next(r for r in rows if r["series_key"] == "anime:complete-show")
    assert item["percent_complete"] == 100.0
    assert item["progress_status"] == "finished"
    cat = (
        db.query(CatalogItem)
        .filter(CatalogItem.series_key == "anime:complete-show")
        .one()
    )
    assert cat.progress_status == "finished"
    # Must not clobber catalog title while finishing
    assert cat.display_title == "Complete Show"


def test_auto_finish_does_not_clobber_title(db):
    from app.db.models import CatalogItem, MediaMetadata
    from app.ingest.service import create_log
    from app.media.progress import aggregate_progress

    create_log(
        db,
        content_type="anime",
        title="English Title",
        source="manual",
        amount=20,
        unit="minutes",
        series_key="anime:title-clobber",
        season=1,
        episode=1,
        source_ref="tc-1",
    )
    create_log(
        db,
        content_type="anime",
        title="English Title",
        source="manual",
        amount=20,
        unit="minutes",
        series_key="anime:title-clobber",
        season=1,
        episode=2,
        source_ref="tc-2",
    )
    cat = (
        db.query(CatalogItem)
        .filter(CatalogItem.series_key == "anime:title-clobber")
        .one()
    )
    cat.display_title = "User Rename"
    db.add(
        MediaMetadata(
            series_key="anime:title-clobber",
            content_type="anime",
            title="日本語タイトル",
            source="jiten",
            external_id="9",
            total_units=2,
            total_units_label="episodes",
            raw_json='{"nativeTitle":"日本語タイトル","title":"Native JP"}',
        )
    )
    db.commit()
    rows = aggregate_progress(db, auto_finish=True)
    item = next(r for r in rows if r["series_key"] == "anime:title-clobber")
    assert item["title"] == "User Rename"
    assert item["progress_status"] == "finished"
    db.refresh(cat)
    assert cat.display_title == "User Rename"
    assert cat.progress_status == "finished"


def test_catalog_title_beats_metadata(db):
    from app.db.models import CatalogItem, MediaMetadata
    from app.ingest.service import create_log
    from app.media.progress import aggregate_progress

    create_log(
        db,
        content_type="anime",
        title="Log Title",
        source="manual",
        amount=20,
        unit="minutes",
        series_key="anime:catalog-wins",
        season=1,
        episode=1,
    )
    cat = (
        db.query(CatalogItem)
        .filter(CatalogItem.series_key == "anime:catalog-wins")
        .one()
    )
    cat.display_title = "My Catalog Name"
    db.add(
        MediaMetadata(
            series_key="anime:catalog-wins",
            content_type="anime",
            title="Web Preferred",
            source="jiten",
            external_id="7",
            raw_json='{"nativeTitle":"ウェブ名"}',
        )
    )
    db.commit()
    rows = aggregate_progress(db, auto_finish=False)
    item = next(r for r in rows if r["series_key"] == "anime:catalog-wins")
    assert item["title"] == "My Catalog Name"


def test_locked_active_survives_auto_finish(client, db):
    from app.db.models import CatalogItem
    from app.media.progress import aggregate_progress

    _seed_complete_show(db, series_key="anime:locked-active", title="Locked Active")
    r = client.post(
        "/api/progress/fixup",
        json={
            "action": "set_status",
            "series_keys": ["anime:locked-active"],
            "progress_status": "active",
        },
    )
    assert r.status_code == 200
    cat = (
        db.query(CatalogItem)
        .filter(CatalogItem.series_key == "anime:locked-active")
        .one()
    )
    assert cat.progress_status_locked is True
    rows = aggregate_progress(db, auto_finish=True)
    item = next(r for r in rows if r["series_key"] == "anime:locked-active")
    assert item["percent_complete"] == 100.0
    assert item["progress_status"] == "active"
    db.refresh(cat)
    assert cat.progress_status == "active"


def test_single_high_episode_not_100_percent(db):
    """One S01E12 log against a 12-ep total must not report 100%."""
    from app.db.models import MediaMetadata
    from app.ingest.service import create_log
    from app.media.progress import aggregate_progress

    create_log(
        db,
        content_type="anime",
        title="Sparse Show",
        source="manual",
        amount=20,
        unit="minutes",
        series_key="anime:sparse-show",
        season=1,
        episode=12,
    )
    db.add(
        MediaMetadata(
            series_key="anime:sparse-show",
            content_type="anime",
            title="Sparse Show",
            source="jiten",
            external_id="3",
            total_units=12,
            total_units_label="episodes",
        )
    )
    db.commit()
    rows = aggregate_progress(db, auto_finish=True)
    item = next(r for r in rows if r["series_key"] == "anime:sparse-show")
    assert item["percent_complete"] is not None
    assert item["percent_complete"] < 100.0
    assert item["progress_status"] == "active"


def test_multi_season_episode_not_false_100(db):
    """S02E05 against a flat 12-ep total must not auto-finish via max episode."""
    from app.db.models import MediaMetadata
    from app.ingest.service import create_log
    from app.media.progress import aggregate_progress

    create_log(
        db,
        content_type="anime",
        title="Sequel Show",
        source="manual",
        amount=20,
        unit="minutes",
        series_key="anime:sequel-show",
        season=2,
        episode=5,
    )
    db.add(
        MediaMetadata(
            series_key="anime:sequel-show",
            content_type="anime",
            title="Sequel Show",
            source="jiten",
            external_id="4",
            total_units=12,
            total_units_label="episodes",
        )
    )
    db.commit()
    rows = aggregate_progress(db, auto_finish=True)
    item = next(r for r in rows if r["series_key"] == "anime:sequel-show")
    assert item["percent_complete"] is not None
    assert item["percent_complete"] < 100.0
    assert item["progress_status"] == "active"


def test_auto_finished_does_not_override_dropped(client, db):
    from app.db.models import CatalogItem, MediaMetadata
    from app.ingest.service import create_log
    from app.media.progress import aggregate_progress

    for ep in range(1, 6):
        create_log(
            db,
            content_type="anime",
            title="Dropped Show",
            source="manual",
            amount=20,
            unit="minutes",
            series_key="anime:dropped-show",
            season=1,
            episode=ep,
            source_ref=f"dropped-e{ep}",
        )
    # create_log already seeds catalog — mark dropped on the existing row
    cat = (
        db.query(CatalogItem)
        .filter(CatalogItem.series_key == "anime:dropped-show")
        .one()
    )
    cat.progress_status = "dropped"
    db.add(
        MediaMetadata(
            series_key="anime:dropped-show",
            content_type="anime",
            title="Dropped Show",
            source="jiten",
            external_id="2",
            total_units=5,
            total_units_label="episodes",
        )
    )
    db.commit()
    rows = aggregate_progress(db, auto_finish=True)
    item = next(r for r in rows if r["series_key"] == "anime:dropped-show")
    assert item["percent_complete"] == 100.0
    assert item["progress_status"] == "dropped"


def test_pull_endpoint_without_user(client, monkeypatch):
    from app.tadoku import pull as pull_mod

    monkeypatch.setattr(pull_mod, "discover_user_id", lambda: None)
    r = client.post("/api/progress/pull-tadoku")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert "user_id" in (body.get("error") or "").lower() or body["imported"] == 0
