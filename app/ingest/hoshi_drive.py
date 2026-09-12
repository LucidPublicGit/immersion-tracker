"""
Google Drive client for Hoshi / ッツ Reader sync layout.

Layout (same as Hoshi Reader Android + ttu-ttu/ebook-reader):

  My Drive/
    ttu-reader-data/                    # root folder name
      <sanitized book title>/           # one folder per book
        statistics_1_6_<ts>_<chars>_….json
        progress_1_6_<ts>_<progress>.json
        bookdata_1_6_….zip
        …

Statistics JSON is a list of daily ReadingStatistics objects.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)

FOLDER_MIME = "application/vnd.google-apps.folder"
DRIVE_API = "https://www.googleapis.com/drive/v3"
DEFAULT_ROOT_FOLDER_NAME = "ttu-reader-data"

@dataclass
class DriveFileInfo:
    id: str
    name: str
    parents: list[str]


@dataclass
class BookFolder:
    id: str
    name: str  # sanitized Drive folder name
    title: str  # desanitized display title


@dataclass
class ReadingStatDay:
    title: str
    date_key: str
    characters_read: int
    reading_time: float  # seconds
    last_statistic_modified: int


class HoshiDriveError(Exception):
    """Drive auth or API failure."""


def sanitize_ttu_filename(title: str) -> str:
    """Mirror Hoshi TtuSyncRules.sanitizeTtuFilename (for tests / matching)."""
    result = title
    if result.endswith(" "):
        result = result[:-1] + "~ttu-spc~"
    if result.endswith("."):
        result = result[:-1] + "~ttu-dend~"
    result = result.replace("*", "~ttu-star~")
    out: list[str] = []
    for ch in result:
        if ch in '/?<>\\:*|%"':
            out.append("%")
            out.append(f"{ord(ch):02X}")
        else:
            out.append(ch)
    return "".join(out)


def desanitize_ttu_filename(name: str) -> str:
    """Mirror Hoshi TtuSyncRules.desanitizeTtuFilename."""
    result = name.replace("~ttu-star~", "*")
    if result.endswith("~ttu-spc~"):
        result = result[: -len("~ttu-spc~")] + " "
    if result.endswith("~ttu-dend~"):
        result = result[: -len("~ttu-dend~")] + "."

    def _hex(m: re.Match[str]) -> str:
        return chr(int(m.group(1), 16))

    return re.sub(r"%([0-9A-Fa-f]{2})", _hex, result)


def parse_statistics_timestamp_millis(filename: str) -> Optional[int]:
    """
    statistics_1_6_<lastStatisticModified>_….json
    index 3 after split on '_' (0=statistics, 1=1, 2=6, 3=ts).
    """
    if not filename.startswith("statistics_"):
        return None
    stem = filename.removesuffix(".json")
    parts = stem.split("_")
    if len(parts) < 4:
        return None
    try:
        return int(parts[3])
    except ValueError:
        return None


def pick_latest_statistics_file(files: list[DriveFileInfo]) -> Optional[DriveFileInfo]:
    best: Optional[DriveFileInfo] = None
    best_ts = float("-inf")
    for f in files:
        if not f.name.startswith("statistics_"):
            continue
        ts = parse_statistics_timestamp_millis(f.name)
        score = float(ts) if ts is not None else float("-inf")
        if score >= best_ts:
            best_ts = score
            best = f
    return best


def parse_progress_timestamp_millis(filename: str) -> Optional[int]:
    """progress_1_6_<ts>_<ratio>.json — index 3."""
    if not filename.startswith("progress_"):
        return None
    stem = filename.removesuffix(".json")
    parts = stem.split("_")
    if len(parts) < 4:
        return None
    try:
        return int(parts[3])
    except ValueError:
        return None


def parse_bookdata_character_count(filename: str) -> Optional[int]:
    """bookdata_1_6_<charCount>_<ts>_….zip — index 3."""
    if not filename.startswith("bookdata_"):
        return None
    stem = filename.removesuffix(".zip")
    parts = stem.split("_")
    if len(parts) < 4:
        return None
    try:
        return int(parts[3])
    except ValueError:
        return None


def pick_latest_progress_file(files: list[DriveFileInfo]) -> Optional[DriveFileInfo]:
    best: Optional[DriveFileInfo] = None
    best_ts = float("-inf")
    for f in files:
        if not f.name.startswith("progress_"):
            continue
        ts = parse_progress_timestamp_millis(f.name)
        score = float(ts) if ts is not None else float("-inf")
        if score >= best_ts:
            best_ts = score
            best = f
    return best


def parse_statistics_json(raw: str | bytes | list[Any]) -> list[ReadingStatDay]:
    """Parse Hoshi/TTU statistics JSON list into ReadingStatDay rows."""
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8")
    if isinstance(raw, str):
        data = json.loads(raw)
    else:
        data = raw
    if not isinstance(data, list):
        raise ValueError("statistics JSON must be a list")

    out: list[ReadingStatDay] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        date_key = str(item.get("dateKey") or "").strip()
        if not date_key:
            continue
        try:
            chars = int(item.get("charactersRead") or 0)
        except (TypeError, ValueError):
            chars = 0
        try:
            reading_time = float(item.get("readingTime") or 0.0)
        except (TypeError, ValueError):
            reading_time = 0.0
        try:
            modified = int(item.get("lastStatisticModified") or 0)
        except (TypeError, ValueError):
            modified = 0
        title = str(item.get("title") or "").strip()
        out.append(
            ReadingStatDay(
                title=title,
                date_key=date_key,
                characters_read=max(0, chars),
                reading_time=max(0.0, reading_time),
                last_statistic_modified=modified,
            )
        )
    # Deduplicate by dateKey keeping highest lastStatisticModified
    by_day: dict[str, ReadingStatDay] = {}
    for row in out:
        existing = by_day.get(row.date_key)
        if existing is None or row.last_statistic_modified >= existing.last_statistic_modified:
            by_day[row.date_key] = row
    return list(by_day.values())


def _load_drive_credentials():
    """
    Reuse the same Google credential resolution as Sheets (SA or OAuth user).

    Prefer scopes already granted on the stored token; request Drive+Sheets.
    """
    from app.core.config import get_settings
    from app.sheets.sync import _load_credentials

    settings = get_settings()
    cfg = settings.yaml_config.sheets
    creds, mode = _load_credentials(settings, cfg)
    if creds is None:
        raise HoshiDriveError(
            "No Google credentials found. Configure Sheets OAuth token or "
            "service account JSON (same files under data/)."
        )
    return creds, mode


class HoshiDriveClient:
    """Minimal Drive v3 client for reading Hoshi/TTU statistics."""

    def __init__(self, *, credentials=None, auth_mode: Optional[str] = None) -> None:
        if credentials is None:
            credentials, auth_mode = _load_drive_credentials()
        self._creds = credentials
        self.auth_mode = auth_mode or "unknown"
        self._token: Optional[str] = None

    def _access_token(self) -> str:
        from google.auth.transport.requests import Request

        if not self._creds.valid:
            if getattr(self._creds, "refresh_token", None) or getattr(
                self._creds, "expired", False
            ):
                self._creds.refresh(Request())
            elif not self._creds.valid:
                # Service accounts always refresh via Request
                self._creds.refresh(Request())
        token = getattr(self._creds, "token", None)
        if not token:
            raise HoshiDriveError("Google credentials produced no access token")
        return str(token)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._access_token()}"}

    def _get_json(self, path: str, params: Optional[dict[str, str]] = None) -> dict[str, Any]:
        url = f"{DRIVE_API}/{path.lstrip('/')}"
        with httpx.Client(timeout=60.0) as client:
            r = client.get(url, headers=self._headers(), params=params or {})
            if r.status_code >= 400:
                raise HoshiDriveError(
                    f"Drive API {r.status_code} on {path}: {r.text[:300]}"
                )
            return r.json()

    def _get_bytes(self, path: str, params: Optional[dict[str, str]] = None) -> bytes:
        url = f"{DRIVE_API}/{path.lstrip('/')}"
        with httpx.Client(timeout=120.0) as client:
            r = client.get(url, headers=self._headers(), params=params or {})
            if r.status_code >= 400:
                raise HoshiDriveError(
                    f"Drive API {r.status_code} on {path}: {r.text[:300]}"
                )
            return r.content

    def list_files(
        self,
        query: str,
        *,
        fields: str = "nextPageToken, files(id, name, parents)",
    ) -> list[DriveFileInfo]:
        files: list[DriveFileInfo] = []
        page_token: Optional[str] = None
        while True:
            params: dict[str, str] = {
                "q": query,
                "fields": fields,
                "pageSize": "1000",
                "spaces": "drive",
            }
            if page_token:
                params["pageToken"] = page_token
            data = self._get_json("files", params)
            for item in data.get("files") or []:
                files.append(
                    DriveFileInfo(
                        id=str(item["id"]),
                        name=str(item["name"]),
                        parents=list(item.get("parents") or []),
                    )
                )
            page_token = data.get("nextPageToken")
            if not page_token:
                break
        return files

    def find_root_folder(
        self,
        *,
        folder_id: str = "",
        folder_name: str = DEFAULT_ROOT_FOLDER_NAME,
    ) -> str:
        """Return Drive folder id for ttu-reader-data (or configured name/id)."""
        if folder_id and folder_id.strip():
            return folder_id.strip()

        name = (folder_name or DEFAULT_ROOT_FOLDER_NAME).replace("'", "\\'")
        # Prefer My Drive root children (Hoshi default)
        q = (
            f"trashed=false and mimeType='{FOLDER_MIME}' and name='{name}' "
            f"and 'root' in parents"
        )
        found = self.list_files(q, fields="files(id, name)")
        if found:
            return found[0].id

        # Fallback: any matching folder the credential can see (shared SA, etc.)
        q2 = f"trashed=false and mimeType='{FOLDER_MIME}' and name='{name}'"
        found2 = self.list_files(q2, fields="files(id, name)")
        if found2:
            logger.info(
                "hoshi drive: using non-root folder %s (%s)",
                found2[0].name,
                found2[0].id,
            )
            return found2[0].id

        raise HoshiDriveError(
            f"Drive folder '{folder_name}' not found. "
            "Enable Hoshi Google Drive sync once, then either use the same "
            "Google OAuth account here, or share ttu-reader-data with the "
            "service account as Viewer/Editor."
        )

    def list_book_folders(self, root_folder_id: str) -> list[BookFolder]:
        rid = root_folder_id.replace("'", "\\'")
        q = (
            f"trashed=false and mimeType='{FOLDER_MIME}' "
            f"and '{rid}' in parents"
        )
        files = self.list_files(q, fields="nextPageToken, files(id, name)")
        books: list[BookFolder] = []
        for f in files:
            books.append(
                BookFolder(
                    id=f.id,
                    name=f.name,
                    title=desanitize_ttu_filename(f.name),
                )
            )
        return books

    def list_children(self, folder_id: str) -> list[DriveFileInfo]:
        fid = folder_id.replace("'", "\\'")
        q = f"trashed=false and mimeType!='{FOLDER_MIME}' and '{fid}' in parents"
        return self.list_files(
            q, fields="nextPageToken, files(id, name, parents)"
        )

    def download_file_text(self, file_id: str) -> str:
        data = self._get_bytes(
            f"files/{quote(file_id, safe='')}",
            params={"alt": "media"},
        )
        return data.decode("utf-8")

    def fetch_book_statistics(
        self, book: BookFolder
    ) -> tuple[Optional[DriveFileInfo], list[ReadingStatDay]]:
        children = self.list_children(book.id)
        stats_file = pick_latest_statistics_file(children)
        if stats_file is None:
            return None, []
        raw = self.download_file_text(stats_file.id)
        days = parse_statistics_json(raw)
        # Prefer book folder title when day title empty
        for i, day in enumerate(days):
            if not day.title:
                days[i] = ReadingStatDay(
                    title=book.title,
                    date_key=day.date_key,
                    characters_read=day.characters_read,
                    reading_time=day.reading_time,
                    last_statistic_modified=day.last_statistic_modified,
                )
        return stats_file, days

    def fetch_book_progress(
        self, book: BookFolder
    ) -> tuple[Optional[int], Optional[int]]:
        """
        Return (explored_char_count, book_total_chars_estimate).

        Progress JSON: ``exploredCharCount``. Total may come from bookdata filename.
        """
        children = self.list_children(book.id)
        progress_file = pick_latest_progress_file(children)
        total: Optional[int] = None
        for f in children:
            if f.name.startswith("bookdata_"):
                total = parse_bookdata_character_count(f.name) or total
        if progress_file is None:
            return None, total
        try:
            raw = self.download_file_text(progress_file.id)
            data = json.loads(raw)
            pos = int(data.get("exploredCharCount") or 0)
            return pos, total
        except Exception as e:  # noqa: BLE001
            logger.warning("progress parse failed for %s: %s", book.title, e)
            return None, total
