from __future__ import annotations

import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any, Optional

import httpx

from app.core.config import get_settings
from app.db.models import LogEntry
from app.media.title_format import tadoku_title
from app.tadoku.session import ensure_session, mark_session_invalid, resolve_cookie

logger = logging.getLogger(__name__)

# Tadoku activity IDs (from tadoku immersion-api domain/activities.go)
ACTIVITY_IDS = {
    "reading": 1,
    "listening": 2,
    "writing": 3,
    "speaking": 4,
    "study": 5,
}

# content_type → Tadoku media tag only (no platform/source tags like plex/hoshi)
CONTENT_TYPE_TAGS = {
    "book": "book",
    "manga": "manga",
    "anime": "anime",
    "audiobook": "audiobook",
    "visual_novel": "vn",
    "vn": "vn",
    "youtube": "youtube",
    "show": "show",
    "drama": "show",
    "game": "game",
    "podcast": "podcast",
    "study": "study",
    "netflix": "show",
}

_TRUTHY = frozenset({"1", "true", "yes", "on"})


def live_submit_blocked() -> bool:
    """
    Hard stop for live tadoku.app POSTs during automated tests / dry-run mode.

    Set IMMERSION_TADOKU_DRY_RUN=1 (pytest conftest does this), or rely on
    PYTEST_CURRENT_TEST which pytest always sets while a test is running.
    """
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return True
    flag = os.environ.get("IMMERSION_TADOKU_DRY_RUN", "").strip().lower()
    return flag in _TRUTHY


