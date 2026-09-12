"""
GameSentenceMiner (GSM) → immersion logs → Tadoku.

Safety contract
---------------
* game_lines / games are **read-only** (SQLite URI mode=ro).
* The only write ever performed on the GSM database is an UPSERT of
  ``stats_export_state`` row ``format_key='tadoku_incremental'`` (the same
  watermark GSM uses after its own Tadoku sync). No DELETEs, no line changes.
* Export watermark advances only after a successful export batch is fully
  pushed/skipped, and only monotonically (new ≥ existing).
* Preview uses max(GSM cursor, immersion-local cursor). Local always advances
  on a finished batch so the UI resets even when the GSM file is locked
  (common with Docker Desktop bind-mounts on Windows). GSM file write is
  retried in the background via ``try_sync_cursor_to_gsm``.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import LogEntry, TadokuStatus, utcnow
from app.ingest.service import DuplicateLogError, create_log
from app.sheets.state import get_state, set_state

logger = logging.getLogger(__name__)

SOURCE = "gsm"
TADOKU_CURSOR_KEY = "tadoku_incremental"
# Immersion-local batch tracker (never written into GSM except the cursor itself)
PENDING_EXPORT_STATE_KEY = "gsm_pending_export"
# Local floor for preview when GSM cursor write is locked/unavailable (Docker bind mount).
# Always max'd with GSM's tadoku_incremental so the UI resets even if the host DB is RO.
LOCAL_CURSOR_KEY = "gsm:local_cursor"
# Per-game skip floors (immersion-local). Preview uses max(global, per-game).
GAME_CURSORS_KEY = "gsm:game_cursors"
TABLE_LINES = "game_lines"
TABLE_GAMES = "games"
TABLE_CURSOR = "stats_export_state"

# Absolute hard list of SQL we may run against GSM (write path uses only these shapes)
_WRITE_ALLOWED_FORMAT_KEY = TADOKU_CURSOR_KEY


class GsmError(RuntimeError):
    """User-facing / API error for GSM integration."""


@dataclass
class GsmPreviewEntry:
    game_key: str
    game_name: str
    characters: int
    lines: int
    content_type: str
    game_type: str = ""
    latest_created_at: float = 0.0
    ready_for_auto: bool = False
    below_min: bool = False
    waiting_idle: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "game_key": self.game_key,
            "game_name": self.game_name,
            "characters": self.characters,
            "lines": self.lines,
            "content_type": self.content_type,
            "game_type": self.game_type,
            "latest_created_at": self.latest_created_at,
            "ready_for_auto": self.ready_for_auto,
            "below_min": self.below_min,
            "waiting_idle": self.waiting_idle,
        }


# Runtime UI prefs (override yaml until changed)
PREF_LOG_MODE = "gsm:pref:log_mode"
PREF_MIN_SUBMIT = "gsm:pref:min_submit_characters"
PREF_IDLE_MINUTES = "gsm:pref:auto_submit_idle_minutes"
PREF_DEDUPE = "gsm:pref:deduplicate"
PREF_STRIP_PUNCT = "gsm:pref:strip_punctuation"
PREF_COLLAPSE_BLOCKS = "gsm:pref:collapse_repeated_blocks"
PREF_REQUIRE_JP = "gsm:pref:require_japanese"
PREF_AUTO_LOG_AT_TIME = "gsm:pref:auto_log_at_time_enabled"
PREF_AUTO_LOG_HOUR = "gsm:pref:auto_log_at_hour"
STATE_LAST_DAILY_LOG = "gsm:last_daily_log_date"  # YYYY-MM-DD in local tz

# GSM util/database/db.py: repeating_chars_regex (optional, off by default there)
_REPEATING_CHARS_RE = re.compile(r"(.+?)\1{2,}")
# Split mail-style lines that start each copy with "From:" (Agent MAGES hook)
_FROM_SPLIT_RE = re.compile(r"(?=From:)")


def get_log_mode(db: Optional[Session] = None) -> str:
    if db is not None:
        raw = (get_state(db, PREF_LOG_MODE) or "").strip().lower()
        if raw in ("manual", "auto", "automatic", "pending"):
            return "manual" if raw in ("pending", "manual") else "auto"
    return (_gsm_cfg().log_mode or "manual").strip().lower() or "manual"


def get_min_submit_characters(db: Optional[Session] = None) -> int:
    if db is not None:
        raw = (get_state(db, PREF_MIN_SUBMIT) or "").strip()
        if raw:
            try:
                return max(1, int(raw))
            except ValueError:
                pass
    return max(1, int(getattr(_gsm_cfg(), "min_submit_characters", 10000) or 10000))


def get_idle_minutes(db: Optional[Session] = None) -> float:
    if db is not None:
        raw = (get_state(db, PREF_IDLE_MINUTES) or "").strip()
        if raw:
            try:
                return max(0.0, float(raw))
            except ValueError:
                pass
    return max(0.0, float(getattr(_gsm_cfg(), "auto_submit_idle_minutes", 30.0) or 0.0))


def get_deduplicate(db: Optional[Session] = None) -> bool:
    if db is not None:
        raw = (get_state(db, PREF_DEDUPE) or "").strip().lower()
        if raw in ("1", "true", "yes", "on"):
            return True
        if raw in ("0", "false", "no", "off"):
            return False
    return bool(getattr(_gsm_cfg(), "deduplicate", False))


def get_strip_punctuation(db: Optional[Session] = None) -> bool:
    """
    Whether to strip punctuation/symbols/separators before counting characters.

    Mirrors GSM's clean_text_for_stats (default ON there and here).
    """
    if db is not None:
        raw = (get_state(db, PREF_STRIP_PUNCT) or "").strip().lower()
        if raw in ("1", "true", "yes", "on"):
            return True
        if raw in ("0", "false", "no", "off"):
            return False
    return bool(getattr(_gsm_cfg(), "strip_punctuation", True))


def get_collapse_repeated_blocks(db: Optional[Session] = None) -> bool:
    """
    Whether to collapse a single line that is the same block repeated many times.

    Catches hook spam (e.g. Steins;Gate mail body emitted × N in one row).
    Default ON — does not change normal dialogue.
    """
    if db is not None:
        raw = (get_state(db, PREF_COLLAPSE_BLOCKS) or "").strip().lower()
        if raw in ("1", "true", "yes", "on"):
            return True
        if raw in ("0", "false", "no", "off"):
            return False
    return bool(getattr(_gsm_cfg(), "collapse_repeated_blocks", True))


def get_require_japanese(db: Optional[Session] = None) -> bool:
    """
    Skip lines with almost no Japanese (clipboard URLs, code, English lookups).

    Default ON for JP immersion. Does not change normal VN dialogue.
    """
    if db is not None:
        raw = (get_state(db, PREF_REQUIRE_JP) or "").strip().lower()
        if raw in ("1", "true", "yes", "on"):
            return True
        if raw in ("0", "false", "no", "off"):
            return False
    return bool(getattr(_gsm_cfg(), "require_japanese", True))


def get_max_line_characters(db: Optional[Session] = None) -> int:
    """Per-line cap after collapse (0 = unlimited). Yaml only for now."""
    _ = db  # reserved if we expose a UI pref later
    return max(0, int(getattr(_gsm_cfg(), "max_line_characters", 0) or 0))


def get_auto_log_at_time_enabled(db: Optional[Session] = None) -> bool:
    if db is not None:
        raw = (get_state(db, PREF_AUTO_LOG_AT_TIME) or "").strip().lower()
        if raw in ("1", "true", "yes", "on"):
            return True
        if raw in ("0", "false", "no", "off"):
            return False
    return bool(getattr(_gsm_cfg(), "auto_log_at_time_enabled", False))


def get_auto_log_at_hour(db: Optional[Session] = None) -> int:
    if db is not None:
        raw = (get_state(db, PREF_AUTO_LOG_HOUR) or "").strip()
        if raw:
            try:
                return max(0, min(23, int(raw)))
            except ValueError:
                pass
    h = int(getattr(_gsm_cfg(), "auto_log_at_hour", 4) or 4)
    return max(0, min(23, h))


def get_timezone_name() -> str:
    """Resolve local timezone for daily auto-log (env TZ → config → system)."""
    env_tz = (os.environ.get("TZ") or "").strip()
    if env_tz:
        return env_tz
    cfg_tz = (getattr(_gsm_cfg(), "timezone", None) or "").strip()
    if cfg_tz:
        return cfg_tz
    try:
        # Python 3.9+: system local zone key when available
        local = datetime.now().astimezone().tzinfo
        key = getattr(local, "key", None)
        if key:
            return str(key)
    except Exception:  # noqa: BLE001
        pass
    return "America/Los_Angeles"


def get_prefs(db: Optional[Session] = None) -> dict[str, Any]:
    return {
        "log_mode": get_log_mode(db),
        "min_submit_characters": get_min_submit_characters(db),
        "auto_submit_idle_minutes": get_idle_minutes(db),
        "deduplicate": get_deduplicate(db),
        "strip_punctuation": get_strip_punctuation(db),
        "collapse_repeated_blocks": get_collapse_repeated_blocks(db),
        "require_japanese": get_require_japanese(db),
        "max_line_characters": get_max_line_characters(db),
        "auto_log_at_time_enabled": get_auto_log_at_time_enabled(db),
        "auto_log_at_hour": get_auto_log_at_hour(db),
        "timezone": get_timezone_name(),
        "tadoku_default": (getattr(_gsm_cfg(), "tadoku_default", None) or "pending"),
        "advance_cursor": bool(getattr(_gsm_cfg(), "advance_cursor", True)),
    }


def set_prefs(
    db: Session,
    *,
    log_mode: Optional[str] = None,
    min_submit_characters: Optional[int] = None,
    auto_submit_idle_minutes: Optional[float] = None,
    deduplicate: Optional[bool] = None,
    strip_punctuation: Optional[bool] = None,
    collapse_repeated_blocks: Optional[bool] = None,
    require_japanese: Optional[bool] = None,
    auto_log_at_time_enabled: Optional[bool] = None,
    auto_log_at_hour: Optional[int] = None,
) -> dict[str, Any]:
    if log_mode is not None:
        m = str(log_mode).strip().lower()
        if m in ("pending", "manual"):
            m = "manual"
        elif m in ("auto", "automatic"):
            m = "auto"
        else:
            raise ValueError("log_mode must be manual or auto")
        set_state(db, PREF_LOG_MODE, m)
    if min_submit_characters is not None:
        set_state(db, PREF_MIN_SUBMIT, str(max(1, int(min_submit_characters))))
    if auto_submit_idle_minutes is not None:
        set_state(db, PREF_IDLE_MINUTES, str(max(0.0, float(auto_submit_idle_minutes))))
    if deduplicate is not None:
        set_state(db, PREF_DEDUPE, "true" if deduplicate else "false")
    if strip_punctuation is not None:
        set_state(db, PREF_STRIP_PUNCT, "true" if strip_punctuation else "false")
    if collapse_repeated_blocks is not None:
        set_state(
            db,
            PREF_COLLAPSE_BLOCKS,
            "true" if collapse_repeated_blocks else "false",
        )
    if require_japanese is not None:
        set_state(
            db,
            PREF_REQUIRE_JP,
            "true" if require_japanese else "false",
        )
    if auto_log_at_time_enabled is not None:
        set_state(
            db,
            PREF_AUTO_LOG_AT_TIME,
            "true" if auto_log_at_time_enabled else "false",
        )
    if auto_log_at_hour is not None:
        set_state(db, PREF_AUTO_LOG_HOUR, str(max(0, min(23, int(auto_log_at_hour)))))
    return get_prefs(db)


def clean_text_for_stats(
    text: Any,
    *,
    strip_punctuation: bool = True,
    strip_repetitions: bool = False,
) -> str:
    """
    Match GSM's ``clean_text_for_stats`` used for Tadoku + stats char counts.

    GSM (util/database/db.py) strips Unicode punctuation (\\p{P}), symbols
    (\\p{S}), and separators (\\p{Z}, including whitespace) via the ``regex``
    package. We use ``unicodedata.category`` for the same classes without
    adding that dependency.
    """
    if text is None:
        return ""
    cleaned = str(text)
    if strip_punctuation:
        cleaned = "".join(
            ch for ch in cleaned if unicodedata.category(ch)[0] not in ("P", "S", "Z")
        )
    cleaned = cleaned.strip()
    if strip_repetitions and cleaned:
        cleaned = _REPEATING_CHARS_RE.sub(r"\1\1\1", cleaned)
    return cleaned


def line_has_japanese(
    text: str,
    *,
    min_cjk: int = 3,
    min_ratio: float = 0.12,
) -> bool:
    """True when the line has enough CJK to count as Japanese immersion."""
    if not text:
        return False
    cjk = 0
    for ch in text:
        o = ord(ch)
        if (
            0x3040 <= o <= 0x30FF  # hiragana + katakana
            or 0x4E00 <= o <= 0x9FFF  # CJK unified
            or 0x3400 <= o <= 0x4DBF  # CJK ext A
            or 0xFF66 <= o <= 0xFF9D  # halfwidth kana
        ):
            cjk += 1
    return cjk >= min_cjk and (cjk / len(text)) >= min_ratio


def collapse_line_block_repeats(
    text: str,
    *,
    min_unit_len: int = 40,
    min_repeats: int = 3,
    min_line_len: int = 200,
    min_coverage: float = 0.85,
) -> str:
    """
    If a single line is mostly the same block repeated N times, keep one copy.

    Targets hook bugs like MAGES Steins;Gate mail (one email body concatenated
    dozens of times into one ``game_lines`` row). Safe for normal dialogue:
    short lines and unique long lines pass through unchanged.

    Named distinctly from the ``collapse_repeated_blocks`` *pref* so call sites
    do not shadow this function with a boolean parameter.
    """
    if not text or len(text) < min_line_len:
        return text
    s = text
    n = len(s)

    # --- Mail-style: many "From:" sections, keep the most common full copy ---
    from_count = s.count("From:")
    if from_count >= min_repeats:
        parts = [p for p in _FROM_SPLIT_RE.split(s) if p]
        if len(parts) >= min_repeats:
            counts: dict[str, int] = {}
            for p in parts:
                counts[p] = counts.get(p, 0) + 1
            common, cnt = max(counts.items(), key=lambda kv: (kv[1], len(kv[0])))
            if (
                cnt >= min_repeats
                and len(common) >= min_unit_len
                and cnt * len(common) >= min_coverage * n
            ):
                return common

    # --- Exact tile: s == unit * k ---
    max_unit = n // min_repeats
    for unit_len in range(min_unit_len, max_unit + 1):
        if n % unit_len != 0:
            continue
        k = n // unit_len
        if k < min_repeats:
            continue
        unit = s[:unit_len]
        if unit * k == s:
            return unit

    # --- Prefix reoccurrence: unit = s[:second_hit], then count consecutive tiles ---
    probe_len = min(120, max(min_unit_len, n // (min_repeats + 1)))
    if probe_len < min_unit_len:
        return text
    probe = s[:probe_len]
    second = s.find(probe, min_unit_len)
    if second < min_unit_len:
        return text
    unit = s[:second]
    if len(unit) < min_unit_len:
        return text
    reps = 0
    i = 0
    while i + len(unit) <= n and s[i : i + len(unit)] == unit:
        reps += 1
        i += len(unit)
    # Allow a trailing partial copy of the same unit
    if i < n and unit.startswith(s[i:]):
        i = n
    if reps >= min_repeats and i >= min_coverage * n:
        return unit
    return text


# Back-compat alias for tests / callers
collapse_repeated_blocks = collapse_line_block_repeats


def _count_text(
    raw: Any,
    *,
    strip_punctuation: bool,
    collapse_blocks: bool = False,
    require_japanese: bool = False,
    max_line_characters: int = 0,
) -> str:
    """Return text used for character counting (and optional dedupe keys)."""
    if not isinstance(raw, str) or not raw:
        return ""
    # Filter on raw first so English clipboard/code never counts.
    if require_japanese and not line_has_japanese(raw):
        return ""
    text = raw
    if collapse_blocks:
        text = collapse_line_block_repeats(text)
    if strip_punctuation:
        text = clean_text_for_stats(text, strip_punctuation=True)
    if max_line_characters and max_line_characters > 0 and len(text) > max_line_characters:
        text = text[:max_line_characters]
    return text


@dataclass
class GsmStatus:
    ok: bool
    configured: bool
    enabled: bool
    path: Optional[str]
    exists: bool
    readable: bool
    writable_cursor: bool
    message: str
    detail: str = ""
    cursor: Optional[float] = None
    gsm_cursor: Optional[float] = None
    local_cursor: Optional[float] = None
    cursor_sync_pending: bool = False
    line_count: Optional[int] = None
    game_count: Optional[int] = None
    schema_ok: bool = False
    candidates_checked: list[str] = field(default_factory=list)
    advance_cursor: bool = True
    pending_export: Optional[dict[str, Any]] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "configured": self.configured,
            "enabled": self.enabled,
            "path": self.path,
            "exists": self.exists,
            "readable": self.readable,
            "writable_cursor": self.writable_cursor,
            "message": self.message,
            "detail": self.detail,
            "cursor": self.cursor,
            "gsm_cursor": self.gsm_cursor,
            "local_cursor": self.local_cursor,
            "cursor_sync_pending": self.cursor_sync_pending,
            "line_count": self.line_count,
            "game_count": self.game_count,
            "schema_ok": self.schema_ok,
            "candidates_checked": self.candidates_checked,
            "advance_cursor": self.advance_cursor,
            "pending_export": self.pending_export,
        }


def _gsm_cfg():
    return get_settings().yaml_config.gsm


def resolve_gsm_db_path() -> tuple[Optional[Path], list[str]]:
    """
    Resolve GSM sqlite path. Returns (path_or_None, candidates_checked).

    Explicit overrides (no fallback if missing):
      1. GSM_DB_PATH env
      2. settings gsm.db_path

    Auto-detect (first existing file wins):
      3. Docker mount /gsm/gsm.db
      4. %APPDATA%/GameSentenceMiner/gsm.db
      5. %LOCALAPPDATA%/GameSentenceMiner/gsm.db
      6. ~/AppData/Roaming/GameSentenceMiner/gsm.db
    """
    cfg = _gsm_cfg()

    env = (os.environ.get("GSM_DB_PATH") or "").strip()
    if env:
        p = Path(env)
        checked = [str(p)]
        try:
            if p.is_file():
                return p.resolve(), checked
        except OSError:
            pass
        return None, checked

    configured = (getattr(cfg, "db_path", None) or "").strip()
    if configured:
        p = Path(configured)
        checked = [str(p)]
        try:
            if p.is_file():
                return p.resolve(), checked
        except OSError:
            pass
        return None, checked

    candidates: list[Path] = [Path("/gsm/gsm.db")]

    appdata = (os.environ.get("APPDATA") or "").strip()
    if appdata:
        candidates.append(Path(appdata) / "GameSentenceMiner" / "gsm.db")

    local = (os.environ.get("LOCALAPPDATA") or "").strip()
    if local:
        candidates.append(Path(local) / "GameSentenceMiner" / "gsm.db")

    home = Path.home()
    candidates.append(home / "AppData" / "Roaming" / "GameSentenceMiner" / "gsm.db")

    checked: list[str] = []
    seen: set[str] = set()
    for c in candidates:
        try:
            key = str(c.resolve()) if c.exists() else str(c)
        except OSError:
            key = str(c)
        if key in seen:
            continue
        seen.add(key)
        checked.append(key)
        try:
            if c.is_file():
                return c.resolve(), checked
        except OSError:
            continue
    return None, checked


def _open_sqlite_ro(path: Path, *, allow_immutable: bool = False) -> sqlite3.Connection:
    """
    Open a sqlite file read-only with query_only when supported.

    ``immutable=1`` ignores the WAL and can return a **stale** cursor / line set.
    Only enable it as a last resort when a live/snapshot open is impossible.
    """
    posix = path.as_posix()
    last_err: Optional[Exception] = None
    uris = [f"file:{posix}?mode=ro"]
    if allow_immutable:
        uris.append(f"file:{posix}?mode=ro&immutable=1")
    for uri in uris:
        try:
            con = sqlite3.connect(uri, uri=True, timeout=30.0)
            con.row_factory = sqlite3.Row
            try:
                con.execute("PRAGMA query_only = ON")
            except sqlite3.Error:
                pass
            con.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' LIMIT 1"
            ).fetchone()
            return con
        except sqlite3.Error as exc:
            last_err = exc
            try:
                con.close()  # type: ignore[name-defined]
            except Exception:  # noqa: BLE001
                pass
    try:
        con = sqlite3.connect(str(path), timeout=30.0)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA query_only = ON")
        con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' LIMIT 1"
        ).fetchone()
        return con
    except sqlite3.Error as exc:
        raise GsmError(str(exc)) from (last_err or exc)


class _SnapshotRoConnection:
    """
    Proxy around sqlite3.Connection that deletes a temp snapshot directory on close.

    sqlite3.Connection.close is read-only on the C type, so we cannot assign a
    wrapper method onto the live connection object.
    """

    def __init__(self, con: sqlite3.Connection, tmp_dir: Path):
        self._con = con
        self._tmp_dir = tmp_dir

    def __getattr__(self, name: str):
        return getattr(self._con, name)

    def close(self) -> None:
        import shutil

        try:
            self._con.close()
        finally:
            try:
                shutil.rmtree(self._tmp_dir, ignore_errors=True)
            except Exception:  # noqa: BLE001
                pass

    def __enter__(self) -> "_SnapshotRoConnection":
        return self

    def __exit__(self, *args) -> None:
        self.close()


def _connect_ro(path: Path):
    """
    Open GSM DB read-only. Never creates the file and never writes.

    Docker Desktop on Windows often fails plain SQLite opens against a host
    bind-mount while GSM holds a WAL lock. Strategies:

    1. Direct read-only open on the live path (includes WAL when possible)
    2. Snapshot copy of gsm.db + -wal + -shm into a temp dir (includes WAL)
    3. immutable=1 on the live path (main file only; may lag uncheckpointed WAL)
    """
    if not path.is_file():
        raise GsmError(f"GSM database not found: {path}")

    errors: list[str] = []

    # 1) Direct (no immutable — that would hide a fresher WAL watermark)
    try:
        return _open_sqlite_ro(path, allow_immutable=False)
    except GsmError as exc:
        errors.append(f"direct: {exc}")

    # 2) Snapshot (db + wal + shm) — read-only copies, never touches originals after copy
    try:
        import shutil
        import tempfile

        tmp = Path(tempfile.mkdtemp(prefix="gsm_ro_"))
        try:
            for suffix in ("", "-wal", "-shm"):
                src = Path(str(path) + suffix) if suffix else path
                if src.is_file():
                    shutil.copy2(src, tmp / src.name)
            snap = tmp / path.name
            con = _open_sqlite_ro(snap, allow_immutable=False)
            return _SnapshotRoConnection(con, tmp)
        except Exception:
            try:
                shutil.rmtree(tmp, ignore_errors=True)
            except Exception:  # noqa: BLE001
                pass
            raise
    except Exception as exc:  # noqa: BLE001
        errors.append(f"snapshot: {exc}")

    # 3) Last resort: immutable main file (may lag GSM's latest WAL)
    try:
        con = _open_sqlite_ro(path, allow_immutable=True)
        logger.warning(
            "gsm db opened with immutable=1 (WAL may be lagging); path=%s",
            path,
        )
        return con
    except GsmError as exc:
        errors.append(f"immutable: {exc}")

    raise GsmError(
        "Could not open GSM database read-only. "
        "If GSM is running on Windows, close it briefly or wait for a checkpoint. "
        f"Details: {'; '.join(errors[:3])}"
    )


def _connect_rw_cursor_only(path: Path) -> sqlite3.Connection:
    """
    Open GSM DB for the **sole** purpose of updating the Tadoku export cursor.

    Does not enable any delete/truncate path; callers must only use
    ``_write_tadoku_cursor``.
    """
    if not path.is_file():
        raise GsmError(f"GSM database not found: {path}")
    # Prefer direct path; fall back is not safe for writes.
    try:
        con = sqlite3.connect(str(path), timeout=30.0)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA busy_timeout = 30000")
        # Verify we can actually read under a write connection
        con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' LIMIT 1"
        ).fetchone()
        return con
    except sqlite3.Error as exc:
        raise GsmError(
            "Could not open GSM database for cursor write (file locked?). "
            "Close GSM briefly, then retry. "
            f"Detail: {exc}"
        ) from exc


def _table_names(con: sqlite3.Connection) -> set[str]:
    rows = con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    return {str(r[0]) for r in rows}


def _schema_ok(con: sqlite3.Connection) -> tuple[bool, str]:
    names = _table_names(con)
    missing = [t for t in (TABLE_LINES, TABLE_GAMES, TABLE_CURSOR) if t not in names]
    if missing:
        return False, f"Missing tables: {', '.join(missing)}"
    cols = {
        r[1]
        for r in con.execute(f'PRAGMA table_info("{TABLE_LINES}")').fetchall()
    }
    need = {"id", "line_text", "created_at", "game_id", "game_name"}
    miss_cols = sorted(need - cols)
    if miss_cols:
        return False, f"{TABLE_LINES} missing columns: {', '.join(miss_cols)}"
    return True, "schema ok"


def _read_cursor(con: sqlite3.Connection) -> Optional[float]:
    row = con.execute(
        f'SELECT last_successful_export_at FROM "{TABLE_CURSOR}" WHERE format_key = ?',
        (TADOKU_CURSOR_KEY,),
    ).fetchone()
    if not row or row[0] is None or str(row[0]).strip() == "":
        return None
    try:
        return float(row[0])
    except (TypeError, ValueError):
        return None


def _get_local_cursor(db: Optional[Session]) -> Optional[float]:
    if db is None:
        return None
    raw = (get_state(db, LOCAL_CURSOR_KEY) or "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _set_local_cursor(db: Session, value: float) -> float:
    """Raise immersion-local cursor floor (monotonic). Used when GSM write fails."""
    new_v = float(value)
    if new_v <= 0:
        raise GsmError("invalid local cursor")
    existing = _get_local_cursor(db)
    if existing is not None and new_v < existing:
        return existing
    set_state(db, LOCAL_CURSOR_KEY, str(new_v))
    return new_v


def _get_game_cursors(db: Optional[Session]) -> dict[str, float]:
    if db is None:
        return {}
    raw = (get_state(db, GAME_CURSORS_KEY) or "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, float] = {}
    for k, v in data.items():
        key = str(k or "").strip()
        if not key:
            continue
        try:
            out[key] = float(v)
        except (TypeError, ValueError):
            continue
    return out


def _set_game_cursor(db: Session, game_key: str, value: float) -> float:
    """Raise per-game skip floor (monotonic). Does not touch GSM files."""
    key = str(game_key or "").strip()
    if not key:
        raise GsmError("game_key required")
    new_v = float(value)
    if new_v <= 0:
        raise GsmError("invalid game cursor")
    cursors = _get_game_cursors(db)
    existing = cursors.get(key)
    if existing is not None and new_v < existing:
        return existing
    cursors[key] = new_v
    set_state(db, GAME_CURSORS_KEY, json.dumps(cursors, separators=(",", ":")))
    return new_v


def _line_after_cursors(
    created_at: float,
    *,
    global_cursor: Optional[float],
    game_cursors: dict[str, float],
    game_key: str,
) -> bool:
    """True if this line is still pending (after global + per-game floors)."""
    floors = [v for v in (global_cursor, game_cursors.get(game_key)) if v is not None]
    if not floors:
        return True
    return float(created_at) > max(floors)


def _effective_cursor(
    gsm_cursor: Optional[float],
    local_cursor: Optional[float],
) -> Optional[float]:
    """Preview watermark = max(GSM tadoku_incremental, immersion local floor)."""
    vals = [v for v in (gsm_cursor, local_cursor) if v is not None]
    if not vals:
        return None
    return max(vals)


def get_status(db: Optional[Session] = None) -> GsmStatus:
    cfg = _gsm_cfg()
    enabled = bool(getattr(cfg, "enabled", True))
    advance = bool(getattr(cfg, "advance_cursor", True))
    path, checked = resolve_gsm_db_path()
    pending = _load_pending_export(db) if db is not None else None
    local_cursor = _get_local_cursor(db) if db is not None else None

    if not enabled:
        return GsmStatus(
            ok=False,
            configured=False,
            enabled=False,
            path=str(path) if path else None,
            exists=bool(path and path.is_file()),
            readable=False,
            writable_cursor=False,
            message="GSM integration is disabled in settings (gsm.enabled: false).",
            detail="Set gsm.enabled: true in config/settings.yaml to use GameSentenceMiner lines.",
            candidates_checked=checked,
            advance_cursor=advance,
            pending_export=pending,
            local_cursor=local_cursor,
            cursor=local_cursor,
            gsm_cursor=None,
        )

    if path is None:
        return GsmStatus(
            ok=False,
            configured=False,
            enabled=True,
            path=None,
            exists=False,
            readable=False,
            writable_cursor=False,
            message="GameSentenceMiner database not found.",
            detail=(
                "Install/run GSM once, or set gsm.db_path / GSM_DB_PATH to gsm.db. "
                "Docker: mount the host GameSentenceMiner folder at /gsm "
                "(see docker-compose GSM_DATA_DIR)."
            ),
            candidates_checked=checked,
            advance_cursor=advance,
            pending_export=pending,
            local_cursor=local_cursor,
            cursor=local_cursor,
            gsm_cursor=None,
        )

    try:
        with _connect_ro(path) as con:
            ok_schema, schema_msg = _schema_ok(con)
            if not ok_schema:
                return GsmStatus(
                    ok=False,
                    configured=True,
                    enabled=True,
                    path=str(path),
                    exists=True,
                    readable=True,
                    writable_cursor=False,
                    message="GSM database found but schema is unexpected.",
                    detail=schema_msg,
                    candidates_checked=checked,
                    advance_cursor=advance,
                    pending_export=pending,
                    local_cursor=local_cursor,
                    cursor=local_cursor,
                    gsm_cursor=None,
                )
            gsm_cursor = _read_cursor(con)
            line_count = con.execute(
                f'SELECT COUNT(*) FROM "{TABLE_LINES}"'
            ).fetchone()[0]
            game_count = con.execute(
                f'SELECT COUNT(*) FROM "{TABLE_GAMES}"'
            ).fetchone()[0]
    except Exception as exc:  # noqa: BLE001
        logger.warning("gsm status read failed: %s", type(exc).__name__)
        return GsmStatus(
            ok=False,
            configured=True,
            enabled=True,
            path=str(path),
            exists=path.is_file(),
            readable=False,
            writable_cursor=False,
            message="Could not open GSM database (read-only).",
            detail=str(exc),
            candidates_checked=checked,
            advance_cursor=advance,
            pending_export=pending,
            local_cursor=local_cursor,
            cursor=local_cursor,
            gsm_cursor=None,
        )

    # Raise local floor if GSM itself moved ahead (e.g. mark-synced / GSM's tool)
    if db is not None and gsm_cursor is not None:
        if local_cursor is None or gsm_cursor > local_cursor:
            try:
                local_cursor = _set_local_cursor(db, float(gsm_cursor))
            except Exception:  # noqa: BLE001
                logger.debug("gsm local cursor bump from gsm failed", exc_info=True)

    cursor = _effective_cursor(gsm_cursor, local_cursor)
    cursor_sync_pending = bool(
        local_cursor is not None
        and (gsm_cursor is None or local_cursor > float(gsm_cursor) + 1e-9)
    )

    writable = False
    write_detail = ""
    if advance:
        try:
            # Probe write access without mutating: open + immediate rollback
            with _connect_rw_cursor_only(path) as wcon:
                wcon.execute("BEGIN IMMEDIATE")
                wcon.execute("ROLLBACK")
            writable = True
        except Exception as exc:  # noqa: BLE001
            write_detail = (
                f"GSM file write not available ({type(exc).__name__}). "
                "Logged characters still clear in this app via a local watermark; "
                "will retry writing GSM’s own cursor when the file unlocks."
            )
            logger.info("gsm cursor write probe failed: %s", type(exc).__name__)

    msg = "GSM database ready."
    detail = schema_msg
    if gsm_cursor is None and local_cursor is None:
        detail += (
            " No Tadoku cursor yet — first preview will treat history carefully "
            "(see mark-synced / first export)."
        )
    if cursor_sync_pending:
        detail = (
            f"{detail} Local export watermark ahead of GSM "
            f"({local_cursor}); waiting to sync."
        ).strip()
    if write_detail:
        detail = f"{detail} {write_detail}".strip()

    st = GsmStatus(
        ok=True,
        configured=True,
        enabled=True,
        path=str(path),
        exists=True,
        readable=True,
        writable_cursor=writable,
        message=msg,
        detail=detail if (write_detail or cursor_sync_pending) else "",
        cursor=cursor,
        gsm_cursor=gsm_cursor,
        local_cursor=local_cursor,
        cursor_sync_pending=cursor_sync_pending,
        line_count=int(line_count),
        game_count=int(game_count),
        schema_ok=True,
        candidates_checked=checked,
        advance_cursor=advance,
        pending_export=pending,
    )
    return st


def _game_key(game_id: Optional[str], game_name: Optional[str]) -> str:
    gid = str(game_id or "").strip()
    if gid:
        return gid
    return f"scene:{game_name or 'Unknown Game'}"


def _content_type_for_game(game_type: str, default_ct: str) -> str:
    gt = (game_type or "").strip().lower()
    if "visual" in gt and "novel" in gt:
        return "visual_novel"
    if gt in ("vn", "visual_novel", "visual novel"):
        return "visual_novel"
    if "novel" in gt:
        return "visual_novel"
    if gt in ("game", "pc game", "console"):
        return "game"
    return default_ct


def _dedupe_ids(
    rows: list[sqlite3.Row],
    *,
    strip_punctuation: bool = False,
    collapse_blocks: bool = False,
    require_japanese: bool = False,
    max_line_characters: int = 0,
) -> set[str]:
    """
    Newer exact-duplicate line texts per game (keep oldest by timestamp).

    When ``strip_punctuation`` is on, compare on GSM-cleaned text (same as GSM
    Tadoku, which cleans line_text before dedupe). Collapse/max-line apply first
    so a spam-tiled line matches a single clean copy of the same text.
    """
    grouped: dict[str, list[sqlite3.Row]] = {}
    for row in rows:
        key = _game_key(row["game_id"], row["game_name"])
        grouped.setdefault(key, []).append(row)

    duplicate_ids: set[str] = set()
    for grouped_rows in grouped.values():
        seen: set[str] = set()
        ordered = sorted(
            grouped_rows,
            key=lambda r: float(r["timestamp"] or r["created_at"] or 0),
        )
        for row in ordered:
            text = _count_text(
                row["line_text"],
                strip_punctuation=strip_punctuation,
                collapse_blocks=collapse_blocks,
                require_japanese=require_japanese,
                max_line_characters=max_line_characters,
            )
            if not text:
                continue
            normalized = text.lower()
            rid = str(row["id"])
            if normalized in seen:
                duplicate_ids.add(rid)
            else:
                seen.add(normalized)
    return duplicate_ids


def _annotate_auto_flags(
    entries: list[GsmPreviewEntry],
    *,
    min_chars: int,
    idle_minutes: float,
    now: float,
) -> None:
    idle_secs = max(0.0, float(idle_minutes)) * 60.0
    for e in entries:
        e.below_min = e.characters < min_chars
        age = now - float(e.latest_created_at or 0)
        e.waiting_idle = (not e.below_min) and idle_secs > 0 and age < idle_secs
        e.ready_for_auto = (not e.below_min) and (not e.waiting_idle) and e.characters > 0


def build_preview(
    *,
    deduplicate: Optional[bool] = None,
    strip_punctuation: Optional[bool] = None,
    collapse_repeated_blocks: Optional[bool] = None,
    require_japanese: Optional[bool] = None,
    upper_bound: Optional[float] = None,
    db: Optional[Session] = None,
) -> dict[str, Any]:
    """
    GSM-equivalent Tadoku preview: per-game character totals since cursor.

    Read-only. Does not create a cursor if missing (unlike GSM first-open which
    stamps 'now' and hides history) — we surface missing cursor so the UI can
    warn and offer mark-synced / first export explicitly.

    Counting prefs (``deduplicate``, ``strip_punctuation``,
    ``collapse_repeated_blocks``, ``require_japanese``) apply to preview, manual
    queue, and auto export the same way when omitted (saved prefs / yaml).
    """
    status = get_status(db)
    prefs = get_prefs(db)
    if deduplicate is None:
        deduplicate = bool(prefs.get("deduplicate"))
    else:
        deduplicate = bool(deduplicate)
    if strip_punctuation is None:
        strip_punctuation = bool(prefs.get("strip_punctuation", True))
    else:
        strip_punctuation = bool(strip_punctuation)
    if collapse_repeated_blocks is None:
        collapse_blocks = bool(prefs.get("collapse_repeated_blocks", True))
    else:
        collapse_blocks = bool(collapse_repeated_blocks)
    if require_japanese is None:
        require_jp = bool(prefs.get("require_japanese", True))
    else:
        require_jp = bool(require_japanese)
    max_line_chars = int(prefs.get("max_line_characters") or 0)
    if not status.ok or not status.path:
        return {
            "ok": False,
            "status": status.to_dict(),
            "prefs": prefs,
            "entries": [],
            "total_characters": 0,
            "total_entries": 0,
            "duplicates_excluded": 0,
            "baseline_characters": 0,
            "stripped_characters": 0,
            "characters_removed": 0,
            "block_collapse_lines": 0,
            "block_collapse_chars_removed": 0,
            "cursor": status.cursor,
            "upper_bound": None,
            "message": status.message,
            "detail": status.detail,
            "deduplicate": deduplicate,
            "strip_punctuation": strip_punctuation,
            "collapse_repeated_blocks": collapse_blocks,
            "require_japanese": require_jp,
            "max_line_characters": max_line_chars,
            "non_jp_lines": 0,
            "non_jp_chars_removed": 0,
        }

    path = Path(status.path)
    cfg = _gsm_cfg()
    default_ct = (getattr(cfg, "content_type", None) or "visual_novel").strip() or "visual_novel"
    cutoff = float(upper_bound if upper_bound is not None else time.time())
    min_chars = int(prefs["min_submit_characters"])
    idle_m = float(prefs["auto_submit_idle_minutes"])

    with _connect_ro(path) as con:
        gsm_cursor = _read_cursor(con)
        local_cursor = _get_local_cursor(db)
        cursor = _effective_cursor(gsm_cursor, local_cursor)
        # No cursor: pending = nothing until user marks synced or we treat as 0
        # GSM would init cursor to now; we require explicit mark-synced for safety.
        if cursor is None:
            return {
                "ok": True,
                "status": status.to_dict(),
                "prefs": prefs,
                "entries": [],
                "total_characters": 0,
                "total_entries": 0,
                "duplicates_excluded": 0,
                "baseline_characters": 0,
                "stripped_characters": 0,
                "characters_removed": 0,
                "block_collapse_lines": 0,
                "block_collapse_chars_removed": 0,
                "cursor": None,
                "gsm_cursor": gsm_cursor,
                "local_cursor": local_cursor,
                "upper_bound": cutoff,
                "message": "No export starting point yet.",
                "detail": (
                    "Set a starting point under Counting settings → “Skip history”, "
                    "or log everything from the beginning carefully."
                ),
                "needs_cursor_init": True,
                "deduplicate": deduplicate,
                "strip_punctuation": strip_punctuation,
                "collapse_repeated_blocks": collapse_blocks,
                "require_japanese": require_jp,
                "max_line_characters": max_line_chars,
                "non_jp_lines": 0,
                "non_jp_chars_removed": 0,
            }

        rows = con.execute(
            f"""
            SELECT id, game_id, game_name, line_text, created_at, timestamp
            FROM "{TABLE_LINES}"
            WHERE CAST(created_at AS REAL) <= ?
            """,
            (cutoff,),
        ).fetchall()

        games: dict[str, sqlite3.Row] = {}
        for grow in con.execute(
            f'SELECT id, title_original, type FROM "{TABLE_GAMES}"'
        ).fetchall():
            games[str(grow["id"])] = grow

        game_cursors = _get_game_cursors(db)
        duplicates = (
            _dedupe_ids(
                rows,
                strip_punctuation=strip_punctuation,
                collapse_blocks=collapse_blocks,
                require_japanese=require_jp,
                max_line_characters=max_line_chars,
            )
            if deduplicate
            else set()
        )
        grouped: dict[str, GsmPreviewEntry] = {}
        dup_in_window = 0
        baseline_characters = 0  # raw line length (no strip, no dedupe, no collapse)
        stripped_characters = 0  # GSM strip only (no dedupe) — for Raw vs Stripped UI
        block_collapse_lines = 0
        block_collapse_chars_removed = 0
        non_jp_lines = 0
        non_jp_chars_removed = 0

        for row in rows:
            created_at = float(row["created_at"] or 0)
            key = _game_key(row["game_id"], row["game_name"])
            if not _line_after_cursors(
                created_at,
                global_cursor=cursor,
                game_cursors=game_cursors,
                game_key=key,
            ):
                continue
            # Comparison totals ignore skip-repeats so strip effect is isolated
            raw_for_baseline = row["line_text"]
            if isinstance(raw_for_baseline, str) and raw_for_baseline:
                baseline_characters += len(raw_for_baseline)
                if not line_has_japanese(raw_for_baseline):
                    non_jp_lines += 1
                    non_jp_chars_removed += len(raw_for_baseline)
                stripped_only = _count_text(
                    raw_for_baseline,
                    strip_punctuation=True,
                    collapse_blocks=False,
                    require_japanese=False,
                )
                if stripped_only:
                    stripped_characters += len(stripped_only)
                # Always measure block-spam for UI (apply only when toggle on)
                collapsed = collapse_line_block_repeats(raw_for_baseline)
                if len(collapsed) < len(raw_for_baseline):
                    block_collapse_lines += 1
                    block_collapse_chars_removed += len(raw_for_baseline) - len(
                        collapsed
                    )
            rid = str(row["id"])
            if rid in duplicates:
                dup_in_window += 1
                continue
            text = _count_text(
                row["line_text"],
                strip_punctuation=strip_punctuation,
                collapse_blocks=collapse_blocks,
                require_japanese=require_jp,
                max_line_characters=max_line_chars,
            )
            if not text:
                continue
            gmeta = games.get(str(row["game_id"] or "").strip())
            gtype = str(gmeta["type"] or "") if gmeta else ""
            name = (
                str(gmeta["title_original"]).strip()
                if gmeta and gmeta["title_original"]
                else (row["game_name"] or "Unknown Game")
            )
            if key not in grouped:
                grouped[key] = GsmPreviewEntry(
                    game_key=key,
                    game_name=name or "Unknown Game",
                    characters=0,
                    lines=0,
                    content_type=_content_type_for_game(gtype, default_ct),
                    game_type=gtype,
                    latest_created_at=created_at,
                )
            grouped[key].characters += len(text)
            grouped[key].lines += 1
            if created_at > grouped[key].latest_created_at:
                grouped[key].latest_created_at = created_at

    entries = sorted(grouped.values(), key=lambda e: (-e.characters, e.game_name.casefold()))
    _annotate_auto_flags(
        entries, min_chars=min_chars, idle_minutes=idle_m, now=cutoff
    )
    # Refresh status cursor fields (effective = max(gsm, local))
    status.cursor = cursor
    status.gsm_cursor = gsm_cursor
    status.local_cursor = local_cursor
    status.cursor_sync_pending = bool(
        local_cursor is not None
        and (gsm_cursor is None or local_cursor > float(gsm_cursor) + 1e-9)
    )
    total_chars = sum(e.characters for e in entries)
    characters_removed = max(0, int(baseline_characters) - int(total_chars))
    auto_ready = [e for e in entries if e.ready_for_auto]
    return {
        "ok": True,
        "status": status.to_dict(),
        "prefs": prefs,
        "entries": [e.to_dict() for e in entries],
        "total_characters": total_chars,
        "total_entries": len(entries),
        "auto_ready_entries": len(auto_ready),
        "auto_ready_characters": sum(e.characters for e in auto_ready),
        "duplicates_excluded": dup_in_window,
        "baseline_characters": int(baseline_characters),
        "stripped_characters": int(stripped_characters),
        "characters_removed": characters_removed,
        "block_collapse_lines": int(block_collapse_lines),
        "block_collapse_chars_removed": int(block_collapse_chars_removed),
        "non_jp_lines": int(non_jp_lines),
        "non_jp_chars_removed": int(non_jp_chars_removed),
        "cursor": cursor,
        "gsm_cursor": gsm_cursor,
        "local_cursor": local_cursor,
        "cursor_sync_pending": status.cursor_sync_pending,
        "upper_bound": cutoff,
        "deduplicate": bool(deduplicate),
        "strip_punctuation": strip_punctuation,
        "collapse_repeated_blocks": collapse_blocks,
        "require_japanese": require_jp,
        "max_line_characters": max_line_chars,
        "message": (
            f"{total_chars:,} characters across {len(entries)} game(s)"
            if entries
            else "Nothing new to log"
        ),
        "detail": "",
        "needs_cursor_init": False,
    }


def _source_ref(game_key: str, upper_bound: float) -> str:
    # Keep under 255; game_key is usually a UUID
    return f"gsm:{game_key}:{upper_bound:.6f}"[:255]


def _series_key(game_key: str) -> str:
    return f"gsm:{game_key}"[:255]


def _load_pending_export(db: Optional[Session]) -> Optional[dict[str, Any]]:
    if db is None:
        return None
    raw = get_state(db, PENDING_EXPORT_STATE_KEY)
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return data


def _save_pending_export(db: Session, payload: Optional[dict[str, Any]]) -> None:
    if payload is None:
        set_state(db, PENDING_EXPORT_STATE_KEY, "")
    else:
        set_state(db, PENDING_EXPORT_STATE_KEY, json.dumps(payload))


def _write_tadoku_cursor(path: Path, new_cursor: float) -> float:
    """
    Monotonic UPSERT of GSM tadoku_incremental watermark.

    NEVER deletes rows. NEVER touches game_lines / games.
    """
    if new_cursor <= 0:
        raise GsmError("invalid cursor")
    new_cursor = float(new_cursor)

    with _connect_rw_cursor_only(path) as con:
        try:
            con.execute("BEGIN IMMEDIATE")
            # Verify table still present
            names = _table_names(con)
            if TABLE_CURSOR not in names:
                raise GsmError(f"GSM missing table {TABLE_CURSOR}")
            if TABLE_LINES not in names:
                # Refuse writes if this does not look like a GSM db
                raise GsmError("Refusing cursor write: game_lines table missing")

            row = con.execute(
                f'SELECT last_successful_export_at FROM "{TABLE_CURSOR}" '
                "WHERE format_key = ?",
                (_WRITE_ALLOWED_FORMAT_KEY,),
            ).fetchone()
            existing: Optional[float] = None
            if row and row[0] is not None and str(row[0]).strip() != "":
                existing = float(row[0])

            if existing is not None and new_cursor < existing:
                con.execute("ROLLBACK")
                logger.info(
                    "gsm cursor not moved backward existing=%s requested=%s",
                    existing,
                    new_cursor,
                )
                return existing

            now = time.time()
            # Only ever write this one format_key
            con.execute(
                f"""
                INSERT INTO "{TABLE_CURSOR}"
                    (format_key, last_successful_export_at, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(format_key) DO UPDATE SET
                    last_successful_export_at = excluded.last_successful_export_at,
                    updated_at = excluded.updated_at
                """,
                (
                    _WRITE_ALLOWED_FORMAT_KEY,
                    str(new_cursor),
                    str(existing if existing is not None else now),
                    str(now),
                ),
            )
            # Safety: ensure we did not create extra rows with wrong keys in this txn
            # (we only issued one parameterized UPSERT)
            con.execute("COMMIT")
            logger.info(
                "gsm tadoku cursor advanced path=%s cursor=%s (was %s)",
                path,
                new_cursor,
                existing,
            )
            return new_cursor
        except Exception:
            try:
                con.execute("ROLLBACK")
            except Exception:  # noqa: BLE001
                pass
            raise


def advance_gsm_cursor(
    new_cursor: float,
    db: Optional[Session] = None,
) -> dict[str, Any]:
    """
    Advance GSM tadoku_incremental watermark (no line data touched).

    When ``db`` is provided, also raises the immersion-local cursor floor so
    previews reset even if the GSM file write fails (common on Docker Desktop
    Windows bind-mounts while GSM holds the DB).
    """
    cfg = _gsm_cfg()
    target = float(new_cursor)
    local_final: Optional[float] = None
    if db is not None:
        try:
            local_final = _set_local_cursor(db, target)
        except Exception:  # noqa: BLE001
            logger.debug("gsm local cursor set failed", exc_info=True)

    if not bool(getattr(cfg, "advance_cursor", True)):
        return {
            "ok": True if local_final is not None else False,
            "advanced": local_final is not None,
            "advanced_local": local_final is not None,
            "advanced_gsm": False,
            "cursor": local_final,
            "local_cursor": local_final,
            "message": (
                "gsm.advance_cursor is false — GSM file not written"
                + ("; local watermark updated." if local_final is not None else ".")
            ),
        }
    path, _ = resolve_gsm_db_path()
    if path is None:
        if local_final is not None:
            return {
                "ok": True,
                "advanced": True,
                "advanced_local": True,
                "advanced_gsm": False,
                "cursor": local_final,
                "local_cursor": local_final,
                "message": "Local watermark set; GSM database not found for file write.",
            }
        raise GsmError("GSM database not found")
    status = get_status(db)
    if not status.ok and local_final is None:
        raise GsmError(status.message)
    try:
        final = _write_tadoku_cursor(path, target)
        return {
            "ok": True,
            "advanced": True,
            "advanced_local": local_final is not None,
            "advanced_gsm": True,
            "cursor": final,
            "local_cursor": local_final,
            "path": str(path),
            "message": f"GSM Tadoku watermark set to {final}",
        }
    except Exception as exc:  # noqa: BLE001
        if local_final is not None:
            logger.warning(
                "gsm file cursor write failed; local watermark kept at %s: %s",
                local_final,
                type(exc).__name__,
            )
            return {
                "ok": True,
                "advanced": True,
                "advanced_local": True,
                "advanced_gsm": False,
                "cursor": local_final,
                "local_cursor": local_final,
                "path": str(path),
                "gsm_write_error": str(exc),
                "message": (
                    f"Local export watermark set to {local_final}. "
                    "Could not write GSM’s file (locked or disk I/O); will retry."
                ),
            }
        raise


def mark_synced_now(db: Session) -> dict[str, Any]:
    """
    Set GSM cursor to now without posting — skips all current lines for Tadoku.

    Same idea as GSM's first-time cursor init. Does not delete GSM data.
    Clears any immersion pending-export batch. Always updates local watermark.
    """
    path, _ = resolve_gsm_db_path()
    if path is None:
        raise GsmError("GSM database not found")
    now = time.time()
    result = advance_gsm_cursor(now, db=db)
    _save_pending_export(db, None)
    result["cleared_pending_export"] = True
    result["message"] = (
        "Marked all current GSM lines as already handled for Tadoku. "
        "Only new lines after this moment will appear in the preview."
        + (
            " (GSM file write pending — local counter already reset.)"
            if result.get("advanced_local") and not result.get("advanced_gsm")
            else ""
        )
    )
    return result


def mark_game_synced(db: Session, game_key: str) -> dict[str, Any]:
    """
    Zero Ready-to-log for one game: raise its per-game skip floor to now.

    Does not delete GSM lines. Other games keep their immersion pending counts.

    GSM's own Tadoku UI only has a **global** watermark. When this game is the
    only title with lines after that watermark, we also advance it so GSM's
    counter goes to 0. If other games still have pending lines, GSM's combined
    total cannot be zeroed without wiping those too — immersion still clears
    just this game.
    """
    key = str(game_key or "").strip()
    if not key:
        raise GsmError("game_key required")
    now = time.time()
    final = _set_game_cursor(db, key, now)

    advanced_gsm = False
    gsm_write: Optional[dict[str, Any]] = None
    other_pending = 0
    path, _ = resolve_gsm_db_path()
    if path is not None:
        try:
            status = get_status(db)
            global_c = status.cursor  # effective max(gsm, local) before this clear
            with _connect_ro(path) as con:
                gsm_c = _read_cursor(con)
                # Count other games still pending on GSM's own watermark
                floor = gsm_c if gsm_c is not None else global_c
                if floor is None:
                    floor = 0.0
                rows = con.execute(
                    f"""
                    SELECT game_id, game_name, CAST(created_at AS REAL) AS ca
                    FROM "{TABLE_LINES}"
                    WHERE CAST(created_at AS REAL) > ?
                    """,
                    (float(floor),),
                ).fetchall()
                for row in rows:
                    gk = _game_key(row["game_id"], row["game_name"])
                    if gk != key:
                        other_pending += 1
                        break
            if other_pending == 0:
                gsm_write = advance_gsm_cursor(now, db=db)
                advanced_gsm = bool(
                    gsm_write.get("advanced_gsm") or gsm_write.get("advanced_local")
                )
        except Exception:  # noqa: BLE001
            logger.debug("gsm mark_game_synced global advance skipped", exc_info=True)

    if advanced_gsm and gsm_write and gsm_write.get("advanced_gsm"):
        msg = (
            "Cleared this game in immersion-tracker and GSM’s Tadoku counter. "
            "Only new lines will count again."
        )
    elif advanced_gsm:
        msg = (
            "Cleared this game here; GSM file counter sync pending "
            "(file locked). Only new lines will count again."
        )
    elif other_pending:
        msg = (
            "Cleared Ready-to-log for this game in immersion-tracker. "
            "GSM’s app still shows a combined total (other games still pending); "
            "GSM only has one global counter."
        )
    else:
        msg = (
            "Cleared Ready-to-log for this game. "
            "Only new lines after this moment will count again."
        )
    return {
        "ok": True,
        "game_key": key,
        "game_cursor": final,
        "advanced_gsm_watermark": bool(gsm_write and gsm_write.get("advanced_gsm")),
        "gsm_write": gsm_write,
        "other_games_pending": bool(other_pending),
        "message": msg,
    }


def queue_from_preview(
    db: Session,
    *,
    deduplicate: Optional[bool] = None,
    strip_punctuation: Optional[bool] = None,
    collapse_repeated_blocks: Optional[bool] = None,
    require_japanese: Optional[bool] = None,
    submit: bool = False,
    include_history_if_no_cursor: bool = False,
    game_keys: Optional[list[str]] = None,
    only_auto_ready: bool = False,
    min_characters: Optional[int] = None,
) -> dict[str, Any]:
    """
    Create immersion LogEntry rows for each pending GSM game.

    * Does not advance GSM cursor until logs are pushed (or submit all succeed).
    * Never deletes GSM data.
    * ``only_auto_ready`` / ``min_characters`` filter which games become logs.
    """
    status = get_status(db)
    prefs = get_prefs(db)
    if deduplicate is None:
        deduplicate = bool(prefs.get("deduplicate"))
    if strip_punctuation is None:
        strip_punctuation = bool(prefs.get("strip_punctuation", True))
    if collapse_repeated_blocks is None:
        collapse_repeated_blocks = bool(prefs.get("collapse_repeated_blocks", True))
    if require_japanese is None:
        require_japanese = bool(prefs.get("require_japanese", True))
    if not status.ok:
        return {
            "ok": False,
            "message": status.message,
            "detail": status.detail,
            "status": status.to_dict(),
            "prefs": prefs,
            "created": [],
            "skipped_duplicate": [],
        }

    upper_bound = time.time()
    preview = build_preview(
        deduplicate=bool(deduplicate),
        strip_punctuation=bool(strip_punctuation),
        collapse_repeated_blocks=bool(collapse_repeated_blocks),
        require_japanese=bool(require_japanese),
        upper_bound=upper_bound,
        db=db,
    )

    if preview.get("needs_cursor_init") and not include_history_if_no_cursor:
        return {
            "ok": False,
            "message": preview.get("message"),
            "detail": preview.get("detail"),
            "status": status.to_dict(),
            "prefs": prefs,
            "needs_cursor_init": True,
            "created": [],
            "skipped_duplicate": [],
        }

    if preview.get("needs_cursor_init") and include_history_if_no_cursor:
        # Force cursor 0 in a one-off aggregation (does not write GSM)
        preview = _preview_with_cursor(
            0.0,
            deduplicate=bool(deduplicate),
            strip_punctuation=bool(strip_punctuation),
            collapse_repeated_blocks=bool(collapse_repeated_blocks),
            require_japanese=bool(require_japanese),
            upper_bound=upper_bound,
            db=db,
        )
        preview["status"] = status.to_dict()

    entries = list(preview.get("entries") or [])
    key_filter = {str(k) for k in (game_keys or []) if k}
    if key_filter:
        entries = [e for e in entries if e.get("game_key") in key_filter]
    min_c = (
        int(min_characters)
        if min_characters is not None
        else (int(prefs["min_submit_characters"]) if only_auto_ready else 0)
    )
    if only_auto_ready:
        entries = [e for e in entries if e.get("ready_for_auto")]
    elif min_c > 0:
        entries = [e for e in entries if int(e.get("characters") or 0) >= min_c]

    if not entries:
        return {
            "ok": True,
            "message": "Nothing ready to log right now.",
            "detail": (
                "Waiting for more characters or idle time."
                if only_auto_ready
                else (preview.get("detail") or "")
            ),
            "preview": preview,
            "prefs": prefs,
            "created": [],
            "skipped_duplicate": [],
            "submitted": None,
            "cursor_advanced": False,
        }

    cfg = _gsm_cfg()
    # Auto path: force tadoku mode auto so queue + process will push
    tadoku_default = (getattr(cfg, "tadoku_default", None) or "pending").strip() or "pending"
    if only_auto_ready or submit:
        # Prefer immediate submit path; mode auto if user wants hands-off
        if get_log_mode(db) == "auto" or only_auto_ready:
            tadoku_default = "auto" if submit else tadoku_default
    created: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    source_refs: list[str] = []

    for ent in entries:
        game_key = ent["game_key"]
        title = ent["game_name"]
        chars = int(ent["characters"])
        if chars <= 0:
            continue
        ct = ent.get("content_type") or "visual_novel"
        ref = _source_ref(game_key, float(preview["upper_bound"]))
        source_refs.append(ref)
        try:
            log = create_log(
                db,
                content_type=ct,
                title=title,
                source=SOURCE,
                amount=float(chars),
                unit="characters",
                activity="reading",
                series_key=_series_key(game_key),
                source_ref=ref,
                language="ja",
                notes=(
                    f"gsm_export; game_key={game_key}; "
                    f"lines={ent['lines']}; "
                    f"cursor={preview.get('cursor')}; "
                    f"upper_bound={preview['upper_bound']:.6f}; "
                    f"dedupe={bool(deduplicate)}; "
                    f"strip_punct={bool(strip_punctuation)}; "
                    f"collapse_blocks={bool(collapse_repeated_blocks)}; "
                    f"require_jp={bool(require_japanese)}"
                ),
                # Media tag only (vn / game) — same as manual immersion logs
                tags=(
                    "vn"
                    if (ct or "").strip().lower() in ("visual_novel", "vn")
                    else ("game" if (ct or "").strip().lower() == "game" else ct)
                ),
                tadoku_mode_override=tadoku_default,
            )
            created.append(
                {
                    "id": log.id,
                    "title": log.title,
                    "amount": log.amount,
                    "tadoku_status": log.tadoku_status,
                    "source_ref": log.source_ref,
                }
            )
        except DuplicateLogError as dup:
            skipped.append(
                {
                    "id": dup.existing.id,
                    "title": dup.existing.title,
                    "amount": dup.existing.amount,
                    "tadoku_status": dup.existing.tadoku_status,
                    "source_ref": dup.existing.source_ref,
                    "reason": "duplicate",
                }
            )

    # Track batch so we can advance GSM cursor after full push
    if source_refs:
        _save_pending_export(
            db,
            {
                "upper_bound": float(preview["upper_bound"]),
                "cursor_before": preview.get("cursor"),
                "source_refs": source_refs,
                "deduplicate": bool(deduplicate),
                "created_at": utcnow().isoformat(),
            },
        )

    submitted = None
    cursor_advanced = False
    cursor_result = None

    if submit and (created or skipped):
        from app.tadoku.queue import approve_many

        ids = [c["id"] for c in created] + [
            s["id"]
            for s in skipped
            if s.get("tadoku_status")
            in (
                TadokuStatus.PENDING.value,
                TadokuStatus.READY.value,
                TadokuStatus.FAILED.value,
            )
        ]
        if ids:
            submitted = approve_many(db, ids)
        cursor_result = try_complete_pending_export(db)
        cursor_advanced = bool(cursor_result.get("advanced"))

    return {
        "ok": True,
        "message": (
            f"Queued {len(created)} GSM log(s)"
            + (f", {len(skipped)} already present" if skipped else "")
            + (" and submitted." if submit else " (pending Tadoku review).")
        ),
        "detail": (
            "GSM cursor advances only after all logs from this export are "
            "pushed or skipped on tadoku.app."
            if not cursor_advanced
            else "GSM Tadoku watermark advanced after successful export."
        ),
        "preview": preview,
        "created": created,
        "skipped_duplicate": skipped,
        "submitted": submitted,
        "cursor_advanced": cursor_advanced,
        "cursor_result": cursor_result,
    }


def _preview_with_cursor(
    cursor: float,
    *,
    deduplicate: bool,
    strip_punctuation: bool = True,
    collapse_repeated_blocks: bool = True,
    require_japanese: bool = True,
    upper_bound: float,
    db: Optional[Session] = None,
) -> dict[str, Any]:
    """Internal aggregation with a synthetic cursor (does not write GSM)."""
    path, _ = resolve_gsm_db_path()
    if path is None:
        raise GsmError("GSM database not found")
    cfg = _gsm_cfg()
    prefs = get_prefs(db)
    collapse_blocks = bool(collapse_repeated_blocks)
    require_jp = bool(require_japanese)
    max_line_chars = int(prefs.get("max_line_characters") or 0)
    default_ct = (getattr(cfg, "content_type", None) or "visual_novel").strip() or "visual_novel"
    with _connect_ro(path) as con:
        rows = con.execute(
            f"""
            SELECT id, game_id, game_name, line_text, created_at, timestamp
            FROM "{TABLE_LINES}"
            WHERE CAST(created_at AS REAL) <= ?
            """,
            (upper_bound,),
        ).fetchall()
        games: dict[str, sqlite3.Row] = {}
        for grow in con.execute(
            f'SELECT id, title_original, type FROM "{TABLE_GAMES}"'
        ).fetchall():
            games[str(grow["id"])] = grow
        game_cursors = _get_game_cursors(db)
        duplicates = (
            _dedupe_ids(
                rows,
                strip_punctuation=strip_punctuation,
                collapse_blocks=collapse_blocks,
                require_japanese=require_jp,
                max_line_characters=max_line_chars,
            )
            if deduplicate
            else set()
        )
        grouped: dict[str, GsmPreviewEntry] = {}
        dup_in_window = 0
        baseline_characters = 0
        stripped_characters = 0
        block_collapse_lines = 0
        block_collapse_chars_removed = 0
        non_jp_lines = 0
        non_jp_chars_removed = 0
        for row in rows:
            created_at = float(row["created_at"] or 0)
            key = _game_key(row["game_id"], row["game_name"])
            if not _line_after_cursors(
                created_at,
                global_cursor=cursor,
                game_cursors=game_cursors,
                game_key=key,
            ):
                continue
            raw_for_baseline = row["line_text"]
            if isinstance(raw_for_baseline, str) and raw_for_baseline:
                baseline_characters += len(raw_for_baseline)
                if not line_has_japanese(raw_for_baseline):
                    non_jp_lines += 1
                    non_jp_chars_removed += len(raw_for_baseline)
                stripped_only = _count_text(
                    raw_for_baseline,
                    strip_punctuation=True,
                    collapse_blocks=False,
                    require_japanese=False,
                )
                if stripped_only:
                    stripped_characters += len(stripped_only)
                collapsed = collapse_line_block_repeats(raw_for_baseline)
                if len(collapsed) < len(raw_for_baseline):
                    block_collapse_lines += 1
                    block_collapse_chars_removed += len(raw_for_baseline) - len(
                        collapsed
                    )
            rid = str(row["id"])
            if rid in duplicates:
                dup_in_window += 1
                continue
            text = _count_text(
                row["line_text"],
                strip_punctuation=strip_punctuation,
                collapse_blocks=collapse_blocks,
                require_japanese=require_jp,
                max_line_characters=max_line_chars,
            )
            if not text:
                continue
            gmeta = games.get(str(row["game_id"] or "").strip())
            gtype = str(gmeta["type"] or "") if gmeta else ""
            name = (
                str(gmeta["title_original"]).strip()
                if gmeta and gmeta["title_original"]
                else (row["game_name"] or "Unknown Game")
            )
            if key not in grouped:
                grouped[key] = GsmPreviewEntry(
                    game_key=key,
                    game_name=name or "Unknown Game",
                    characters=0,
                    lines=0,
                    content_type=_content_type_for_game(gtype, default_ct),
                    game_type=gtype,
                    latest_created_at=created_at,
                )
            grouped[key].characters += len(text)
            grouped[key].lines += 1
            if created_at > grouped[key].latest_created_at:
                grouped[key].latest_created_at = created_at
    entries = sorted(grouped.values(), key=lambda e: (-e.characters, e.game_name.casefold()))
    _annotate_auto_flags(
        entries,
        min_chars=int(prefs["min_submit_characters"]),
        idle_minutes=float(prefs["auto_submit_idle_minutes"]),
        now=upper_bound,
    )
    total_chars = sum(e.characters for e in entries)
    return {
        "ok": True,
        "prefs": prefs,
        "entries": [e.to_dict() for e in entries],
        "total_characters": total_chars,
        "total_entries": len(entries),
        "duplicates_excluded": dup_in_window,
        "baseline_characters": int(baseline_characters),
        "stripped_characters": int(stripped_characters),
        "characters_removed": max(0, int(baseline_characters) - int(total_chars)),
        "block_collapse_lines": int(block_collapse_lines),
        "block_collapse_chars_removed": int(block_collapse_chars_removed),
        "non_jp_lines": int(non_jp_lines),
        "non_jp_chars_removed": int(non_jp_chars_removed),
        "cursor": cursor,
        "upper_bound": upper_bound,
        "deduplicate": bool(deduplicate),
        "strip_punctuation": bool(strip_punctuation),
        "collapse_repeated_blocks": collapse_blocks,
        "require_japanese": require_jp,
        "max_line_characters": max_line_chars,
        "message": f"History export: {len(entries)} game(s), {total_chars:,} characters.",
        "detail": "Synthetic cursor 0 — all lines up to upper_bound.",
        "needs_cursor_init": False,
    }


def process_auto_export(db: Session) -> dict[str, Any]:
    """
    Scheduler entry: finish any pending export/cursor sync, then when
    log_mode=auto queue+submit games that meet min characters and idle quiet.
    """
    cfg = _gsm_cfg()
    if not bool(getattr(cfg, "enabled", True)):
        return {"ok": True, "skipped": True, "reason": "disabled"}

    # Always finish pending batches / retry GSM file writes (manual mode too)
    finish = finish_pending_export_work(db)

    if get_log_mode(db) != "auto":
        return {
            "ok": True,
            "skipped": True,
            "reason": "manual_mode",
            "finish": finish,
        }

    # Don't start a new auto batch while a previous GSM export is unfinished
    pending = _load_pending_export(db)
    if pending:
        return {
            "ok": True,
            "skipped": True,
            "reason": "pending_export_incomplete",
            "pending": pending,
            "finish": finish,
        }

    result = queue_from_preview(
        db,
        deduplicate=get_deduplicate(db),
        strip_punctuation=get_strip_punctuation(db),
        collapse_repeated_blocks=get_collapse_repeated_blocks(db),
        submit=True,
        only_auto_ready=True,
    )
    result["finish"] = finish
    if result.get("created") or result.get("submitted"):
        logger.info(
            "gsm auto-export: created=%s submitted=%s cursor_advanced=%s",
            len(result.get("created") or []),
            (result.get("submitted") or {}).get("pushed"),
            result.get("cursor_advanced"),
        )
    return result


def process_daily_time_export(db: Session, *, force: bool = False) -> dict[str, Any]:
    """
    Once-per-day export at the configured local hour.

    Logs every game that meets min characters (ignores idle — intended for
    overnight dump). Default enabled=false.

    Always retries pending export completion / GSM cursor sync first so a
    finished batch is not stuck waiting for the daily window.
    """
    cfg = _gsm_cfg()
    if not bool(getattr(cfg, "enabled", True)):
        return {"ok": True, "skipped": True, "reason": "disabled"}

    # Cursor / pending work is independent of daily auto-log prefs
    finish = finish_pending_export_work(db)

    if not force and not get_auto_log_at_time_enabled(db):
        return {
            "ok": True,
            "skipped": True,
            "reason": "auto_log_at_time_off",
            "finish": finish,
        }

    try:
        tz = ZoneInfo(get_timezone_name())
    except Exception:  # noqa: BLE001
        tz = ZoneInfo("America/Los_Angeles")
    now = datetime.now(tz)
    hour = get_auto_log_at_hour(db)
    today = now.date().isoformat()

    if not force:
        if now.hour != hour:
            return {
                "ok": True,
                "skipped": True,
                "reason": "wrong_hour",
                "local_hour": now.hour,
                "target_hour": hour,
                "timezone": str(tz),
                "finish": finish,
            }
        # Run in the first 5 minutes of the hour (job polls every minute)
        if now.minute > 5:
            return {
                "ok": True,
                "skipped": True,
                "reason": "past_window",
                "finish": finish,
            }
        last = (get_state(db, STATE_LAST_DAILY_LOG) or "").strip()
        if last == today:
            return {
                "ok": True,
                "skipped": True,
                "reason": "already_ran_today",
                "date": today,
                "finish": finish,
            }

    pending = _load_pending_export(db)
    if pending:
        return {
            "ok": True,
            "skipped": True,
            "reason": "pending_export_incomplete",
            "finish": finish,
        }

    # Min chars only (no idle wait) — daily dump; same counting prefs as manual
    result = queue_from_preview(
        db,
        deduplicate=get_deduplicate(db),
        strip_punctuation=get_strip_punctuation(db),
        collapse_repeated_blocks=get_collapse_repeated_blocks(db),
        submit=True,
        min_characters=get_min_submit_characters(db),
        only_auto_ready=False,
    )
    result["finish"] = finish
    # Mark day only when we actually attempted an export (including nothing to do)
    if result.get("ok") is not False:
        set_state(db, STATE_LAST_DAILY_LOG, today)
    result["daily"] = True
    result["local_date"] = today
    result["timezone"] = str(tz)
    result["target_hour"] = hour
    if result.get("created") or (result.get("submitted") or {}).get("pushed"):
        logger.info(
            "gsm daily time-export: hour=%s tz=%s created=%s pushed=%s",
            hour,
            tz,
            len(result.get("created") or []),
            (result.get("submitted") or {}).get("pushed"),
        )
    return result


def try_complete_pending_export(db: Session) -> dict[str, Any]:
    """
    If every log from the pending GSM export batch is pushed or skipped,
    advance the export watermark to that batch's upper_bound.

    Always raises the immersion-local cursor so the GSM panel resets even when
    the GSM sqlite file cannot be written (Docker/Windows lock). GSM file write
    is best-effort and retried by ``try_sync_cursor_to_gsm``.
    """
    pending = _load_pending_export(db)
    if not pending:
        return {"ok": True, "advanced": False, "reason": "no_pending_export"}

    refs = pending.get("source_refs") or []
    upper = pending.get("upper_bound")
    if not refs or upper is None:
        _save_pending_export(db, None)
        return {"ok": True, "advanced": False, "reason": "invalid_pending"}

    logs = (
        db.query(LogEntry)
        .filter(LogEntry.source == SOURCE, LogEntry.source_ref.in_(list(refs)))
        .all()
    )
    by_ref = {l.source_ref: l for l in logs}
    missing = [r for r in refs if r not in by_ref]
    if missing:
        return {
            "ok": True,
            "advanced": False,
            "reason": "missing_logs",
            "missing": missing[:5],
        }

    terminal = {
        TadokuStatus.PUSHED.value,
        TadokuStatus.SKIPPED.value,
    }
    not_done = [
        l
        for l in logs
        if (l.tadoku_status or "").lower() not in terminal
    ]
    if not_done:
        return {
            "ok": True,
            "advanced": False,
            "reason": "batch_incomplete",
            "remaining": [
                {"id": l.id, "status": l.tadoku_status, "title": l.title}
                for l in not_done[:10]
            ],
        }

    # Batch is fully terminal — clear pending and raise watermarks (local always).
    _save_pending_export(db, None)
    try:
        result = advance_gsm_cursor(float(upper), db=db)
    except Exception as exc:  # noqa: BLE001
        # Last-resort: still keep local so preview resets
        logger.exception("gsm cursor advance failed")
        try:
            local = _set_local_cursor(db, float(upper))
        except Exception as local_exc:  # noqa: BLE001
            return {
                "ok": False,
                "advanced": False,
                "reason": "cursor_write_failed",
                "error": str(exc),
                "local_error": str(local_exc),
            }
        return {
            "ok": True,
            "advanced": True,
            "advanced_local": True,
            "advanced_gsm": False,
            "cursor": local,
            "local_cursor": local,
            "reason": "local_only",
            "gsm_write_error": str(exc),
            "message": (
                f"Export complete; local watermark {local}. "
                "GSM file still locked — will retry."
            ),
            "batch_upper_bound": float(upper),
        }

    return {
        "ok": True,
        "advanced": bool(result.get("advanced")),
        "advanced_local": bool(result.get("advanced_local")),
        "advanced_gsm": bool(result.get("advanced_gsm")),
        "cursor": result.get("cursor"),
        "local_cursor": result.get("local_cursor"),
        "message": result.get("message"),
        "gsm_write_error": result.get("gsm_write_error"),
        "batch_upper_bound": float(upper),
    }


def try_sync_cursor_to_gsm(db: Session) -> dict[str, Any]:
    """
    If immersion-local watermark is ahead of GSM's tadoku_incremental, retry
    writing the GSM file. No-op when already in sync or writes disabled.
    """
    cfg = _gsm_cfg()
    if not bool(getattr(cfg, "advance_cursor", True)):
        return {"ok": True, "synced": False, "reason": "advance_cursor_disabled"}

    local = _get_local_cursor(db)
    if local is None:
        return {"ok": True, "synced": False, "reason": "no_local_cursor"}

    path, _ = resolve_gsm_db_path()
    if path is None:
        return {"ok": True, "synced": False, "reason": "no_gsm_db"}

    try:
        with _connect_ro(path) as con:
            gsm_cursor = _read_cursor(con)
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "synced": False,
            "reason": "gsm_read_failed",
            "error": str(exc),
        }

    if gsm_cursor is not None and float(gsm_cursor) >= float(local) - 1e-9:
        return {
            "ok": True,
            "synced": False,
            "reason": "already_in_sync",
            "gsm_cursor": gsm_cursor,
            "local_cursor": local,
        }

    try:
        final = _write_tadoku_cursor(path, float(local))
        logger.info(
            "gsm cursor synced from local watermark path=%s cursor=%s",
            path,
            final,
        )
        return {
            "ok": True,
            "synced": True,
            "cursor": final,
            "local_cursor": local,
            "message": f"GSM watermark synced to {final}",
        }
    except Exception as exc:  # noqa: BLE001
        logger.info(
            "gsm cursor sync retry failed: %s",
            type(exc).__name__,
        )
        return {
            "ok": True,
            "synced": False,
            "reason": "gsm_write_failed",
            "error": str(exc),
            "local_cursor": local,
            "gsm_cursor": gsm_cursor,
        }


def finish_pending_export_work(db: Session) -> dict[str, Any]:
    """
    Complete a finished GSM export batch and/or retry GSM file cursor write.

    Safe to call from manual mode, process_ready, and the scheduler.
    """
    complete = try_complete_pending_export(db)
    sync = try_sync_cursor_to_gsm(db)
    return {
        "complete": complete,
        "sync": sync,
        "advanced": bool(complete.get("advanced")),
        "synced": bool(sync.get("synced")),
    }
