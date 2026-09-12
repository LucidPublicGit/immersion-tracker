"""Canonical work identity: shelf filtering, title clean, key collapse."""

from app.media.work_identity import (
    canonical_series_key,
    is_progress_shelf_work,
    is_study_tool,
    normalize_work_title,
    prepare_log_identity,
)


def test_normalize_episode_comma_list():
    """Episode lists like 'Gachiakuta 2,3' must not stick in the shelf title."""
    assert normalize_work_title("Gachiakuta 2,3") == "Gachiakuta"
    assert normalize_work_title("Gachiakuta 2, 3") == "Gachiakuta"
    assert normalize_work_title("Gachiakuta 2,3 (double)") == "Gachiakuta"
    assert normalize_work_title("GTO 5,6") == "GTO"
    from app.media.work_identity import peel_log_fields, prepare_log_identity

    peel = peel_log_fields("Gachiakuta 2,3")
    assert peel["title"] == "Gachiakuta"
    assert peel["episode"] == 3
    ident = prepare_log_identity(
        content_type="anime", title="Gachiakuta 2,3", series_key="anime:gachiakuta"
    )
    assert ident["title"] == "Gachiakuta"


def test_normalize_one_piece_volumes():
    assert normalize_work_title("One Piece 19 (218 pages]") == "One Piece"
    assert normalize_work_title("One Piece 18 (224 pages]") == "One Piece"
    assert normalize_work_title("One Piece vol 11 page") == "One Piece"
    assert normalize_work_title("One Piece 31 half") == "One Piece"
    # Must not swallow distinct works
    assert "Film" in normalize_work_title("ONE PIECE FILM RED") or "Red" in normalize_work_title(
        "ONE PIECE FILM RED"
    ) or normalize_work_title("ONE PIECE FILM RED") != "One Piece"
    # One Piece Red is the theatrical film, not the TV series
    red = normalize_work_title("One Piece Red")
    assert red != "One Piece"
    assert "Red" in red or "FILM" in red.upper()
    assert canonical_series_key("anime", "One Piece Red").startswith("movie:")
    assert "film-red" in canonical_series_key("anime", "One Piece Red")
    from app.media.work_identity import infer_content_type

    assert infer_content_type("One Piece Red", "anime") == "movie"
    assert infer_content_type("ONE PIECE FILM RED", "anime") == "movie"


def test_normalize_episode_fragments():
    assert "Attack" in normalize_work_title("Attack On Titan E1-E17")
    assert "Arcane" in normalize_work_title("Arcane S1+S2")
    assert normalize_work_title("Re:ZERO S01E01").lower().startswith("re")


def test_normalize_mad_and_totsukuni():
    assert normalize_work_title("MAD chapter") == "MAD"
    assert normalize_work_title("mad ch") == "MAD"
    assert normalize_work_title("MAD chapter 4-8") == "MAD"
    assert normalize_work_title("とつくにの少女 ９－１０") == "とつくにの少女"
    assert normalize_work_title("とつくにの少女 1-8") == "とつくにの少女"
    k1 = canonical_series_key(
        "manga",
        "とつくにの少女 ９－１０",
        existing_key="anime:とつくにの少女-9-10",
    )
    k2 = canonical_series_key(
        "manga",
        "とつくにの少女",
        existing_key="anime:とつくにの少女",
    )
    assert k1 == k2
    assert "totsukuni" in k1
    assert k1.startswith("manga:")
    mad_key = canonical_series_key(
        "anime", "MAD chapter", existing_key="anime:mad-chapter"
    )
    assert mad_key == "manga:mad"
    assert canonical_series_key(
        "game", "Hogwards Legacy", existing_key="anime:hogwards-legacy"
    ) == "game:hogwarts-legacy"
    assert canonical_series_key(
        "anime", "Arcane S1+S2", existing_key="anime:arcane-s1-s2"
    ) == "show:arcane"


def test_study_tools():
    assert is_study_tool("Anki", content_type="anime")
    assert is_study_tool("Bunpro", series_key="anime:bunpro")
    assert is_study_tool("Italki", source="manual")
    assert is_study_tool("Anki (11-25) 14min", series_key="anime:anki-11-25")
    assert not is_study_tool("One Piece", content_type="anime")


