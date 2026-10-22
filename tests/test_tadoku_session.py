"""Tadoku session cookie resolution + health (no live HTTP by default)."""
from __future__ import annotations

from pathlib import Path

import httpx
import pytest


@pytest.fixture(autouse=True)
def isolated_runtime(tmp_path, monkeypatch):
    from app.tadoku import credentials, session

    monkeypatch.setattr(credentials, "_data_dir", lambda: tmp_path / "credentials")
    monkeypatch.setattr(session, "cookie_file_path", lambda: tmp_path / "session.cookie")
    monkeypatch.setattr(session, "_login_retry_after", 0.0)
    session.invalidate_session_cache()
    yield
    session.invalidate_session_cache()


def test_resolve_cookie_prefers_file(tmp_path, monkeypatch):
    from app.tadoku import session as sess

    cookie_path = tmp_path / "tadoku_session.cookie"
    cookie_path.write_text("tadoku_session=abc\n", encoding="utf-8")
    monkeypatch.setattr(sess, "cookie_file_path", lambda: cookie_path)
    monkeypatch.setenv("TADOKU_COOKIE", "tadoku_session=xyz")
    assert sess.resolve_cookie() == "tadoku_session=abc"
    assert sess.cookie_source() == "file"


def test_resolve_cookie_falls_back_to_env(tmp_path, monkeypatch):
    from app.tadoku import session as sess

    cookie_path = tmp_path / "tadoku_session.cookie"
    monkeypatch.setattr(sess, "cookie_file_path", lambda: cookie_path)
    monkeypatch.setenv("TADOKU_COOKIE", "tadoku_session=xyz")
    # Clear yaml/session leftovers from settings if present
    from app.core.config import get_settings

    get_settings().yaml_config.tadoku.session_cookie = ""
    assert sess.resolve_cookie() == "tadoku_session=xyz"
    assert sess.cookie_source() == "env"


def test_save_cookie_strips_cookie_prefix(tmp_path, monkeypatch):
    from app.tadoku import session as sess

    cookie_path = tmp_path / "tadoku_session.cookie"
    monkeypatch.setattr(sess, "cookie_file_path", lambda: cookie_path)
    sess.save_cookie("Cookie: tadoku_session=tok; other=1")
    assert cookie_path.read_text(encoding="utf-8").strip() == "tadoku_session=tok"


def test_check_session_skipped_under_pytest(tmp_path, monkeypatch):
    from app.core.config import get_settings
    from app.tadoku import session as sess

    cookie_path = tmp_path / "tadoku_session.cookie"
    monkeypatch.setattr(sess, "cookie_file_path", lambda: cookie_path)
    monkeypatch.setenv("TADOKU_COOKIE", "tadoku_session=fake")
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
    monkeypatch.setenv("TADOKU_COOKIE", "tadoku_session=fake")
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
        json={"cookie": "tadoku_session=newtok; path=/"},
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
    cookie_path.write_text("tadoku_session=dead\n", encoding="utf-8")
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


@pytest.fixture()
def mocked_probe(monkeypatch):
    from app.core.config import get_settings
    from app.tadoku import session

    real_client = httpx.Client
    calls = []
    get_settings().yaml_config.tadoku.live_submit = True
    get_settings().yaml_config.tadoku.api_base = "https://tadoku.app/api/internal/immersion"
    monkeypatch.setattr(session, "_live_submit_blocked", lambda: False)

    def install(response):
        def handler(request):
            calls.append(request)
            assert request.method == "GET"
            assert str(request.url) == "https://tadoku.app/api/internal/identity/session"
            assert request.headers["Cookie"] == "tadoku_session=token"
            return response

        monkeypatch.setattr(session.httpx, "Client", lambda **kwargs: real_client(
            transport=httpx.MockTransport(handler), **kwargs
        ))
        return calls

    return install


