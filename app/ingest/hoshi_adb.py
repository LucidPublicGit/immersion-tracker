"""
Read Hoshi Reader book statistics from a Boox/Android device via ADB.

On-device layout (app-private filesDir)::

  /data/data/moe.antimony.hoshi/files/Books/<folder>/
      metadata.json
      statistics.json
      bookmark.json
      …

Release builds are not ``run-as``-debuggable. Access strategies tried in order:

1. ``run-as <package>`` (debug APKs only)
2. Direct shell read under ``/data/data/...`` (requires root / special firmware)
3. Shared storage ``/sdcard/Android/data/<package>/files/Books`` (if present)
4. Explicit ``books_path`` override from config

USB note: Docker Desktop on Windows usually cannot see USB ADB devices.
Prefer the host script ``scripts/hoshi_adb_poll.ps1``, or wireless ADB
(``adb connect <boox-ip>:5555``) with adb available to the poller process.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from app.ingest.hoshi_drive import BookFolder, ReadingStatDay, parse_statistics_json

logger = logging.getLogger(__name__)

DEFAULT_PACKAGE = "moe.antimony.hoshi"
STATISTICS_NAME = "statistics.json"
METADATA_NAME = "metadata.json"


class HoshiAdbError(Exception):
    """ADB or device access failure."""


@dataclass
class AdbDeviceBook:
    folder: str
    title: str
    days: list[ReadingStatDay]
    access_mode: str


def _which_adb(binary: str = "adb") -> str:
    """Resolve adb executable (PATH, ANDROID_HOME, common Windows locations)."""
    raw = (binary or "adb").strip() or "adb"
    p = Path(raw)
    if p.is_file():
        return str(p.resolve())

    found = shutil.which(raw)
    if found:
        return found

    candidates: list[Path] = []
    for env in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        root = os.environ.get(env)
        if root:
            candidates.append(Path(root) / "platform-tools" / "adb.exe")
            candidates.append(Path(root) / "platform-tools" / "adb")
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    if local:
        candidates.append(local / "Android" / "Sdk" / "platform-tools" / "adb.exe")
    # Repo-vendored platform-tools (optional)
    repo = Path(__file__).resolve().parents[2]
    candidates.append(repo / "tools" / "platform-tools" / "adb.exe")
    candidates.append(repo / "tools" / "platform-tools" / "adb")
    candidates.append(Path("/usr/bin/adb"))
    candidates.append(Path("/usr/local/bin/adb"))

    for c in candidates:
        if c.is_file():
            return str(c.resolve())

    raise HoshiAdbError(
        f"adb not found ({raw!r}). Install Android platform-tools, add them to PATH, "
        "or set hoshi.adb.binary. Host helper: scripts/install-platform-tools.ps1"
    )


class HoshiAdbClient:
    def __init__(
        self,
        *,
        binary: str = "adb",
        serial: str = "",
        package: str = DEFAULT_PACKAGE,
        connect: str = "",
        books_path: str = "",
        timeout: float = 60.0,
    ) -> None:
        self.binary = _which_adb(binary)
        self.serial = (serial or "").strip()
        self.package = (package or DEFAULT_PACKAGE).strip() or DEFAULT_PACKAGE
        self.connect = (connect or "").strip()
        self.books_path_override = (books_path or "").strip()
        self.timeout = timeout
        self.access_mode: Optional[str] = None
        self.books_root: Optional[str] = None

    def _base_cmd(self) -> list[str]:
        cmd = [self.binary]
        if self.serial:
            cmd.extend(["-s", self.serial])
        return cmd

    def run(
        self,
        *args: str,
        check: bool = True,
        text: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        cmd = self._base_cmd() + list(args)
        logger.debug("adb: %s", " ".join(cmd))
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=text,
                timeout=self.timeout,
                encoding="utf-8",
                errors="replace",
            )
        except FileNotFoundError as e:
            raise HoshiAdbError(f"adb binary missing: {self.binary}") from e
        except subprocess.TimeoutExpired as e:
            raise HoshiAdbError(f"adb timed out: {' '.join(args)}") from e
        if check and proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip()
            raise HoshiAdbError(
                f"adb {' '.join(args)} failed (rc={proc.returncode}): {err[:400]}"
            )
        return proc

    def ensure_device(self) -> str:
        """Connect (optional) and return selected device serial."""
        if self.connect:
            # Wireless ADB — ignore non-zero if already connected
            self.run("connect", self.connect, check=False)

        proc = self.run("devices", check=True)
        lines = [
            ln.strip()
            for ln in (proc.stdout or "").splitlines()
            if ln.strip() and not ln.startswith("List of devices")
        ]
        devices: list[str] = []
        for ln in lines:
            parts = ln.split()
            if len(parts) >= 2 and parts[1] == "device":
                devices.append(parts[0])
        if not devices:
            raise HoshiAdbError(
                "No ADB device online. Plug in the Boox, enable USB debugging, "
                "authorize this PC, or set hoshi.adb.connect to wireless IP:port."
            )
        if self.serial:
            if self.serial not in devices:
                raise HoshiAdbError(
                    f"Configured serial {self.serial!r} not online; online={devices}"
                )
            return self.serial
        if len(devices) > 1:
            logger.warning(
                "multiple ADB devices %s; using first. Set hoshi.adb.serial to pin.",
                devices,
            )
        return devices[0]

    def shell(self, remote_cmd: str, *, check: bool = True) -> str:
        proc = self.run("shell", remote_cmd, check=check)
        return proc.stdout or ""

    def package_installed(self) -> bool:
        out = self.shell(f"pm path {self.package}", check=False)
        return "package:" in out

    def _list_dir_names(self, remote_dir: str, *, via_run_as: bool) -> list[str]:
        if via_run_as:
            cmd = f"run-as {self.package} ls -1 {remote_dir}"
        else:
            cmd = f"ls -1 {remote_dir}"
        out = self.shell(cmd, check=False)
        if "Permission denied" in out or "run-as:" in out.lower():
            return []
        names: list[str] = []
        for line in out.splitlines():
            name = line.strip()
            if not name or name.startswith(".") or name in (
                "current.epub",
                "shelves.json",
            ):
                continue
            # ls errors
            if "No such file" in name or "Permission denied" in name:
                continue
            names.append(name)
        return names

    def _read_file(self, remote_path: str, *, via_run_as: bool) -> Optional[str]:
        if via_run_as:
            # Relative to app files/ when path starts with files/
            cmd = f"run-as {self.package} cat {remote_path}"
        else:
            cmd = f"cat {remote_path}"
        proc = self.run("shell", cmd, check=False)
        out = proc.stdout or ""
        err = proc.stderr or ""
        if proc.returncode != 0:
            return None
        if "Permission denied" in out or "Permission denied" in err:
            return None
        if "No such file" in out or out.strip().startswith("run-as:"):
            return None
        text = out
        # Some firmwares mix stderr into stdout for run-as failures
        if text.lstrip().startswith("run-as:"):
            return None
        return text

    def resolve_books_access(self) -> tuple[str, str]:
        """
        Return (access_mode, books_root_path_for_reads).

        access_mode:
          - run-as: paths relative to app cwd (usually files/)
          - absolute: full device paths
        """
        if self.books_path_override:
            names = self._list_dir_names(self.books_path_override, via_run_as=False)
            # empty dir is still valid access if path exists
            probe = self.shell(f"ls -ld {self.books_path_override}", check=False)
            if "No such file" not in probe and "Permission denied" not in probe:
                return "absolute", self.books_path_override.rstrip("/")

        candidates: list[tuple[str, str, bool]] = [
            # mode, path, via_run_as
            ("run-as", "files/Books", True),
            ("run-as", "Books", True),
            (
                "absolute",
                f"/data/data/{self.package}/files/Books",
                False,
            ),
            (
                "absolute",
                f"/sdcard/Android/data/{self.package}/files/Books",
                False,
            ),
            (
                "absolute",
                f"/storage/emulated/0/Android/data/{self.package}/files/Books",
                False,
            ),
        ]

        for mode, path, via_run_as in candidates:
            # Prefer a path that lists at least one child OR exists as directory
            names = self._list_dir_names(path, via_run_as=via_run_as)
            if names:
                return mode, path
            exists = self.shell(
                (
                    f"run-as {self.package} sh -c 'test -d {path} && echo OK'"
                    if via_run_as
                    else f"sh -c 'test -d {path} && echo OK'"
                ),
                check=False,
            )
            if "OK" in exists:
                return mode, path

        raise HoshiAdbError(
            f"Could not read Hoshi Books dir for package {self.package}. "
            "Stock release Hoshi is not debuggable, so ADB cannot read "
            "/data/data/.../files/Books without root. Options: "
            "(1) install a debug Hoshi APK (applicationId moe.antimony.hoshi.debug), "
            "(2) root/firmware that allows app-data reads, "
            "(3) set hoshi.source: drive (Google Drive sync), or "
            "(4) hoshi.source: auto (ADB then Drive). "
            f"Checked: {[c[1] for c in candidates]}"
        )

    def list_book_folders(self) -> list[str]:
        assert self.books_root is not None and self.access_mode is not None
        via = self.access_mode == "run-as"
        names = self._list_dir_names(self.books_root, via_run_as=via)
        # Filter to directories that look like books (have metadata or statistics)
        books: list[str] = []
        for name in names:
            # skip files in Books root
            if name.endswith(".json") or name.endswith(".epub"):
                continue
            books.append(name)
        return books

    def _child_path(self, folder: str, filename: str) -> str:
        root = self.books_root or "files/Books"
        return f"{root.rstrip('/')}/{folder}/{filename}"

    def read_metadata_title(self, folder: str) -> str:
        via = self.access_mode == "run-as"
        raw = self._read_file(self._child_path(folder, METADATA_NAME), via_run_as=via)
        if not raw:
            return folder
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return folder
        if not isinstance(data, dict):
            return folder
        renamed = str(data.get("renamedTitle") or "").strip()
        title = str(data.get("title") or "").strip()
        return renamed or title or folder

    def read_statistics(self, folder: str) -> list[ReadingStatDay]:
        via = self.access_mode == "run-as"
        raw = self._read_file(self._child_path(folder, STATISTICS_NAME), via_run_as=via)
        if not raw or not raw.strip():
            return []
        try:
            return parse_statistics_json(raw)
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("bad statistics.json for %s: %s", folder, e)
            return []

    def fetch_all_books(self) -> list[AdbDeviceBook]:
        self.ensure_device()
        if not self.package_installed():
            # also try debug suffix
            alt = f"{self.package}.debug"
            out = self.shell(f"pm path {alt}", check=False)
            if "package:" in out:
                logger.info("using debug package %s", alt)
                self.package = alt
            else:
                raise HoshiAdbError(
                    f"Package {self.package} not installed on device "
                    f"(also checked {self.package}.debug)."
                )

        mode, root = self.resolve_books_access()
        self.access_mode = mode
        self.books_root = root
        logger.info("hoshi adb: mode=%s books_root=%s", mode, root)

        out: list[AdbDeviceBook] = []
        for folder in self.list_book_folders():
            title = self.read_metadata_title(folder)
            days = self.read_statistics(folder)
            out.append(
                AdbDeviceBook(
                    folder=folder,
                    title=title,
                    days=days,
                    access_mode=mode,
                )
            )
        return out


def adb_book_to_folder(book: AdbDeviceBook) -> BookFolder:
    """Stable folder id for delta state (device-local, not Drive id)."""
    # Sanitize folder name for source_ref safety
    safe = re.sub(r"[^\w.\-]+", "_", book.folder, flags=re.UNICODE)
    if not safe:
        safe = "book"
    return BookFolder(
        id=f"adb:{safe}",
        name=book.folder,
        title=book.title,
    )


def client_from_settings() -> HoshiAdbClient:
    from app.core.config import get_settings

    cfg = get_settings().yaml_config.hoshi
    adb = cfg.adb
    return HoshiAdbClient(
        binary=adb.binary,
        serial=adb.serial,
        package=adb.package,
        connect=adb.connect,
        books_path=adb.books_path,
    )


def probe_adb_status() -> dict[str, Any]:
    """Non-throwing diagnostics for /api/hoshi/status."""
    try:
        client = client_from_settings()
        serial = client.ensure_device()
        installed = client.package_installed()
        mode = root = None
        book_count = None
        err = None
        if installed:
            try:
                mode, root = client.resolve_books_access()
                client.access_mode = mode
                client.books_root = root
                book_count = len(client.list_book_folders())
            except HoshiAdbError as e:
                err = str(e)
        return {
            "adb_binary": client.binary,
            "device_serial": serial,
            "package": client.package,
            "package_installed": installed,
            "access_mode": mode,
            "books_root": root,
            "book_folders": book_count,
            "error": err,
        }
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}
