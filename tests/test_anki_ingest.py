"""AnkiConnect study ingest (mocked HTTP; never talks to a real Anki)."""

from __future__ import annotations

from typing import Any, Optional
from unittest.mock import patch

import httpx
import pytest
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings, reload_settings
from app.db.models import LogEntry
from app.db.session import get_engine
from app.ingest.anki import (
    STATE_BOOTSTRAPPED,
    STATE_LAST_REVIEW_ID,
    AnkiConnectError,
    anki_invoke,
    anki_status,
    deck_allowed,
    poll_anki,
)
from app.sheets.state import get_state, set_state


def _db():
    SessionLocal = sessionmaker(bind=get_engine(), autoflush=False, autocommit=False)
    return SessionLocal()


def _review(rid: int, time_ms: int, *, nine: bool = True) -> list[int]:
    """Build a cardReviews row (official 9-field or compact 8-field)."""
    if nine:
        # id, cardID, usn, ease, ivl, lastIvl, factor, time, type
        return [rid, 1001, -1, 3, 1, 0, 2500, time_ms, 1]
    # id, usn, ease, ivl, lastIvl, factor, time, type
    return [rid, -1, 3, 1, 0, 2500, time_ms, 1]


class _FakeResponse:
    def __init__(self, body: dict[str, Any], status_code: int = 200):
        self._body = body
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            req = httpx.Request("POST", "http://anki.test")
            resp = httpx.Response(self.status_code, request=req)
            raise httpx.HTTPStatusError("err", request=req, response=resp)

    def json(self) -> dict[str, Any]:
        return self._body


class _FakeAnki:
    """In-memory AnkiConnect stand-in keyed by action."""

    def __init__(
        self,
        *,
        decks: Optional[list[str]] = None,
        reviews_by_deck: Optional[dict[str, list[list[int]]]] = None,
        version: int = 6,
        fail_transport: bool = False,
        fail_actions: Optional[set[str]] = None,
    ):
        self.decks = list(decks or ["Default", "Japanese::Core", "Math"])
        self.reviews_by_deck = {
            k: list(v) for k, v in (reviews_by_deck or {}).items()
        }
        self.version = version
        self.fail_transport = fail_transport
        self.fail_actions = set(fail_actions or [])
        self.calls: list[tuple[str, Any]] = []

    def handle(self, payload: dict[str, Any]) -> _FakeResponse:
        action = payload.get("action")
        params = payload.get("params") or {}
        self.calls.append((action, params))

        if self.fail_transport:
            raise httpx.ConnectError("connection refused")

        if action in self.fail_actions:
            return _FakeResponse({"result": None, "error": f"{action} denied"})

        if action == "version":
            return _FakeResponse({"result": self.version, "error": None})
        if action == "requestPermission":
            return _FakeResponse(
                {
                    "result": {"permission": "granted", "requireApiKey": False},
                    "error": None,
                }
            )
        if action == "deckNames":
            return _FakeResponse({"result": list(self.decks), "error": None})
        if action == "getLatestReviewID":
            deck = params.get("deck", "")
            rows = self.reviews_by_deck.get(deck, [])
            latest = max((r[0] for r in rows), default=0)
            return _FakeResponse({"result": latest, "error": None})
        if action == "cardReviews":
            deck = params.get("deck", "")
            start = int(params.get("startID") or 0)
            rows = [
                r for r in self.reviews_by_deck.get(deck, []) if int(r[0]) > start
            ]
            return _FakeResponse({"result": rows, "error": None})

        return _FakeResponse({"result": None, "error": f"unknown action {action}"})


def _enable_anki(**overrides):
    reload_settings()
    cfg = get_settings().yaml_config.anki
    cfg.enabled = True
    cfg.connect_url = "http://anki.test:8765"
    cfg.deck_allowlist = []
    cfg.deck_blocklist = []
    cfg.min_delta_minutes = 0.5
    cfg.content_type = "study"
    cfg.unit = "minutes"
    cfg.activity = "study"
    cfg.title = "Anki"
    cfg.series_key = "anki"
    cfg.timeout_seconds = 5.0
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


def _clear_anki_state(db) -> None:
    set_state(db, STATE_LAST_REVIEW_ID, "")
    set_state(db, STATE_BOOTSTRAPPED, "")


def _patch_httpx(fake: _FakeAnki):
    class _Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, json=None):
            return fake.handle(json or {})

    return patch("app.ingest.anki.httpx.Client", _Client)


