#!/usr/bin/env python3
"""
Host-side Hoshi ADB poller for Docker (Windows USB).

Docker Desktop usually cannot see USB devices. This script runs on the host:

  1. Reads Books/*/statistics.json from the Boox via adb
  2. POSTs them to immersion-tracker ``/api/hoshi/ingest-stats``

Usage (from repo root, with venv optional)::

  python scripts/hoshi_adb_poll.py
  python scripts/hoshi_adb_poll.py --dry-run
  python scripts/hoshi_adb_poll.py --api http://127.0.0.1:8000

Or: scripts\\hoshi_adb_poll.ps1
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow `python scripts/hoshi_adb_poll.py` without install
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description="Poll Hoshi stats via ADB → immersion-tracker")
    parser.add_argument(
        "--api",
        default="http://127.0.0.1:8000",
        help="Immersion Tracker base URL",
    )
    parser.add_argument("--dry-run", action="store_true", help="Server dry-run (no log writes)")
    parser.add_argument(
        "--local",
        action="store_true",
        help="Ingest into local SQLite (no HTTP; needs CONFIG/DATABASE env)",
    )
    parser.add_argument("--binary", default="", help="Path to adb.exe (else PATH / tools/)")
    parser.add_argument("--serial", default="", help="adb device serial")
    parser.add_argument("--connect", default="", help="Wireless adb host:port")
    parser.add_argument("--package", default="moe.antimony.hoshi")
    parser.add_argument("--books-path", default="", help="Override Books dir on device")
    args = parser.parse_args()

    from app.ingest.hoshi_adb import HoshiAdbClient, HoshiAdbError, adb_book_to_folder

    binary = args.binary or "adb"
    # Prefer repo-vendored platform-tools when present
    vendored = ROOT / "tools" / "platform-tools" / "adb.exe"
    if not args.binary and vendored.is_file():
        binary = str(vendored)

    try:
        client = HoshiAdbClient(
            binary=binary,
            serial=args.serial,
            package=args.package,
            connect=args.connect,
            books_path=args.books_path,
        )
        books = client.fetch_all_books()
    except HoshiAdbError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    payload_books = []
    for b in books:
        folder = adb_book_to_folder(b)
        stats = [
            {
                "title": d.title or b.title,
                "dateKey": d.date_key,
                "charactersRead": d.characters_read,
                "readingTime": d.reading_time,
                "lastStatisticModified": d.last_statistic_modified,
            }
            for d in b.days
        ]
        payload_books.append(
            {
                "folder_id": folder.id.removeprefix("adb:"),
                "title": b.title,
                "statistics": stats,
            }
        )
        print(f"  {b.title}: {len(stats)} day(s), mode={b.access_mode}")

    print(f"Fetched {len(payload_books)} book(s) via ADB ({client.access_mode} @ {client.books_root})")

    if args.local:
        from app.core.config import reload_settings
        from app.db.session import get_engine, init_db, reset_engine
        from app.ingest.hoshi import ingest_stats_payload
        from sqlalchemy.orm import sessionmaker

        reload_settings()
        reset_engine()
        init_db()
        SessionLocal = sessionmaker(bind=get_engine(), autoflush=False, autocommit=False)
        db = SessionLocal()
        try:
            result = ingest_stats_payload(db, payload_books, dry_run=args.dry_run)
        finally:
            db.close()
        print(json.dumps(result.to_dict(), indent=2))
        return 0 if result.ok else 1

    try:
        import httpx
    except ImportError:
        print("httpx required for API mode; pip install httpx", file=sys.stderr)
        return 2

    url = args.api.rstrip("/") + "/api/hoshi/ingest-stats"
    if args.dry_run:
        url += "?dry_run=true"
    try:
        r = httpx.post(url, json={"books": payload_books}, timeout=120.0)
    except httpx.HTTPError as e:
        print(f"ERROR: HTTP {e}", file=sys.stderr)
        return 2
    print(f"POST {url} → {r.status_code}")
    try:
        print(json.dumps(r.json(), indent=2))
    except Exception:
        print(r.text)
    return 0 if r.is_success else 1


if __name__ == "__main__":
    raise SystemExit(main())
