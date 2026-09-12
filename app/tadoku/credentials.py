"""
Secure storage for Tadoku username/password.

Password is encrypted at rest with Fernet. The key lives next to the
credentials file under data/ (volume-mounted, gitignored). Username is
stored in cleartext so the UI can repopulate it; the password is never
returned by the public settings API.

Resolution order for credentials:
  1. data/tadoku_credentials.json (UI / API)
  2. env TADOKU_USERNAME + TADOKU_PASSWORD
"""
from __future__ import annotations

import json
import logging
import os
import stat
import threading
from pathlib import Path
from typing import Any, Optional

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

_lock = threading.Lock()

_FILENAME = "tadoku_credentials.json"
_KEY_FILENAME = "tadoku_credentials.key"


class TadokuCredentialsError(RuntimeError):
    """Safe credential-store error (never embeds secrets)."""


def _data_dir() -> Path:
    docker = Path("/app/data")
    if docker.is_dir():
        return docker
    return Path("data")


def credentials_file_path() -> Path:
    return _data_dir() / _FILENAME


def key_file_path() -> Path:
    return _data_dir() / _KEY_FILENAME


def _restrict_permissions(path: Path) -> None:
    """Best-effort owner-only access (no-op / partial on some Windows hosts)."""
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        logger.debug("could not chmod %s", path, exc_info=True)


def _load_or_create_fernet() -> Fernet:
    path = key_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        raw = path.read_bytes().strip()
        if raw:
            return Fernet(raw)
    key = Fernet.generate_key()
    path.write_bytes(key + b"\n")
    _restrict_permissions(path)
    logger.info("created tadoku credentials encryption key at %s", path)
    return Fernet(key)


def _encrypt_password(password: str) -> str:
    f = _load_or_create_fernet()
    return f.encrypt(password.encode("utf-8")).decode("ascii")


def _decrypt_password(token: str) -> str:
    f = _load_or_create_fernet()
    try:
        return f.decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, TypeError) as exc:
        raise TadokuCredentialsError(
            "Stored Tadoku password could not be decrypted; re-save credentials"
        ) from exc


def _read_file_blob() -> dict[str, Any]:
    path = credentials_file_path()
    try:
        if not path.is_file():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        logger.warning("could not read tadoku credentials file", exc_info=True)
        return {}


def _write_file_blob(data: dict[str, Any]) -> Path:
    path = credentials_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # Atomic-ish write
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    _restrict_permissions(tmp)
    tmp.replace(path)
    _restrict_permissions(path)
    return path


def load_credentials() -> tuple[str, str]:
    """
    Return (username, password). Empty strings if not configured.

    Never logs the password.
    """
    with _lock:
        blob = _read_file_blob()
        username = str(blob.get("username") or "").strip()
        password = ""
        enc = blob.get("password_enc")
        if isinstance(enc, str) and enc.strip():
            try:
                password = _decrypt_password(enc.strip())
            except TadokuCredentialsError:
                logger.warning("tadoku stored password decrypt failed")
                password = ""

        if username and password:
            return username, password

        env_user = os.environ.get("TADOKU_USERNAME", "").strip()
        env_pass = os.environ.get("TADOKU_PASSWORD", "")
        # Prefer file username if present; fill missing pieces from env
        return (username or env_user), (password or env_pass)


def credentials_configured() -> bool:
    user, password = load_credentials()
    return bool(user and password)


def password_configured() -> bool:
    """True when a password is stored (file or env), without loading for display."""
    _, password = load_credentials()
    return bool(password)


def saved_username() -> str:
    """Username for UI repopulation (file first, then env). Never password."""
    with _lock:
        blob = _read_file_blob()
        user = str(blob.get("username") or "").strip()
    if user:
        return user
    return os.environ.get("TADOKU_USERNAME", "").strip()


def save_credentials(
    username: str,
    password: Optional[str] = None,
    *,
    preserve_password_if_blank: bool = True,
) -> Path:
    """
    Persist username and (optionally) password.

    If password is blank/None and preserve_password_if_blank is True, keep the
    previously stored encrypted password. Changing username or password
    invalidates the session cookie (caller should clear it when credentials change).
    """
    username = (username or "").strip()
    if not username:
        raise TadokuCredentialsError("Tadoku username is required")

    with _lock:
        blob = _read_file_blob()
        old_user = str(blob.get("username") or "").strip()
        old_enc = blob.get("password_enc") if isinstance(blob.get("password_enc"), str) else ""

        pw = password if password is not None else ""
        if not pw and preserve_password_if_blank:
            if not old_enc:
                # Fall back: if only env password exists, re-encrypt into file
                env_pass = os.environ.get("TADOKU_PASSWORD", "")
                if env_pass:
                    pw = env_pass
                else:
                    raise TadokuCredentialsError(
                        "Tadoku password is required (no saved password to keep)"
                    )
            else:
                new_blob = {"username": username, "password_enc": old_enc}
                path = _write_file_blob(new_blob)
                logger.info(
                    "tadoku credentials saved (username updated, password preserved) path=%s",
                    path,
                )
                return path

        if not pw:
            raise TadokuCredentialsError("Tadoku password is required")

        enc = _encrypt_password(pw)
        path = _write_file_blob({"username": username, "password_enc": enc})
        # Never log password or ciphertext details beyond length
        logger.info(
            "tadoku credentials saved path=%s username_changed=%s password_set=true",
            path,
            username != old_user,
        )
        return path


def clear_credentials() -> bool:
    """Remove stored username/password file. Returns True if a file was removed."""
    with _lock:
        path = credentials_file_path()
        removed = False
        try:
            if path.is_file():
                path.unlink()
                removed = True
        except OSError:
            logger.debug("could not remove tadoku credentials file", exc_info=True)
        # Keep encryption key so re-saves work; optional wipe is fine too
        if removed:
            logger.info("tadoku credentials cleared")
        return removed


def credentials_source() -> str:
    """Where credentials came from (never secret values): file | env | none."""
    with _lock:
        blob = _read_file_blob()
        user = str(blob.get("username") or "").strip()
        enc = blob.get("password_enc") if isinstance(blob.get("password_enc"), str) else ""
        if user and enc:
            return "file"
    env_user = os.environ.get("TADOKU_USERNAME", "").strip()
    env_pass = os.environ.get("TADOKU_PASSWORD", "")
    if env_user and env_pass:
        return "env"
    if user or enc or env_user or env_pass:
        return "partial"
    return "none"


def credentials_public_dict() -> dict[str, Any]:
    """Safe payload for settings API — never includes password or ciphertext."""
    user = saved_username()
    configured = credentials_configured()
    return {
        "tadoku_username": user,
        "tadoku_password_configured": password_configured(),
        "tadoku_credentials_configured": configured,
        "tadoku_credentials_source": credentials_source(),
    }