@pytest.mark.parametrize("payload,expected", [
    ({"account": {"id": "id", "email": "private-response"}}, "ok"),
    ({"account": None, "account_app": "v2"}, "expired"),
    ({}, "error"),
    ({"account": {}}, "error"),
    ({"account": []}, "error"),
    ([], "error"),
])
def test_identity_session_checks_account_even_on_200(monkeypatch, mocked_probe, payload, expected, caplog):
    from app.tadoku import session

    monkeypatch.setenv("TADOKU_COOKIE", "tadoku_session=token")
    calls = mocked_probe(httpx.Response(200, json=payload))
    health = session.check_session(force=True)
    assert health.status == expected
    assert health.http_status == 200 or expected == "error"
    assert len(calls) == 1
    assert session.check_session().status == expected
    assert len(calls) == 1
    assert "private-response" not in caplog.text


@pytest.mark.parametrize("status,expected", [(401, "expired"), (403, "error"), (429, "error"), (503, "error"), (302, "error")])
def test_identity_probe_never_logs_in_or_follows_redirect(monkeypatch, mocked_probe, status, expected, caplog):
    from app.tadoku import session

    monkeypatch.setenv("TADOKU_COOKIE", "tadoku_session=token")
    calls = mocked_probe(httpx.Response(status, headers={"Location": "https://evil.example"}, text="response-secret"))
    assert session.check_session(force=True).status == expected
    assert len(calls) == 1
    assert "response-secret" not in caplog.text


def test_health_without_cookie_never_logs_in(monkeypatch):
    from app.core.config import get_settings
    from app.tadoku import credentials, session

    get_settings().yaml_config.tadoku.live_submit = True
    credentials.save_credentials("email@example.com", "pw")
    monkeypatch.setattr(session, "_live_submit_blocked", lambda: False)
    monkeypatch.setattr(session.httpx, "Client", lambda **kwargs: pytest.fail("health must not log in"))
    assert session.check_session(force=True).status == "missing"


def test_resolve_skips_obsolete_file_for_new_env_cookie(tmp_path, monkeypatch):
    from app.tadoku import session

    path = session.cookie_file_path()
    path.write_text("ory_kratos_session=obsolete")
    monkeypatch.setenv("TADOKU_COOKIE", "tadoku_session=current")
    assert session.resolve_cookie() == "tadoku_session=current"
    assert session.cookie_source() == "env"


def test_only_obsolete_cookies_are_unconfigured(monkeypatch):
    from app.core.config import get_settings
    from app.tadoku import session

    session.cookie_file_path().write_text("ory_kratos_session=file")
    monkeypatch.setenv("TADOKU_COOKIE", "ory_kratos_session=env")
    get_settings().yaml_config.tadoku.session_cookie = "ory_kratos_session=config"
    assert session.resolve_cookie() == ""
    assert session.cookie_source() == "none"


def test_save_rejects_legacy_without_changing_previous_file():
    from app.tadoku import session

    session.save_cookie("tadoku_session=previous")
    with pytest.raises(ValueError, match="tadoku_session"):
        session.save_cookie("Cookie: ory_kratos_session=obsolete")
    assert session.cookie_file_path().read_text().strip() == "tadoku_session=previous"


def test_save_cookie_is_private_before_write_and_after_replace(monkeypatch):
    import os
    import stat
    from app.tadoku import session

    path = session.cookie_file_path()
    path.write_text("tadoku_session=old")
    path.chmod(0o644)
    real_fdopen = os.fdopen

    def private_fdopen(fd, *args, **kwargs):
        assert stat.S_IMODE(os.fstat(fd).st_mode) == 0o600
        return real_fdopen(fd, *args, **kwargs)

    monkeypatch.setattr(session.os, "fdopen", private_fdopen)
    session.save_cookie("tadoku_session=new")
    assert path.read_text().strip() == "tadoku_session=new"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert not list(path.parent.glob(".tadoku-session-*"))


