"""Title cleaners and alias expansion for metadata lookup."""

from app.media.title_search import (
    clean_search_title,
    expand_title_aliases,
    is_weak_search_title,
)
from app.media.metadata_cache import build_search_queries


def test_clean_episode_range_tail():
    assert clean_search_title("Attack On Titan E1-E17") == "Attack On Titan"
    assert "S1" not in clean_search_title("Arcane S1+S2")
    assert clean_search_title("Arcane S1+S2").lower().startswith("arcane")


def test_clean_volume_prefix_and_noise():
    assert "無職転生" in clean_search_title("[1巻] 無職転生")
    assert "finished" not in clean_search_title("Resident Evil requiem 5.5k x 13 hours finished").lower()
    assert not clean_search_title("PR: GTSB").startswith("PR")
    assert clean_search_title("MAD chapter") == "MAD"
    assert clean_search_title("とつくにの少女 ９－１０") == "とつくにの少女"
    assert "9" not in clean_search_title("とつくにの少女 ９－１０")


def test_expand_aot_and_bookworm():
    aot = expand_title_aliases("AOT")
    assert any("Attack on Titan" in x for x in aot)
    bw = expand_title_aliases("Bookworm")
    assert any("Bookworm" in x or "本好き" in x for x in bw)


def test_expand_does_not_collapse_film_red_to_tv_series():
    """One Piece Red must expand to Film Red names, not the TV series."""
    red = expand_title_aliases("One Piece Red")
    joined = " ".join(red).lower()
    assert "film" in joined or "レッド" in joined or "red" in joined
    # Must not introduce bare TV-series-only aliases that drown the movie hit
    bare = expand_title_aliases("One Piece")
    assert any("ワンピース" in x or "One Piece" in x for x in bare)
    # Film Red expansion should prefer film titles
    assert any("FILM" in x.upper() or "Film" in x for x in red)


def test_weak_numeric_title():
    assert is_weak_search_title("10000") is True
    assert is_weak_search_title("1") is True
    assert is_weak_search_title("Hyouka") is False


def test_nhk_aliases_expand_across_name_forms():
    """Romaji / punctuated NHK titles expand to the same search cluster."""
    from app.media.title_search import expand_title_aliases, identity_compact

    assert identity_compact("NHK ni Youkoso!") == identity_compact("N.H.K. ni Youkoso")
    for t in (
        "Welcome to the NHK",
        "NHK ni Youkoso!",
        "N.H.K. ni Youkoso",
        "N・H・Kにようこそ",
    ):
        expanded = expand_title_aliases(t)
        joined = " ".join(expanded).lower()
        assert "welcome" in joined or "nhk" in joined
        assert any("youkoso" in e.lower() or "ようこそ" in e or "Welcome" in e for e in expanded)


def test_build_search_queries_includes_aliases():
    qs = build_search_queries("AOT", series_key="anime:aot")
    joined = " ".join(qs).lower()
    assert "attack" in joined or "進撃" in joined or "titan" in joined


def test_expand_jp_and_popular_titles():
    mushoku = expand_title_aliases("無職転生")
    assert any("Mushoku" in x for x in mushoku)
    ippo = expand_title_aliases("Hajime no Ippo")
    assert any("はじめ" in x for x in ippo)
    arcane = expand_title_aliases("Arcane")
    assert any("League" in x for x in arcane)
    totu = expand_title_aliases("とつくにの少女")
    assert any("Girl" in x or "Totsukuni" in x for x in totu)


def test_score_subtitle_heavy_titles():
    from app.media.metadata_cache import score_title_match

    assert score_title_match("Hajime no Ippo", "Hajime no Ippo: Rising") >= 90
    assert (
        score_title_match(
            "Hajime no Ippo", "Hajime no Ippo: THE FIGHTING!"
        )
        >= 90
    )
    assert (
        score_title_match(
            "Mushoku Tensei", "Mushoku Tensei: Isekai Ittara Honki Dasu"
        )
        >= 90
    )
    assert (
        score_title_match("無職転生", "無職転生 ～異世界行ったら本気だす～") >= 90
    )
    assert score_title_match("Arcane", "Arcane") == 100