def test_shelf_excludes_junk():
    assert not is_progress_shelf_work(title="Anki", content_type="anime")
    assert not is_progress_shelf_work(title="Bunpro", content_type="study")
    assert not is_progress_shelf_work(title="2024 Weeb Club Carry Over")
    assert not is_progress_shelf_work(title="10000", series_key="anime:10000")
    assert not is_progress_shelf_work(title="Video", content_type="youtube")
    assert is_progress_shelf_work(title="One Piece", content_type="anime")


def test_shelf_excludes_english_shows():
    assert not is_progress_shelf_work(
        title="Silo",
        content_type="show",
        series_key="show:silo",
        languages={"en"},
        tadoku_modes={"never"},
    )
    assert not is_progress_shelf_work(
        title="House of the Dragon",
        content_type="show",
        series_key="show:house-of-the-dragon",
        tadoku_modes={"never"},
    )
    # Japanese content stays even if mode=never on some logs
    assert is_progress_shelf_work(
        title="この素晴らしい世界に祝福を！",
        content_type="anime",
        languages={"ja"},
        tadoku_modes={"never"},
    )
    # 水曜日のダウンタウン must not match denylist "wednesday"
    assert is_progress_shelf_work(
        title="水曜日のダウンタウン",
        content_type="show",
        languages={"ja"},
    )


def test_canonical_one_piece_key():
    k1 = canonical_series_key(
        "anime",
        "One Piece 19 (218 pages]",
        existing_key="anime:one-piece-19-218-pages",
    )
    k2 = canonical_series_key(
        "anime",
        "One Piece 18 (224 pages]",
        existing_key="anime:one-piece-18-224-pages",
    )
    k3 = canonical_series_key("anime", "One Piece", existing_key="anime:one-piece")
    assert k1 == k2 == k3 == "anime:one-piece"


def test_combine_en_jp_romaji_titles():
    """
    Same work under different names → one series_key (Progress shelf).

    e.g. Welcome to the NHK / NHK ni Youkoso! / N・H・Kにようこそ
    """
    from app.media.work_identity import resolve_title_identity

    nhk_titles = [
        "Welcome to the NHK",
        "welcome to the nhk",
        "Welcome to the N-H-K",
        "NHK ni Youkoso!",
        "NHK ni Youkoso",
        "N.H.K. ni Youkoso",
        "N・H・Kにようこそ",
        "NHKにようこそ",
    ]
    keys = {canonical_series_key("anime", t) for t in nhk_titles}
    assert keys == {"anime:welcome-to-the-nhk"}
    for t in nhk_titles:
        assert normalize_work_title(t) == "Welcome to the NHK"
        assert resolve_title_identity(t) == "Welcome to the NHK"

    # Existing distinct auto-keys must rewrite onto the same target
    for sk, t in [
        ("anime:nhk", "Welcome to the NHK"),
        ("anime:welcome-to-the-n-h-k", "Welcome to the N-H-K"),
        ("anime:nhk-ni-youkoso", "NHK ni Youkoso!"),
        ("anime:n-h-k-ni-youkoso", "N.H.K. ni Youkoso"),
    ]:
        assert (
            canonical_series_key("anime", t, existing_key=sk)
            == "anime:welcome-to-the-nhk"
        )

    # Other EN/JP pairs stay grouped under their known keys
    assert canonical_series_key("anime", "Frieren") == canonical_series_key(
        "anime", "葬送のフリーレン"
    )
    assert canonical_series_key("anime", "GTO") == canonical_series_key(
        "anime", "Great Teacher Onizuka"
    )
    assert canonical_series_key("anime", "GTO") == "anime:gto"


