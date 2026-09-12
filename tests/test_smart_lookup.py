"""Multi-query media lookup (JP / EN / aliases)."""

from app.media.metadata_cache import build_search_queries, score_title_match


def test_build_search_queries_includes_jp_bang_and_key_slug():
    qs = build_search_queries(
        "この素晴らしい世界に祝福を",
        series_key="anime:konosuba",
        aliases=["KonoSuba", "anime:konosuba"],
    )
    assert any("この素晴らしい世界に祝福を" in q for q in qs)
    # bang variant
    assert any(q.endswith("！") or q.endswith("!") for q in qs)
    assert any("konosuba" in q.lower() for q in qs)
    # no raw series_key forms like anime:konosuba
    assert not any(q.startswith("anime:") for q in qs)
    assert len(qs) <= 12


def test_build_search_queries_strips_contest_noise():
    qs = build_search_queries("Gashiakuta (double)", series_key="anime:gashiakuta")
    assert any(q == "Gashiakuta" for q in qs)
    assert not any("double" in q.lower() for q in qs)


def test_konosuba_jp_matches_official_with_bang():
    score = score_title_match(
        "この素晴らしい世界に祝福を",
        "この素晴らしい世界に祝福を！",
        "Kono Subarashii Sekai ni Shukufuku wo!",
        "KONOSUBA",
    )
    assert score >= 75
