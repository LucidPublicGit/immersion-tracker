from __future__ import annotations

import logging
import time
from collections import defaultdict
from collections.abc import Callable
from typing import Any, Optional, TypeVar

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import CatalogItem, LogEntry, TadokuStatus
from app.ingest.service import DuplicateLogError, create_log
from app.media.work_identity import prepare_log_identity
from app.sheets import enums as E
from app.sheets.merge import apply_log_fields, is_delete_row, row_to_dict
from app.sheets.state import (
    clear_sheets_dirty,
    get_push_hash,
    is_row_local_ahead,
    is_sheets_dirty,
    mark_sheets_dirty,
    rows_content_hash,
    set_last_push_at,
    set_push_hash,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")


def _with_retry(fn: Callable[[], T], *, attempts: int = 8, base_delay: float = 5.0) -> T:
    """Retry on Google Sheets 429 quota errors (60 write/min/user is easy to blow)."""
    last: Exception | None = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            msg = str(exc)
            last = exc
            if "429" in msg or "Quota exceeded" in msg or "RATE_LIMIT" in msg:
                delay = min(base_delay * (2**i), 90.0)
                logger.warning("Sheets quota/rate limit; sleeping %.1fs (%s)", delay, msg[:120])
                time.sleep(delay)
                continue
            raise
    assert last is not None
    raise last


# Re-apply dropdowns at most once per hour (each tab = many writes → 429s)
_last_validation_mono: float = 0.0
_VALIDATION_INTERVAL_S = 3600.0

# Reuse authenticated client across scheduler ticks (auth is expensive; sleep is free)
_client_mono: float = 0.0
_client_instance: Optional["SheetsClient"] = None
_CLIENT_TTL_S = 600.0


def _should_apply_validations(*, force: bool = False) -> bool:
    global _last_validation_mono
    if force:
        _last_validation_mono = time.monotonic()
        return True
    now = time.monotonic()
    if now - _last_validation_mono >= _VALIDATION_INTERVAL_S:
        _last_validation_mono = now
        return True
    return False


def get_sheets_client(*, force_new: bool = False) -> "SheetsClient":
    """Cached SheetsClient — avoids re-auth every 20–60s poll."""
    global _client_mono, _client_instance
    now = time.monotonic()
    if (
        not force_new
        and _client_instance is not None
        and (now - _client_mono) < _CLIENT_TTL_S
    ):
        return _client_instance
    _client_instance = SheetsClient()
    _client_mono = now
    return _client_instance


SHEETS_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def _load_credentials(settings, cfg):
    """
    Resolve Google credentials.

    Order:
      1. GOOGLE_SERVICE_ACCOUNT_JSON env
      2. service_account_file (if the path exists)
      3. oauth_token_file (user OAuth — works when org blocks SA keys)
    """
    from pathlib import Path

    if settings.google_service_account_json:
        import json

        from google.oauth2.service_account import Credentials as SACreds

        info = json.loads(settings.google_service_account_json)
        return SACreds.from_service_account_info(info, scopes=SHEETS_SCOPES), "service_account_env"

    sa_path = (cfg.service_account_file or "").strip()
    if sa_path and Path(sa_path).is_file():
        from google.oauth2.service_account import Credentials as SACreds

        return SACreds.from_service_account_file(sa_path, scopes=SHEETS_SCOPES), "service_account_file"

    for candidate in (
        Path("data/google-service-account.json"),
        Path("/app/data/google-service-account.json"),
    ):
        if candidate.is_file():
            from google.oauth2.service_account import Credentials as SACreds

            return (
                SACreds.from_service_account_file(str(candidate), scopes=SHEETS_SCOPES),
                "service_account_file",
            )

    token_path = Path(
        (cfg.oauth_token_file or "").strip() or "data/google-oauth-token.json"
    )
    if not token_path.is_file():
        for candidate in (
            Path("data/google-oauth-token.json"),
            Path("/app/data/google-oauth-token.json"),
        ):
            if candidate.is_file():
                token_path = candidate
                break

    if token_path.is_file():
        import json

        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials as UserCreds

        data = json.loads(token_path.read_text(encoding="utf-8"))
        creds = UserCreds.from_authorized_user_info(data, SHEETS_SCOPES)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            token_path.write_text(creds.to_json(), encoding="utf-8")
        return creds, "oauth_user"

    return None, None


class SheetsClient:
    """Thin wrapper; no-op when sheets disabled or gspread unavailable."""

    def __init__(self) -> None:
        self._gc = None
        self._sh = None
        self.enabled = False
        self.auth_mode: Optional[str] = None
        self._init()

    def _init(self) -> None:
        settings = get_settings()
        cfg = settings.yaml_config.sheets
        if not cfg.enabled or not cfg.spreadsheet_id:
            return
        try:
            import gspread  # noqa: F401
        except ImportError:
            logger.warning("gspread/google-auth not available")
            return

        try:
            creds, mode = _load_credentials(settings, cfg)
        except Exception:
            logger.exception("Failed to load Google credentials")
            return

        if not creds:
            logger.warning(
                "Sheets enabled but no credentials. Options: "
                "(1) service account JSON if your org allows keys, "
                "(2) OAuth user token — run: python scripts/google_oauth_login.py "
                "See docs/GOOGLE_SHEETS.md"
            )
            return

        try:
            import gspread

            self._gc = gspread.authorize(creds)
            self._sh = self._gc.open_by_key(cfg.spreadsheet_id)
            self.enabled = True
            self.auth_mode = mode
            logger.info("Google Sheets connected via %s", mode)
        except Exception:
            logger.exception("Failed to open spreadsheet %s", cfg.spreadsheet_id)

    def worksheet(self, tab_key_or_title: str, *, create: bool = True):
        """Open by config tab key or exact title."""
        if not self.enabled or not self._sh:
            return None
        tabs = get_settings().yaml_config.sheets.tabs
        name = tabs.get(tab_key_or_title, tab_key_or_title)
        try:
            return self._sh.worksheet(name)
        except Exception:
            if not create:
                return None
            return self._sh.add_worksheet(title=name, rows=2000, cols=20)

    def worksheet_by_title(self, title: str, *, rows: int = 2000, cols: int = 16):
        if not self.enabled or not self._sh:
            return None

        def _open():
            try:
                return self._sh.worksheet(title)
            except Exception:
                time.sleep(0.4)  # soft spacing between creates
                return self._sh.add_worksheet(title=title, rows=rows, cols=cols)

        return _with_retry(_open)


def gspread_cell(row: int, col: int) -> str:
    letters = ""
    n = col
    while n:
        n, rem = divmod(n - 1, 26)
        letters = chr(65 + rem) + letters
    return f"{letters}{row}"


def _col_letter(col: int) -> str:
    return gspread_cell(1, col)[:-1]  # strip row "1"


def _clear_all_validations(ws, *, max_rows: int = 2000, max_cols: int = 24) -> None:
    """
    Remove every data-validation rule on the sheet.
    Important after column layout changes (e.g. season/episode inserted);
    otherwise old 'unit' dropdowns stick on the wrong column.
    """
    try:
        sheet_id = ws.id
        # Google API: setDataValidation without a rule clears validation in range
        req = {
            "requests": [
                {
                    "setDataValidation": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": 0,
                            "endRowIndex": max_rows,
                            "startColumnIndex": 0,
                            "endColumnIndex": max_cols,
                        }
                    }
                }
            ]
        }
        _with_retry(lambda: ws.spreadsheet.batch_update(req))
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "clear validations failed on %s: %s", getattr(ws, "title", "?"), exc
        )