def test_aggregate_combines_nhk_name_variants(client):
    """Progress aggregation must show one row for EN + romaji NHK logs."""
    from app.db.session import _SessionLocal
    from app.ingest.service import create_log
    from app.media.progress import aggregate_progress

    assert _SessionLocal is not None
    db = _SessionLocal()
    try:
        create_log(
            db,
            content_type="anime",
            title="Welcome to the NHK",
            source="manual",
            amount=24,
            unit="minutes",
            series_key="anime:welcome-to-the-nhk",
            source_ref="nhk-en-1",
            season=1,
            episode=1,
        )
        create_log(
            db,
            content_type="anime",
            title="NHK ni Youkoso!",
            source="manual",
            amount=24,
            unit="minutes",
            series_key="anime:nhk-ni-youkoso",
            source_ref="nhk-romaji-1",
            season=1,
            episode=2,
        )
        create_log(
            db,
            content_type="anime",
            title="N・H・Kにようこそ",
            source="manual",
            amount=24,
            unit="minutes",
            series_key="anime:nhk",
            source_ref="nhk-jp-1",
            season=1,
            episode=3,
        )
        rows = aggregate_progress(db, auto_finish=False)
        nhk = [
            r
            for r in rows
            if "nhk" in (r.get("series_key") or "").lower()
            or "nhk" in (r.get("title") or "").lower()
            or "youkoso" in (r.get("title") or "").lower()
        ]
        assert len(nhk) == 1, f"expected 1 NHK row, got {nhk}"
        assert nhk[0]["series_key"] == "anime:welcome-to-the-nhk"
        assert nhk[0]["log_count"] >= 3
        assert nhk[0]["title"] == "Welcome to the NHK"
    finally:
        db.close()


def test_prepare_log_identity_study_and_peel():
    id_anki = prepare_log_identity(
        content_type="anime", title="Anki", source="manual", series_key="anime:anki"
    )
    assert id_anki["content_type"] == "study"
    assert id_anki["series_key"].startswith("study:")

    id_op = prepare_log_identity(
        content_type="anime",
        title="One Piece 20 (218 pages]",
        source="manual",
        series_key="anime:one-piece-20-218-pages",
    )
    assert id_op["title"] == "One Piece"
    assert id_op["series_key"] == "anime:one-piece"


def test_aggregate_collapses_and_hides_study(client):
    from app.db.session import _SessionLocal
    from app.ingest.service import create_log
    from app.media.progress import aggregate_progress

    assert _SessionLocal is not None
    db = _SessionLocal()
    try:
        create_log(
            db,
            content_type="anime",
            title="One Piece 99 (99 pages]",
            source="manual",
            amount=10,
            unit="pages",
            series_key="anime:one-piece-99-pages",
            source_ref="op-frag-1",
        )
        create_log(
            db,
            content_type="anime",
            title="One Piece",
            source="manual",
            amount=10,
            unit="pages",
            series_key="anime:one-piece",
            source_ref="op-main-1",
        )
        create_log(
            db,
            content_type="anime",
            title="Bunpro",
            source="manual",
            amount=15,
            unit="minutes",
            series_key="anime:bunpro",
            source_ref="bp-1",
        )
        rows = aggregate_progress(db, auto_finish=False)
        keys = {r["series_key"] for r in rows}
        titles = {r["title"] for r in rows}
        # Page-unit logs are manga immersion, not the anime series key
        assert "manga:one-piece" in keys or "anime:one-piece" in keys
        assert "anime:bunpro" not in keys
        assert "Bunpro" not in titles
        op = [
            r
            for r in rows
            if "one-piece" in r["series_key"] or r["title"] == "One Piece"
        ]
        assert len(op) == 1
        assert op[0]["log_count"] >= 2
        assert op[0]["content_type"] in ("manga", "anime")
    finally:
        db.close()


def test_normalize_library_fixup(client):
    from app.db.models import LogEntry
    from app.db.session import _SessionLocal
    from app.ingest.service import create_log

    assert _SessionLocal is not None
    db = _SessionLocal()
    try:
        create_log(
            db,
            content_type="anime",
            title="Italki",
            source="manual",
            amount=30,
            unit="minutes",
            series_key="anime:italki",
            source_ref="it-1",
        )
        log = db.query(LogEntry).filter(LogEntry.source_ref == "it-1").one()
        assert log.content_type == "study"
    finally:
        db.close()

    r = client.post(
        "/api/progress/fixup",
        json={"action": "normalize_library", "series_keys": []},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    items = body["progress"]["items"]
    assert not any(
        "italki" in (i.get("title") or "").lower()
        or "italki" in (i.get("series_key") or "")
        for i in items
    )
