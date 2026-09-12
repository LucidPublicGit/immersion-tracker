"""PATCH / DELETE /api/logs and status edits that mark sheets dirty."""

from __future__ import annotations


def test_patch_log_fields(client):
    r = client.post(
        "/api/logs",
        json={
            "content_type": "book",
            "title": "Old Title",
            "amount": 10,
            "unit": "pages",
            "series_key": "book:patch",
        },
    )
    assert r.status_code == 201
    log_id = r.json()["id"]
    assert r.json()["tadoku_status"] == "pending"

    up = client.patch(
        f"/api/logs/{log_id}",
        json={
            "title": "New Title",
            "amount": 20,
            "notes": "edited",
        },
    )
    assert up.status_code == 200
    body = up.json()
    assert body["title"] == "New Title"
    assert body["amount"] == 20
    assert body["notes"] == "edited"
    # pages * 1.0 score
    assert body["tadoku_score_estimate"] == 20.0


def test_patch_tadoku_status_and_mode(client):
    r = client.post(
        "/api/logs",
        json={
            "content_type": "anime",
            "title": "Show",
            "amount": 24,
            "series_key": "anime:status",
        },
    )
    log_id = r.json()["id"]

    # Set ready without approving (no submit)
    up = client.patch(
        f"/api/logs/{log_id}",
        json={"tadoku_status": "ready", "tadoku_mode": "auto"},
    )
    assert up.status_code == 200
    assert up.json()["tadoku_status"] == "ready"
    assert up.json()["tadoku_mode"] == "auto"

    # Skip via status
    up2 = client.patch(
        f"/api/logs/{log_id}",
        json={"tadoku_status": "skipped"},
    )
    assert up2.status_code == 200
    assert up2.json()["tadoku_status"] == "skipped"
    assert up2.json()["tadoku_mode"] == "never"


def test_patch_mode_derives_status(client):
    r = client.post(
        "/api/logs",
        json={
            "content_type": "book",
            "title": "Mode derive",
            "amount": 5,
            "unit": "pages",
        },
    )
    log_id = r.json()["id"]
    up = client.patch(f"/api/logs/{log_id}", json={"tadoku_mode": "never"})
    assert up.status_code == 200
    assert up.json()["tadoku_mode"] == "never"
    assert up.json()["tadoku_status"] == "skipped"


def test_patch_mode_auto_derives_ready_and_catalog(client):
    """Queue mode=auto must promote status + persist series catalog override."""
    r = client.post(
        "/api/logs",
        json={
            "content_type": "anime",
            "title": "Welcome to the N-H-K",
            "amount": 24,
            "series_key": "anime:welcome-to-the-n-h-k-test",
            "season": 1,
            "episode": 1,
        },
    )
    assert r.status_code == 201
    log_id = r.json()["id"]
    assert r.json()["tadoku_mode"] == "pending"
    assert r.json()["tadoku_status"] == "pending"

    # Second pending episode of the same series
    r2 = client.post(
        "/api/logs",
        json={
            "content_type": "anime",
            "title": "Welcome to the N-H-K",
            "amount": 24,
            "series_key": "anime:welcome-to-the-n-h-k-test",
            "season": 1,
            "episode": 2,
            "source_ref": "manual:sibling-ep2",
        },
    )
    assert r2.status_code == 201
    sib_id = r2.json()["id"]
    assert r2.json()["tadoku_status"] == "pending"

    up = client.patch(f"/api/logs/{log_id}", json={"tadoku_mode": "auto"})
    assert up.status_code == 200
    assert up.json()["tadoku_mode"] == "auto"
    assert up.json()["tadoku_status"] == "ready"

    # Sibling pipeline log also promoted
    sib = client.get(f"/api/logs/{sib_id}").json()
    assert sib["tadoku_mode"] == "auto"
    assert sib["tadoku_status"] == "ready"

    # Catalog override so the *next* episode inherits auto
    cats = client.get("/api/catalog").json()
    cat = next(
        c for c in cats if c["series_key"] == "anime:welcome-to-the-n-h-k-test"
    )
    assert cat["tadoku_override"] == "auto"

    # New log on same key picks up catalog override
    r3 = client.post(
        "/api/logs",
        json={
            "content_type": "anime",
            "title": "Welcome to the N-H-K",
            "amount": 24,
            "series_key": "anime:welcome-to-the-n-h-k-test",
            "season": 1,
            "episode": 3,
            "source_ref": "manual:next-ep3",
        },
    )
    assert r3.status_code == 201
    assert r3.json()["tadoku_mode"] == "auto"
    assert r3.json()["tadoku_status"] == "ready"


