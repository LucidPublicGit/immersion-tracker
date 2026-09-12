from app.sheets import enums as E


def test_type_tab_titles():
    assert E.type_tab_title("anime") == "Logs · Anime"
    assert E.type_tab_title("visual_novel") == "Logs · VN"
    assert E.type_tab_title("book") == "Logs · Book"
    assert E.type_tab_title("game") == "Logs · Game"


def test_content_types_include_core():
    types = E.content_types()
    for t in ("anime", "book", "visual_novel", "game", "youtube"):
        assert t in types


def test_log_headers_stable():
    assert E.LOG_HEADERS[0] == "id"
    assert "content_type" in E.LOG_HEADERS
    assert "tadoku_mode" in E.LOG_HEADERS
