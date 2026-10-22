"""Live mode must fail closed when migration invalidates its only cookie."""
import importlib.util
from pathlib import Path

from app.core.config import get_settings
from app.db.models import LogEntry


def test_rejected_cookie_does_not_mark_live_submission_successful(tmp_path, monkeypatch):
    # Load an independent class to exercise its real constructor, not conftest's
    # forced dry-run wrapper. All auth/HTTP paths remain explicitly blocked.
    spec = importlib.util.spec_from_file_location(
        "isolated_tadoku_client", Path(__file__).resolve().parents[1] / "app/tadoku/client.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    settings = get_settings()
    monkeypatch.setattr(settings.yaml_config.tadoku, "live_submit", True)
    monkeypatch.setenv("TADOKU_COOKIE", "ory_kratos_session=obsolete")
    monkeypatch.setattr(module, "live_submit_blocked", lambda: False)
    monkeypatch.setattr(module.TadokuClient, "_cookie", lambda self: "")
    monkeypatch.setattr(module.TadokuClient, "_cookie_for_submit", lambda self: "")
    client = module.TadokuClient(export_dir=str(tmp_path))
    assert client.dry_run is False
    ok, remote_id, error = client.submit(LogEntry(id="synthetic", title="synthetic"))
    assert ok is False
    assert "credentials" in error.lower()
