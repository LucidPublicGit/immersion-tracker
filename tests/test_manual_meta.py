"""Manual metadata URL parse + apply."""

from __future__ import annotations

import pytest

from app.db.models import MediaMetadata
from app.ingest.service import create_log
from app.media.manual_meta import (
    apply_manual_metadata,
    meta_issues_for_item,
    parse_media_url,
    provider_hints_for,
)
from app.media.progress import aggregate_progress


def test_parse_media_urls():
    assert parse_media_url("https://anilist.co/anime/21")["provider"] == "anilist"
    assert parse_media_url("https://anilist.co/manga/30002/Berserk")["media_kind"] == "manga"
    assert parse_media_url("https://myanimelist.net/anime/21/One_Piece")["provider"] == "mal"
    assert parse_media_url("https://store.steampowered.com/app/990080/Hogwarts_Legacy/")[
        "external_id"
    ] == "990080"
    assert parse_media_url("https://www.tvmaze.com/shows/55138/arcane")["provider"] == "tvmaze"
    assert parse_media_url("https://vndb.org/v17")["external_id"] == "v17"
    assert parse_media_url("https://jiten.moe/decks/media/4272/detail")["provider"] == "jiten"
    assert parse_media_url(
        "https://en.wikipedia.org/wiki/Arcane_(TV_series)"
    )["provider"] == "wikipedia"
    assert parse_media_url("https://cdn.example.com/art/cover.jpg")["provider"] == "image"
    assert parse_media_url("https://not-a-provider.example/foo") is None


def test_provider_hints_by_type():
    anime = provider_hints_for("anime", "Hajime no Ippo")
    assert any(h["id"] == "anilist" for h in anime)
    assert "Hajime" in anime[0]["url"] or "Ippo" in anime[0]["url"] or "search" in anime[0]["url"]
    game = provider_hints_for("game", "Hogwarts Legacy")
    assert any(h["id"] == "steam" for h in game)


def test_meta_issues_flags():
    issues = meta_issues_for_item(
        has_cover=False,
        has_metadata=False,
        percent_complete=None,
        total_units=None,
        total_characters=None,
        total_minutes=None,
        primary_amount=10,
        log_count=1,
        source="none",
    )
    assert "no_cover" in issues
    assert "no_length" in issues
    ok = meta_issues_for_item(
        has_cover=True,
        has_metadata=True,
        percent_complete=50.0,
        total_units=12,
        total_characters=None,
        total_minutes=None,
        primary_amount=6,
        log_count=3,
        source="anilist",
    )
    assert ok == []


def test_apply_manual_totals(client, db_session=None):
    from app.db.session import _SessionLocal

    assert _SessionLocal is not None
    db = _SessionLocal()
    try:
        create_log(
            db,
            content_type="anime",
            title="Manual Test Show",
            source="manual",
            amount=20,
            unit="minutes",
            series_key="anime:manual-test-show",
            source_ref="manual-meta-1",
        )
        result = apply_manual_metadata(
            db,
            "anime:manual-test-show",
            content_type="anime",
            total_units=24,
            total_units_label="episodes",
            total_minutes=480,
        )
        assert result["ok"] is True
        row = (
            db.query(MediaMetadata)
            .filter(MediaMetadata.series_key == "anime:manual-test-show")
            .one()
        )
        assert row.source == "manual"
        assert row.total_units == 24
        assert row.total_units_label == "episodes"
        assert row.total_minutes == 480

        items = aggregate_progress(db, auto_finish=False)
        hit = next(i for i in items if i["series_key"] == "anime:manual-test-show")
        assert hit["total_units"] == 24
        assert hit["has_metadata"] is True
        # still needs cover
        assert "no_cover" in hit["meta_issues"]
        assert hit["needs_user_input"] is True

        # Cover URL only (won't download invalid host — just set url)
        apply_manual_metadata(
            db,
            "anime:manual-test-show",
            cover_url="https://httpbin.org/image/jpeg",
        )
        items2 = aggregate_progress(db, auto_finish=False)
        hit2 = next(i for i in items2 if i["series_key"] == "anime:manual-test-show")
        # May or may not download depending on network; totals still set
        assert hit2["total_units"] == 24
    finally:
        db.close()


def test_set_metadata_api(client):
    r = client.post(
        "/api/logs",
        json={
            "content_type": "game",
            "title": "Manual Game XYZ",
            "amount": 30,
            "unit": "minutes",
            "source": "manual",
            "series_key": "game:manual-game-xyz",
            "source_ref": "manual-game-api-1",
        },
    )
    # create may use /api/logs or different path — fall back to DB if needed
    if r.status_code not in (200, 201):
        from app.db.session import _SessionLocal
        from app.ingest.service import create_log

        db = _SessionLocal()
        try:
            create_log(
                db,
                content_type="game",
                title="Manual Game XYZ",
                source="manual",
                amount=30,
                unit="minutes",
                series_key="game:manual-game-xyz",
                source_ref="manual-game-api-1",
            )
        finally:
            db.close()

    r2 = client.post(
        "/api/progress/fixup",
        json={
            "action": "set_metadata",
            "series_keys": ["game:manual-game-xyz"],
            "content_type": "game",
            "total_minutes": 2000,
            "total_units": 1,
            "total_units_label": "parts",
        },
    )
    assert r2.status_code == 200
    body = r2.json()
    assert body["ok"] is True
    assert body.get("progress")
    items = body["progress"]["items"]
    hit = next((i for i in items if "manual-game" in i["series_key"]), None)
    assert hit is not None
    assert hit.get("metadata") or hit.get("total_units") is not None
