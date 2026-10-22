#!/usr/bin/env python3
"""
List your ongoing Tadoku contest registrations (name + registration UUID).

Cookie sources (first match wins):
  1. data/tadoku_session.cookie  (Queue UI "Save login")
  2. env TADOKU_COOKIE / TADOKU_SESSION_COOKIE
  3. .env TADOKU_COOKIE=

  cd path/to/immersion-tracker
  python scripts/tadoku_list_registrations.py
  # or:  .\\scripts\\docker\\tadoku-list-registrations.ps1
"""
from __future__ import annotations

import json
import os
import sys
from http.cookies import SimpleCookie
from pathlib import Path

import httpx

API = "https://tadoku.app/api/internal/immersion/contests/ongoing-registrations"
ROOT = Path(__file__).resolve().parent.parent


def load_cookie() -> str:
    for path in (
        ROOT / "data" / "tadoku_session.cookie",
        Path("/app/data/tadoku_session.cookie"),
    ):
        try:
            if path.is_file():
                text = normalize_cookie(path.read_text(encoding="utf-8"))
                if text:
                    return text
        except OSError:
            pass

    for key in ("TADOKU_COOKIE", "TADOKU_SESSION_COOKIE"):
        c = normalize_cookie(os.environ.get(key, ""))
        if c:
            return c

    env_path = ROOT / ".env"
    if env_path.is_file():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("TADOKU_COOKIE="):
                cookie = normalize_cookie(line.split("=", 1)[1].strip().strip('"').strip("'"))
                if cookie:
                    return cookie
    return ""


def normalize_cookie(raw: str) -> str:
    """Send only the new session cookie; obsolete Kratos tokens cannot migrate."""
    raw = raw.strip()
    if raw.lower().startswith("cookie:"):
        raw = raw.split(":", 1)[1].strip()
    if not raw or "\r" in raw or "\n" in raw:
        return ""
    if "=" not in raw:
        return f"tadoku_session={raw}"
    jar = SimpleCookie()
    try:
        jar.load(raw)
    except Exception:
        return ""
    token = jar.get("tadoku_session")
    return f"tadoku_session={token.value}" if token and token.value else ""


def main() -> int:
    cookie = normalize_cookie(load_cookie())
    if not cookie:
        print(
            "No current Tadoku session found (old Kratos cookies no longer work).\n"
            "  1. Open http://127.0.0.1:8000/queue → Save login\n"
            "  2. Re-run this script (reads data/tadoku_session.cookie)\n"
            "Or set TADOKU_COOKIE in .env (legacy).",
            file=sys.stderr,
        )
        return 1

    headers = {
        "Cookie": cookie,
        "Accept": "application/json",
        "Origin": "https://tadoku.app",
        "Referer": "https://tadoku.app/logs/new",
    }
    r = httpx.get(API, headers=headers, timeout=30.0, follow_redirects=True)
    print(f"HTTP {r.status_code}  {API}")
    if r.status_code != 200:
        print(
            "\nIf 401: sign in again via Queue → Refresh Tadoku login, or copy a new "
            "tadoku_session cookie from tadoku.app. Sessions last 30 days.",
            file=sys.stderr,
        )
        return 1

    data = r.json()
    regs = data if isinstance(data, list) else (
        data.get("registrations") or data.get("Registrations") or []
    )

    if not regs and isinstance(data, dict):
        # dump keys to help debug shape
        print("Response keys:", list(data.keys()))
        print(json.dumps(data, indent=2)[:2000])
        return 0

    print(f"\nFound {len(regs)} registration(s):\n")
    for reg in regs:
        rid = reg.get("id") or reg.get("registration_id")
        contest = reg.get("contest") or {}
        name = contest.get("name") or contest.get("title") or reg.get("contest_name") or "?"
        cid = contest.get("id") or reg.get("contest_id") or ""
        print(f"  Contest name:     {name}")
        print(f"  contest_id:       {cid}")
        print(f"  registration_id:  {rid}   <--- put this in settings.yaml")
        print()

    # Hint for Deep Weeb Club
    for reg in regs:
        name = str((reg.get("contest") or {}).get("name") or "")
        if "weeb" in name.lower() or "kanjieater" in name.lower() or "deep" in name.lower():
            rid = reg.get("id")
            print(f"Likely match → registration_id: {rid}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
