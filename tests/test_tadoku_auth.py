"""Tadoku username/password auth + encrypted credentials (mocked HTTP)."""
from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest


@pytest.fixture(autouse=True)
def cred_paths(tmp_path, monkeypatch):
    from app.tadoku import credentials as cred

    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(cred, "_data_dir", lambda: data)
    return data


@pytest.fixture(autouse=True)
def cookie_path(tmp_path, monkeypatch):
    from app.tadoku import session as sess

    path = tmp_path / "tadoku_session.cookie"
    monkeypatch.setattr(sess, "cookie_file_path", lambda: path)
    monkeypatch.setattr(sess, "_login_retry_after", 0.0)
    sess.invalidate_session_cache()
    yield path
    sess.invalidate_session_cache()


@pytest.fixture()
def mocked_http(monkeypatch):
    """Exercise actual httpx JSON/header/cookie handling without any network."""
    from app.tadoku import auth

    real_client = httpx.Client
    calls = []

    def install(handler):
        def respond(request):
            calls.append(request)
            return handler(request)

        monkeypatch.setattr(auth.httpx, "Client", lambda **kwargs: real_client(
            transport=httpx.MockTransport(respond), **kwargs
        ))
        monkeypatch.setattr(auth, "live_auth_blocked", lambda: False)
        return calls

    return install


def test_missing_credentials_rejected_before_network(monkeypatch):
    from app.tadoku.auth import TadokuAuthClient, TadokuAuthenticationError

    def boom(*a, **k):
        raise AssertionError("HTTP client should not be created")

    monkeypatch.setattr(httpx, "Client", boom)
    for username, password in (("", "x"), ("user", "")):
        with pytest.raises(TadokuAuthenticationError, match="not configured"):
            TadokuAuthClient(username, password)


def test_login_posts_identity_json_and_new_cookie(mocked_http, caplog):
    from app.tadoku.auth import TadokuAuthClient

    def handler(request):
        assert request.method == "POST"
        assert str(request.url) == "https://tadoku.app/api/internal/identity/login"
        assert request.headers["Content-Type"] == "application/json"
        assert request.headers["Origin"] == "https://tadoku.app"
        assert json.loads(request.content) == {"email": "alice@example.com", "password": "secret-pw"}
        return httpx.Response(200, headers={
            "Set-Cookie": "tadoku_session=secret-token; Domain=tadoku.app; Path=/; Secure; HttpOnly"
        }, json={"account": {"id": "account-id", "email": "private-email"}})

    calls = mocked_http(handler)
    with TadokuAuthClient("alice@example.com", "secret-pw") as auth:
        assert auth.login() == "tadoku_session=secret-token"
    assert len(calls) == 1
    assert not any(secret in caplog.text for secret in ("secret-pw", "secret-token", "private-email"))


@pytest.mark.parametrize("status", [400, 401, 403, 429, 503, 302])
def test_failed_login_never_retried_or_leaks_response(mocked_http, caplog, status):
    from app.tadoku.auth import TadokuAuthClient, TadokuAuthenticationError

    calls = mocked_http(lambda request: httpx.Response(status, headers={
        "Location": "https://evil.example/steal",
        "Set-Cookie": "tadoku_session=response-secret; Domain=tadoku.app; Path=/"
    }, text="response-secret password-secret"))
    with TadokuAuthClient("u", "password-secret") as auth:
        with pytest.raises(TadokuAuthenticationError) as error:
            auth.request("GET", "logs")
        assert not auth.has_session_cookie()
    assert len(calls) == 1
    assert "response-secret" not in str(error.value) + caplog.text
    assert "password-secret" not in str(error.value) + caplog.text
    if status == 429:
        assert "15 minutes" in str(error.value)


@pytest.mark.parametrize("cookie", [None, "ory_kratos_session=old; Domain=tadoku.app; Path=/"])
def test_login_requires_fresh_new_cookie(mocked_http, cookie):
    from app.tadoku.auth import TadokuAuthClient, TadokuAuthenticationError

    calls = mocked_http(lambda request: httpx.Response(
        200, headers={"Set-Cookie": cookie} if cookie else {}, json={"account": {"id": "id"}}
    ))
    with TadokuAuthClient("u", "p", session_cookie="tadoku_session=stale") as auth:
        with pytest.raises(TadokuAuthenticationError, match="did not return"):
            auth.login()
    assert len(calls) == 1


