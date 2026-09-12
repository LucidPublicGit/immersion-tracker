"""Strict media title matching + jiten false-positive guards."""

from app.media.metadata_cache import MIN_MATCH_SCORE, score_title_match


def test_yanineko_not_whisker_away():
    # This false positive previously assigned A Whisker Away's cover
    score = score_title_match(
        "yanineko",
        "A Whisker Away",
        "Nakitai Watashi wa Neko wo Kaburu",
        "泣きたい私は猫をかぶる",
    )
    assert score < MIN_MATCH_SCORE


def test_yanineko_matches_yani_neko_and_japanese():
    assert score_title_match("yanineko", "Yani Neko") >= MIN_MATCH_SCORE
    assert score_title_match("yani neko", "Yani Neko") >= MIN_MATCH_SCORE
    assert score_title_match("ヤニねこ", "ヤニねこ", "Yani Neko") >= MIN_MATCH_SCORE
    assert score_title_match("yanineko", "Yani Neko", "Chainsmoker Cat", "ヤニねこ") >= 75


def test_gto_exact():
    assert score_title_match("GTO", "GTO: Great Teacher Onizuka", "GTO") >= MIN_MATCH_SCORE
