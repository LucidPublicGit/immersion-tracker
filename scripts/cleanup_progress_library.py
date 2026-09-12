"""
Heal Progress library identity (CLI).

Rewrites log series_key / titles so:
  - One Piece 18/19/… collapse to One Piece
  - Anki / Bunpro / Italki become study (off the Progress shelf)
  - Contest carry-overs and garbage keys stay off the shelf

Also available in the UI: Progress → Maintain → Heal library.

Usage (from repo root, with DB available):
  python scripts/cleanup_progress_library.py
  python scripts/cleanup_progress_library.py --dry-run
"""

from __future__ import annotations

import argparse
import os
import sys

# Allow running from repo root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize Progress library keys/titles")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Count changes without committing",
    )
    args = parser.parse_args()

    from app.db.session import get_engine, init_db
    from app.db.session import _SessionLocal
    from app.media.progress_fixup import normalize_library

    init_db()
    get_engine()
    assert _SessionLocal is not None
    db = _SessionLocal()
    try:
        result = normalize_library(db, dry_run=args.dry_run)
        print("ok:", result.get("ok"))
        print("dry_run:", result.get("dry_run"))
        print("updated_logs:", result.get("updated_logs"))
        print("study_reclassified:", result.get("study_reclassified"))
        print("targets:", result.get("targets"))
        print("removed_catalog:", result.get("removed_catalog"))
        for s in result.get("samples") or []:
            print(" ", s)
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