def test_login_transport_error_is_safe(mocked_http, caplog):
    from app.tadoku.auth import TadokuAuthClient, TadokuAuthenticationError

    def handler(request):
        raise httpx.ConnectError("response-secret password-secret", request=request)

    calls = mocked_http(handler)
    with TadokuAuthClient("u", "password-secret") as auth:
        with pytest.raises(TadokuAuthenticationError) as error:
            auth.login()
    assert len(calls) == 1
    assert error.value.__suppress_context__
    assert "response-secret" not in str(error.value) + caplog.text
    assert "password-secret" not in str(error.value) + caplog.text


def test_login_blocked_in_test_mode(mocked_http, monkeypatch):
    from app.tadoku import auth

    calls = mocked_http(lambda request: pytest.fail("must not send request"))
    monkeypatch.setattr(auth, "live_auth_blocked", lambda: True)
    with auth.TadokuAuthClient("u", "p") as client:
        with pytest.raises(auth.TadokuAuthenticationError, match="blocked"):
            client.login()
    assert calls == []


def test_request_reuses_cookie_without_login(mocked_http):
    from app.tadoku.auth import TadokuAuthClient

    def handler(request):
        assert request.method == "GET"
        assert request.headers["Cookie"] == "tadoku_session=seeded"
        return httpx.Response(200)

    calls = mocked_http(handler)
    with TadokuAuthClient("u", "p", "tadoku_session=seeded; ory_kratos_session=obsolete") as auth:
        assert auth.request("GET", "logs").status_code == 200
    assert len(calls) == 1


@pytest.mark.parametrize("retry_status", [200, 401])
def test_request_401_relogin_once(mocked_http, retry_status):
    from app.tadoku.auth import TadokuAuthClient

    def handler(request):
        if request.url.path.endswith("/identity/login"):
            return httpx.Response(200, headers={
                "Set-Cookie": "tadoku_session=fresh; Domain=tadoku.app; Path=/"
            })
        if request.headers["Cookie"] == "tadoku_session=old":
            return httpx.Response(401)
        assert request.headers["Cookie"] == "tadoku_session=fresh"
        return httpx.Response(retry_status)

    calls = mocked_http(handler)
    with TadokuAuthClient("u", "p", "tadoku_session=old") as auth:
        assert auth.request("GET", "logs").status_code == retry_status
    assert [r.method for r in calls] == ["GET", "POST", "GET"]


@pytest.mark.parametrize("status", [403, 429, 500])
def test_request_reauthenticates_only_on_401(mocked_http, status):
    from app.tadoku.auth import TadokuAuthClient

    calls = mocked_http(lambda request: httpx.Response(status))
    with TadokuAuthClient("u", "p", "tadoku_session=old") as auth:
        assert auth.request("GET", "logs").status_code == status
    assert len(calls) == 1


def test_failed_relogin_stops_request_retry(mocked_http):
    from app.tadoku.auth import TadokuAuthClient, TadokuAuthenticationError

    calls = mocked_http(lambda request: httpx.Response(401))
    with TadokuAuthClient("u", "p", "tadoku_session=old") as auth:
        with pytest.raises(TadokuAuthenticationError):
            auth.request("POST", "logs", json={"amount": 1})
    assert [r.method for r in calls] == ["POST", "POST"]
    assert calls[0].url.path.endswith("/immersion/logs")
    assert calls[1].url.path.endswith("/identity/login")


@pytest.mark.parametrize("value,expected", [
    ("raw-token", "tadoku_session=raw-token"),
    ("Cookie: tadoku_session=token; other=x", "tadoku_session=token"),
    ("ory_kratos_session=old", ""),
    ("Cookie: ory_kratos_session=old; other=x", ""),
    ("unknown=token", ""),
    ("tadoku_session=", ""),
    ("tadoku_session=x\r\nInjected: yes", ""),
])
def test_cookie_normalization_rejects_legacy(value, expected):
    from app.tadoku.auth import format_session_cookie_header

    assert format_session_cookie_header(value) == expected


