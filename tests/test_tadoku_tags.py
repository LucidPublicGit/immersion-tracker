"""Tadoku submit tags for content types."""
from __future__ import annotations

from datetime import datetime, timezone

from app.db.models import LogEntry
from app.tadoku.client import TadokuClient


def _entry(**kwargs) -> LogEntry:
    defaults = dict(
        content_type="anime",
        title="Test",
        amount=10,
        unit="minutes",
        activity="listening",
        language="ja",
        source="manual",
        timestamp=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    defaults.update(kwargs)
    return LogEntry(**defaults)


def test_youtube_content_type_tag_is_youtube(tmp_path):
    client = TadokuClient(export_dir=str(tmp_path / "exp"), dry_run=True)
    entry = _entry(
        content_type="youtube",
        source="youtube",
        series_key="yt:@channel",
    )
    tags = client._tags_for(entry)
    assert tags == ["youtube"]


def test_youtube_source_alone_gets_youtube_tag(tmp_path):
    client = TadokuClient(export_dir=str(tmp_path / "exp"), dry_run=True)
    entry = _entry(content_type="", source="youtube", series_key=None)
    assert client._tags_for(entry) == ["youtube"]


def test_media_type_only_no_platform_or_series_tags(tmp_path):
    client = TadokuClient(export_dir=str(tmp_path / "exp"), dry_run=True)
    entry = _entry(content_type="anime", source="plex", series_key="anime:konosuba")
    tags = client._tags_for(entry)
    assert tags == ["anime"]
    assert "plex" not in tags
    assert "konosuba" not in tags


def test_visual_novel_tag_is_vn(tmp_path):
    client = TadokuClient(export_dir=str(tmp_path / "exp"), dry_run=True)
    entry = _entry(content_type="visual_novel", source="manual", series_key=None)
    assert client._tags_for(entry) == ["vn"]


def test_gsm_visual_novel_tags_as_vn_not_game_gsm(tmp_path):
    """GSM exports should look like normal VN logs on tadoku (not #game #gsm)."""
    client = TadokuClient(export_dir=str(tmp_path / "exp"), dry_run=True)
    entry = _entry(
        content_type="visual_novel",
        source="gsm",
        unit="characters",
        amount=15000,
        activity="reading",
        series_key="gsm:some-uuid",
    )
    tags = client._tags_for(entry)
    assert tags == ["vn"]
    assert "game" not in tags
    assert "gsm" not in tags


def test_book_tag_no_hoshi(tmp_path):
    client = TadokuClient(export_dir=str(tmp_path / "exp"), dry_run=True)
    entry = _entry(content_type="book", source="hoshi", series_key="hoshi:Some Book")
    assert client._tags_for(entry) == ["book"]


def test_audiobook_tag_and_dense_duration(tmp_path):
    client = TadokuClient(export_dir=str(tmp_path / "exp"), dry_run=True)
    entry = _entry(
        content_type="audiobook",
        source="audiobookshelf",
        unit="minutes_high_density",
        amount=25,
    )
    assert client._tags_for(entry) == ["audiobook"]
    assert client._duration_seconds(entry) == 25 * 60


def test_youtube_description_includes_link(tmp_path):
    client = TadokuClient(export_dir=str(tmp_path / "exp"), dry_run=True)
    entry = _entry(
        content_type="youtube",
        source="youtube",
        title="Comprehensible Japanese #12",
        source_ref="dQw4w9WgXcQ",
    )
    assert client._description_for(entry) == (
        "Comprehensible Japanese #12 https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    )


def test_youtube_source_alone_description_includes_link(tmp_path):
    client = TadokuClient(export_dir=str(tmp_path / "exp"), dry_run=True)
    entry = _entry(
        content_type="",
        source="youtube",
        title="Some Video",
        source_ref="abc123xyz01",
    )
    assert client._description_for(entry) == (
        "Some Video https://www.youtube.com/watch?v=abc123xyz01"
    )


def test_youtube_description_prefers_notes_url(tmp_path):
    client = TadokuClient(export_dir=str(tmp_path / "exp"), dry_run=True)
    entry = _entry(
        content_type="youtube",
        source="youtube",
        title="Clip",
        source_ref="vid999",
        notes="ratio=1.000; url=https://youtu.be/vid999",
    )
    assert client._description_for(entry) == "Clip https://youtu.be/vid999"


def test_youtube_description_legacy_source_ref(tmp_path):
    client = TadokuClient(export_dir=str(tmp_path / "exp"), dry_run=True)
    entry = _entry(
        content_type="youtube",
        source="youtube",
        title="Old row",
        source_ref="legacyvid:2026-07-01",
    )
    assert client._description_for(entry) == (
        "Old row https://www.youtube.com/watch?v=legacyvid"
    )


def test_non_youtube_description_unprefixed(tmp_path):
    client = TadokuClient(export_dir=str(tmp_path / "exp"), dry_run=True)
    entry = _entry(
        content_type="anime",
        source="plex",
        title="KonoSuba",
        season=1,
        episode=2,
    )
    assert client._description_for(entry) == "KonoSuba S01E02"
