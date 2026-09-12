"""Quick local smoke check."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

td = tempfile.mkdtemp()
db = Path(td) / "s.db"
os.environ["DATABASE_URL"] = f"sqlite:///{db.as_posix()}"
os.environ["WEBHOOK_SECRET"] = ""
# Never live-post to tadoku.app from smoke checks
os.environ["TADOKU_COOKIE"] = ""
os.environ["TADOKU_SESSION_COOKIE"] = ""
os.environ["IMMERSION_TADOKU_DRY_RUN"] = "1"

from app.core.config import reload_settings  # noqa: E402
from app.db.session import init_db, reset_engine  # noqa: E402

reload_settings()
reset_engine()
init_db()

import app.workers.scheduler as scheduler  # noqa: E402

scheduler.start_scheduler = lambda: None  # type: ignore
scheduler.stop_scheduler = lambda: None  # type: ignore

from app.main import app  # noqa: E402

c = TestClient(app)
assert c.get("/api/health").json()["status"] == "ok"
assert c.get("/queue").status_code == 200
assert "Manual Entry" in c.get("/api/sheet-template").json()
r = c.post(
    "/api/webhooks/youtube",
    json={
        "video_id": "smoke",
        "title": "t",
        "channel_id": "UC",
        "duration_seconds": 100,
        "watched_seconds": 95,
        "ratio": 0.95,
    },
)
assert r.status_code == 201 and r.json()["accepted"]
print("smoke ok")
