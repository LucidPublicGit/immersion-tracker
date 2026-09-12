"""Tadoku username/password auth + encrypted credentials (mocked HTTP)."""
from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest


@pytest.fixture()
def cred_paths(tmp_path, monkeypatch):
    from app.tadoku import credentials as cred

    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(cred, "_data_dir", lambda: data)
    return data


@pytest.fixture()
def cookie_path(tmp_path, monkeypatch):
    from app.tadoku import session as sess

    path = tmp_path / "tadoku_session.cookie"
    monkeypatch.setattr(sess, "cookie_file_path", lambda: path)
    return path


def test_missing_credentials_rejected_before_network(monkeypatch):
    from app.tadoku.auth import TadokuAuthClient, TadokuAuthenticationError

    calls = []

    def boom(*a, **k):
        calls.append(1)
        raise AssertionError("network should not be called")

    monkeypatch.setattr(httpx.Client, "get", boom)
    with pytest.raises(TadokuAuthenticationError, match="not configured"):
        TadokuAuthClient("", "x")
    with pytest.raises(TadokuAuthenticationError, match="not configured"):
        TadokuAuthClient("user", "")
    assert calls == []


def test_login_flow_extracts_csrf_and_posts_form(monkeypatch):
    from app.tadoku.auth import TadokuAuthClient

    monkeypatch.setattr("app.tadoku.auth.live_auth_blocked", lambda: False)

    class FakeResp:
        def __init__(self, status_code=200, payload=None, set_cookie=None):
            self.status_code = status_code
            self._payload = payload or {}
            self._set_cookie = set_cookie
            self.is_success = 200 <= status_code < 300
            self.text = json.dumps(self._payload)

        def raise_for_status(self):
            if self.status_code >= 400:
                raise httpx.HTTPStatusError("err", request=None, response=self)

        def json(self):
            return self._payload

    posts = []

    class FakeClient:
        def __init__(self, *a, **k):
            self.cookies = httpx.Cookies()
            self.headers = {}

        def get(self, url, **kwargs):
            assert "self-service/login/browser" in url
            assert kwargs.get("headers", {}).get("Accept") == "application/json"
            return FakeResp(
                payload={
                    "ui": {
                        "action": (
                            "https://account.tadoku.app/kratos/self-service/login"
                            "?flow=abc"
                        ),
                        "nodes": [
                            {
                                "attributes": {
                                    "name": "csrf_token",
                                    "value": "csrf-secret",
                                }
                            }
                        ],
                    }
                }
            )

        def post(self, url, **kwargs):
            posts.append({"url": url, "data": kwargs.get("data"), "headers": kwargs.get("headers")})
            self.cookies.set(
                "ory_kratos_session",
                "session-tok",
                domain=".tadoku.app",
                path="/",
            )
            return FakeResp(status_code=200, payload={"session": {}})

        def close(self):
            pass

        def request(self, *a, **k):
            raise AssertionError("not used in this test")

    monkeypatch.setattr(httpx, "Client", FakeClient)

    with TadokuAuthClient("alice@example.com", "s3cret") as auth:
        header = auth.login()
    assert header == "ory_kratos_session=session-tok"
    assert len(posts) == 1
    data = posts[0]["data"]
    assert data["identifier"] == "alice@example.com"
    assert data["password"] == "s3cret"
    assert data["method"] == "password"
    assert data["csrf_token"] == "csrf-secret"
    assert posts[0]["url"].startswith(
        "https://account.tadoku.app/kratos/self-service/login?"
    )


