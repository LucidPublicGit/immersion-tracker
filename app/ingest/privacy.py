"""
Helpers so integration status / logs never leak secrets.

Credentials live only in:
  * host ``.env`` (gitignored)
  * ``data/*token*.json`` / oauth files (gitignored under data/**)
  * process env inside Docker (from compose .env substitution)

Status endpoints must return booleans / redacted ids, never raw keys or tokens.
"""

from __future__ import annotations

from typing import Any, Optional


def redact_id(value: Optional[str], *, keep_tail: int = 4) -> Optional[str]:
    """Show only the last few characters of an id (SteamID, client id, …)."""
    s = (value or "").strip()
    if not s:
        return None
    if len(s) <= keep_tail:
        return "*" * len(s)
    return f"…{s[-keep_tail:]}"


def scrub_mapping(data: Any) -> Any:
    """
    Recursively drop/redact keys that look like secrets from arbitrary dicts
    (e.g. accidental inclusion in last_result dumps).
    """
    secret_keys = {
        "api_key",
        "apikey",
        "access_token",
        "refresh_token",
        "client_secret",
        "client_id",
        "password",
        "secret",
        "token",
        "authorization",
        "webhook_secret",
        "cookie",
        "session_cookie",
    }
    if isinstance(data, dict):
        out: dict[str, Any] = {}
        for k, v in data.items():
            lk = str(k).lower()
            if lk in secret_keys or lk.endswith("_token") or lk.endswith("_secret"):
                out[k] = "***" if v else None
            else:
                out[k] = scrub_mapping(v)
        return out
    if isinstance(data, list):
        return [scrub_mapping(x) for x in data]
    return data
