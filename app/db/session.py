from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.db.models import Base

_engine = None
_SessionLocal = None


def get_engine():
    global _engine, _SessionLocal
    if _engine is None:
        settings = get_settings()
        url = settings.database_url
        connect_args = {}
        if url.startswith("sqlite"):
            connect_args["check_same_thread"] = False
        _engine = create_engine(url, connect_args=connect_args)
        if url.startswith("sqlite"):

            @event.listens_for(_engine, "connect")
            def set_sqlite_pragma(dbapi_conn, _connection_record):
                cursor = dbapi_conn.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()

        _SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False)
    return _engine


def init_db() -> None:
    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    _migrate_sqlite(engine)


def _migrate_sqlite(engine) -> None:
    """Add columns introduced after first deploy (SQLite has no Alembic here)."""
    url = str(engine.url)
    if not url.startswith("sqlite"):
        return
    with engine.begin() as conn:
        # leftover from removed challenges feature (separate app)
        conn.exec_driver_sql("DROP TABLE IF EXISTS challenges")
        rows = conn.exec_driver_sql("PRAGMA table_info(log_entries)").fetchall()
        cols = {r[1] for r in rows}  # name is index 1
        if "season" not in cols:
            conn.exec_driver_sql("ALTER TABLE log_entries ADD COLUMN season INTEGER")
        if "episode" not in cols:
            conn.exec_driver_sql("ALTER TABLE log_entries ADD COLUMN episode INTEGER")

        cat_rows = conn.exec_driver_sql("PRAGMA table_info(catalog_items)").fetchall()
        cat_cols = {r[1] for r in cat_rows}
        if cat_cols and "aliases" not in cat_cols:
            conn.exec_driver_sql("ALTER TABLE catalog_items ADD COLUMN aliases TEXT")
        if cat_cols and "progress_status" not in cat_cols:
            conn.exec_driver_sql(
                "ALTER TABLE catalog_items ADD COLUMN progress_status VARCHAR(32) "
                "DEFAULT 'active'"
            )
        if cat_cols and "progress_status_locked" not in cat_cols:
            conn.exec_driver_sql(
                "ALTER TABLE catalog_items ADD COLUMN progress_status_locked "
                "BOOLEAN DEFAULT 0"
            )

        hoshi_rows = conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='hoshi_book_buckets'"
        ).fetchall()
        if hoshi_rows:
            hb_cols = {
                r[1]
                for r in conn.exec_driver_sql(
                    "PRAGMA table_info(hoshi_book_buckets)"
                ).fetchall()
            }
            if "min_submit_characters" not in hb_cols:
                conn.exec_driver_sql(
                    "ALTER TABLE hoshi_book_buckets ADD COLUMN min_submit_characters INTEGER"
                )
            if "last_logged_position_chars" not in hb_cols:
                conn.exec_driver_sql(
                    "ALTER TABLE hoshi_book_buckets ADD COLUMN last_logged_position_chars INTEGER"
                )
            if "credited_position_chars" not in hb_cols:
                conn.exec_driver_sql(
                    "ALTER TABLE hoshi_book_buckets ADD COLUMN credited_position_chars INTEGER"
                )


def get_db() -> Generator[Session, None, None]:
    get_engine()
    assert _SessionLocal is not None
    db = _SessionLocal()
    try:
        yield db
    finally:
        db.close()


def reset_engine() -> None:
    """Test helper: dispose engine so DATABASE_URL can change."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None