def test_deck_allowed_exact_and_prefix():
    assert deck_allowed("Japanese::Core", ["Japanese*"], [])
    assert deck_allowed("Japanese::Core", ["Japanese::Core"], [])
    assert not deck_allowed("Math", ["Japanese*"], [])
    assert deck_allowed("Math", [], [])  # empty allowlist = all
    assert not deck_allowed("Math", [], ["Math"])
    assert not deck_allowed("Japanese::Core", ["Japanese*"], ["Japanese*"])
    assert deck_allowed("Default", [], ["Japanese*"])


def test_anki_invoke_error_field(client):
    _enable_anki()
    fake = _FakeAnki(fail_actions={"version"})
    with _patch_httpx(fake):
        with pytest.raises(AnkiConnectError, match="denied"):
            anki_invoke("version")


def test_poll_disabled(client):
    get_settings().yaml_config.anki.enabled = False
    db = _db()
    try:
        result = poll_anki(db)
        assert result.ok is True
        assert result.source == "anki"
        assert result.message == "disabled"
        assert result.logs_created == 0
    finally:
        db.close()


def test_poll_connection_fail(client):
    _enable_anki()
    fake = _FakeAnki(fail_transport=True)
    db = _db()
    try:
        _clear_anki_state(db)
        with _patch_httpx(fake):
            result = poll_anki(db)
        assert result.ok is False
        assert result.logs_created == 0
        assert result.errors
        assert "fail" in result.message.lower() or "connection" in result.message.lower()
    finally:
        db.close()


def test_bootstrap_skips_history(client):
    """First successful contact baselines watermark; does not create a log."""
    _enable_anki()
    reviews = {
        "Default": [
            _review(1_700_000_000_000, 30_000),
            _review(1_700_000_000_100, 45_000),
        ],
        "Japanese::Core": [
            _review(1_700_000_000_200, 120_000),
        ],
        "Math": [],
    }
    fake = _FakeAnki(reviews_by_deck=reviews)
    db = _db()
    try:
        _clear_anki_state(db)
        with _patch_httpx(fake):
            result = poll_anki(db)
        assert result.ok is True
        assert result.logs_created == 0
        assert "bootstrap" in result.message.lower()
        assert get_state(db, STATE_BOOTSTRAPPED) in ("1", "true", "yes")
        last = int(get_state(db, STATE_LAST_REVIEW_ID))
        assert last == 1_700_000_000_200

        n = db.query(LogEntry).filter(LogEntry.source == "anki").count()
        assert n == 0
    finally:
        db.close()


def test_delta_creates_study_log(client):
    """After bootstrap, new review time ≥ min_delta creates one study log."""
    _enable_anki()
    base_id = 1_700_000_000_000
    bootstrap_reviews = {
        "Default": [_review(base_id, 10_000)],
        "Japanese::Core": [],
        "Math": [],
    }
    fake = _FakeAnki(reviews_by_deck=bootstrap_reviews)
    db = _db()
    try:
        _clear_anki_state(db)
        with _patch_httpx(fake):
            r0 = poll_anki(db)
        assert r0.ok and r0.logs_created == 0

        new_id_1 = base_id + 1_000
        new_id_2 = base_id + 2_000
        fake.reviews_by_deck["Default"] = [
            _review(base_id, 10_000),
            _review(new_id_1, 60_000),  # 1 min
            _review(new_id_2, 60_000),  # 1 min
        ]

        with _patch_httpx(fake):
            r1 = poll_anki(db)
        assert r1.ok is True
        assert r1.logs_created == 1
        assert r1.details.get("review_count") == 2

        logs = (
            db.query(LogEntry)
            .filter(LogEntry.source == "anki")
            .order_by(LogEntry.id.desc())
            .all()
        )
        assert len(logs) == 1
        log = logs[0]
        assert log.content_type == "study"
        assert log.unit == "minutes"
        assert log.activity == "study"
        assert log.title == "Anki"
        assert log.series_key == "anki"
        assert log.amount == 2.0
        assert get_state(db, STATE_LAST_REVIEW_ID) == str(new_id_2)

        with _patch_httpx(fake):
            r2 = poll_anki(db)
        assert r2.ok is True
        assert r2.logs_created == 0
        assert db.query(LogEntry).filter(LogEntry.source == "anki").count() == 1
    finally:
        db.close()


