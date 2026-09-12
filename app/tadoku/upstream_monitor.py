"""
Infrequent live monitor for minimal tadoku.app path contracts.

GET-only. Intended to run every many hours from the app scheduler so we notice
when contest leaderboard URLs or public API shapes break (without hammering
tadoku or re-running the full pytest suite).

Status is written to data/tadoku_upstream_status.json for API/UI inspection.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx

from app.tadoku import upstream as up

logger = logging.getLogger(__name__)

_TIMEOUT = 15.0
_UA = "immersion-tracker/upstream-monitor"
_STATUS_NAME = "tadoku_upstream_status.json"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def status_path() -> Path:
    docker = Path("/app/data") / _STATUS_NAME
    if docker.parent.is_dir():
        return docker
    return Path("data") / _STATUS_NAME


@dataclass
class ProbeResult:
    name: str
    ok: bool
    url: str
    status_code: Optional[int] = None
    detail: str = ""


@dataclass
class MonitorReport:
    ok: bool
    checked_at: str
    contest_id: str
    probes: list[ProbeResult] = field(default_factory=list)
    error_count: int = 0
    skipped_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "checked_at": self.checked_at,
            "contest_id": self.contest_id,
            "error_count": self.error_count,
            "skipped_reason": self.skipped_reason,
            "probes": [asdict(p) for p in self.probes],
        }


def load_last_report() -> Optional[dict[str, Any]]:
    path = status_path()
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def save_report(report: MonitorReport) -> Path:
    path = status_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(report.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    tmp.replace(path)
    return path


def _headers() -> dict[str, str]:
    return {
        "Accept": "application/json, text/html;q=0.9,*/*;q=0.8",
        "Origin": up.TADOKU_ORIGIN,
        "Referer": f"{up.TADOKU_ORIGIN}/",
        "User-Agent": _UA,
    }


def _probe_get(
    name: str,
    url: str,
    *,
    params: Optional[dict[str, Any]] = None,
    expect_json: bool = False,
    json_required_keys: tuple[str, ...] = (),
    html_not_found: bool = False,
) -> ProbeResult:
    try:
        r = httpx.get(
            url,
            headers=_headers(),
            params=params,
            timeout=_TIMEOUT,
            follow_redirects=True,
        )
    except httpx.TransportError as e:
        return ProbeResult(
            name=name,
            ok=False,
            url=url,
            detail=f"network error: {e}",
        )

    if r.status_code != 200:
        return ProbeResult(
            name=name,
            ok=False,
            url=url,
            status_code=r.status_code,
            detail=f"HTTP {r.status_code}",
        )

    if html_not_found:
        text = (r.text or "").lower()
        if "this page could not be found" in text:
            return ProbeResult(
                name=name,
                ok=False,
                url=url,
                status_code=200,
                detail="HTML 404 page body (route missing)",
            )

    if expect_json:
        try:
            data = r.json()
        except ValueError:
            return ProbeResult(
                name=name,
                ok=False,
                url=url,
                status_code=r.status_code,
                detail="response is not JSON",
            )
        missing = [k for k in json_required_keys if k not in data]
        if missing:
            return ProbeResult(
                name=name,
                ok=False,
                url=url,
                status_code=r.status_code,
                detail=f"missing keys: {missing}",
            )
        if "entries" in json_required_keys:
            entries = data.get("entries") or []
            if not isinstance(entries, list) or len(entries) < 1:
                return ProbeResult(
                    name=name,
                    ok=False,
                    url=url,
                    status_code=r.status_code,
                    detail="leaderboard entries empty",
                )

    return ProbeResult(
        name=name,
        ok=True,
        url=url,
        status_code=r.status_code,
        detail="ok",
    )


def run_minimal_probes(
    *,
    contest_id: Optional[str] = None,
    api_base: Optional[str] = None,
) -> MonitorReport:
    """
    Minimal public canaries (2 GETs):

      1. Contest leaderboard HTML page (UI link)
      2. Contest leaderboard JSON API (race / momentum cache)

    No auth, no POST.
    """
    from app.core.config import get_settings

    cfg = get_settings().yaml_config.tadoku
    cid = (contest_id or (cfg.contest.contest_id if cfg.contest else "") or "").strip()
    base = (api_base or cfg.api_base or up.DEFAULT_API_BASE).rstrip("/")
    checked_at = _utc_now_iso()

    if not cid:
        report = MonitorReport(
            ok=False,
            checked_at=checked_at,
            contest_id="",
            skipped_reason="no contest_id configured",
            error_count=1,
        )
        logger.error("tadoku upstream monitor: no contest_id configured")
        save_report(report)
        return report

    page_url = up.contest_leaderboard_page_url(cid)
    api_url = up.join_api(base, up.api_contest_leaderboard_path(cid))

    probes = [
        _probe_get(
            "contest_leaderboard_page",
            page_url,
            html_not_found=True,
        ),
        _probe_get(
            "contest_leaderboard_api",
            api_url,
            params={"page": 0, "page_size": 1},
            expect_json=True,
            json_required_keys=("entries",),
        ),
    ]

    failures = [p for p in probes if not p.ok]
    report = MonitorReport(
        ok=len(failures) == 0,
        checked_at=checked_at,
        contest_id=cid,
        probes=probes,
        error_count=len(failures),
    )
    save_report(report)

    if report.ok:
        logger.info(
            "tadoku upstream monitor ok contest=%s probes=%s",
            cid,
            ",".join(p.name for p in probes),
        )
    else:
        for p in failures:
            logger.error(
                "tadoku upstream monitor FAIL name=%s url=%s detail=%s",
                p.name,
                p.url,
                p.detail,
            )
        logger.error(
            "tadoku upstream monitor: %s/%s probes failed (contest=%s) — "
            "check tadoku.app paths / contest_id",
            len(failures),
            len(probes),
            cid,
        )
    return report
