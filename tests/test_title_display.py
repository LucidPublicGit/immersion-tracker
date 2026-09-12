"""Contest-noise stripping + preferred web titles for Progress."""

from app.media.metadata_cache import prefer_web_title, strip_contest_noise


def test_strip_double_and_past_pick():
    assert strip_contest_noise("Gashiakuta (double)") == "Gashiakuta"
    assert strip_contest_noise("Gashiakuta (double]") == "Gashiakuta"
    assert strip_contest_noise("Bookworm (1x past pick)") == "Bookworm"
    assert strip_contest_noise("Mahoyo (double]") == "Mahoyo"
    assert strip_contest_noise("Re:ZERO S01E01 (double") == "Re:ZERO S01E01"
    assert strip_contest_noise("Bookworm 1 (33,537 chars x 2 - 10/25 event) Finished") == "Bookworm 1"


def test_prefer_japanese_web_title():
    assert (
        prefer_web_title(
            native="ガシャクタ",
            romaji="Gachiakuta",
            english="Gachiakuta",
        )
        == "ガシャクタ"
    )
    assert prefer_web_title(native=None, romaji="Dr. STONE", english="Dr. STONE") == "Dr. STONE"
