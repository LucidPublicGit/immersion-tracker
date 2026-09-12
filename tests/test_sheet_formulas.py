"""Unit tests for sheet formula builders (no Google API)."""

from app.sheets import enums as E
from app.sheets.formulas import (
    col_letter,
    escape_sheet_title,
    metrics_formula_rows,
    queue_filter_formula,
    type_tab_filter_formula,
)


def test_escape_sheet_title():
    assert escape_sheet_title("Logs (All)") == "'Logs (All)'"
    assert escape_sheet_title("O'Brien") == "'O''Brien'"


def test_col_letter():
    assert col_letter(1) == "A"
    assert col_letter(3) == "C"
    assert col_letter(26) == "Z"
    assert col_letter(27) == "AA"


def test_type_tab_filter_targets_content_type_column():
    f = type_tab_filter_formula("Logs (All)", "anime")
    assert f.startswith("=")
    assert "FILTER" in f
    assert "Logs (All)" in f
    assert '="anime"' in f
    # content_type is column C
    assert "!C2:C" in f
    end = col_letter(len(E.LOG_HEADERS))
    assert f"!A2:{end}" in f or f"A2:{end}" in f


def test_queue_filter_actionable_statuses():
    f = queue_filter_formula("Logs (All)")
    assert "FILTER" in f
    assert "HSTACK" in f
    assert "pending" in f
    assert "ready" in f
    assert "failed" in f
    # tadoku_title uses season/episode columns E/F
    assert "TEXT" in f


def test_metrics_formulas_reference_logs():
    rows = metrics_formula_rows("Logs (All)")
    assert rows[0] == ["metric", "value"]
    assert rows[1][0] == "total_logs"
    assert rows[1][1].startswith("=")
    assert "COUNTA" in rows[1][1]
    assert any(r and r[0] == "anime" for r in rows)