def test_untrusted_action_rejected(monkeypatch):
    from app.tadoku.auth import TadokuAuthClient, TadokuAuthenticationError

    monkeypatch.setattr("app.tadoku.auth.live_auth_blocked", lambda: False)

    class FakeResp:
        status_code = 200
        is_success = True

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "ui": {
                    "action": "https://evil.example/steal",
                    "nodes": [
                        {"attributes": {"name": "csrf_token", "value": "x"}}
                    ],
                }
            }

    class FakeClient:
        def __init__(self, *a, **k):
            self.cookies = httpx.Cookies()

        def get(self, *a, **k):
            return FakeResp()

        def post(self, *a, **k):
            raise AssertionError("must not post to untrusted action")

        def close(self):
            pass

    monkeypatch.setattr(httpx, "Client", FakeClient)
    with TadokuAuthClient("u", "p") as auth:
        with pytest.raises(TadokuAuthenticationError, match="invalid login flow"):
            auth.login()


def test_missing_csrf_rejected(monkeypatch):
    from app.tadoku.auth import TadokuAuthClient, TadokuAuthenticationError

    monkeypatch.setattr("app.tadoku.auth.live_auth_blocked", lambda: False)

    class FakeResp:
        status_code = 200
        is_success = True

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "ui": {
                    "action": (
                        "https://account.tadoku.app/kratos/self-service/login?flow=1"
                    ),
                    "nodes": [],
                }
            }

    class FakeClient:
        def __init__(self, *a, **k):
            self.cookies = httpx.Cookies()

        def get(self, *a, **k):
            return FakeResp()

        def post(self, *a, **k):
            raise AssertionError("no csrf")

        def close(self):
            pass

    monkeypatch.setattr(httpx, "Client", FakeClient)
    with TadokuAuthClient("u", "p") as auth:
        with pytest.raises(TadokuAuthenticationError, match="CSRF"):
            auth.login()


def test_invalid_credentials_safe_error(monkeypatch):
    from app.tadoku.auth import TadokuAuthClient, TadokuAuthenticationError

    monkeypatch.setattr("app.tadoku.auth.live_auth_blocked", lambda: False)

    class FlowResp:
        status_code = 200
        is_success = True

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "ui": {
                    "action": (
                        "https://account.tadoku.app/kratos/self-service/login?flow=1"
                    ),
                    "nodes": [
                        {"attributes": {"name": "csrf_token", "value": "csrf"}}
                    ],
                }
            }

    class BadLogin:
        status_code = 400
        is_success = False
        text = "password wrong secret-should-not-leak"

    class FakeClient:
        def __init__(self, *a, **k):
            self.cookies = httpx.Cookies()

        def get(self, *a, **k):
            return FlowResp()

        def post(self, *a, **k):
            return BadLogin()

        def close(self):
            pass

    monkeypatch.setattr(httpx, "Client", FakeClient)
    with TadokuAuthClient("u", "super-secret-password") as auth:
        with pytest.raises(TadokuAuthenticationError) as ei:
            auth.login()
    msg = str(ei.value)
    assert "super-secret-password" not in msg
    assert "login failed" in msg.lower()


def test_request_reuses_cookie_without_login(monkeypatch):
    from app.tadoku.auth import TadokuAuthClient

    monkeypatch.setattr("app.tadoku.auth.live_auth_blocked", lambda: False)
    login_calls = []

    class FakeResp:
        def __init__(self, code=200):
            self.status_code = code
            self.is_success = code < 400
            self.text = "{}"

        def json(self):
            return {"units": []}

    class FakeClient:
        def __init__(self, *a, **k):
            self.cookies = httpx.Cookies()
            self.cookies.set(
                "ory_kratos_session", "seeded", domain=".tadoku.app", path="/"
            )

        def get(self, *a, **k):
            login_calls.append("get")
            return FakeResp()

        def post(self, *a, **k):
            login_calls.append("post")
            return FakeResp()

        def request(self, method, url, **kwargs):
            login_calls.append(("request", method, url))
            return FakeResp(200)

        def close(self):
            pass

    monkeypatch.setattr(httpx, "Client", FakeClient)
    with TadokuAuthClient("u", "p", session_cookie="ory_kratos_session=seeded") as auth:
        # Re-seed after Client init (FakeClient replaces jar)
        auth.client.cookies.set(
            "ory_kratos_session", "seeded", domain=".tadoku.app", path="/"
        )
        r = auth.request("GET", "logs/configuration-options")
    assert r.status_code == 200
    assert not any(c in ("get", "post") for c in login_calls)
    assert any(isinstance(c, tuple) and c[0] == "request" for c in login_calls)