def _header_index_map(ws) -> dict[str, int]:
    """Map lowercased header name -> 1-based column index from row 1."""
    try:
        row = ws.row_values(1)
    except Exception:  # noqa: BLE001
        return {}
    out: dict[str, int] = {}
    for i, h in enumerate(row, start=1):
        key = (h or "").strip().lower()
        if key and key not in out:
            out[key] = i
    return out


def _apply_list_validation(ws, col_index: int, values: list[str], max_row: int = 2000) -> None:
    """Dropdown for a 1-based column on rows 2..max_row."""
    if not values or col_index < 1:
        return
    try:
        from gspread.utils import ValidationConditionType
    except ImportError:
        return

    clean = [str(v) for v in values if v is not None and str(v) != ""]
    if not clean:
        return
    col = _col_letter(col_index)
    cell_range = f"{col}2:{col}{max_row}"
    try:
        _with_retry(
            lambda: ws.add_validation(
                cell_range,
                ValidationConditionType.one_of_list,
                clean,
                showCustomUi=True,
                strict=False,  # allow blank (e.g. tadoku_override inherit)
            )
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "dropdown validation failed on %s %s: %s",
            getattr(ws, "title", "?"),
            cell_range,
            exc,
        )


def _apply_number_validation(ws, col_index: int, max_row: int = 2000) -> None:
    """Allow integers (and blank) for season/episode — not a dropdown."""
    if col_index < 1:
        return
    try:
        from gspread.utils import ValidationConditionType
    except ImportError:
        return
    col = _col_letter(col_index)
    cell_range = f"{col}2:{col}{max_row}"
    try:
        # Whole number >= 0; blank still allowed with strict=False
        ws.add_validation(
            cell_range,
            ValidationConditionType.number_greater_than_or_equal,
            [0],
            showCustomUi=True,
            strict=False,
        )
    except Exception as exc:  # noqa: BLE001
        # Fallback: leave free-text integer entry with no rule
        logger.debug(
            "number validation failed on %s %s: %s",
            getattr(ws, "title", "?"),
            cell_range,
            exc,
        )


def _apply_dropdowns_by_header(
    ws,
    dropdowns: dict[str, list[str]],
    *,
    number_cols: tuple[str, ...] = ("season", "episode"),
) -> None:
    """
    Clear old rules, then attach dropdowns using *current* header names.
    Never hard-code column letters so layout changes cannot mis-assign unit → episode.
    """
    _clear_all_validations(ws)
    headers = _header_index_map(ws)
    if not headers:
        return
    for name, values in dropdowns.items():
        col = headers.get(name.lower())
        if col:
            _apply_list_validation(ws, col, values)
    for name in number_cols:
        col = headers.get(name.lower())
        if col:
            _apply_number_validation(ws, col)


def _write_rows(
    ws,
    rows: list[list[Any]],
    *,
    apply_freeze: bool = True,
    db: Optional[Session] = None,
    tab_key: Optional[str] = None,
    force: bool = False,
) -> dict[str, Any]:
    """
    Overwrite sheet data. Prefer single update over clear+update when possible.

    When db + tab_key are provided, skip the Google write if the payload hash
    matches the last successful push (saves quota + avoids stomping mid-edit
    when nothing in the DB actually changed).
    """
    safe = [[("" if c is None else c) for c in row] for row in rows] if rows else []
    # Hash the *logical* data only (not wipe-pad blanks) so pad size never forces rewrites.
    digest = rows_content_hash(safe)
    if db is not None and tab_key and not force:
        if get_push_hash(db, tab_key) == digest:
            logger.debug("skip write %s (hash match)", tab_key)
            return {"written": False, "skipped": True, "hash": digest}

    def _do() -> None:
        if not safe:
            ws.clear()
            return
        # Pad a few blank rows so old longer content is wiped without a full clear
        # (clear + update = 2 write quota units per tab).
        pad = max(5, min(20, len(safe)))
        width = max(len(r) for r in safe)
        blank = [""] * width
        payload = safe + [blank] * pad
        ws.update("A1", payload, value_input_option="USER_ENTERED")
        if apply_freeze:
            try:
                ws.freeze(rows=1)
            except Exception:  # noqa: BLE001
                pass

    _with_retry(_do)
    if db is not None and tab_key:
        set_push_hash(db, tab_key, digest)
    # Soft spacing only when we actually wrote (hash skips write nothing)
    time.sleep(0.6)
    return {"written": True, "skipped": False, "hash": digest}


