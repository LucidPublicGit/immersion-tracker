from app.media.title_format import (
    format_episode_tag,
    format_progress_position,
    suggest_series_key,
    tadoku_title,
)


def test_tadoku_title_season_episode():
    assert tadoku_title("KonoSuba", season=1, episode=2) == "KonoSuba S01E02"
    assert (
        tadoku_title("KonoSuba", season=1, episode=2, content_type="anime")
        == "KonoSuba S01E02"
    )


def test_tadoku_title_episode_only():
    assert tadoku_title("Show", episode=5) == "Show E05"


def test_tadoku_title_manga_volume():
    assert tadoku_title("Slam Dunk", episode=9, content_type="manga") == "Slam Dunk Vol 9"
    assert tadoku_title("Kokoro", episode=1, content_type="book") == "Kokoro Vol 1"


def test_tadoku_title_no_ep():
    assert tadoku_title("Book Title") == "Book Title"


def test_series_key_anime():
    assert suggest_series_key("anime", "KonoSuba") == "anime:konosuba"
    assert suggest_series_key("visual_novel", "Steins;Gate") == "vn:steins-gate"


def test_format_tag():
    assert format_episode_tag(1, 12) == "S01E12"
    assert format_progress_position("manga", episode=9) == "Vol 9"
