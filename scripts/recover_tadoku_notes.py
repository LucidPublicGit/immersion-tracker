"""One-shot: recover Demonbane/etc. swallowed by bad merges (uses Tadoku notes)."""
from __future__ import annotations

import json
import os
import sys

# Prefer host data path when run outside Docker
if "DATABASE_URL" not in os.environ:
    os.environ.setdefault("DATABASE_URL", "sqlite:///./data/immersion.db")

from app.core.config import reload_settings
from app.db.session import init_db, reset_engine
from app.db.session import get_engine
from sqlalchemy.orm import sessionmaker

from app.media.progress_fixup import recover_tadoku_notes, refetch_covers


def main() -> int:
    reload_settings()
    reset_engine()
    init_db()
    db = sessionmaker(bind=get_engine())()
    dry = "--dry-run" in sys.argv
    result = recover_tadoku_notes(db, dry_run=dry)
    print(json.dumps({k: v for k, v in result.items() if k != "progress"}, indent=2, ensure_ascii=False))
    if not dry and result.get("recovered"):
        targets = list((result.get("by_target") or {}).keys())
        if targets:
            covers = refetch_covers(db, targets)
            print("covers:", json.dumps(covers.get("results"), indent=2, ensure_ascii=False))
    db.close()
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