def test_request_401_relogin_once(monkeypatch):
    from app.tadoku.auth import TadokuAuthClient

    monkeypatch.setattr("app.tadoku.auth.live_auth_blocked", lambda: False)
    state = {"n": 0, "logins": 0}

    class FakeResp:
        def __init__(self, code=200, payload=None):
            self.status_code = code
            self.is_success = 200 <= code < 300
            self._payload = payload or {}
            self.text = json.dumps(self._payload)

        def raise_for_status(self):
            if self.status_code >= 400:
                raise httpx.HTTPStatusError("e", request=None, response=self)

        def json(self):
            return self._payload

    class FakeClient:
        def __init__(self, *a, **k):
            self.cookies = httpx.Cookies()
            self.cookies.set(
                "ory_kratos_session", "old", domain=".tadoku.app", path="/"
            )

        def get(self, *a, **k):
            state["logins"] += 1
            return FakeResp(
                payload={
                    "ui": {
                        "action": (
                            "https://account.tadoku.app/kratos/self-service/login"
                            "?flow=1"
                        ),
                        "nodes": [
                            {"attributes": {"name": "csrf_token", "value": "c"}}
                        ],
                    }
                }
            )

        def post(self, *a, **k):
            self.cookies.set(
                "ory_kratos_session", "new", domain=".tadoku.app", path="/"
            )
            return FakeResp(200, {"ok": True})

        def request(self, method, url, **kwargs):
            state["n"] += 1
            if state["n"] == 1:
                return FakeResp(401)
            return FakeResp(200, {"units": []})

        def close(self):
            pass

    monkeypatch.setattr(httpx, "Client", FakeClient)
    with TadokuAuthClient("u", "p", session_cookie="ory_kratos_session=old") as auth:
        auth.client.cookies.set(
            "ory_kratos_session", "old", domain=".tadoku.app", path="/"
        )
        r = auth.request("GET", "logs/configuration-options")
    assert r.status_code == 200
    assert state["logins"] == 1
    assert state["n"] == 2


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
    cookie_path.write_text("ory_kratos_session=old\n", encoding="utf-8")

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
        return "ory_kratos_session=fresh-tok"

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
    assert "ory_kratos_session=fresh-tok" in cookie_path.read_text(encoding="utf-8")


def test_failed_refresh_keeps_previous_cookie(
    client, cred_paths, cookie_path, monkeypatch
):
    from app.tadoku import credentials as cred
    from app.tadoku import session as sess
    from app.tadoku.auth import TadokuAuthenticationError

    monkeypatch.setattr(cred, "_data_dir", lambda: cred_paths)
    monkeypatch.setattr(sess, "cookie_file_path", lambda: cookie_path)
    cred.save_credentials("erin", "pw")
    cookie_path.write_text("ory_kratos_session=keep-me\n", encoding="utf-8")

    def boom(*a, **k):
        raise TadokuAuthenticationError("Tadoku login failed; check the saved username and password")

    monkeypatch.setattr("app.tadoku.auth.login_and_get_cookie", boom)

    r = client.post("/api/tadoku/auth/refresh")
    assert r.status_code == 400
    assert cookie_path.read_text(encoding="utf-8").strip() == "ory_kratos_session=keep-me"


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
    cookie_path.write_text("ory_kratos_session=x\n", encoding="utf-8")

    r = client.post(
        "/api/tadoku/credentials",
        json={"username": "new", "password": ""},
    )
    assert r.status_code == 200
    assert not cookie_path.is_file() or not cookie_path.read_text(encoding="utf-8").strip()
