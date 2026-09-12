"""Spotify podcast poller: token refresh, allowlist, dedupe, podcasts_only."""

from __future__ import annotations

import json
import time
from pathlib import Path

import httpx

from app.db.models import LogEntry
from app.db.session import get_engine
from app.ingest.spotify import (
    parse_play_item,
    poll_spotify,
    show_allowed,
    spotify_status,
)
from sqlalchemy.orm import sessionmaker


def _db():
    SessionLocal = sessionmaker(bind=get_engine(), autoflush=False, autocommit=False)
    return SessionLocal()


def _episode_item(
    *,
    episode_id: str = "ep1",
    episode_name: str = "Nihongo Episode 1",
    show_id: str = "show123",
    show_name: str = "Comprehensible Japanese",
    duration_ms: int = 1_800_000,
    played_at: str = "2026-07-20T12:00:00.000Z",
) -> dict:
    return {
        "played_at": played_at,
        "context": {
            "type": "show",
            "uri": f"spotify:show:{show_id}",
        },
        "track": {
            "id": episode_id,
            "name": episode_name,
            "duration_ms": duration_ms,
            "type": "episode",
            "uri": f"spotify:episode:{episode_id}",
            "show": {
                "id": show_id,
                "name": show_name,
            },
        },
    }


def _track_item(
    *,
    track_id: str = "tr1",
    name: str = "Some Song",
    duration_ms: int = 200_000,
    played_at: str = "2026-07-20T11:00:00.000Z",
) -> dict:
    return {
        "played_at": played_at,
        "context": {"type": "album", "uri": "spotify:album:abc"},
        "track": {
            "id": track_id,
            "name": name,
            "duration_ms": duration_ms,
            "type": "track",
            "uri": f"spotify:track:{track_id}",
            "artists": [{"id": "art1", "name": "Artist"}],
            "album": {"name": "Album"},
        },
    }


def _enable_spotify(monkeypatch, tmp_path: Path, **overrides):
    from app.core.config import get_settings

    token_path = tmp_path / "spotify-oauth-token.json"
    token_path.write_text(
        json.dumps(
            {
                "refresh_token": "refresh-xyz",
                "access_token": "access-old",
                "expires_at": int(time.time()) - 10,  # force refresh
            }
        ),
        encoding="utf-8",
    )

    cfg = get_settings().yaml_config.spotify
    cfg.enabled = True
    cfg.client_id = "cid"
    cfg.client_secret = "csecret"
    cfg.token_file = str(token_path)
    cfg.podcasts_only = True
    cfg.show_allowlist = []
    cfg.show_blocklist = []
    cfg.content_type = "podcast"
    cfg.unit = "minutes"
    cfg.activity = "listening"
    cfg.tadoku_default = "pending"
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return token_path


class _FakeResponse:
    def __init__(
        self,
        status_code: int,
        payload: dict | None = None,
        text: str | None = None,
    ):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        if text is not None:
            self.text = text
        else:
            self.text = json.dumps(self._payload) if self._payload is not None else ""
        self.content = self.text.encode("utf-8") if self.text else b""

    def json(self):
        return self._payload


def _patch_httpx(monkeypatch, *, recent_items: list[dict], refresh_ok: bool = True):
    """Patch httpx.Client so token refresh + recently-played use mocks."""

    def handler(method: str, url: str, **kwargs):
        url = str(url)
        if "accounts.spotify.com/api/token" in url:
            if not refresh_ok:
                return _FakeResponse(401, {"error": "invalid_client"}, "invalid")
            return _FakeResponse(
                200,
                {
                    "access_token": "access-new",
                    "expires_in": 3600,
                    "token_type": "Bearer",
                },
            )
        if "recently-played" in url:
            return _FakeResponse(200, {"items": recent_items})
        if "currently-playing" in url:
            return _FakeResponse(204, payload=None, text="")
        return _FakeResponse(404, {"error": "not found"}, text="not found")

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, **kwargs):
            return handler("POST", url, **kwargs)

        def get(self, url, **kwargs):
            return handler("GET", url, **kwargs)

        def close(self):
            pass

    monkeypatch.setattr(httpx, "Client", FakeClient)
    return FakeClient


def test_parse_episode_item():
    play = parse_play_item(_episode_item())
    assert play is not None
    assert play["kind"] == "episode"
    assert play["source_ref"] == "spotify:episode:ep1"
    assert play["series_key"] == "spotify:show:show123"
    assert play["show_name"] == "Comprehensible Japanese"
    assert play["duration_ms"] == 1_800_000


def test_parse_track_item():
    play = parse_play_item(_track_item())
    assert play is not None
    assert play["kind"] == "track"
    assert play["source_ref"] == "spotify:track:tr1"