def test_below_min_delta_holds_watermark(client):
    """Sub-threshold batches hold the watermark so time can accumulate."""
    _enable_anki(min_delta_minutes=5.0)
    base_id = 1_700_000_100_000
    fake = _FakeAnki(
        reviews_by_deck={
            "Default": [_review(base_id, 1_000)],
            "Japanese::Core": [],
            "Math": [],
        }
    )
    db = _db()
    try:
        _clear_anki_state(db)
        with _patch_httpx(fake):
            assert poll_anki(db).logs_created == 0  # bootstrap

        fake.reviews_by_deck["Default"].append(
            _review(base_id + 50, 30_000)
        )  # 0.5 min
        with _patch_httpx(fake):
            r = poll_anki(db)
        assert r.ok is True
        assert r.logs_created == 0
        assert r.skipped == 1
        assert "min_delta" in r.message.lower()
        assert int(get_state(db, STATE_LAST_REVIEW_ID)) == base_id
        assert db.query(LogEntry).filter(LogEntry.source == "anki").count() == 0

        fake.reviews_by_deck["Default"].append(
            _review(base_id + 100, 300_000)  # +5 min → total 5.5 min pending
        )
        with _patch_httpx(fake):
            r2 = poll_anki(db)
        assert r2.ok is True
        assert r2.logs_created == 1
        log = db.query(LogEntry).filter(LogEntry.source == "anki").one()
        assert log.amount == 5.5
        assert int(get_state(db, STATE_LAST_REVIEW_ID)) == base_id + 100
    finally:
        db.close()


def test_deck_filter_allowlist_and_blocklist(client):
    _enable_anki(
        deck_allowlist=["Japanese*"],
        deck_blocklist=["Japanese::Suspended"],
        min_delta_minutes=0.1,
    )

    base = 1_700_000_200_000
    fake = _FakeAnki(
        decks=["Default", "Japanese::Core", "Japanese::Suspended", "Math"],
        reviews_by_deck={
            "Default": [_review(base + 99, 600_000)],
            "Japanese::Core": [_review(base, 1_000)],
            "Japanese::Suspended": [_review(base + 50, 600_000)],
            "Math": [_review(base + 80, 600_000)],
        },
    )
    db = _db()
    try:
        _clear_anki_state(db)
        with _patch_httpx(fake):
            r0 = poll_anki(db)
        assert r0.ok and r0.logs_created == 0
        # Bootstrap max only among selected decks (Japanese::Core)
        assert int(get_state(db, STATE_LAST_REVIEW_ID)) == base

        fake.reviews_by_deck["Japanese::Core"].append(_review(base + 10, 60_000))
        fake.reviews_by_deck["Default"].append(_review(base + 1000, 600_000))

        with _patch_httpx(fake):
            r1 = poll_anki(db)
        assert r1.ok is True
        assert r1.logs_created == 1
        assert r1.details.get("review_count") == 1
        log = (
            db.query(LogEntry)
            .filter(LogEntry.source == "anki")
            .order_by(LogEntry.id.desc())
            .first()
        )
        assert log is not None
        assert log.amount == 1.0
    finally:
        db.close()


def test_anki_status_disabled(client):
    get_settings().yaml_config.anki.enabled = False
    db = _db()
    try:
        st = anki_status(db)
        assert st["enabled"] is False
        assert st["ok"] is False
        assert st["connected"] is False
        assert "disabled" in st["message"].lower()
    finally:
        db.close()


def test_anki_status_connected(client):
    _enable_anki(deck_allowlist=["Japanese*"])
    fake = _FakeAnki(
        decks=["Default", "Japanese::Core"],
        reviews_by_deck={"Default": [_review(99, 1000)], "Japanese::Core": []},
    )
    db = _db()
    try:
        _clear_anki_state(db)
        with _patch_httpx(fake):
            st = anki_status(db)
        assert st["ok"] is True
        assert st["connected"] is True
        assert st["anki_connect_version"] == 6
        assert st["decks_total"] == 2
        assert st["decks_selected"] == 1
        assert st["bootstrapped"] is False
    finally:
        db.close()


def test_anki_status_unreachable(client):
    _enable_anki()
    fake = _FakeAnki(fail_transport=True)
    db = _db()
    try:
        with _patch_httpx(fake):
            st = anki_status(db)
        assert st["ok"] is False
        assert st["connected"] is False
        assert "unreachable" in st["message"].lower()
    finally:
        db.close()


def test_compact_review_row_format(client):
    """8-field rows still parse duration correctly."""
    _enable_anki(min_delta_minutes=0.5)
    base = 1_700_000_300_000
    fake = _FakeAnki(
        decks=["Default"],
        reviews_by_deck={"Default": [_review(base, 5_000, nine=False)]},
    )
    db = _db()
    try:
        _clear_anki_state(db)
        with _patch_httpx(fake):
            poll_anki(db)  # bootstrap
        fake.reviews_by_deck["Default"].append(
            _review(base + 1, 90_000, nine=False)  # 1.5 min
        )
        with _patch_httpx(fake):
            r = poll_anki(db)
        assert r.ok and r.logs_created == 1
        log = db.query(LogEntry).filter(LogEntry.source == "anki").one()
        assert log.amount == 1.5
    finally:
        db.close()