def test_skip_does_not_set_catalog_never(client):
    """Skip is one-off; must not poison series catalog for future episodes."""
    r = client.post(
        "/api/logs",
        json={
            "content_type": "anime",
            "title": "Skip Catalog Show",
            "amount": 24,
            "series_key": "anime:skip-catalog-show",
            "season": 1,
            "episode": 1,
        },
    )
    log_id = r.json()["id"]
    # First set series to auto via mode dropdown
    client.patch(f"/api/logs/{log_id}", json={"tadoku_mode": "auto"})
    cats = client.get("/api/catalog").json()
    cat = next(c for c in cats if c["series_key"] == "anime:skip-catalog-show")
    assert cat["tadoku_override"] == "auto"

    sk = client.post(f"/api/logs/{log_id}/skip")
    assert sk.status_code == 200
    assert sk.json()["tadoku_mode"] == "never"
    assert sk.json()["tadoku_status"] == "skipped"

    cats2 = client.get("/api/catalog").json()
    cat2 = next(c for c in cats2 if c["series_key"] == "anime:skip-catalog-show")
    assert cat2["tadoku_override"] == "auto"


def test_demote_from_pushed_clears_remote(client, tmp_path, monkeypatch):
    from app.tadoku.client import TadokuClient

    export = tmp_path / "export"
    export.mkdir()
    monkeypatch.setattr(
        "app.tadoku.queue.TadokuClient",
        lambda: TadokuClient(export_dir=str(export), dry_run=True),
    )

    r = client.post(
        "/api/logs",
        json={
            "content_type": "anime",
            "title": "Push then demote",
            "amount": 24,
            "series_key": "anime:demote",
        },
    )
    log_id = r.json()["id"]
    ap = client.post(f"/api/logs/{log_id}/approve")
    assert ap.json()["tadoku_status"] == "pushed"
    assert ap.json()["tadoku_remote_id"]

    up = client.patch(
        f"/api/logs/{log_id}",
        json={"tadoku_status": "pending"},
    )
    assert up.status_code == 200
    assert up.json()["tadoku_status"] == "pending"
    assert not up.json().get("tadoku_remote_id")


def test_delete_log(client):
    r = client.post(
        "/api/logs",
        json={
            "content_type": "book",
            "title": "Delete me",
            "amount": 3,
            "unit": "pages",
        },
    )
    log_id = r.json()["id"]
    d = client.delete(f"/api/logs/{log_id}")
    assert d.status_code == 200
    assert d.json()["ok"] is True
    assert client.get(f"/api/logs/{log_id}").status_code == 404


def test_list_logs_search(client):
    client.post(
        "/api/logs",
        json={
            "content_type": "book",
            "title": "UniqueZebraTitle",
            "amount": 1,
            "unit": "pages",
        },
    )
    r = client.get("/api/logs", params={"q": "zebra", "limit": 50})
    assert r.status_code == 200
    titles = [x["title"] for x in r.json()]
    assert any("Zebra" in t for t in titles)


def test_invalid_status_rejected(client):
    r = client.post(
        "/api/logs",
        json={
            "content_type": "book",
            "title": "Bad status",
            "amount": 1,
            "unit": "pages",
        },
    )
    log_id = r.json()["id"]
    up = client.patch(f"/api/logs/{log_id}", json={"tadoku_status": "nope"})
    assert up.status_code == 400


def test_logs_page_renders(client):
    r = client.get("/logs")
    assert r.status_code == 200
    assert b"Browse" in r.content or b"logs-table" in r.content
    assert b"/api/logs" in r.content or b"loadLogs" in r.content
    # Scope tabs: Recent (default) + All; type filter is a select
    assert b'data-tab="recent"' in r.content
    assert b'data-tab="all"' in r.content
    assert b"logs-tab active" in r.content
    assert b"setTab" in r.content
    # Progress deep-link: exact series_key filter
    assert b"series_key" in r.content
    assert b"applyUrlParams" in r.content
    assert b"series-filter-banner" in r.content


def test_logs_api_filter_by_series_key(client):
    for body in (
        {
            "content_type": "anime",
            "title": "Deep Link Show",
            "source": "manual",
            "amount": 20,
            "unit": "minutes",
            "series_key": "anime:deep-link-show",
            "season": 1,
            "episode": 1,
            "source_ref": "dl-1",
        },
        {
            "content_type": "anime",
            "title": "Other Show",
            "source": "manual",
            "amount": 20,
            "unit": "minutes",
            "series_key": "anime:other-show",
            "season": 1,
            "episode": 1,
            "source_ref": "dl-2",
        },
    ):
        cr = client.post("/api/logs", json=body)
        assert cr.status_code in (200, 201)
    r = client.get("/api/logs", params={"series_key": "anime:deep-link-show"})
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1
    assert rows[0]["series_key"] == "anime:deep-link-show"