class TadokuClient:
    """
    Submit logs to tadoku.app immersion API when session cookie is configured;
    always also write a local export JSON for audit.

    API (from open source tadoku monorepo):
      POST {api_base}/logs
      Auth: browser session cookie (Ory / tadoku.app)
    """

    def __init__(
        self,
        export_dir: Optional[str] = None,
        dry_run: Optional[bool] = None,
    ):
        settings = get_settings()
        cfg = settings.yaml_config.tadoku
        self.cfg = cfg
        self.api_base = (cfg.api_base or "https://tadoku.app/api/internal/immersion").rstrip(
            "/"
        )
        if dry_run is None:
            # Live when live_submit is on and we have a cookie or saved credentials
            from app.tadoku.credentials import credentials_configured

            can_auth = bool(self._cookie()) or credentials_configured()
            dry_run = not (cfg.live_submit and can_auth)
        # Tests / explicit dry-run env must never hit tadoku.app even if cookie leaks in
        if live_submit_blocked():
            dry_run = True
        self.dry_run = dry_run
        if export_dir:
            self.export_dir = Path(export_dir)
        else:
            docker = Path("/app/data/tadoku_export")
            self.export_dir = (
                docker if docker.parent.is_dir() else Path("data/tadoku_export")
            )
        self.export_dir.mkdir(parents=True, exist_ok=True)
        self._unit_cache: Optional[dict[str, str]] = None

    def _cookie(self) -> str:
        return resolve_cookie()

    def _cookie_for_submit(self) -> str:
        """
        Prefer an existing session cookie; if missing and credentials exist,
        perform browser login once and persist the new cookie.
        """
        cookie = self._cookie()
        if cookie:
            return cookie
        try:
            return ensure_session(force_login=False)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "tadoku auto-login skipped/failed: %s",
                type(exc).__name__,
            )
            return ""

    def _relogin_after_401(self) -> str:
        """Discard rejected cookie and login once with saved credentials."""
        from app.tadoku.session import clear_cookie_file, invalidate_session_cache

        clear_cookie_file()
        invalidate_session_cache()
        try:
            return ensure_session(force_login=True)
        except Exception as exc:  # noqa: BLE001
            logger.warning("tadoku re-login after 401 failed: %s", type(exc).__name__)
            return ""

    def to_local_payload(self, entry: LogEntry) -> dict:
        display = tadoku_title(
            entry.title, season=entry.season, episode=entry.episode
        )
        contest = self.cfg.contest
        return {
            "activity": entry.activity,
            "language": entry.language or self.cfg.language_code or "jpn",
            "amount": entry.amount,
            "unit": entry.unit,
            "title": display,
            "title_base": entry.title,
            "season": entry.season,
            "episode": entry.episode,
            "series_key": entry.series_key,
            "timestamp": entry.timestamp.isoformat() if entry.timestamp else None,
            "score_estimate": entry.tadoku_score_estimate,
            "source": entry.source,
            "local_id": entry.id,
            "contest": {
                "name": contest.name if contest else None,
                "contest_id": contest.contest_id if contest else None,
                "registration_id": contest.registration_id if contest else None,
            },
        }

    def _activity_id(self, entry: LogEntry) -> int:
        key = (entry.activity or "listening").strip().lower()
        return ACTIVITY_IDS.get(key, 2)

    def _duration_seconds(self, entry: LogEntry) -> Optional[int]:
        unit = (entry.unit or "").lower().replace(" ", "_")
        if unit in (
            "minutes",
            "minute",
            "min",
            "minutes_high_density",
            "minute_high_density",
        ):
            return max(1, int(round(float(entry.amount) * 60)))
        if unit in ("seconds", "second", "sec"):
            return max(1, int(round(float(entry.amount))))
        return None

    def _content_type_tag(self, entry: LogEntry) -> Optional[str]:
        """Media-type tag only (book, anime, vn, …). Never platform/source."""
        ct = (entry.content_type or "").strip().lower()
        if ct in CONTENT_TYPE_TAGS:
            return CONTENT_TYPE_TAGS[ct]
        # YouTube logs sometimes only set source=
        src = (entry.source or "").strip().lower()
        if src == "youtube":
            return "youtube"
        if ct:
            # Unknown types: short slug, no spaces (visual novel → visual-novel)
            return ct.replace("_", "-").replace(" ", "-")[:32]
        return None

    def _tags_for(self, entry: LogEntry) -> list[str]:
        """
        Build tadoku.app tags: media type only (book, anime, manga, vn, …).

        Do not tag platform/source (plex, hoshi, gsm, extension) or series
        titles — full titles go in description. Long JP title tags make
        tadoku.app 500. GSM visual novels tag as ``vn`` like any other VN log.
        """
        type_tag = self._content_type_tag(entry)
        if type_tag:
            return [type_tag]
        return ["immersion"]

    def _is_youtube(self, entry: LogEntry) -> bool:
        ct = (entry.content_type or "").strip().lower()
        src = (entry.source or "").strip().lower()
        return ct == "youtube" or src == "youtube"

    def _youtube_url_for(self, entry: LogEntry) -> Optional[str]:
        """Resolve watch URL from notes (url=…) or source_ref video_id."""
        notes = entry.notes or ""
        for part in notes.split(";"):
            part = part.strip()
            if part.lower().startswith("url="):
                url = part[4:].strip()
                if url:
                    return url
        ref = (entry.source_ref or "").strip()
        if not ref:
            return None
        if ref.startswith("http://") or ref.startswith("https://"):
            return ref
        # New: video_id · Legacy: video_id:YYYY-MM-DD
        vid = ref.split(":")[0].strip()
        if not vid:
            return None
        return f"https://www.youtube.com/watch?v={vid}"

    def _description_for(self, entry: LogEntry) -> str:
        """Tadoku log description (title + SxxExx). YouTube: TITLE LINK."""
        description = tadoku_title(
            entry.title, season=entry.season, episode=entry.episode
        )
        if not description.strip():
            description = entry.title or "immersion log"
        if self._is_youtube(entry):
            link = self._youtube_url_for(entry)
            if link and link not in description:
                description = f"{description} {link}".strip()
        return description

    def _fetch_units(self, client: httpx.Client) -> dict[str, str]:
        """Map unit name lower -> unit uuid for current activity context."""
        if self._unit_cache is not None:
            return self._unit_cache
        r = client.get(f"{self.api_base}/logs/configuration-options")
        r.raise_for_status()
        data = r.json()
        mapping: dict[str, str] = {}
        for u in data.get("units") or []:
            name = (u.get("name") or "").strip().lower()
            uid = u.get("id")
            act = u.get("log_activity_id")
            if name and uid:
                mapping[f"{act}:{name}"] = uid
                mapping.setdefault(name, uid)
                # also index singular/plural-ish keys
                if name.endswith("s") and len(name) > 2:
                    mapping.setdefault(name[:-1], uid)
                    if act is not None:
                        mapping.setdefault(f"{act}:{name[:-1]}", uid)
        self._unit_cache = mapping
        logger.info("Tadoku units loaded: %s", sorted({k for k in mapping if ":" not in k}))
        return mapping

    def _resolve_unit_id(
        self, client: httpx.Client, entry: LogEntry, activity_id: int
    ) -> Optional[str]:
        # Config override
        overrides = self.cfg.unit_ids or {}
        unit_name = (entry.unit or "minutes").lower().replace("_", " ").strip()
        # normalize comic_pages etc. → names used by tadoku.app
        aliases = {
            "minutes": "minute",
            "minute": "minute",
            "min": "minute",
            "pages": "page",
            "page": "page",
            "comic pages": "comic page",
            "comic_pages": "comic page",
            "comic page": "comic page",
            "characters": "character",
            "character": "character",
            "chars": "character",
            "sentences": "sentence",
            "sentence": "sentence",
            "two column pages": "2 column page",
            "two_column_pages": "2 column page",
            "minutes high density": "minute (high density)",
            "minutes_high_density": "minute (high density)",
        }
        lookup = aliases.get(unit_name, unit_name)
        candidates = [unit_name, lookup, f"{lookup}s", lookup.rstrip("s")]
        for key in candidates:
            if key in overrides and overrides[key]:
                return overrides[key]
        units = self._fetch_units(client)
        for key in candidates:
            found = units.get(f"{activity_id}:{key}") or units.get(key)
            if found:
                return found
        # listening fallback: any unit containing "minute" for this activity
        if activity_id == 2:
            for k, uid in units.items():
                if k.startswith(f"{activity_id}:") and "minute" in k:
                    return uid
        return None

    def _api_body(self, entry: LogEntry, client: httpx.Client) -> dict[str, Any]:
        activity_id = self._activity_id(entry)
        lang = (entry.language or self.cfg.language_code or "jpn").strip()
        # ISO-639-3: ja -> jpn
        if lang == "ja":
            lang = "jpn"

        # Always put season/episode into description (Tadoku has no separate fields)
        body: dict[str, Any] = {
            "language_code": lang,
            "activity_id": activity_id,
            "tags": self._tags_for(entry),
            "description": self._description_for(entry),
        }
        reg = (self.cfg.contest.registration_id if self.cfg.contest else "") or ""
        if reg.strip():
            body["registration_ids"] = [reg.strip()]

        duration = self._duration_seconds(entry)
        unit_id = self._resolve_unit_id(client, entry, activity_id)

        # Match the website form: amount + unit_id whenever possible so the UI
        # shows minutes/pages (duration-only logs show amount=0 on tadoku.app).
        if unit_id and entry.amount is not None and float(entry.amount) > 0:
            amt = float(entry.amount)
            # Character/page counts are whole numbers; some tadoku paths 500 on floats.
            unit_l = (entry.unit or "").lower()
            if any(
                x in unit_l
                for x in ("char", "page", "sentence", "comic")
            ):
                body["amount"] = int(round(amt))
            else:
                body["amount"] = amt
            body["unit_id"] = unit_id
        if duration is not None:
            body["duration_seconds"] = duration

        # Fallback if unit lookup failed
        if "amount" not in body and "duration_seconds" not in body:
            if entry.amount is not None and float(entry.amount) > 0:
                body["amount"] = float(entry.amount)
            else:
                raise ValueError("log has no amount/duration to submit")

        if "amount" in body and "unit_id" not in body and duration is not None:
            # Keep duration so score still computes for listening
            body.setdefault("duration_seconds", duration)

        return body

    def _write_export(self, entry: LogEntry, extra: Optional[dict] = None) -> str:
        payload = self.to_local_payload(entry)
        if extra:
            payload["api"] = extra
        remote_id = f"export-{uuid.uuid4().hex[:12]}"
        path = self.export_dir / f"{remote_id}.json"
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return remote_id

    def submit(self, entry: LogEntry) -> tuple[bool, Optional[str], Optional[str]]:
        """
        Returns (success, remote_id, error_message).
        """
        # Explicit dry_run, live_submit off, or test/dry-run guard → local export only
        if self.dry_run or not self.cfg.live_submit or live_submit_blocked():
            try:
                mode = "local_export_only"
                if live_submit_blocked():
                    mode = "blocked_test_or_dry_run"
                rid = self._write_export(
                    entry,
                    {
                        "mode": mode,
                        "contest": self.cfg.contest.name if self.cfg.contest else None,
                    },
                )
                return True, rid, None
            except Exception as exc:  # noqa: BLE001
                return False, None, str(exc)

        cookie = self._cookie_for_submit()
        if not cookie:
            try:
                rid = self._write_export(
                    entry,
                    {
                        "mode": "blocked",
                        "reason": "missing_tadoku_auth",
                        "contest": self.cfg.contest.name if self.cfg.contest else None,
                    },
                )
            except Exception:  # noqa: BLE001
                rid = None
            return (
                False,
                rid,
                "Tadoku credentials not configured — save username/password "
                "on the queue page. See docs/TADOKU.md",
            )

        try:
            return self._submit_live(entry, cookie)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Tadoku submit failed")
            try:
                self._write_export(entry, {"error": str(exc)})
            except Exception:  # noqa: BLE001
                pass
            return False, None, str(exc)

    def _submit_live(
        self, entry: LogEntry, cookie: str
    ) -> tuple[bool, Optional[str], Optional[str]]:
        """POST once; on 401 re-login once and retry exactly once."""

        def _post(active_cookie: str) -> tuple[httpx.Response, dict[str, Any]]:
            headers = {
                "Content-Type": "application/json",
                "Cookie": active_cookie,
                "Origin": "https://tadoku.app",
                "Referer": "https://tadoku.app/logs/new",
            }
            with httpx.Client(
                timeout=30.0, headers=headers, follow_redirects=True
            ) as client:
                req_body = self._api_body(entry, client)
                logger.info(
                    "Tadoku submit local_id=%s contest=%s body_keys=%s",
                    entry.id,
                    self.cfg.contest.name if self.cfg.contest else None,
                    list(req_body.keys()),
                )
                resp = client.post(f"{self.api_base}/logs", json=req_body)
                return resp, req_body

        r, body = _post(cookie)
        if r.status_code in (401, 403):
            mark_session_invalid(
                f"submit HTTP {r.status_code}",
                http_status=r.status_code,
            )
            new_cookie = self._relogin_after_401()
            if new_cookie:
                r, body = _post(new_cookie)
            if r.status_code in (401, 403):
                mark_session_invalid(
                    f"submit HTTP {r.status_code} after re-login",
                    http_status=r.status_code,
                )
                err = (
                    f"HTTP {r.status_code}: Tadoku session rejected after re-login. "
                    "Check saved username/password (Refresh Tadoku login)."
                )
                self._write_export(entry, {"error": err, "request": body})
                return False, None, err

        if r.status_code != 200:
            err = f"HTTP {r.status_code}: {r.text[:500]}"
            self._write_export(entry, {"error": err, "request": body})
            return False, None, err
        data = r.json()
        remote_id = str(data.get("id") or f"tadoku-{uuid.uuid4().hex[:12]}")
        self._write_export(
            entry,
            {
                "mode": "live",
                "response": data,
                "request": body,
                "contest": self.cfg.contest.model_dump() if self.cfg.contest else None,
            },
        )
        return True, remote_id, None