def ensure_enums_sheet(
    client: SheetsClient,
    *,
    force: bool = False,
    db: Optional[Session] = None,
) -> dict[str, Any]:
    """
    Reference tab for enum lists. Skips rewrite when already present (saves quota).
    """
    ws = client.worksheet_by_title("Enums", rows=50, cols=12)
    if not ws:
        return {"ok": False}

    columns: list[list[str]] = [
        ["content_type", *E.content_types()],
        ["activity", *E.ACTIVITIES],
        ["unit", *E.UNITS],
        ["tadoku_mode", *E.TADOKU_MODES],
        ["tadoku_override", "auto", "pending", "never"],
        ["tadoku_status", *E.TADOKU_STATUSES],
        ["source", *E.SOURCES],
        ["imported", *E.IMPORTED_FLAGS],
    ]
    if not force:
        try:
            existing = _with_retry(lambda: ws.row_values(1))
            if existing and existing[0].strip().lower() == "content_type":
                return {"ok": True, "skipped": True, "columns": [c[0] for c in columns]}
        except Exception:  # noqa: BLE001
            pass

    max_len = max(len(c) for c in columns)
    rows: list[list[str]] = []
    for i in range(max_len):
        row = []
        for col in columns:
            row.append(col[i] if i < len(col) else "")
        rows.append(row)
    wr = _write_rows(ws, rows, db=db, tab_key="enums", force=force)
    return {"ok": True, "columns": [c[0] for c in columns], **wr}


def _log_row(e: LogEntry) -> list[Any]:
    return [
        e.id,
        e.timestamp.isoformat() if e.timestamp else "",
        e.content_type,
        e.title,
        e.season if e.season is not None else "",
        e.episode if e.episode is not None else "",
        e.series_key or "",
        e.source,
        e.amount,
        e.unit,
        e.activity,
        e.tadoku_mode,
        e.tadoku_status,
        e.tadoku_score_estimate,
        e.watch_ratio if e.watch_ratio is not None else "",
        e.notes or "",
    ]


def _apply_log_validations(ws) -> None:
    _apply_dropdowns_by_header(
        ws,
        {
            "content_type": E.content_types(),
            "source": E.SOURCES,
            "unit": E.UNITS,
            "activity": E.ACTIVITIES,
            "tadoku_mode": E.TADOKU_MODES,
            "tadoku_status": E.TADOKU_STATUSES,
        },
        number_cols=("season", "episode"),
    )


def _apply_manual_validations(ws) -> None:
    _apply_dropdowns_by_header(
        ws,
        {
            "content_type": E.content_types(),
            "unit": E.UNITS,
            "activity": E.ACTIVITIES,
            "imported": E.IMPORTED_FLAGS,
        },
        number_cols=("season", "episode"),
    )


def _apply_catalog_validations(ws) -> None:
    """Dropdowns for Catalog: content_type, tadoku_override, default_unit."""
    _apply_dropdowns_by_header(
        ws,
        {
            "content_type": E.content_types(),
            # blank cell = inherit (strict=False allows empty outside the list)
            "tadoku_override": ["auto", "pending", "never"],
            "default_unit": E.UNITS,
        },
        number_cols=(),
    )


def _apply_queue_validations(ws) -> None:
    _apply_dropdowns_by_header(
        ws,
        {
            "content_type": E.content_types(),
            "unit": E.UNITS,
            "tadoku_mode": E.TADOKU_MODES,
            "tadoku_status": E.TADOKU_STATUSES,
        },
        number_cols=("season", "episode"),
    )


def _sort_key_content_type(ct: str) -> tuple[int, str]:
    try:
        return (E.CONTENT_TYPE_ORDER.index(ct), ct)
    except ValueError:
        return (len(E.CONTENT_TYPE_ORDER), ct)


def _master_logs_worksheet(client: SheetsClient):
    """Prefer Logs (All); migrate legacy 'Logs' tab title if present."""
    if not client.enabled or not client._sh:
        return None
    target = get_settings().yaml_config.sheets.tabs.get("logs", "Logs (All)")
    try:
        return client._sh.worksheet(target)
    except Exception:
        pass
    try:
        legacy = client._sh.worksheet("Logs")
        if target != "Logs":
            legacy.update_title(target)
        return legacy
    except Exception:
        return client.worksheet_by_title(target)


def _formula_views_enabled() -> bool:
    return bool(get_settings().yaml_config.sheets.formula_views)


def push_logs(
    db: Session,
    client: Optional[SheetsClient] = None,
    *,
    apply_validations: bool = False,
    push_type_tabs: bool = True,
    force: bool = False,
) -> dict[str, Any]:
    """
    Write:
      - Logs (All): every log, sorted by content_type then id
      - Logs · * : either live FILTER formulas (formula_views) or dumped rows

    With formula_views (default), type tabs are not row-copied — they FILTER
    Logs (All) in the browser, so they update the moment the master tab does.
    """
    client = client or get_sheets_client()
    if not client.enabled:
        return {"ok": False, "reason": "sheets_disabled"}

    entries = db.query(LogEntry).order_by(LogEntry.id.asc()).all()
    by_type: dict[str, list[LogEntry]] = defaultdict(list)
    for e in entries:
        by_type[e.content_type].append(e)

    sorted_entries = sorted(
        entries,
        key=lambda e: (_sort_key_content_type(e.content_type), e.id),
    )
    master_rows: list[list[Any]] = [E.LOG_HEADERS]
    for e in sorted_entries:
        master_rows.append(_log_row(e))

    ws_all = _master_logs_worksheet(client)
    if not ws_all:
        return {"ok": False, "reason": "no_worksheet"}

    writes = 0
    skips = 0
    wr = _write_rows(
        ws_all, master_rows, db=db, tab_key="logs_all", force=force
    )
    if wr.get("written"):
        writes += 1
    else:
        skips += 1
    # Master tab reached successfully — local log edits are now on (or already on) sheet
    set_last_push_at(db, "logs")
    if apply_validations:
        try:
            _apply_log_validations(ws_all)
        except Exception as exc:  # noqa: BLE001
            logger.warning("log validations skipped: %s", exc)

    type_counts: dict[str, int] = {ct: len(items) for ct, items in by_type.items()}
    type_writes = 0
    formula_mode = _formula_views_enabled()
    master_title = getattr(ws_all, "title", "Logs (All)")

    if formula_mode:
        # Type tabs are FILTER formulas (installed by ensure_formula_views in push cycle)
        return {
            "ok": True,
            "rows": len(master_rows) - 1,
            "by_type": type_counts,
            "master_tab": master_title,
            "validations": apply_validations,
            "writes": writes,
            "skips": skips,
            "type_writes": 0,
            "formula_views": True,
        }

    # Legacy: dump type-tab row copies (hash-skipped when unchanged)
    if push_type_tabs:
        for ct in sorted(by_type.keys(), key=_sort_key_content_type):
            items = by_type[ct]
            title = E.type_tab_title(ct)
            ws = client.worksheet_by_title(title) if items else None
            if not ws and client._sh:
                try:
                    ws = client._sh.worksheet(title)
                except Exception:
                    ws = None
            if not ws:
                continue
            rows = [E.LOG_HEADERS] + [_log_row(e) for e in items]
            tw = _write_rows(
                ws,
                rows,
                apply_freeze=True,
                db=db,
                tab_key=f"logs_type:{ct}",
                force=force,
            )
            if tw.get("written"):
                type_writes += 1
                writes += 1
            else:
                skips += 1

    return {
        "ok": True,
        "rows": len(master_rows) - 1,
        "by_type": type_counts,
        "master_tab": master_title,
        "validations": apply_validations,
        "writes": writes,
        "skips": skips,
        "type_writes": type_writes,
        "formula_views": False,
    }


