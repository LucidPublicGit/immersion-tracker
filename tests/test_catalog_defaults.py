from __future__ import annotations


def test_new_catalog_defaults_unit_by_content_type(client):
    cases = [
        ("anime", "minutes"),
        ("visual_novel", "characters"),
        ("game", "minutes"),
        ("book", "characters"),
        ("manga", "characters"),
        ("youtube", "minutes"),
    ]
    for ctype, expected_unit in cases:
        r = client.post(
            "/api/catalog",
            json={
                "series_key": f"{ctype}:default-unit-test",
                "display_title": f"Test {ctype}",
                "content_type": ctype,
            },
        )
        assert r.status_code == 201, r.text
        assert r.json()["default_unit"] == expected_unit


def test_catalog_default_unit_can_be_overridden(client):
    r = client.post(
        "/api/catalog",
        json={
            "series_key": "book:custom-unit",
            "display_title": "Custom",
            "content_type": "book",
            "default_unit": "pages",
        },
    )
    assert r.status_code == 201
    assert r.json()["default_unit"] == "pages"

    r = client.patch(
        "/api/catalog/book:custom-unit",
        json={"default_unit": "comic_pages"},
    )
    assert r.status_code == 200
    assert r.json()["default_unit"] == "comic_pages"


def test_log_uses_catalog_default_unit(client):
    client.post(
        "/api/catalog",
        json={
            "series_key": "book:char-default",
            "display_title": "文字本",
            "content_type": "book",
            "default_unit": "characters",
        },
    )
    r = client.post(
        "/api/logs",
        json={
            "content_type": "book",
            "title": "文字本",
            "amount": 5000,
            "series_key": "book:char-default",
        },
    )
    assert r.status_code == 201
    assert r.json()["unit"] == "characters"
