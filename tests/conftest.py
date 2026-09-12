from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Isolate test DB before app imports engine
TEST_DB = Path(__file__).resolve().parent / "test_immersion.db"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB.as_posix()}"
os.environ["CONFIG_PATH"] = str(
    Path(__file__).resolve().parent.parent / "config" / "settings.yaml"
)
os.environ["WEBHOOK_SECRET"] = ""

# Never live-post to tadoku.app from the test suite.
# Real TADOKU_COOKIE from .env + live_submit:true would otherwise POST on approve/process.
os.environ["TADOKU_COOKIE"] = ""
os.environ["TADOKU_SESSION_COOKIE"] = ""
os.environ["TADOKU_USERNAME"] = ""
os.environ["TADOKU_PASSWORD"] = ""
os.environ["IMMERSION_TADOKU_DRY_RUN"] = "1"


@pytest.fixture(autouse=True)
def _never_live_tadoku(monkeypatch, tmp_path_factory):
    """
    Hard block live Tadoku submits for every test.

    - Clears session cookies (even if a test sets them)
    - Forces IMMERSION_TADOKU_DRY_RUN (honored by TadokuClient)
    - Writes exports under tmp so tests do not pollute data/tadoku_export
    - Forces yaml live_submit/session_cookie off after settings load
    """
    monkeypatch.setenv("TADOKU_COOKIE", "")
    monkeypatch.setenv("TADOKU_SESSION_COOKIE", "")
    monkeypatch.setenv("TADOKU_USERNAME", "")
    monkeypatch.setenv("TADOKU_PASSWORD", "")
    monkeypatch.setenv("IMMERSION_TADOKU_DRY_RUN", "1")

    export = tmp_path_factory.mktemp("tadoku_export")

    from app.tadoku import client as tadoku_client

    real_init = tadoku_client.TadokuClient.__init__

    def _safe_init(self, export_dir=None, dry_run=None):  # noqa: ANN001
        # Always dry_run; default export into isolated temp dir
        real_init(
            self,
            export_dir=export_dir or str(export),
            dry_run=True,
        )

    monkeypatch.setattr(tadoku_client.TadokuClient, "__init__", _safe_init)

    try:
        from app.core.config import get_settings

        _isolate_runtime_settings(get_settings())
    except Exception:  # noqa: BLE001
        pass

    yield


def _isolate_runtime_settings(settings) -> None:
    """Strip production secrets/filters so tests do not use live Tadoku or personal allowlists."""
    settings.yaml_config.tadoku.live_submit = False
    settings.yaml_config.tadoku.session_cookie = ""
    settings.tadoku_cookie = ""
    # Personal allowlists in settings.yaml must not reject fixture webhooks
    settings.yaml_config.youtube.viewer_allowlist = []
    settings.yaml_config.youtube.channel_allowlist = []
    settings.yaml_config.youtube.channel_blocklist = []
    # Keep status expectations stable regardless of local settings.yaml
    settings.yaml_config.youtube.tadoku_default = "pending"
    settings.yaml_config.plex.tadoku_default = "pending"
    for key in ("youtube", "anime", "show", "book", "manga"):
        if key in settings.yaml_config.content_type_defaults:
            settings.yaml_config.content_type_defaults[key].tadoku_mode = "pending"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path.as_posix()}")
    monkeypatch.setenv("WEBHOOK_SECRET", "")
    monkeypatch.setenv("TADOKU_COOKIE", "")
    monkeypatch.setenv("TADOKU_SESSION_COOKIE", "")
    monkeypatch.setenv("TADOKU_USERNAME", "")
    monkeypatch.setenv("TADOKU_PASSWORD", "")
    monkeypatch.setenv("IMMERSION_TADOKU_DRY_RUN", "1")

    from app.core.config import reload_settings
    from app.db.session import init_db, reset_engine

    settings = reload_settings()
    _isolate_runtime_settings(settings)
    reset_engine()
    init_db()

    # Disable scheduler side effects
    monkeypatch.setattr("app.workers.scheduler.start_scheduler", lambda: None)
    monkeypatch.setattr("app.workers.scheduler.stop_scheduler", lambda: None)

    from app.main import app

    with TestClient(app) as c:
        yield c

    reset_engine()