def push_queue(
    db: Session,
    client: Optional[SheetsClient] = None,
    *,
    apply_validations: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    """
    Tadoku Queue tab.

    formula_views (default): live FILTER of Logs (All) for pending/ready/failed.
    Instant browser update; edit tadoku_mode/status on Logs (All) instead.
    Legacy mode: dump rows from SQLite (hash-skipped when unchanged).
    """
    client = client or get_sheets_client()
    if not client.enabled:
        return {"ok": False, "reason": "sheets_disabled"}

    if _formula_views_enabled():
        # Formula installed once via push_db_to_sheets → ensure_formula_views
        return {
            "ok": True,
            "formula_views": True,
            "written": False,
            "skipped": True,
            "validations": False,
            "rows": None,
            "note": "edit tadoku fields on Logs (All); Queue is a live FILTER view",
        }

    ws = client.worksheet("queue")
    if not ws:
        return {"ok": False, "reason": "no_worksheet"}
    rows: list[list[Any]] = [E.QUEUE_HEADERS]
    from app.media.title_format import tadoku_title

    for e in (
        db.query(LogEntry)
        .order_by(LogEntry.timestamp.desc())
        .limit(2000)
        .all()
    ):
        rows.append(
            [
                e.id,
                e.timestamp.isoformat() if e.timestamp else "",
                e.title,
                e.season if e.season is not None else "",
                e.episode if e.episode is not None else "",
                tadoku_title(e.title, season=e.season, episode=e.episode),
                e.content_type,
                e.amount,
                e.unit,
                e.tadoku_score_estimate,
                e.tadoku_mode,
                e.tadoku_status,
                e.tadoku_remote_id or "",
            ]
        )
    wr = _write_rows(ws, rows, db=db, tab_key="queue", force=force)
    if apply_validations:
        try:
            _apply_queue_validations(ws)
        except Exception as exc:  # noqa: BLE001
            logger.warning("queue validations skipped: %s", exc)
    return {
        "ok": True,
        "rows": len(rows) - 1,
        "validations": apply_validations,
        "formula_views": False,
        **wr,
    }


def _pull_log_rows_from_values(
    db: Session,
    values: list[list[str]],
    *,
    allow_create: bool,
) -> dict[str, int | list[str]]:
    """Shared apply logic for Logs (All) and Logs · Type tabs."""
    updated = created = deleted = 0
    skipped_local = 0
    errors: list[str] = []
    if not values or len(values) < 2:
        return {
            "updated": updated,
            "created": created,
            "deleted": deleted,
            "skipped_local": skipped_local,
            "errors": errors,
        }

    headers = [h.strip().lower() for h in values[0]]
    if "title" not in headers:
        return {
            "updated": 0,
            "created": 0,
            "deleted": 0,
            "skipped_local": 0,
            "errors": ["bad_headers"],
        }

    for row in values[1:]:
        data = row_to_dict(headers, row)
        id_raw = (data.get("id") or "").strip()
        title = (data.get("title") or "").strip()
        amount_s = (data.get("amount") or "").strip()

        if id_raw:
            try:
                log_id = int(float(id_raw))
            except ValueError:
                errors.append(f"bad_id:{id_raw}")
                continue
            entry = db.get(LogEntry, log_id)
            if not entry:
                # Stale sheet row after DB delete — ignore
                continue
            if is_delete_row(data):
                db.delete(entry)
                deleted += 1
                continue
            # Local API/UI edits (relink, approve, …) win until next successful push.
            # Otherwise frequent sheet polls re-apply stale English titles / modes.
            if is_row_local_ahead(db, entry.updated_at, scope="logs"):
                skipped_local += 1
                continue
            changed = apply_log_fields(entry, data)
            if changed:
                updated += 1
            continue

        if not allow_create:
            continue
        # New row (no id) — typically only from Logs (All)
        if not title or not amount_s:
            continue
        try:
            amount = float(amount_s.replace(",", ""))
        except ValueError:
            continue
        content_type = (data.get("content_type") or "study").strip() or "study"
        season = episode = None
        try:
            if (data.get("season") or "").strip():
                season = int(float(data["season"]))
            if (data.get("episode") or "").strip():
                episode = int(float(data["episode"]))
        except ValueError:
            pass
        try:
            create_log(
                db,
                content_type=content_type,
                title=title,
                source=(data.get("source") or "sheet").strip() or "sheet",
                amount=amount,
                unit=(data.get("unit") or "").strip() or None,
                activity=(data.get("activity") or "").strip() or None,
                series_key=(data.get("series_key") or "").strip() or None,
                notes=(data.get("notes") or "").strip() or None,
                tadoku_mode_override=(data.get("tadoku_mode") or "").strip() or None,
                season=season,
                episode=episode,
            )
            created += 1
        except DuplicateLogError:
            pass
        except Exception as exc:  # noqa: BLE001
            errors.append(str(exc))

    return {
        "updated": updated,
        "created": created,
        "deleted": deleted,
        "skipped_local": skipped_local,
        "errors": errors,
    }


def pull_logs(
    db: Session,
    client: Optional[SheetsClient] = None,
    *,
    include_type_tabs: bool = False,
) -> dict[str, Any]:
    """
    Apply edits from log sheets into SQLite, then a later push refreshes all tabs.

    Default (frequent poll): Logs (All) only — cheap and authoritative.
    Type tabs are DB views; pull them only on full_sync (include_type_tabs=True).

    Pull order when type tabs included (later wins on conflicts):
      1) Logs · Anime / VN / Book / …
      2) Logs (All)

    - Row with id → update (or delete if title+amount cleared)
    - Row without id + title+amount → create (Logs All only)
    Manual Entry is separate (new imports only, not a full log mirror).
    """
    client = client or get_sheets_client()
    if not client.enabled:
        return {"ok": False, "reason": "sheets_disabled"}

    totals: dict[str, Any] = {
        "updated": 0,
        "created": 0,
        "deleted": 0,
        "skipped_local": 0,
        "errors": [],
        "sources": [],
    }

    # 1) Type tabs first (optional — many API reads)
    if include_type_tabs and client._sh:
        try:
            for ws in client._sh.worksheets():
                title = ws.title or ""
                if not title.startswith("Logs ·"):
                    continue
                values = _with_retry(ws.get_all_values)
                part = _pull_log_rows_from_values(db, values, allow_create=False)
                totals["updated"] += int(part["updated"])
                totals["deleted"] += int(part["deleted"])
                totals["skipped_local"] += int(part.get("skipped_local") or 0)
                totals["errors"].extend(part["errors"])  # type: ignore[arg-type]
                totals["sources"].append({"tab": title, **part})
        except Exception as exc:  # noqa: BLE001
            logger.warning("type-tab pull failed: %s", exc)

    # 2) Logs (All) last — authoritative for creates + final field values
    #    (except rows still local-ahead of last push — see is_row_local_ahead)
    ws = _master_logs_worksheet(client)
    if ws:
        values = _with_retry(ws.get_all_values)
        part = _pull_log_rows_from_values(db, values, allow_create=True)
        totals["updated"] += int(part["updated"])
        totals["created"] += int(part["created"])
        totals["deleted"] += int(part["deleted"])
        totals["skipped_local"] += int(part.get("skipped_local") or 0)
        totals["errors"].extend(part["errors"])  # type: ignore[arg-type]
        totals["sources"].append({"tab": getattr(ws, "title", "Logs (All)"), **part})

    db.commit()
    changed = (
        int(totals["updated"]) + int(totals["created"]) + int(totals["deleted"])
    )
    if changed:
        mark_sheets_dirty(db)
    return {
        "ok": True,
        "updated": totals["updated"],
        "created": totals["created"],
        "deleted": totals["deleted"],
        "skipped_local": totals["skipped_local"],
        "errors": totals["errors"][:20],
        "sources": totals["sources"],
        "include_type_tabs": include_type_tabs,
    }


def pull_queue(db: Session, client: Optional[SheetsClient] = None) -> dict[str, Any]:
    """Apply Tadoku Queue tab edits (by id) into SQLite.

    With formula_views, Queue is a live FILTER (read-only spill) — edits go on
    Logs (All). Skip pull so we never treat formula output as source rows.
    """
    client = client or get_sheets_client()
    if not client.enabled:
        return {"ok": False, "reason": "sheets_disabled"}
    if _formula_views_enabled():
        return {
            "ok": True,
            "updated": 0,
            "skipped": True,
            "reason": "formula_view",
            "note": "edit tadoku_mode/status on Logs (All)",
        }
    ws = client.worksheet("queue")
    if not ws:
        return {"ok": False, "reason": "no_worksheet"}

    values = _with_retry(ws.get_all_values)
    if not values or len(values) < 2:
        return {"ok": True, "updated": 0}

    headers = [h.strip().lower() for h in values[0]]
    # Map score → tadoku_score_estimate for apply_log_fields
    updated = 0
    errors: list[str] = []
    for row in values[1:]:
        data = row_to_dict(headers, row)
        if "score" in data and "tadoku_score_estimate" not in data:
            data["tadoku_score_estimate"] = data["score"]
        id_raw = (data.get("id") or "").strip()
        if not id_raw:
            continue
        try:
            log_id = int(float(id_raw))
        except ValueError:
            continue
        entry = db.get(LogEntry, log_id)
        if not entry:
            errors.append(f"missing_id:{log_id}")
            continue
        if is_delete_row(data):
            db.delete(entry)
            updated += 1
            continue
        if is_row_local_ahead(db, entry.updated_at, scope="logs"):
            continue
        changed = apply_log_fields(entry, data)
        if changed:
            updated += 1

    db.commit()
    if updated:
        mark_sheets_dirty(db)
    return {"ok": True, "updated": updated, "errors": errors[:20]}


def push_metrics(
    db: Session,
    client: Optional[SheetsClient] = None,
    *,
    force: bool = False,
) -> dict[str, Any]:
    client = client or get_sheets_client()
    if not client.enabled:
        return {"ok": False, "reason": "sheets_disabled"}

    if _formula_views_enabled():
        return {
            "ok": True,
            "formula_views": True,
            "written": False,
            "skipped": True,
        }

    ws = client.worksheet("metrics")
    if not ws:
        return {"ok": False, "reason": "no_worksheet"}

    from sqlalchemy import func

    total = db.query(func.count(LogEntry.id)).scalar() or 0
    minutes = (
        db.query(func.coalesce(func.sum(LogEntry.amount), 0.0))
        .filter(LogEntry.unit == "minutes")
        .scalar()
        or 0.0
    )
    score = db.query(func.coalesce(func.sum(LogEntry.tadoku_score_estimate), 0.0)).scalar() or 0.0
    pending = (
        db.query(func.count(LogEntry.id))
        .filter(LogEntry.tadoku_status == TadokuStatus.PENDING.value)
        .scalar()
        or 0
    )
    ready = (
        db.query(func.count(LogEntry.id))
        .filter(LogEntry.tadoku_status == TadokuStatus.READY.value)
        .scalar()
        or 0
    )
    pushed = (
        db.query(func.count(LogEntry.id))
        .filter(LogEntry.tadoku_status == TadokuStatus.PUSHED.value)
        .scalar()
        or 0
    )

    rows: list[list[Any]] = [
        ["metric", "value"],
        ["total_logs", total],
        ["total_minutes", float(minutes)],
        ["tadoku_score_estimate", float(score)],
        ["tadoku_pending", pending],
        ["tadoku_ready", ready],
        ["tadoku_pushed", pushed],
        [],
        ["content_type", "label", "count", "amount_sum"],
    ]
    type_rows = (
        db.query(
            LogEntry.content_type,
            func.count(LogEntry.id),
            func.coalesce(func.sum(LogEntry.amount), 0.0),
        )
        .group_by(LogEntry.content_type)
        .all()
    )
    type_rows = sorted(type_rows, key=lambda r: _sort_key_content_type(r[0]))
    for ct, cnt, amt in type_rows:
        label = E.CONTENT_TYPE_LABELS.get(ct, ct)
        rows.append([ct, label, cnt, float(amt)])

    wr = _write_rows(ws, rows, db=db, tab_key="metrics", force=force)
    return {"ok": True, "formula_views": False, **wr}


def pull_catalog_overrides(db: Session, client: Optional[SheetsClient] = None) -> dict[str, Any]:
    """
    Merge Catalog tab into SQLite.

    Sheet edits apply for rows not modified locally since the last catalog push.
    Local catalog UI/API edits (aliases, display_title, tadoku_override) win until
    push_catalog records last_push_at:catalog — otherwise poll reverts them.
    """
    client = client or get_sheets_client()
    if not client.enabled:
        return {"ok": False, "reason": "sheets_disabled", "updated": 0}
    ws = client.worksheet("catalog")
    if not ws:
        return {"ok": False, "reason": "no_worksheet", "updated": 0}
    values = _with_retry(ws.get_all_values)
    if not values or len(values) < 2:
        return {"ok": True, "updated": 0}
    headers = [h.strip().lower() for h in values[0]]
    if "series_key" not in headers:
        return {"ok": False, "reason": "bad_headers", "updated": 0}
    updated = 0
    skipped_local = 0
    for row in values[1:]:
        data = {headers[j]: row[j] if j < len(row) else "" for j in range(len(headers))}
        key = (data.get("series_key") or "").strip()
        if not key:
            continue
        title = (data.get("display_title") or key).strip()
        ctype = (data.get("content_type") or "youtube").strip()
        raw_aliases = (data.get("aliases") or "").strip() or None
        if raw_aliases:
            from app.media.catalog_resolve import format_aliases, parse_aliases

            raw_aliases = format_aliases(parse_aliases(raw_aliases)) or None
        # Normalize dropdown values (trim + lowercase known modes)
        raw_override = (data.get("tadoku_override") or "").strip()
        override = raw_override.lower() if raw_override else None
        if override and override not in ("auto", "pending", "never"):
            # Keep unknown values as-is (trimmed) rather than dropping the edit
            override = raw_override
        unit = (data.get("default_unit") or "").strip() or None
        notes = (data.get("notes") or "").strip() or None
        item = (
            db.query(CatalogItem)
            .filter(CatalogItem.series_key == key)
            .one_or_none()
        )
        if not item:
            if not unit:
                from app.tadoku.rules import resolve_activity_unit

                _, unit = resolve_activity_unit(ctype)
            item = CatalogItem(
                series_key=key,
                display_title=title,
                content_type=ctype,
                aliases=raw_aliases,
                tadoku_override=override,
                default_unit=unit,
                notes=notes,
            )
            db.add(item)
            updated += 1
        else:
            if is_row_local_ahead(db, item.updated_at, scope="catalog"):
                skipped_local += 1
                continue
            changed = False
            if title and item.display_title != title:
                item.display_title = title
                changed = True
            if ctype and item.content_type != ctype:
                item.content_type = ctype
                changed = True
            if (item.aliases or None) != raw_aliases:
                item.aliases = raw_aliases
                changed = True
            if item.tadoku_override != override:
                item.tadoku_override = override
                changed = True
            if item.default_unit != unit:
                item.default_unit = unit
                changed = True
            if item.notes != notes:
                item.notes = notes
                changed = True
            if changed:
                updated += 1
    db.commit()
    if updated:
        mark_sheets_dirty(db)
    return {"ok": True, "updated": updated, "skipped_local": skipped_local}


def pull_manual(
    db: Session,
    client: Optional[SheetsClient] = None,
    *,
    apply_validations: bool = False,
) -> dict[str, Any]:
    client = client or get_sheets_client()
    if not client.enabled:
        return {"ok": False, "reason": "sheets_disabled", "imported": 0}
    ws = client.worksheet("manual")
    if not ws:
        return {"ok": False, "reason": "no_worksheet", "imported": 0}

    values = ws.get_all_values()
    if not values:
        _write_rows(ws, [E.MANUAL_HEADERS], db=db, tab_key="manual_headers")
        if apply_validations:
            _apply_manual_validations(ws)
        return {"ok": True, "imported": 0}

    headers = [h.strip().lower() for h in values[0]]
    # Ensure header row is correct if empty sheet had junk
    if "content_type" not in headers:
        _write_rows(ws, [E.MANUAL_HEADERS], db=db, tab_key="manual_headers", force=True)
        if apply_validations:
            _apply_manual_validations(ws)
        return {"ok": True, "imported": 0}

    imported = 0
    updated = 0
    updates = []
    for i, row in enumerate(values[1:], start=2):
        data = {headers[j]: row[j] if j < len(row) else "" for j in range(len(headers))}
        flag = (data.get("imported") or "").strip().lower()
        already = flag in ("1", "true", "yes", "y")
        content_type = (data.get("content_type") or "").strip()
        title = (data.get("title") or "").strip()
        amount_s = (data.get("amount") or "").strip()
        if not content_type or not title or not amount_s:
            continue
        try:
            amount = float(amount_s)
        except ValueError:
            continue
        unit = (data.get("unit") or "").strip() or None
        series_key = (data.get("series_key") or "").strip() or None
        activity = (data.get("activity") or "").strip() or None
        notes = (data.get("notes") or "").strip() or None
        season = episode = None
        try:
            if (data.get("season") or "").strip():
                season = int(float(str(data["season"]).strip()))
            if (data.get("episode") or "").strip():
                episode = int(float(str(data["episode"]).strip()))
        except ValueError:
            pass

        # Same identity path as create_log so re-apply cannot undo
        # yanineko → ヤニねこ (or other catalog/alias canon titles).
        ident = prepare_log_identity(
            content_type=content_type,
            title=title,
            source="manual",
            series_key=series_key,
            season=season,
            episode=episode,
            unit=unit or "",
            activity=activity or "",
        )
        content_type = ident["content_type"]
        title = ident["title"]
        series_key = ident["series_key"]
        season = ident["season"]
        episode = ident["episode"]

        source_ref = f"sheet-row-{i}"
        existing = (
            db.query(LogEntry)
            .filter(LogEntry.source == "manual", LogEntry.source_ref == source_ref)
            .one_or_none()
        )

        if existing:
            # Keep Manual Entry as editable source: re-apply fields every sync
            patch = {
                "content_type": content_type,
                "title": title,
                "amount": str(amount),
                "unit": unit or "",
                "series_key": series_key or "",
                "activity": activity or "",
                "notes": notes or "",
                "season": "" if season is None else str(season),
                "episode": "" if episode is None else str(episode),
            }
            changed = apply_log_fields(existing, patch)
            if changed:
                updated += 1
        elif already:
            # Marked imported but no matching log — allow re-create
            already = False

        if not existing and not already:
            try:
                create_log(
                    db,
                    content_type=content_type,
                    title=title,
                    source="manual",
                    amount=amount,
                    unit=unit,
                    activity=activity,
                    series_key=series_key,
                    source_ref=source_ref,
                    notes=notes,
                    season=season,
                    episode=episode,
                )
                imported += 1
            except DuplicateLogError as dup:
                changed = apply_log_fields(
                    dup.existing,
                    {
                        "content_type": content_type,
                        "title": title,
                        "amount": str(amount),
                        "unit": unit or "",
                        "series_key": series_key or "",
                        "activity": activity or "",
                        "notes": notes or "",
                        "season": "" if season is None else str(season),
                        "episode": "" if episode is None else str(episode),
                    },
                )
                if changed:
                    updated += 1

        if "imported" in headers:
            # Only write TRUE for rows that are not already marked (avoid no-op writes)
            if not already:
                col = headers.index("imported") + 1
                updates.append({"range": gspread_cell(i, col), "values": [["TRUE"]]})

    if updates and client.enabled:
        try:
            _with_retry(
                lambda: ws.batch_update(
                    [{"range": u["range"], "values": u["values"]} for u in updates]
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to mark manual rows imported: %s", exc)

    db.commit()
    if imported or updated:
        mark_sheets_dirty(db)
    if apply_validations:
        _apply_manual_validations(ws)
    return {"ok": True, "imported": imported, "updated": updated}


def push_catalog(
    db: Session,
    client: Optional[SheetsClient] = None,
    *,
    apply_validations: bool = True,
    force: bool = False,
) -> dict[str, Any]:
    """
    Push Catalog rows. Dropdowns (content_type / tadoku_override / default_unit)
    are re-applied by default — range updates wipe data-validation rules, and
    hourly-only re-apply left those columns as free text.
    """
    client = client or get_sheets_client()
    if not client.enabled:
        return {"ok": False, "reason": "sheets_disabled"}
    ws = client.worksheet("catalog")
    if not ws:
        return {"ok": False, "reason": "no_worksheet"}
    rows: list[list[Any]] = [E.CATALOG_HEADERS]
    for c in db.query(CatalogItem).order_by(CatalogItem.series_key).all():
        rows.append(
            [
                c.series_key,
                c.display_title,
                c.content_type,
                c.aliases or "",
                c.tadoku_override or "",
                c.default_unit or "",
                c.notes or "",
            ]
        )
    wr = _write_rows(ws, rows, db=db, tab_key="catalog", force=force)
    set_last_push_at(db, "catalog")
    # Always re-apply when we wrote data, or when caller asks (default True so
    # hash-skip still restores dropdowns if they were wiped earlier).
    do_vals = apply_validations or bool(wr.get("written"))
    vals_ok = False
    if do_vals:
        try:
            _apply_catalog_validations(ws)
            vals_ok = True
        except Exception as exc:  # noqa: BLE001
            logger.warning("catalog validations skipped: %s", exc)
    return {
        "ok": True,
        "rows": len(rows) - 1,
        "validations": vals_ok,
        **wr,
    }


def ensure_manual_headers(
    client: SheetsClient,
    *,
    apply_validations: bool = False,
    db: Optional[Session] = None,
) -> dict[str, Any]:
    ws = client.worksheet("manual")
    if not ws:
        return {"ok": False}
    values = ws.get_all_values()
    if not values:
        _write_rows(ws, [E.MANUAL_HEADERS], db=db, tab_key="manual_headers")
        if apply_validations:
            _apply_manual_validations(ws)
        return {"ok": True, "wrote_headers": True}
    headers = [h.strip().lower() for h in values[0]]
    # Upgrade header row if missing season/episode (keep data rows)
    if "season" not in headers or "episode" not in headers:
        try:
            _with_retry(
                lambda: ws.update(
                    "A1", [E.MANUAL_HEADERS], value_input_option="USER_ENTERED"
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not upgrade Manual Entry headers: %s", exc)
    if apply_validations:
        _apply_manual_validations(ws)
    return {"ok": True, "wrote_headers": False}


def pull_user_edits(
    db: Session,
    client: Optional[SheetsClient] = None,
    *,
    include_type_tabs: bool = False,
) -> dict[str, Any]:
    """
    Lightweight sheet → DB poll. Prioritizes user-editable tabs.
    Mostly reads (cheap quota); minimal writes (manual imported flags only).
    """
    client = client or get_sheets_client()
    if not client.enabled:
        return {"ok": False, "reason": "sheets_disabled"}

    result: dict[str, Any] = {"ok": True, "mode": "pull"}

    def step(name: str, fn: Callable[[], Any]) -> None:
        try:
            result[name] = fn()
        except Exception as exc:  # noqa: BLE001
            logger.exception("pull_user_edits step %s failed", name)
            result[name] = {"ok": False, "error": str(exc)}

    # Order: catalog/logs/queue/manual — user edits land in DB before any later push
    step("catalog_pull", lambda: pull_catalog_overrides(db, client))
    step(
        "logs_pull",
        lambda: pull_logs(db, client, include_type_tabs=include_type_tabs),
    )
    step("queue_pull", lambda: pull_queue(db, client))
    step("manual", lambda: pull_manual(db, client, apply_validations=False))
    return result


def push_db_to_sheets(
    db: Session,
    client: Optional[SheetsClient] = None,
    *,
    apply_validations: bool = False,
    push_type_tabs: bool = True,
    force: bool = False,
    skip_if_clean: bool = False,
) -> dict[str, Any]:
    """
    DB → sheet. Hash-skips tabs whose content is unchanged.
    When skip_if_clean and sheets are not dirty, only metrics/hash checks
    still run only if force — otherwise returns early with skipped=True.
    """
    client = client or get_sheets_client()
    if not client.enabled:
        return {"ok": False, "reason": "sheets_disabled"}

    if skip_if_clean and not force and not is_sheets_dirty(db):
        return {"ok": True, "skipped": True, "reason": "clean"}

    result: dict[str, Any] = {"ok": True, "mode": "push"}

    def step(name: str, fn: Callable[[], Any]) -> None:
        try:
            result[name] = fn()
        except Exception as exc:  # noqa: BLE001
            logger.exception("push_db_to_sheets step %s failed", name)
            result[name] = {"ok": False, "error": str(exc)}

    if apply_validations:
        step("enums", lambda: ensure_enums_sheet(client, force=False, db=db))
        step(
            "manual_headers",
            lambda: ensure_manual_headers(
                client, apply_validations=True, db=db
            ),
        )

    step(
        "logs",
        lambda: push_logs(
            db,
            client,
            apply_validations=apply_validations,
            push_type_tabs=push_type_tabs and not _formula_views_enabled(),
            force=force,
        ),
    )
    if _formula_views_enabled():
        # One install pass for type tabs / queue / metrics FILTER formulas
        def _formula_views() -> Any:
            from app.sheets.formulas import ensure_formula_views

            ws_all = _master_logs_worksheet(client)
            title = getattr(ws_all, "title", None) if ws_all else None
            return ensure_formula_views(
                client,
                logs_title=title,
                force=force,
                type_tabs=push_type_tabs,
                queue=True,
                metrics=True,
                db=db,
            )

        step("formula_views", _formula_views)
    else:
        step(
            "queue",
            lambda: push_queue(
                db, client, apply_validations=apply_validations, force=force
            ),
        )
        step("metrics", lambda: push_metrics(db, client, force=force))
    # Catalog: re-pull immediately before rewrite so mid-sync edits stick
    step("catalog_pull_final", lambda: pull_catalog_overrides(db, client))
    step(
        "catalog",
        lambda: push_catalog(
            db, client, apply_validations=apply_validations, force=force
        ),
    )

    clear_sheets_dirty(db)
    return result


def full_sync(
    db: Session,
    *,
    run_tadoku: bool = False,
    include_type_tabs: Optional[bool] = None,
) -> dict[str, Any]:
    """
    Bidirectional sync (manual / API force):
      1) Pull sheet edits into SQLite (user priority)
      2) Push DB → sheets (hash-skipped where unchanged)
      3) Optional tadoku process (default off — scheduler handles it)

    Scheduled work uses pull_user_edits + push_db_to_sheets separately so
    user edits are polled often without rewriting the whole workbook.

    With formula_views, type tabs are FILTER spills — never pull them as source
    data (default include_type_tabs=False).
    """
    client = get_sheets_client()
    if not client.enabled:
        return {
            "catalog_pull": {"ok": False, "reason": "sheets_disabled"},
            "manual": {"ok": False, "reason": "sheets_disabled"},
            "logs": {"ok": False, "reason": "sheets_disabled"},
        }

    if include_type_tabs is None:
        include_type_tabs = not _formula_views_enabled()

    result: dict[str, Any] = {}
    apply_vals = _should_apply_validations()
    result["apply_validations"] = apply_vals

    def step(name: str, fn: Callable[[], Any]) -> None:
        try:
            result[name] = fn()
        except Exception as exc:  # noqa: BLE001
            logger.exception("full_sync step %s failed", name)
            result[name] = {"ok": False, "error": str(exc)}

    # --- PULL first (never overwrite user cells before reading them) ---
    pull = pull_user_edits(
        db, client, include_type_tabs=include_type_tabs
    )
    result.update({k: v for k, v in pull.items() if k not in ("ok", "mode")})
    result["pull"] = {"ok": pull.get("ok", True)}

    # --- PUSH (hash skips no-op tabs) ---
    push = push_db_to_sheets(
        db,
        client,
        apply_validations=apply_vals,
        push_type_tabs=True,
        force=False,
        skip_if_clean=False,
    )
    for k, v in push.items():
        if k not in ("ok", "mode"):
            result[k] = v
    result["push"] = {"ok": push.get("ok", True)}

    if run_tadoku:
        from app.tadoku.queue import process_ready

        step("tadoku_auto", lambda: process_ready(db))
        tadoku = result.get("tadoku_auto") or {}
        if tadoku.get("pushed") or tadoku.get("promoted_auto"):
            mark_sheets_dirty(db)
            # Hash will write only changed tabs (status columns)
            step(
                "logs_after_tadoku",
                lambda: push_logs(
                    db, client, apply_validations=False, push_type_tabs=False
                ),
            )
            step(
                "queue_after_tadoku",
                lambda: push_queue(db, client, apply_validations=False),
            )
            clear_sheets_dirty(db)
    return result
