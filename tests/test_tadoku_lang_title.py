"""Language normalize + movie title (no S00E00)."""

from app.media.title_format import format_episode_tag, tadoku_title
from app.tadoku.client import normalize_tadoku_language


def test_normalize_tadoku_language():
    assert normalize_tadoku_language("ja") == "jpn"
    assert normalize_tadoku_language("en") == "eng"
    assert normalize_tadoku_language("jpn") == "jpn"
    assert normalize_tadoku_language("") == "jpn"
    assert normalize_tadoku_language(None, default="jpn") == "jpn"


def test_movie_title_no_s00e00():
    from app.media.title_format import format_progress_position

    assert format_episode_tag(0, 0) == ""
    assert format_progress_position("movie", 0, 0) == ""
    assert format_progress_position("movie", 1, 1) == ""
    assert (
        tadoku_title(
            "Chiikawa the Movie: The Secret of the Mermaid Island",
            season=0,
            episode=0,
            content_type="movie",
        )
        == "Chiikawa the Movie: The Secret of the Mermaid Island"
    )
    assert tadoku_title("Film", season=1, episode=2, content_type="film") == "Film"
    assert tadoku_title("Show", season=1, episode=2, content_type="anime") == "Show S01E02"


if __name__ == "__main__":
    test_normalize_tadoku_language()
    test_movie_title_no_s00e00()
    print("ok")
