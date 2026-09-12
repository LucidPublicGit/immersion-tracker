"""GameSentenceMiner read + cursor + queue (never touches real GSM data)."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings, reload_settings
from app.db.models import LogEntry, TadokuStatus
from app.db.session import get_engine, init_db
from app.ingest.gsm import (
    GAME_CURSORS_KEY,
    LOCAL_CURSOR_KEY,
    TADOKU_CURSOR_KEY,
    advance_gsm_cursor,
    build_preview,
    clean_text_for_stats,
    collapse_line_block_repeats,
    collapse_repeated_blocks,
    finish_pending_export_work,
    get_status,
    line_has_japanese,
    mark_game_synced,
    mark_synced_now,
    process_auto_export,
    queue_from_preview,
    set_prefs,
    try_complete_pending_export,
    try_sync_cursor_to_gsm,
)
from app.sheets.state import get_state, set_state


def _db():
    init_db()
    SessionLocal = sessionmaker(bind=get_engine(), autoflush=False, autocommit=False)
    return SessionLocal()


def _make_gsm_db(path: Path, *, cursor: float | None = 1000.0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path))
    con.executescript(
        """
        CREATE TABLE game_lines (
            id TEXT PRIMARY KEY,
            game_name TEXT,
            line_text TEXT,
            timestamp REAL,
            game_id TEXT,
            created_at TEXT
        );
        CREATE TABLE games (
            id TEXT PRIMARY KEY,
            title_original TEXT,
            type TEXT
        );
        CREATE TABLE stats_export_state (
            format_key TEXT PRIMARY KEY,
            last_successful_export_at TEXT,
            created_at TEXT,
            updated_at TEXT
        );
        """
    )
    con.execute(
        "INSERT INTO games (id, title_original, type) VALUES (?,?,?)",
        ("g1", "Test VN", "Visual Novel"),
    )
    # before cursor
    con.execute(
        "INSERT INTO game_lines (id, game_name, line_text, timestamp, game_id, created_at) "
        "VALUES (?,?,?,?,?,?)",
        ("old1", "Test VN", "古い", 900.0, "g1", "900.0"),
    )
    # after cursor
    con.execute(
        "INSERT INTO game_lines (id, game_name, line_text, timestamp, game_id, created_at) "
        "VALUES (?,?,?,?,?,?)",
        ("new1", "Test VN", "あいうえお", 1100.0, "g1", "1100.0"),
    )
    con.execute(
        "INSERT INTO game_lines (id, game_name, line_text, timestamp, game_id, created_at) "
        "VALUES (?,?,?,?,?,?)",
        ("new2", "Test VN", "あいうえお", 1200.0, "g1", "1200.0"),  # duplicate text
    )
    con.execute(
        "INSERT INTO game_lines (id, game_name, line_text, timestamp, game_id, created_at) "
        "VALUES (?,?,?,?,?,?)",
        ("new3", "Test VN", "かきくけこ", 1300.0, "g1", "1300.0"),
    )
    if cursor is not None:
        con.execute(
            "INSERT INTO stats_export_state "
            "(format_key, last_successful_export_at, created_at, updated_at) "
            "VALUES (?,?,?,?)",
            (TADOKU_CURSOR_KEY, str(cursor), "1", "1"),
        )
    con.commit()
    con.close()
    return path


@pytest.fixture
def gsm_db(tmp_path, monkeypatch):
    from app.ingest.gsm import PENDING_EXPORT_STATE_KEY
    from app.sheets.state import set_state

    path = _make_gsm_db(tmp_path / "gsm.db")
    monkeypatch.setenv("GSM_DB_PATH", str(path))
    reload_settings()
    # Ensure gsm enabled
    s = get_settings()
    s.yaml_config.gsm.enabled = True
    s.yaml_config.gsm.advance_cursor = True
    s.yaml_config.gsm.db_path = str(path)
    # Shared test_immersion.db may retain local watermark / pending from other tests
    db = _db()
    try:
        set_state(db, LOCAL_CURSOR_KEY, "")
        set_state(db, GAME_CURSORS_KEY, "")
        set_state(db, PENDING_EXPORT_STATE_KEY, "")
    finally:
        db.close()
    yield path
    reload_settings()


def test_clean_text_for_stats_matches_gsm():
    """GSM strips Unicode P/S/Z before counting (tadoku_sync clean_columns)."""
    assert clean_text_for_stats("「あいうえお」") == "あいうえお"
    assert clean_text_for_stats("あ！？…") == "あ"
    assert clean_text_for_stats("hello world") == "helloworld"
    assert clean_text_for_stats("　全角　") == "全角"
    assert clean_text_for_stats("★あ★") == "あ"
    # Prolonged sound mark is a letter modifier (Lm), not punctuation — keep
    assert clean_text_for_stats("あー") == "あー"
    # Off path leaves raw text
    assert clean_text_for_stats("「あ」", strip_punctuation=False) == "「あ」"
    # Optional repetition collapse (GSM regex_out_repetitions, default off)
    assert clean_text_for_stats("あああああ", strip_repetitions=True) == "あああ"


def test_status_and_preview(gsm_db):
    st = get_status()
    assert st.ok
    assert st.line_count == 4
    assert st.cursor == 1000.0

    preview = build_preview(deduplicate=False)
    assert preview["ok"]
    assert preview["strip_punctuation"] is True  # default ON
    assert preview["total_entries"] == 1
    # あいうえお(5) + あいうえお(5) + かきくけこ(5) = 15 (no punctuation in fixture)
    assert preview["total_characters"] == 15
    assert preview["entries"][0]["game_name"] == "Test VN"
    assert preview["entries"][0]["content_type"] == "visual_novel"

    preview_d = build_preview(deduplicate=True)
    # drops second あいうえお → 10 chars
    assert preview_d["total_characters"] == 10
    assert preview_d["duplicates_excluded"] == 1


def test_line_has_japanese():
    assert line_has_japanese("ダルによれば、数日前に")
    assert not line_has_japanese("https://github.com/herdr")
    assert not line_has_japanese("powershell -ExecutionPolicy Bypass")
    assert not line_has_japanese("AGENTS.md\n\n[Skills]")


def test_require_japanese_in_preview(gsm_db):
    """Clipboard/code English lines must not inflate Ready-to-log."""
    junk = "herdr plugin install foo\n" + ("x" * 200)
    con = sqlite3.connect(str(gsm_db))
    con.execute(
        "INSERT INTO game_lines (id, game_name, line_text, timestamp, game_id, created_at) "
        "VALUES (?,?,?,?,?,?)",
        ("junk1", "Test VN", junk, 1400.0, "g1", "1400.0"),
    )
    con.commit()
    con.close()

    raw = build_preview(
        deduplicate=False, strip_punctuation=False, require_japanese=False
    )
    assert raw["total_characters"] == 15 + len(junk)
    assert raw["non_jp_lines"] == 1

    fixed = build_preview(
        deduplicate=False, strip_punctuation=False, require_japanese=True
    )
    assert fixed["total_characters"] == 15
    assert fixed["non_jp_lines"] == 1
    assert fixed["non_jp_chars_removed"] == len(junk)


def test_collapse_repeated_blocks_unit():
    """Within-line mail/hook spam collapses to one copy."""
    unit = "From: ジョン・タイター\r\nSubject: あなたは本物ですか？\r\n" + ("あ" * 80)
    spam = unit * 54
    assert len(spam) > 200
    collapsed = collapse_line_block_repeats(spam)
    assert collapsed == unit
    assert len(collapsed) < len(spam) // 10
    # Alias and normal dialogue
    assert collapse_repeated_blocks(spam) == unit
    assert collapse_line_block_repeats("倫太郎: 「……！」") == "倫太郎: 「……！」"
    assert collapse_line_block_repeats("x" * 100) == "x" * 100


def test_collapse_repeated_blocks_in_preview(gsm_db):
    """Ready-to-log applies collapse so a 54× mail row does not inflate totals."""
    unit = "From: Titor\r\nSubject: hi\r\n" + ("本文" * 40)
    spam = unit * 20
    con = sqlite3.connect(str(gsm_db))
    con.execute(
        "INSERT INTO game_lines (id, game_name, line_text, timestamp, game_id, created_at) "
        "VALUES (?,?,?,?,?,?)",
        ("spam1", "Test VN", spam, 1400.0, "g1", "1400.0"),
    )
    con.commit()
    con.close()

    raw = build_preview(deduplicate=False, strip_punctuation=False, collapse_repeated_blocks=False)
    assert raw["total_characters"] == 15 + len(spam)
    assert raw["collapse_repeated_blocks"] is False
    # Metrics always measured so UI can show “would remove” when toggle is off
    assert raw["block_collapse_lines"] == 1
    assert raw["block_collapse_chars_removed"] == len(spam) - len(unit)

    fixed = build_preview(deduplicate=False, strip_punctuation=False, collapse_repeated_blocks=True)
    assert fixed["total_characters"] == 15 + len(unit)
    assert fixed["block_collapse_lines"] == 1
    assert fixed["block_collapse_chars_removed"] == len(spam) - len(unit)
    # With dedupe + collapse: spam unit matches nothing in fixture unless identical
    both = build_preview(deduplicate=True, strip_punctuation=False, collapse_repeated_blocks=True)
    assert both["total_characters"] == 10 + len(unit)  # fixture drops one あいうえお


def test_strip_punctuation_counts(gsm_db):
    """Punctuation-only inflation is removed when strip is on (GSM match)."""
    con = sqlite3.connect(str(gsm_db))
    con.execute(
        "INSERT INTO game_lines (id, game_name, line_text, timestamp, game_id, created_at) "
        "VALUES (?,?,?,?,?,?)",
        ("punct1", "Test VN", "「あいうえお」！？", 1400.0, "g1", "1400.0"),
    )
    con.commit()
    con.close()

    # Raw: あいうえお×2 + かきくけこ + 「あいうえお」！？
    # 「」(2) + あいうえお(5) + ！？(2) = 9 raw for new line
    raw = build_preview(deduplicate=False, strip_punctuation=False)
    assert raw["total_characters"] == 15 + 9
    assert raw["baseline_characters"] == 15 + 9
    # stripped_characters always reflects GSM strip (independent of toggle)
    assert raw["stripped_characters"] == 15 + 5
    assert raw["characters_removed"] == 0

    stripped = build_preview(deduplicate=False, strip_punctuation=True)
    # stripped new line contributes 5 (あいうえお)
    assert stripped["total_characters"] == 15 + 5
    assert stripped["strip_punctuation"] is True
    assert stripped["baseline_characters"] == 15 + 9
    assert stripped["stripped_characters"] == 15 + 5
    assert stripped["characters_removed"] == 4  # 「」！？

    # Dedupe on cleaned text: 「あいうえお」！？ matches earlier あいうえお
    deduped = build_preview(deduplicate=True, strip_punctuation=True)
    assert deduped["total_characters"] == 10  # second あいうえお + punct variant dropped
    assert deduped["duplicates_excluded"] == 2
    assert deduped["baseline_characters"] == 15 + 9
    # Raw vs Stripped ignores skip-repeats (strip-only comparison)
    assert deduped["stripped_characters"] == 15 + 5
    assert deduped["characters_removed"] == (15 + 9) - 10


def test_counting_prefs_apply_to_preview_and_queue(gsm_db):
    """Saved strip/dedupe prefs apply when preview/queue omit overrides."""
    db = _db()
    try:
        set_prefs(db, deduplicate=True, strip_punctuation=True)
        preview = build_preview(db=db)  # no explicit overrides
        assert preview["deduplicate"] is True
        assert preview["strip_punctuation"] is True
        assert preview["total_characters"] == 10

        result = queue_from_preview(db, submit=False)  # prefs only
        assert result["ok"]
        assert len(result["created"]) == 1
        log = db.get(LogEntry, result["created"][0]["id"])
        assert log is not None
        assert log.amount == 10.0
        assert "dedupe=True" in (log.notes or "")
        assert "strip_punct=True" in (log.notes or "")
    finally:
        db.close()


def test_preview_is_readonly(gsm_db):
    before = gsm_db.read_bytes()
    build_preview()
    get_status()
    after = gsm_db.read_bytes()
    assert before == after


def test_cursor_advance_monotonic(gsm_db):
    r = advance_gsm_cursor(1500.0)
    assert r["ok"] and r["advanced"]
    assert r["cursor"] == 1500.0

    # backward refused
    r2 = advance_gsm_cursor(1200.0)
    assert r2["cursor"] == 1500.0

    preview = build_preview()
    assert preview["total_characters"] == 0


def test_mark_synced_now(gsm_db):
    db = _db()
    try:
        r = mark_synced_now(db)
        assert r["ok"]
        preview = build_preview()
        assert preview["total_characters"] == 0
        # lines still present
        con = sqlite3.connect(str(gsm_db))
        n = con.execute("SELECT COUNT(*) FROM game_lines").fetchone()[0]
        con.close()
        assert n == 4
    finally:
        db.close()


def test_mark_game_synced_only_one_game(gsm_db):
    """Per-game Clear zeros one title; other games stay pending."""
    con = sqlite3.connect(str(gsm_db))
    con.execute(
        "INSERT INTO games (id, title_original, type) VALUES (?,?,?)",
        ("g2", "Other VN", "Visual Novel"),
    )
    con.execute(
        "INSERT INTO game_lines (id, game_name, line_text, timestamp, game_id, created_at) "
        "VALUES (?,?,?,?,?,?)",
        ("o1", "Other VN", "さしすせそ", 1400.0, "g2", "1400.0"),
    )
    con.commit()
    con.close()

    db = _db()
    try:
        before = build_preview(deduplicate=False, db=db)
        assert before["total_entries"] == 2
        r = mark_game_synced(db, "g1")
        assert r["ok"] and r["game_key"] == "g1"
        # g2 still pending → must NOT advance GSM global watermark
        assert r.get("other_games_pending") is True
        assert r.get("advanced_gsm_watermark") is False
        after = build_preview(deduplicate=False, db=db)
        keys = {e["game_key"] for e in after["entries"]}
        assert "g1" not in keys
        assert "g2" in keys
        assert after["entries"][0]["characters"] == 5
        # GSM lines untouched; global cursor unchanged
        con = sqlite3.connect(str(gsm_db))
        n = con.execute("SELECT COUNT(*) FROM game_lines").fetchone()[0]
        cur = con.execute(
            "SELECT last_successful_export_at FROM stats_export_state "
            "WHERE format_key=?",
            (TADOKU_CURSOR_KEY,),
        ).fetchone()[0]
        con.close()
        assert n == 5
        assert float(cur) == 1000.0
    finally:
        db.close()


def test_mark_game_synced_advances_gsm_when_alone(gsm_db):
    """Sole pending game: Clear also moves GSM tadoku_incremental."""
    db = _db()
    try:
        r = mark_game_synced(db, "g1")
        assert r["ok"]
        assert r.get("other_games_pending") is False
        assert r.get("advanced_gsm_watermark") is True
        assert build_preview(deduplicate=False, db=db)["total_characters"] == 0
        con = sqlite3.connect(str(gsm_db))
        cur = float(
            con.execute(
                "SELECT last_successful_export_at FROM stats_export_state "
                "WHERE format_key=?",
                (TADOKU_CURSOR_KEY,),
            ).fetchone()[0]
        )
        n = con.execute("SELECT COUNT(*) FROM game_lines").fetchone()[0]
        con.close()
        assert cur > 1000.0
        assert n == 4
    finally:
        db.close()


def test_queue_game_keys_filters(gsm_db):
    """Manual subset: only selected game_keys become logs."""
    con = sqlite3.connect(str(gsm_db))
    con.execute(
        "INSERT INTO games (id, title_original, type) VALUES (?,?,?)",
        ("g2", "Other VN", "Visual Novel"),
    )
    con.execute(
        "INSERT INTO game_lines (id, game_name, line_text, timestamp, game_id, created_at) "
        "VALUES (?,?,?,?,?,?)",
        ("o1", "Other VN", "さしすせそ", 1400.0, "g2", "1400.0"),
    )
    con.commit()
    con.close()

    db = _db()
    try:
        preview = build_preview(deduplicate=True, db=db)
        assert preview["total_entries"] == 2
        keys = [e["game_key"] for e in preview["entries"]]
        only = keys[0]
        result = queue_from_preview(
            db, deduplicate=True, submit=False, game_keys=[only]
        )
        assert result["ok"]
        assert len(result["created"]) == 1
        assert result["created"][0]["title"] in ("Test VN", "Other VN")
        # The other game is still in the full preview until cursor advances
        assert build_preview(deduplicate=True, db=db)["total_entries"] == 2
    finally:
        db.close()


def test_queue_creates_logs_no_cursor_until_pushed(gsm_db, monkeypatch):
    db = _db()
    try:
        # dry-run tadoku already set by conftest
        result = queue_from_preview(db, deduplicate=True, submit=False)
        assert result["ok"]
        assert len(result["created"]) == 1
        log = db.get(LogEntry, result["created"][0]["id"])
        assert log is not None
        assert log.source == "gsm"
        assert log.unit == "characters"
        assert log.amount == 10.0
        assert log.activity == "reading"
        assert log.tags == "vn"
        assert log.tadoku_status == TadokuStatus.PENDING.value

        # GSM cursor not advanced yet
        preview = build_preview(deduplicate=True, db=db)
        assert preview["total_characters"] == 10

        # Simulate push
        log.tadoku_status = TadokuStatus.PUSHED.value
        log.tadoku_remote_id = "fake-remote"
        db.commit()

        done = try_complete_pending_export(db)
        assert done.get("advanced") is True

        preview2 = build_preview(deduplicate=True, db=db)
        assert preview2["total_characters"] == 0
    finally:
        db.close()


def test_local_cursor_resets_preview_when_gsm_write_fails(gsm_db, monkeypatch):
    """
    After a successful Tadoku push, the GSM panel must clear even if writing
    GSM's tadoku_incremental row fails (Docker bind-mount / file lock).
    """
    db = _db()
    try:
        result = queue_from_preview(db, deduplicate=True, submit=False)
        assert result["ok"] and result["created"]
        log = db.get(LogEntry, result["created"][0]["id"])
        assert log is not None
        log.tadoku_status = TadokuStatus.PUSHED.value
        log.tadoku_remote_id = "fake-remote"
        db.commit()

        def boom(*_a, **_k):
            raise RuntimeError("disk I/O error")

        monkeypatch.setattr(
            "app.ingest.gsm._write_tadoku_cursor",
            boom,
        )

        done = try_complete_pending_export(db)
        assert done.get("advanced") is True
        assert done.get("advanced_local") is True
        assert done.get("advanced_gsm") is False

        # GSM file cursor unchanged
        con = sqlite3.connect(str(gsm_db))
        gsm_cur = float(
            con.execute(
                "SELECT last_successful_export_at FROM stats_export_state "
                "WHERE format_key=?",
                (TADOKU_CURSOR_KEY,),
            ).fetchone()[0]
        )
        con.close()
        assert gsm_cur == 1000.0

        # Local watermark set → preview empty
        local = float(get_state(db, LOCAL_CURSOR_KEY))
        assert local > 1000.0
        preview = build_preview(deduplicate=True, db=db)
        assert preview["total_characters"] == 0
        assert preview["local_cursor"] == local
        assert preview["cursor_sync_pending"] is True

        # Pending batch cleared (not stuck forever)
        finish = finish_pending_export_work(db)
        assert finish["complete"].get("reason") == "no_pending_export"

        # Sync retry still fails while write is broken
        sync = try_sync_cursor_to_gsm(db)
        assert sync.get("synced") is False
        assert sync.get("reason") == "gsm_write_failed"

        # Once write works again, local watermark is pushed into GSM
        monkeypatch.setattr(
            "app.ingest.gsm._write_tadoku_cursor",
            lambda path, new_cursor: float(new_cursor),
        )
        sync2 = try_sync_cursor_to_gsm(db)
        assert sync2.get("synced") is True
    finally:
        db.close()


def test_manual_mode_still_finishes_pending_export(gsm_db, monkeypatch):
    """Scheduler auto-export job used to skip entirely in manual mode."""
    db = _db()
    try:
        set_prefs(db, log_mode="manual")
        result = queue_from_preview(db, deduplicate=True, submit=False)
        log = db.get(LogEntry, result["created"][0]["id"])
        log.tadoku_status = TadokuStatus.PUSHED.value
        log.tadoku_remote_id = "fake-remote"
        db.commit()

        out = process_auto_export(db)
        assert out.get("reason") == "manual_mode"
        assert out.get("finish", {}).get("advanced") is True
        preview = build_preview(deduplicate=True, db=db)
        assert preview["total_characters"] == 0
    finally:
        db.close()


def test_never_deletes_lines_on_cursor_write(gsm_db):
    con = sqlite3.connect(str(gsm_db))
    before = con.execute("SELECT COUNT(*) FROM game_lines").fetchone()[0]
    con.close()
    advance_gsm_cursor(time.time())
    con = sqlite3.connect(str(gsm_db))
    after = con.execute("SELECT COUNT(*) FROM game_lines").fetchone()[0]
    # only cursor row may change
    games = con.execute("SELECT COUNT(*) FROM games").fetchone()[0]
    con.close()
    assert before == after == 4
    assert games == 1


def test_status_missing_db(monkeypatch, tmp_path):
    missing = tmp_path / "nope" / "gsm.db"
    monkeypatch.setenv("GSM_DB_PATH", str(missing))
    reload_settings()
    s = get_settings()
    s.yaml_config.gsm.enabled = True
    s.yaml_config.gsm.db_path = str(missing)
    st = get_status()
    assert not st.ok
    assert not st.exists
    assert "not found" in st.message.lower()
    reload_settings()


def test_auto_prefs_and_filter(gsm_db):
    from app.ingest.gsm import process_auto_export, process_daily_time_export

    db = _db()
    try:
        prefs = set_prefs(
            db,
            log_mode="auto",
            min_submit_characters=100,  # higher than fixture's 10 with dedupe
            auto_submit_idle_minutes=0,
            deduplicate=True,
            strip_punctuation=False,
            auto_log_at_time_enabled=False,
            auto_log_at_hour=4,
        )
        assert prefs["log_mode"] == "auto"
        assert prefs["min_submit_characters"] == 100
        assert prefs["strip_punctuation"] is False
        assert prefs["auto_log_at_time_enabled"] is False
        assert prefs["auto_log_at_hour"] == 4

        # Pref sticks for preview
        preview = build_preview(db=db)
        assert preview["strip_punctuation"] is False

        # Not enough chars → auto export creates nothing
        result = process_auto_export(db)
        assert result.get("ok")
        assert not result.get("created")

        set_prefs(db, min_submit_characters=5, auto_submit_idle_minutes=0)
        result2 = process_auto_export(db)
        assert result2.get("ok")
        assert len(result2.get("created") or []) == 1
        assert result2["created"][0]["amount"] == 10.0

        # Daily off → skip
        daily = process_daily_time_export(db)
        assert daily.get("skipped") and daily.get("reason") == "auto_log_at_time_off"

        # Force daily after cursor advanced by previous auto
        set_prefs(db, auto_log_at_time_enabled=True, min_submit_characters=1)
        # New lines after cursor would be empty — force still ok
        daily2 = process_daily_time_export(db, force=True)
        assert daily2.get("ok") is not False
        assert daily2.get("daily") is True
    finally:
        db.close()
