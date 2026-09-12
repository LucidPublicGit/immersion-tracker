#!/usr/bin/env python3
"""
List your ongoing Tadoku contest registrations (name + registration UUID).

Uses TADOKU_COOKIE from the environment or .env in the project root.

  cd path/to/immersion-tracker
  .\\.venv\\Scripts\\python scripts\\tadoku_list_registrations.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx

API = "https://tadoku.app/api/internal/immersion/contests/ongoing-registrations"


def load_cookie() -> str:
    c = os.environ.get("TADOKU_COOKIE", "").strip()
    if c:
        return c
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.is_file():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("TADOKU_COOKIE="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def main() -> int:
    cookie = load_cookie()
    if not cookie:
        print("TADOKU_COOKIE not set. Put it in .env first.", file=sys.stderr)
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
        print(r.text[:800])
        print(
            "\nIf 401: cookie expired or incomplete. Re-copy Cookie from DevTools "
            "while logged into tadoku.app, update .env, try again.",
            file=sys.stderr,
        )
        return 1

    data = r.json()
    regs = data.get("registrations") or data.get("Registrations") or []
    if isinstance(data, list):
        regs = data

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
