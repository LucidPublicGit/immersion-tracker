"""Tadoku session cookie resolution + health (no live HTTP by default)."""
from __future__ import annotations

from pathlib import Path

import pytest


def test_resolve_cookie_prefers_file(tmp_path, monkeypatch):
    from app.tadoku import session as sess

    cookie_path = tmp_path / "tadoku_session.cookie"
    cookie_path.write_text("file_cookie=abc\n", encoding="utf-8")
    monkeypatch.setattr(sess, "cookie_file_path", lambda: cookie_path)
    monkeypatch.setenv("TADOKU_COOKIE", "env_cookie=xyz")
    assert sess.resolve_cookie() == "file_cookie=abc"
    assert sess.cookie_source() == "file"


def test_resolve_cookie_falls_back_to_env(tmp_path, monkeypatch):
    from app.tadoku import session as sess

    cookie_path = tmp_path / "tadoku_session.cookie"
    monkeypatch.setattr(sess, "cookie_file_path", lambda: cookie_path)
    monkeypatch.setenv("TADOKU_COOKIE", "env_cookie=xyz")
    # Clear yaml/session leftovers from settings if present
    from app.core.config import get_settings

    get_settings().yaml_config.tadoku.session_cookie = ""
    assert sess.resolve_cookie() == "env_cookie=xyz"
    assert sess.cookie_source() == "env"


def test_save_cookie_strips_cookie_prefix(tmp_path, monkeypatch):
    from app.tadoku import session as sess

    cookie_path = tmp_path / "tadoku_session.cookie"
    monkeypatch.setattr(sess, "cookie_file_path", lambda: cookie_path)
    sess.save_cookie("Cookie: ory_kratos_session=tok; other=1")
    assert cookie_path.read_text(encoding="utf-8").strip() == "ory_kratos_session=tok; other=1"


def test_check_session_skipped_under_pytest(tmp_path, monkeypatch):
    from app.core.config import get_settings
    from app.tadoku import session as sess

    cookie_path = tmp_path / "tadoku_session.cookie"
    monkeypatch.setattr(sess, "cookie_file_path", lambda: cookie_path)
    monkeypatch.setenv("TADOKU_COOKIE", "fake=1")
    get_settings().yaml_config.tadoku.live_submit = True
    sess.invalidate_session_cache()
    h = sess.check_session(force=True)
    # live_submit on + pytest dry-run guard → probe never hits network
    assert h.status == "skipped"
    assert h.configured is True


def test_mark_session_invalid_sets_expired(tmp_path, monkeypatch):
    from app.tadoku import session as sess

    cookie_path = tmp_path / "tadoku_session.cookie"
    monkeypatch.setattr(sess, "cookie_file_path", lambda: cookie_path)
    monkeypatch.setenv("TADOKU_COOKIE", "fake=1")
    h = sess.mark_session_invalid("test 401", http_status=401)
    assert h.status == "expired"
    assert sess.get_cached_session_health() is not None
    assert sess.get_cached_session_health().status == "expired"


def test_settings_includes_session_fields(client):
    r = client.get("/api/tadoku/settings")
    assert r.status_code == 200
    body = r.json()
    assert "session_status" in body
    assert "session_cookie_configured" in body
    assert "session_cookie_source" in body
    # pytest dry-run → probe skipped, not live HTTP
    assert body["session_status"] in ("skipped", "missing", "disabled", "ok", "expired")


def test_post_session_saves_file(client, tmp_path, monkeypatch):
    from app.tadoku import session as sess

    cookie_path = tmp_path / "tadoku_session.cookie"
    monkeypatch.setattr(sess, "cookie_file_path", lambda: cookie_path)
    r = client.post(
        "/api/tadoku/session",
        json={"cookie": "ory_kratos_session=newtok; path=/"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["session_cookie_configured"] is True
    assert cookie_path.is_file()
    assert "newtok" in cookie_path.read_text(encoding="utf-8")
    # Must never echo full secret back in a way that dumps raw cookie field
    assert "cookie" not in body or body.get("cookie") is None


def test_check_session_expired_on_401(tmp_path, monkeypatch):
    from app.core.config import get_settings
    from app.tadoku import session as sess

    cookie_path = tmp_path / "tadoku_session.cookie"
    cookie_path.write_text("ory=dead\n", encoding="utf-8")
    monkeypatch.setattr(sess, "cookie_file_path", lambda: cookie_path)
    # Bypass dry-run guard for this unit test only
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setenv("IMMERSION_TADOKU_DRY_RUN", "0")
    monkeypatch.setattr(sess, "_live_submit_blocked", lambda: False)
    get_settings().yaml_config.tadoku.live_submit = True
    sess.invalidate_session_cache()

    class _Resp:
        status_code = 401
        text = "unauthorized"

    class _Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, *a, **k):
            return _Resp()

    monkeypatch.setattr(sess.httpx, "Client", _Client)
    h = sess.check_session(force=True)
    assert h.status == "expired"
    assert h.http_status == 401
