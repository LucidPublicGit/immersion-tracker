"""Unit tests for sheet push hashing / dirty flags (no Google API)."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import sessionmaker

from app.db.models import SheetSyncState
from app.db.session import get_engine, init_db, reset_engine
from app.sheets.state import (
    DIRTY_KEY,
    clear_sheets_dirty,
    get_push_hash,
    is_sheets_dirty,
    mark_sheets_dirty,
    rows_content_hash,
    set_push_hash,
)


def test_rows_content_hash_stable():
    a = [["id", "title"], [1, "foo"], [2, None]]
    b = [["id", "title"], [1, "foo"], [2, ""]]
    # None and "" both normalize to ""
    assert rows_content_hash(a) == rows_content_hash(b)
    c = [["id", "title"], [1, "bar"], [2, ""]]
    assert rows_content_hash(a) != rows_content_hash(c)


def test_rows_content_hash_order_matters():
    a = [[1, 2], [3, 4]]
    b = [[3, 4], [1, 2]]
    assert rows_content_hash(a) != rows_content_hash(b)


@pytest.fixture()
def db_session(tmp_path, monkeypatch):
    db_path = tmp_path / "state.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path.as_posix()}")
    from app.core.config import reload_settings

    reload_settings()
    reset_engine()
    init_db()
    Session = sessionmaker(bind=get_engine(), autoflush=False, autocommit=False)
    s = Session()
    try:
        yield s
    finally:
        s.close()
        reset_engine()


def test_dirty_flag_roundtrip(db_session):
    assert not is_sheets_dirty(db_session)
    mark_sheets_dirty(db_session)
    assert is_sheets_dirty(db_session)
    clear_sheets_dirty(db_session)
    assert not is_sheets_dirty(db_session)
    row = (
        db_session.query(SheetSyncState)
        .filter(SheetSyncState.key == DIRTY_KEY)
        .one_or_none()
    )
    assert row is not None
    assert row.value == "0"


def test_push_hash_roundtrip(db_session):
    assert get_push_hash(db_session, "logs_all") == ""
    digest = rows_content_hash([["a"], ["b"]])
    set_push_hash(db_session, "logs_all", digest)
    assert get_push_hash(db_session, "logs_all") == digest