def test_ensure_cookie_reuses_cookie_without_credentials(cred_paths, monkeypatch):
    from app.tadoku.auth import ensure_session_cookie

    monkeypatch.setattr("app.tadoku.auth.login_and_get_cookie", lambda *args: pytest.fail("no login"))
    assert ensure_session_cookie(existing_cookie="tadoku_session=cached") == "tadoku_session=cached"


def test_ensure_cookie_does_not_relabel_legacy(cred_paths):
    from app.tadoku.auth import ensure_session_cookie, TadokuAuthenticationError

    with pytest.raises(TadokuAuthenticationError, match="not configured"):
        ensure_session_cookie(existing_cookie="ory_kratos_session=obsolete")


def test_credentials_encrypt_and_never_return_password(cred_paths):
    from app.tadoku.credentials import (
        credentials_configured,
        credentials_public_dict,
        load_credentials,
        save_credentials,
    )

    save_credentials("bob", "hunter2")
    user, pw = load_credentials()
    assert user == "bob"
    assert pw == "hunter2"
    assert credentials_configured() is True
    public = credentials_public_dict()
    assert public["tadoku_username"] == "bob"
    assert public["tadoku_password_configured"] is True
    assert "hunter2" not in json.dumps(public)
    assert "password" not in public
    raw = (cred_paths / "tadoku_credentials.json").read_text(encoding="utf-8")
    assert "hunter2" not in raw
    assert "password_enc" in raw


def test_blank_password_preserves_saved(cred_paths):
    from app.tadoku.credentials import load_credentials, save_credentials

    save_credentials("bob", "hunter2")
    save_credentials("bob", "", preserve_password_if_blank=True)
    user, pw = load_credentials()
    assert user == "bob"
    assert pw == "hunter2"


def test_clear_credentials(cred_paths):
    from app.tadoku.credentials import (
        clear_credentials,
        credentials_configured,
        save_credentials,
    )

    save_credentials("bob", "hunter2")
    assert clear_credentials() is True
    assert credentials_configured() is False


def test_settings_returns_username_not_password(client, cred_paths, monkeypatch):
    from app.tadoku import credentials as cred

    monkeypatch.setattr(cred, "_data_dir", lambda: cred_paths)
    cred.save_credentials("carol", "topsecret")
    r = client.get("/api/tadoku/settings")
    assert r.status_code == 200
    body = r.json()
    assert body["tadoku_username"] == "carol"
    assert body["tadoku_password_configured"] is True
    assert body["tadoku_credentials_configured"] is True
    dumped = json.dumps(body)
    assert "topsecret" not in dumped
    assert "password_enc" not in dumped
    assert body.get("password") is None
    assert body.get("tadoku_password") is None
    assert body.get("session_cookie") is None


