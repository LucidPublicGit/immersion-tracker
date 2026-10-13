"""Consistent SQLite snapshots (online backup API)."""

from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_WEEKLY_GLOB = "immersion-weekly-*.db"


def sqlite_online_backup(src: Path, dest: Path) -> None:
    """Copy src → dest via sqlite3 backup (safe while DB is open)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Unique neighbor so Windows can release handles before os.replace
    tmp = dest.with_name(f".{dest.name}.{os.getpid()}.partial")
    src_conn: sqlite3.Connection | None = None
    dst_conn: sqlite3.Connection | None = None
    try:
        src_conn = sqlite3.connect(str(src))
        src_conn.execute("PRAGMA busy_timeout=5000")
        dst_conn = sqlite3.connect(str(tmp))
        src_conn.backup(dst_conn)
        dst_conn.commit()
    except Exception:
        if dst_conn is not None:
            try:
                dst_conn.close()
            except sqlite3.Error:
                pass
            dst_conn = None
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    finally:
        if dst_conn is not None:
            dst_conn.close()
        if src_conn is not None:
            src_conn.close()
    os.replace(tmp, dest)


def weekly_backup_dir(db_path: Path) -> Path:
    return db_path.parent / "backups"


def list_weekly_backups(backup_dir: Path) -> list[Path]:
    if not backup_dir.is_dir():
        return []
    return sorted(backup_dir.glob(_WEEKLY_GLOB), reverse=True)


def run_weekly_db_backup(src: Path | None, *, keep: int = 4) -> Path | None:
    """
    Write data/backups/immersion-weekly-YYYYMMDD.db and prune older than keep.
    """
    if src is None or not src.is_file():
        logger.warning("weekly db backup skipped: no sqlite file")
        return None
    keep = max(1, int(keep))
    backup_dir = weekly_backup_dir(src)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    dest = backup_dir / f"immersion-weekly-{stamp}.db"
    sqlite_online_backup(src, dest)
    remaining = list_weekly_backups(backup_dir)
    for old in remaining[keep:]:
        try:
            old.unlink(missing_ok=True)
        except OSError:
            logger.warning("could not remove old backup %s", old)
    logger.info("weekly db backup written %s (retain %s)", dest.name, keep)
    return dest
