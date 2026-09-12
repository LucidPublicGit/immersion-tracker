"""
Live Google Sheets views via FILTER/QUERY formulas.

Logs (All) is the only log table the app writes. Type tabs, Tadoku Queue, and
Metrics reference it so the browser updates instantly — no wait for the app.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any, Optional

from app.sheets import enums as E

logger = logging.getLogger(__name__)

# Bump when formula shapes change so ensure re-installs views
FORMULA_VIEWS_VERSION = "2"


def escape_sheet_title(title: str) -> str:
    """Quote a sheet name for use in A1 formulas."""
    t = (title or "").replace("'", "''")
    return f"'{t}'"


def col_letter(col: int) -> str:
    """1-based column index → A, B, …, Z, AA, …"""
    letters = ""
    n = col
    while n:
        n, rem = divmod(n - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def logs_data_range(logs_title: str, *, num_cols: Optional[int] = None) -> str:
    """Open-ended range for log rows (excludes header row 1)."""
    n = num_cols or len(E.LOG_HEADERS)
    end = col_letter(n)
    src = escape_sheet_title(logs_title)
    return f"{src}!A2:{end}"


def type_tab_filter_formula(logs_title: str, content_type: str) -> str:
    """
    Spill all Logs (All) rows where content_type matches.
    content_type is column C (3) in LOG_HEADERS.
    """
    src = escape_sheet_title(logs_title)
    n = len(E.LOG_HEADERS)
    end = col_letter(n)
    ct = (content_type or "").replace('"', '""')
    # FILTER over open ranges; IFERROR → blank when no matches
    return (
        f'=IFERROR(FILTER({src}!A2:{end},{src}!C2:C="{ct}"),"")'
    )


def tadoku_title_array_expr(logs_title: str) -> str:
    """
    ARRAYFORMULA expression matching app.media.title_format.tadoku_title
    (title + optional SxxExx), relative to Logs sheet columns D/E/F.
    """
    src = escape_sheet_title(logs_title)
    # D=title E=season F=episode
    return (
        f'IF({src}!D2:D="","",'
        f'{src}!D2:D&'
        f'IF(({src}!E2:E<>"")*({src}!F2:F<>""),'
        f'" S"&TEXT({src}!E2:E,"00")&"E"&TEXT({src}!F2:F,"00"),'
        f'IF({src}!E2:E<>""," S"&TEXT({src}!E2:E,"00"),'
        f'IF({src}!F2:F<>""," E"&TEXT({src}!F2:F,"00"),""))))'
    )


def queue_filter_formula(logs_title: str) -> str:
    """
    Actionable Tadoku queue as a live view of Logs (All).

    Columns (QUEUE_HEADERS):
      id, timestamp, title, season, episode, tadoku_title, content_type,
      amount, unit, score, tadoku_mode, tadoku_status, remote_id

    remote_id is blank in the formula view (not on Logs); status/mode edits
    belong on Logs (All) so they do not require a mirrored Queue write.
    Shows pending / ready / failed only (same as Queue UI).
    """
    src = escape_sheet_title(logs_title)
    title_expr = tadoku_title_array_expr(logs_title)
    # HSTACK columns then FILTER by status (M = tadoku_status)
    # Note: ARRAYFORMULA wraps the constructed tadoku_title column.
    return (
        f"=IFERROR(FILTER("
        f"HSTACK("
        f"{src}!A2:A,"  # id
        f"{src}!B2:B,"  # timestamp
        f"{src}!D2:D,"  # title
        f"{src}!E2:E,"  # season
        f"{src}!F2:F,"  # episode
        f"ARRAYFORMULA({title_expr}),"  # tadoku_title
        f"{src}!C2:C,"  # content_type
        f"{src}!I2:I,"  # amount
        f"{src}!J2:J,"  # unit
        f"{src}!N2:N,"  # score
        f"{src}!L2:L,"  # tadoku_mode
        f"{src}!M2:M,"  # tadoku_status
        f'ARRAYFORMULA(IF({src}!A2:A="","","")),'  # remote_id (edit via Logs / API)
        f"),"
        f'({src}!M2:M="pending")+({src}!M2:M="ready")+({src}!M2:M="failed")'
        f'),"")'
    )


def metrics_formula_rows(logs_title: str) -> list[list[str]]:
    """Static labels + formulas for the Metrics tab."""
    src = escape_sheet_title(logs_title)
    # A=id C=content_type I=amount J=unit M=status N=score
    rows: list[list[str]] = [
        ["metric", "value"],
        ["total_logs", f'=COUNTA({src}!A2:A)'],
        ["total_minutes", f'=SUMIF({src}!J:J,"minutes",{src}!I:I)'],
        ["tadoku_score_estimate", f'=SUM({src}!N2:N)'],
        ["tadoku_pending", f'=COUNTIF({src}!M:M,"pending")'],
        ["tadoku_ready", f'=COUNTIF({src}!M:M,"ready")'],
        ["tadoku_pushed", f'=COUNTIF({src}!M:M,"pushed")'],
        [],
        ["content_type", "label", "count", "amount_sum"],
    ]
    for ct in E.content_types():
        label = E.CONTENT_TYPE_LABELS.get(ct, ct)
        ct_esc = ct.replace('"', '""')
        rows.append(
            [
                ct,
                label,
                f'=COUNTIF({src}!C:C,"{ct_esc}")',
                f'=SUMIF({src}!C:C,"{ct_esc}",{src}!I:I)',
            ]
        )
    return rows


def _normalize_formula(s: Any) -> str:
    """Loose compare so cosmetic spacing differences do not force rewrites."""
    if s is None:
        return ""
    return re.sub(r"\s+", "", str(s).strip())


def _read_a1_formula(ws, a1: str = "A2") -> str:
    try:
        # gspread: value_render_option FORMULA returns the formula text
        cell = ws.acell(a1, value_render_option="FORMULA")
        if not cell or cell.value is None:
            return ""
        return str(cell.value)
    except Exception:  # noqa: BLE001
        try:
            vals = ws.get(a1, value_render_option="FORMULA")
            if vals and vals[0] and vals[0][0] is not None:
                return str(vals[0][0])
        except Exception:  # noqa: BLE001
            pass
    return ""


def _headers_match(ws, expected: list[str]) -> bool:
    try:
        row = ws.row_values(1)
    except Exception:  # noqa: BLE001
        return False
    got = [str(h or "").strip().lower() for h in row]
    want = [str(h or "").strip().lower() for h in expected]
    # allow extra trailing columns; require prefix match
    if len(got) < len(want):
        return False
    return got[: len(want)] == want


def _install_header_and_formula(
    ws,
    headers: list[str],
    formula: str,
    *,
    clear_first: bool = True,
) -> bool:
    """
    Write header row + formula in A2. Returns True if a Google write happened.
    """
    existing = _read_a1_formula(ws, "A2")
    headers_ok = _headers_match(ws, headers)
    if headers_ok and _normalize_formula(existing) == _normalize_formula(formula):
        return False

    def _do() -> None:
        if clear_first and not (
            headers_ok and existing.startswith("=")
        ):
            # Full clear only when migrating from dumped values → formula
            try:
                ws.clear()
            except Exception:  # noqa: BLE001
                pass
        ws.update("A1", [headers], value_input_option="USER_ENTERED")
        ws.update("A2", [[formula]], value_input_option="USER_ENTERED")
        try:
            ws.freeze(rows=1)
        except Exception:  # noqa: BLE001
            pass

    from app.sheets.sync import _with_retry

    _with_retry(_do)
    time.sleep(0.5)
    return True


def _install_metrics_formulas(ws, logs_title: str) -> bool:
    rows = metrics_formula_rows(logs_title)
    # Compare first formula cell
    existing = _read_a1_formula(ws, "B2")
    expected_b2 = rows[1][1] if len(rows) > 1 else ""
    if _normalize_formula(existing) == _normalize_formula(expected_b2):
        # Still check content_type block exists
        try:
            a9 = str(ws.acell("A9").value or "").strip().lower()
            if a9 == "content_type":
                return False
        except Exception:  # noqa: BLE001
            pass

    def _do() -> None:
        try:
            ws.clear()
        except Exception:  # noqa: BLE001
            pass
        ws.update("A1", rows, value_input_option="USER_ENTERED")
        try:
            ws.freeze(rows=1)
        except Exception:  # noqa: BLE001
            pass

    from app.sheets.sync import _with_retry

    _with_retry(_do)
    time.sleep(0.5)
    return True


def ensure_formula_views(
    client,
    *,
    logs_title: Optional[str] = None,
    force: bool = False,
    type_tabs: bool = True,
    queue: bool = True,
    metrics: bool = True,
    db: Any = None,
) -> dict[str, Any]:
    """
    Install / refresh FILTER views. Idempotent — skips tabs already correct.

    Call once per push cycle. Does not write log row data (Logs (All) only).
    When db is provided and views match FORMULA_VIEWS_VERSION, skips entirely
    (no API) until force=True or version bump.
    """
    if not client or not getattr(client, "enabled", False):
        return {"ok": False, "reason": "sheets_disabled"}

    from app.core.config import get_settings

    cfg = get_settings().yaml_config.sheets
    logs_title = logs_title or cfg.tabs.get("logs", "Logs (All)")
    state_key = f"formula_views:{FORMULA_VIEWS_VERSION}:{logs_title}"

    if db is not None and not force:
        try:
            from app.sheets.state import get_state

            if get_state(db, state_key) == "1":
                return {
                    "ok": True,
                    "skipped": True,
                    "cached": True,
                    "logs_title": logs_title,
                    "version": FORMULA_VIEWS_VERSION,
                }
        except Exception:  # noqa: BLE001
            pass

    result: dict[str, Any] = {
        "ok": True,
        "logs_title": logs_title,
        "version": FORMULA_VIEWS_VERSION,
        "type_tabs": {},
        "queue": None,
        "metrics": None,
    }

    # --- Per-type log views ---
    if type_tabs:
        for ct in E.content_types():
            title = E.type_tab_title(ct)
            formula = type_tab_filter_formula(logs_title, ct)
            try:
                ws = client.worksheet_by_title(
                    title, rows=2000, cols=len(E.LOG_HEADERS) + 2
                )
                if not ws:
                    result["type_tabs"][ct] = {"ok": False, "reason": "no_worksheet"}
                    continue
                existing = "" if force else _read_a1_formula(ws, "A2")
                wrote = False
                if force or _normalize_formula(existing) != _normalize_formula(
                    formula
                ):
                    wrote = _install_header_and_formula(
                        ws, E.LOG_HEADERS, formula, clear_first=True
                    )
                elif not _headers_match(ws, E.LOG_HEADERS):
                    wrote = _install_header_and_formula(
                        ws, E.LOG_HEADERS, formula, clear_first=False
                    )
                result["type_tabs"][ct] = {
                    "ok": True,
                    "tab": title,
                    "written": wrote,
                    "skipped": not wrote,
                }
            except Exception as exc:  # noqa: BLE001
                logger.warning("formula type tab %s failed: %s", title, exc)
                result["type_tabs"][ct] = {"ok": False, "error": str(exc)}

    # --- Tadoku Queue view ---
    if queue:
        try:
            ws = client.worksheet("queue")
            if ws:
                formula = queue_filter_formula(logs_title)
                existing = "" if force else _read_a1_formula(ws, "A2")
                if force or _normalize_formula(existing) != _normalize_formula(
                    formula
                ):
                    wrote = _install_header_and_formula(
                        ws, E.QUEUE_HEADERS, formula, clear_first=True
                    )
                else:
                    wrote = False
                result["queue"] = {
                    "ok": True,
                    "written": wrote,
                    "skipped": not wrote,
                }
            else:
                result["queue"] = {"ok": False, "reason": "no_worksheet"}
        except Exception as exc:  # noqa: BLE001
            logger.warning("formula queue failed: %s", exc)
            result["queue"] = {"ok": False, "error": str(exc)}

    # --- Metrics ---
    if metrics:
        try:
            ws = client.worksheet("metrics")
            if ws:
                wrote = _install_metrics_formulas(ws, logs_title)
                result["metrics"] = {
                    "ok": True,
                    "written": wrote,
                    "skipped": not wrote,
                }
            else:
                result["metrics"] = {"ok": False, "reason": "no_worksheet"}
        except Exception as exc:  # noqa: BLE001
            logger.warning("formula metrics failed: %s", exc)
            result["metrics"] = {"ok": False, "error": str(exc)}

    # Only cache success when every requested section is ok (retry partial fails)
    all_ok = True
    if type_tabs:
        for info in (result.get("type_tabs") or {}).values():
            if not info.get("ok"):
                all_ok = False
                break
    if queue and result.get("queue") and not result["queue"].get("ok"):
        all_ok = False
    if metrics and result.get("metrics") and not result["metrics"].get("ok"):
        all_ok = False

    if db is not None and all_ok:
        try:
            from app.sheets.state import set_state

            set_state(db, state_key, "1")
        except Exception:  # noqa: BLE001
            pass
    result["cached_ok"] = all_ok

    return result