def test_post_credentials_and_clear(client, cred_paths, cookie_path, monkeypatch):
    from app.tadoku import credentials as cred
    from app.tadoku import session as sess

    monkeypatch.setattr(cred, "_data_dir", lambda: cred_paths)
    monkeypatch.setattr(sess, "cookie_file_path", lambda: cookie_path)
    cookie_path.write_text("tadoku_session=old\n", encoding="utf-8")

    r = client.post(
        "/api/tadoku/credentials",
        json={"username": "dave", "password": "pw1"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["tadoku_username"] == "dave"
    assert body["tadoku_credentials_configured"] is True
    assert "pw1" not in json.dumps(body)
    # Changing credentials invalidates session cookie
    assert not cookie_path.is_file() or not cookie_path.read_text().strip()

    # Blank password preserves
    r2 = client.post(
        "/api/tadoku/credentials",
        json={"username": "dave", "password": ""},
    )
    assert r2.status_code == 200
    assert cred.load_credentials()[1] == "pw1"

    r3 = client.delete("/api/tadoku/credentials")
    assert r3.status_code == 200
    assert r3.json()["tadoku_credentials_configured"] is False
    assert cred.credentials_configured() is False


def test_refresh_rejects_missing_credentials(client, cred_paths, monkeypatch):
    from app.tadoku import credentials as cred

    monkeypatch.setattr(cred, "_data_dir", lambda: cred_paths)
    r = client.post("/api/tadoku/auth/refresh")
    assert r.status_code == 400
    assert "not configured" in r.json()["detail"].lower()


def test_refresh_persists_cookie_and_hides_secrets(
    client, cred_paths, cookie_path, monkeypatch
):
    from app.tadoku import credentials as cred
    from app.tadoku import session as sess

    monkeypatch.setattr(cred, "_data_dir", lambda: cred_paths)
    monkeypatch.setattr(sess, "cookie_file_path", lambda: cookie_path)
    cred.save_credentials("erin", "pw")

    def fake_login(username, password):
        assert username == "erin"
        assert password == "pw"
        return "tadoku_session=fresh-tok"

    monkeypatch.setattr(
        "app.tadoku.auth.login_and_get_cookie",
        fake_login,
    )
    # Avoid live probe
    monkeypatch.setattr(
        sess,
        "check_session",
        lambda force=False: sess.SessionHealth(
            status="ok",
            configured=True,
            source="file",
            detail="ok",
            live_submit=True,
        ),
    )

    r = client.post("/api/tadoku/auth/refresh")
    assert r.status_code == 200
    body = r.json()
    assert body["authenticated"] is True
    assert "fresh-tok" not in json.dumps(body)
    assert "pw" not in json.dumps(body)
    assert "tadoku_session=fresh-tok" in cookie_path.read_text(encoding="utf-8")


def test_failed_refresh_keeps_previous_cookie(
    client, cred_paths, cookie_path, monkeypatch
):
    from app.tadoku import credentials as cred
    from app.tadoku import session as sess
    from app.tadoku.auth import TadokuAuthenticationError

    monkeypatch.setattr(cred, "_data_dir", lambda: cred_paths)
    monkeypatch.setattr(sess, "cookie_file_path", lambda: cookie_path)
    cred.save_credentials("erin", "pw")
    cookie_path.write_text("tadoku_session=keep-me\n", encoding="utf-8")

    def boom(*a, **k):
        raise TadokuAuthenticationError("Tadoku login failed; check the saved username and password")

    monkeypatch.setattr("app.tadoku.auth.login_and_get_cookie", boom)

    r = client.post("/api/tadoku/auth/refresh")
    assert r.status_code == 400
    assert cookie_path.read_text(encoding="utf-8").strip() == "tadoku_session=keep-me"


def test_queue_ui_has_refresh_button():
    from app.web.queue_ui import QUEUE_JS

    src = QUEUE_JS
    assert "Refresh Tadoku login" in src
    assert "refreshTadokuLogin" in src
    assert "btn-refresh-tadoku-login" in src
    assert "Refreshing…" in src
    assert "btn.disabled=false" in src
    assert 'autocomplete="username"' in src
    assert 'autocomplete="current-password"' in src
    # Cookie paste UI removed
    assert "paste Cookie header" not in src


def test_queue_ui_recent_logs_link_to_tadoku():
    """Recent pushed rows open their log page on tadoku.app."""
    from app.web.queue_ui import QUEUE_JS

    src = QUEUE_JS
    assert "tadokuLogPageUrl" in src
    assert "https://tadoku.app/logs/" in src
    assert "openTadokuLog" in src
    assert "is-link" in src
    assert "tadoku-log-link" in src


def test_changing_username_invalidates_cookie(
    client, cred_paths, cookie_path, monkeypatch
):
    from app.tadoku import credentials as cred
    from app.tadoku import session as sess

    monkeypatch.setattr(cred, "_data_dir", lambda: cred_paths)
    monkeypatch.setattr(sess, "cookie_file_path", lambda: cookie_path)
    cred.save_credentials("old", "pw")
    cookie_path.write_text("tadoku_session=x\n", encoding="utf-8")

    r = client.post(
        "/api/tadoku/credentials",
        json={"username": "new", "password": ""},
    )
    assert r.status_code == 200
    assert not cookie_path.is_file() or not cookie_path.read_text(encoding="utf-8").strip()
