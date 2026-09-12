"""Content-type-aware metadata matching (anime ≠ manga ≠ movie)."""

from app.media.metadata_cache import (
    _filter_jiten_by_type,
    _jiten_allowed_types,
    _jiten_format_bonus,
    _resolved_fits_content_type,
    ResolvedMedia,
)


def test_jiten_allowed_types_strict():
    assert _jiten_allowed_types("anime") == {1}
    assert 3 not in (_jiten_allowed_types("anime") or set())  # not movies
    assert 9 not in (_jiten_allowed_types("anime") or set())  # not manga
    assert _jiten_allowed_types("manga") == {9}
    assert _jiten_allowed_types("movie") == {3}


def test_filter_jiten_drops_wrong_type():
    cands = [
        {"deckId": 1, "mediaType": 1, "englishTitle": "Yu-Gi-Oh!"},
        {"deckId": 2, "mediaType": 9, "englishTitle": "Yu-Gi-Oh!"},
        {"deckId": 3, "mediaType": 3, "englishTitle": "Yu-Gi-Oh! Movie"},
    ]
    anime_only = _filter_jiten_by_type(cands, "anime")
    assert all(c["mediaType"] == 1 for c in anime_only)
    assert len(anime_only) == 1
    manga_only = _filter_jiten_by_type(cands, "manga")
    assert manga_only[0]["deckId"] == 2


def test_format_bonus_prefers_long_anime():
    # Short pilot / Toei 4-ep
    short = _jiten_format_bonus("anime", media_type=1, units=4, min_episode=18)
    long = _jiten_format_bonus("anime", media_type=1, units=144, min_episode=18)
    assert long > short
    assert short < 0  # penalized vs logged E18


def test_resolved_fits_rejects_short_for_logged_ep():
    short = ResolvedMedia(
        source="jiten",
        external_id="875",
        external_url=None,
        title="Yu-Gi-Oh!",
        cover_url=None,
        total_units=4,
        total_units_label="episodes",
        total_characters=16939,
        total_minutes=52,
        raw={"detail_main": {"mediaType": 1}},
    )
    assert _resolved_fits_content_type(short, "anime", min_episode=18) is False
    long = ResolvedMedia(
        source="jiten",
        external_id="18917",
        external_url=None,
        title="Yu-Gi-Oh! Duel Monsters",
        cover_url=None,
        total_units=144,
        total_units_label="episodes",
        total_characters=600000,
        total_minutes=2000,
        raw={"detail_main": {"mediaType": 1}},
    )
    assert _resolved_fits_content_type(long, "anime", min_episode=18) is True


def test_resolved_fits_rejects_manga_for_anime():
    manga = ResolvedMedia(
        source="jiten",
        external_id="1",
        external_url=None,
        title="Something",
        cover_url=None,
        total_units=10,
        total_units_label="volumes",
        total_characters=None,
        total_minutes=None,
        raw={"detail_main": {"mediaType": 9}},
    )
    assert _resolved_fits_content_type(manga, "anime") is False


def test_resolved_fits_rejects_anime_for_audiobook():
    """Mushoku audiobook must not accept the 11-ep anime jiten deck."""
    anime = ResolvedMedia(
        source="jiten",
        external_id="22937",
        external_url=None,
        title="Mushoku Tensei",
        cover_url=None,
        total_units=11,
        total_units_label="episodes",
        total_characters=46306,
        total_minutes=148,
        raw={"detail_main": {"mediaType": 1}, "match": {"mediaType": 1}},
    )
    assert _resolved_fits_content_type(anime, "audiobook") is False
    assert _resolved_fits_content_type(anime, "book") is False
    book = ResolvedMedia(
        source="jiten",
        external_id="54768",
        external_url=None,
        title="Mushoku Tensei",
        cover_url=None,
        total_units=26,
        total_units_label="volumes",
        total_characters=None,
        total_minutes=None,
        raw={"detail_main": {"mediaType": 4}},
    )
    assert _resolved_fits_content_type(book, "audiobook") is True
    assert _resolved_fits_content_type(book, "book") is True