def test_show_allowlist_match_id_and_name():
    from app.core.config import SpotifyConfig

    cfg = SpotifyConfig(show_allowlist=["show123", "nihongo"])
    assert show_allowed("show123", "Other", cfg=cfg)[0] is True
    assert show_allowed("other", "Comprehensible Nihongo Pod", cfg=cfg)[0] is True
    assert show_allowed("zzz", "Music Talk", cfg=cfg)[0] is False


def test_show_blocklist():
    from app.core.config import SpotifyConfig

    cfg = SpotifyConfig(show_blocklist=["badshow"])
    assert show_allowed("badshow", "X", cfg=cfg)[0] is False
    assert show_allowed("ok", "Fine Show", cfg=cfg)[0] is True


def test_poll_disabled(client, monkeypatch, tmp_path):
    from app.core.config import get_settings

    get_settings().yaml_config.spotify.enabled = False
    db = _db()
    try:
        result = poll_spotify(db)
        assert result.ok is True
        assert result.message == "disabled"
        assert result.logs_created == 0
    finally:
        db.close()


def test_poll_logs_episode(client, monkeypatch, tmp_path):
    _enable_spotify(monkeypatch, tmp_path)
    _patch_httpx(monkeypatch, recent_items=[_episode_item()])

    db = _db()
    try:
        result = poll_spotify(db)
        assert result.ok is True
        assert result.logs_created == 1
        rows = db.query(LogEntry).filter(LogEntry.source == "spotify").all()
        assert len(rows) == 1
        row = rows[0]
        assert row.source_ref == "spotify:episode:ep1"
        assert row.title == "Nihongo Episode 1"
        assert row.series_key == "spotify:show:show123"
        assert row.amount == 30.0  # 1_800_000 ms
        assert row.content_type == "podcast"
        assert row.unit == "minutes"
        assert row.activity == "listening"
        assert "Comprehensible Japanese" in (row.notes or "")
    finally:
        db.close()


def test_poll_dedupe(client, monkeypatch, tmp_path):
    _enable_spotify(monkeypatch, tmp_path)
    items = [_episode_item(episode_id="dup-ep")]
    _patch_httpx(monkeypatch, recent_items=items)

    db = _db()
    try:
        r1 = poll_spotify(db)
        r2 = poll_spotify(db)
        assert r1.logs_created == 1
        assert r2.logs_created == 0
        assert r2.details.get("duplicates", 0) >= 1
        n = db.query(LogEntry).filter(LogEntry.source_ref == "spotify:episode:dup-ep").count()
        assert n == 1
    finally:
        db.close()


def test_poll_podcasts_only_skips_music(client, monkeypatch, tmp_path):
    _enable_spotify(monkeypatch, tmp_path, podcasts_only=True)
    _patch_httpx(
        monkeypatch,
        recent_items=[
            _track_item(track_id="m1"),
            _episode_item(episode_id="e-only"),
        ],
    )

    db = _db()
    try:
        result = poll_spotify(db)
        assert result.ok is True
        assert result.logs_created == 1
        assert result.details.get("music_skipped", 0) >= 1
        refs = [r.source_ref for r in db.query(LogEntry).filter(LogEntry.source == "spotify")]
        assert "spotify:episode:e-only" in refs
        assert "spotify:track:m1" not in refs
    finally:
        db.close()


def test_poll_allowlist_filters(client, monkeypatch, tmp_path):
    _enable_spotify(monkeypatch, tmp_path, show_allowlist=["show-allowed"])
    _patch_httpx(
        monkeypatch,
        recent_items=[
            _episode_item(
                episode_id="blocked-ep",
                show_id="show-other",
                show_name="Other Podcast",
            ),
            _episode_item(
                episode_id="ok-ep",
                show_id="show-allowed",
                show_name="JP Listening",
            ),
        ],
    )

    db = _db()
    try:
        result = poll_spotify(db)
        assert result.ok is True
        assert result.logs_created == 1
        assert result.details.get("filtered", 0) >= 1
        refs = [r.source_ref for r in db.query(LogEntry).filter(LogEntry.source == "spotify")]
        assert refs == ["spotify:episode:ok-ep"]
    finally:
        db.close()


def test_poll_refreshes_token_file(client, monkeypatch, tmp_path):
    token_path = _enable_spotify(monkeypatch, tmp_path)
    _patch_httpx(monkeypatch, recent_items=[])

    db = _db()
    try:
        result = poll_spotify(db)
        assert result.ok is True
        data = json.loads(token_path.read_text(encoding="utf-8"))
        assert data["access_token"] == "access-new"
        assert data["expires_at"] > time.time()
        assert data["refresh_token"] == "refresh-xyz"
    finally:
        db.close()


def test_spotify_status(client, monkeypatch, tmp_path):
    _enable_spotify(monkeypatch, tmp_path)
    db = _db()
    try:
        st = spotify_status(db)
        assert st["enabled"] is True
        assert st["token_file_exists"] is True
        assert st["token_ok"] is True
        assert st["has_client_id"] is True
        assert st["podcasts_only"] is True
    finally:
        db.close()
