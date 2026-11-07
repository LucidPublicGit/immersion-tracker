"""Current Tadoku unit-key and time-only contract; no network or real data."""
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import AppYamlConfig
from app.db.models import Base, LogEntry
from app.tadoku.client import TadokuClient
from app.tadoku.pull import import_remote_log


@pytest.fixture
def submitter(monkeypatch, tmp_path):
    from app.tadoku import client
    settings = SimpleNamespace(yaml_config=AppYamlConfig())
    # Old UUID settings must never leak onto the wire.
    settings.yaml_config.tadoku.unit_ids = {"pages": "obsolete-uuid"}
    monkeypatch.setattr(client, "get_settings", lambda: settings)
    return TadokuClient(export_dir=str(tmp_path))


@pytest.mark.parametrize("activity,unit,key", [
    ("reading", "pages", "pages"),
    ("reading", "comic_pages", "pages"),
    ("reading", "characters", "characters"),
    ("writing", "sentences", "sentences"),
    ("writing", "pages", "pages"),
])
def test_amount_uses_canonical_key(submitter, activity, unit, key):
    entry = LogEntry(activity=activity, unit=unit, amount=12.5, title="Test", language="ja")
    body = submitter._api_body(entry)
    assert body["unit_key"] == key
    assert body["amount"] == 12.5
    assert "unit_id" not in body
    assert "duration_seconds" not in body


@pytest.mark.parametrize("activity", ["reading", "listening", "writing", "speaking", "study"])
@pytest.mark.parametrize("unit,amount,seconds", [("minutes", 1.5, 90), ("seconds", 90, 90), ("minutes_high_density", 1.5, 90)])
def test_time_only_submission(submitter, activity, unit, amount, seconds):
    body = submitter._api_body(LogEntry(activity=activity, unit=unit, amount=amount, title="Test"))
    assert body["duration_seconds"] == seconds
    assert not {"unit_key", "unit_id", "amount"} & body.keys()


@pytest.mark.parametrize("activity,unit", [("listening", "pages"), ("reading", "two_column_pages"), ("study", "characters")])
def test_unsupported_amount_rejected(submitter, activity, unit):
    with pytest.raises(ValueError, match="does not support"):
        submitter._api_body(LogEntry(activity=activity, unit=unit, amount=10, title="Test"))


@pytest.mark.parametrize("fields,unit,amount", [
    ({"unit_key": "characters", "unit_name": "Page", "amount": 120}, "characters", 120),
    ({"unit_name": "Page", "amount": 12}, "pages", 12),
    ({"unit_name": "", "amount": 0, "duration_seconds": 90}, "minutes", 1.5),
])
def test_import_current_and_legacy_logs(fields, unit, amount):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        entry = import_remote_log(db, {
            "id": "synthetic-log", "activity": {"id": 1, "name": "Reading"},
            "description": "Synthetic book", "tags": ["book"],
            "language": {"code": "jpn"}, **fields,
        })
        assert entry is not None
        assert entry.unit == unit
        assert entry.amount == amount
        assert entry.tadoku_remote_id == "synthetic-log"
    engine.dispose()
