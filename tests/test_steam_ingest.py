"""Steam playtime ingest — mocked HTTP, isolated DB via client fixture."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.db.models import LogEntry
from app.db.session import get_engine
from app.ingest.steam import (
    game_allowed,
    get_playtime_watermark,
    poll_steam,
    steam_status,
)
from sqlalchemy.orm import sessionmaker


def _db():
    SessionLocal = sessionmaker(bind=get_engine(), autoflush=False, autocommit=False)
    return SessionLocal()


def _enable_steam(
    *,
    api_key: str = "test-key",
    steam_id: str = "76561198000000000",
    bootstrap: bool = False,
    min_delta_minutes: float = 1.0,
    app_allowlist: list | None = None,
    app_blocklist: list | None = None,
    name_allowlist: list | None = None,
    name_blocklist: list | None = None,
) -> None:
    from app.core.config import get_settings

    cfg = get_settings().yaml_config.steam
    cfg.enabled = True
    cfg.api_key = api_key
    cfg.steam_id = steam_id
    cfg.bootstrap = bootstrap
    cfg.min_delta_minutes = min_delta_minutes
    cfg.app_allowlist = list(app_allowlist or [])
    cfg.app_blocklist = list(app_blocklist or [])
    cfg.name_allowlist = list(name_allowlist or [])
    cfg.name_blocklist = list(name_blocklist or [])
    cfg.content_type = "game"
    cfg.unit = "minutes"
    cfg.activity = "reading"
    cfg.tadoku_default = "never"


def _games_payload(games: list[dict]) -> dict:
    return {"response": {"game_count": len(games), "games": games}}


def _mock_httpx_get(payload: dict, status_code: int = 200):
    """Patch httpx.Client so GET returns payload JSON."""

    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.raise_for_status = MagicMock()
    if status_code >= 400:
        import httpx

        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error",
            request=MagicMock(),
            response=mock_resp,
        )
    mock_resp.json.return_value = payload

    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.get.return_value = mock_resp
    return mock_client


def test_steam_disabled(client):
    from app.core.config import get_settings

    get_settings().yaml_config.steam.enabled = False
    db = _db()
    try:
        r = poll_steam(db)
        assert r.ok is True
        assert r.source == "steam"
        assert r.message == "disabled"
        assert r.logs_created == 0
    finally:
        db.close()


def test_steam_missing_credentials(client):
    from app.core.config import get_settings

    cfg = get_settings().yaml_config.steam
    cfg.enabled = True
    cfg.api_key = ""
    cfg.steam_id = ""

    db = _db()
    try:
        with patch.dict("os.environ", {"STEAM_API_KEY": "", "STEAM_ID": ""}, clear=False):
            r = poll_steam(db)
        assert r.ok is False
        assert "missing credentials" in r.message
        assert r.logs_created == 0
    finally:
        db.close()


def test_steam_bootstrap_baseline_then_delta(client):
    """bootstrap=False: first poll baselines only; second poll logs the delta."""
    _enable_steam(bootstrap=False, min_delta_minutes=1.0)
    games_v1 = [
        {"appid": 12345, "name": "JP Visual Novel", "playtime_forever": 100},
    ]
    games_v2 = [
        {"appid": 12345, "name": "JP Visual Novel", "playtime_forever": 145},
    ]

    db = _db()
    try:
        with patch("app.ingest.steam.httpx.Client") as Client:
            Client.return_value = _mock_httpx_get(_games_payload(games_v1))
            r1 = poll_steam(db)
        assert r1.ok is True
        assert r1.logs_created == 0
        assert get_playtime_watermark(db, 12345) == 100
        assert db.query(LogEntry).filter(LogEntry.source == "steam").count() == 0

        with patch("app.ingest.steam.httpx.Client") as Client:
            Client.return_value = _mock_httpx_get(_games_payload(games_v2))
            r2 = poll_steam(db)
        assert r2.ok is True
        assert r2.logs_created == 1
        assert get_playtime_watermark(db, 12345) == 145

        entry = db.query(LogEntry).filter(LogEntry.source == "steam").one()
        assert entry.amount == 45.0
        assert entry.title == "JP Visual Novel"
        assert entry.series_key == "steam:12345"
        assert entry.source_ref == "steam:12345:145"
        assert entry.unit == "minutes"
        assert entry.content_type == "game"
    finally:
        db.close()


def test_steam_allowlist_filters(client):
    _enable_steam(
        bootstrap=False,
        app_allowlist=[111],
        min_delta_minutes=1.0,
    )
    # Seed watermarks so both would create logs if not filtered
    from app.ingest.steam import set_playtime_watermark

    db = _db()
    try:
        set_playtime_watermark(db, 111, 10)
        set_playtime_watermark(db, 222, 10)
        games = [
            {"appid": 111, "name": "Allowed Game", "playtime_forever": 40},
            {"appid": 222, "name": "Blocked Other", "playtime_forever": 99},
        ]
        with patch("app.ingest.steam.httpx.Client") as Client:
            Client.return_value = _mock_httpx_get(_games_payload(games))
            r = poll_steam(db)
        assert r.ok is True
        assert r.logs_created == 1
        entries = db.query(LogEntry).filter(LogEntry.source == "steam").all()
        assert len(entries) == 1
        assert entries[0].series_key == "steam:111"
        assert entries[0].amount == 30.0
        # Blocked app watermark must not advance (never processed past filter)
        assert get_playtime_watermark(db, 222) == 10
        assert get_playtime_watermark(db, 111) == 40
    finally:
        db.close()


def test_steam_name_blocklist(client):
    assert game_allowed(
        1,
        "Cool VN",
        app_allowlist=[],
        app_blocklist=[],
        name_allowlist=[],
        name_blocklist=["dota", "counter-strike"],
    )
    assert not game_allowed(
        1,
        "Dota 2",
        app_allowlist=[],
        app_blocklist=[],
        name_allowlist=[],
        name_blocklist=["dota"],
    )


def test_steam_min_delta_minutes_skip(client):
    """Deltas below min_delta are skipped; watermark held so time accumulates."""
    _enable_steam(bootstrap=False, min_delta_minutes=30.0)
    from app.ingest.steam import set_playtime_watermark

    db = _db()
    try:
        set_playtime_watermark(db, 555, 100)
        games = [
            {"appid": 555, "name": "Short Session", "playtime_forever": 110},
        ]
        with patch("app.ingest.steam.httpx.Client") as Client:
            Client.return_value = _mock_httpx_get(_games_payload(games))
            r = poll_steam(db)
        assert r.ok is True
        assert r.logs_created == 0
        # Watermark held at baseline so 10m is not dropped
        assert get_playtime_watermark(db, 555) == 100
        assert db.query(LogEntry).filter(LogEntry.source == "steam").count() == 0

        # Accumulated: 100→145 = 45 ≥ 30 → log full gap
        games2 = [
            {"appid": 555, "name": "Short Session", "playtime_forever": 145},
        ]
        with patch("app.ingest.steam.httpx.Client") as Client:
            Client.return_value = _mock_httpx_get(_games_payload(games2))
            r2 = poll_steam(db)
        assert r2.logs_created == 1
        entry = db.query(LogEntry).filter(LogEntry.source == "steam").one()
        assert entry.amount == 45.0
        assert get_playtime_watermark(db, 555) == 145
    finally:
        db.close()


def test_steam_http_error_graceful(client):
    import httpx

    _enable_steam()
    db = _db()
    try:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = httpx.ConnectError("no network")

        with patch("app.ingest.steam.httpx.Client", return_value=mock_client):
            r = poll_steam(db)
        assert r.ok is False
        assert "http_error" in r.message
        assert r.logs_created == 0
    finally:
        db.close()


def test_steam_status(client):
    _enable_steam(api_key="k", steam_id="76561198000000000")
    db = _db()
    try:
        st = steam_status(db)
        assert st["enabled"] is True
        assert st["configured"] is True
        assert st["has_api_key"] is True
        assert st["has_steam_id"] is True
        assert st["tracked_apps"] == 0
        assert st["poll_seconds"] >= 60
    finally:
        db.close()