def test_save_failure_preserves_previous_cookie(monkeypatch):
    from app.tadoku import session

    session.save_cookie("tadoku_session=old")

    def fail(*args):
        raise OSError("replace failed")

    monkeypatch.setattr(session.os, "replace", fail)
    with pytest.raises(OSError, match="replace failed"):
        session.save_cookie("tadoku_session=new")
    assert session.cookie_file_path().read_text().strip() == "tadoku_session=old"
    assert not list(session.cookie_file_path().parent.glob(".tadoku-session-*"))


def test_ensure_session_reuses_cookie_without_login(monkeypatch):
    from app.tadoku import session

    session.save_cookie("tadoku_session=cached")
    monkeypatch.setattr("app.tadoku.auth.ensure_session_cookie", lambda **kwargs: pytest.fail("no login"))
    assert session.ensure_session() == "tadoku_session=cached"


def test_ensure_session_saves_successful_login(monkeypatch):
    from app.tadoku import credentials, session

    credentials.save_credentials("email@example.com", "pw")
    calls = []

    def login(**kwargs):
        calls.append(kwargs)
        return "tadoku_session=fresh"

    monkeypatch.setattr("app.tadoku.auth.ensure_session_cookie", login)
    assert session.ensure_session() == "tadoku_session=fresh"
    assert session.ensure_session() == "tadoku_session=fresh"
    assert len(calls) == 1


def test_automatic_login_failure_cooldown_survives_health_invalidation(monkeypatch):
    from app.tadoku import auth, credentials, session

    credentials.save_credentials("email@example.com", "pw")
    clock = [100.0]
    calls = []
    monkeypatch.setattr(session.time, "monotonic", lambda: clock[0])

    def fail(**kwargs):
        calls.append(kwargs)
        raise auth.TadokuAuthenticationError("login failed")

    monkeypatch.setattr(auth, "ensure_session_cookie", fail)
    with pytest.raises(auth.TadokuAuthenticationError, match="login failed"):
        session.ensure_session()
    for force_login in (False, True):
        session.invalidate_session_cache()
        with pytest.raises(auth.TadokuAuthenticationError, match="paused"):
            session.ensure_session(force_login=force_login)
    assert len(calls) == 1
    clock[0] += 901
    with pytest.raises(auth.TadokuAuthenticationError, match="login failed"):
        session.ensure_session()
    assert len(calls) == 2


def test_failed_forced_login_preserves_cookie_and_starts_cooldown(monkeypatch):
    from app.tadoku import auth, credentials, session

    credentials.save_credentials("email@example.com", "pw")
    session.save_cookie("tadoku_session=previous")

    def fail(**kwargs):
        raise auth.TadokuAuthenticationError("login failed")

    monkeypatch.setattr(auth, "ensure_session_cookie", fail)
    with pytest.raises(auth.TadokuAuthenticationError):
        session.ensure_session(force_login=True)
    assert session.resolve_cookie() == "tadoku_session=previous"
    assert session._login_retry_after > 0


def test_explicit_refresh_bypasses_cooldown_and_resets_it(monkeypatch):
    from app.tadoku import auth, credentials, session

    credentials.save_credentials("email@example.com", "pw")
    monkeypatch.setattr(session, "_login_retry_after", float("inf"))
    monkeypatch.setattr(auth, "login_and_get_cookie", lambda *args: "tadoku_session=fresh")
    assert session.refresh_login()["authenticated"] is True
    assert session.resolve_cookie() == "tadoku_session=fresh"
    assert session._login_retry_after == 0


def test_credential_change_clears_login_cooldown(monkeypatch):
    from app.tadoku import session

    monkeypatch.setattr(session, "_login_retry_after", float("inf"))
    session.invalidate_saved_session()
    assert session._login_retry_after == 0


def test_refresh_does_not_claim_authenticated_on_null_account(monkeypatch, mocked_probe):
    from app.tadoku import auth, credentials, session

    credentials.save_credentials("email@example.com", "pw")
    monkeypatch.setattr(auth, "login_and_get_cookie", lambda *args: "tadoku_session=token")
    mocked_probe(httpx.Response(200, json={"account": None}))
    result = session.refresh_login()
    assert result["authenticated"] is False
    assert result["session_status"] == "expired"
