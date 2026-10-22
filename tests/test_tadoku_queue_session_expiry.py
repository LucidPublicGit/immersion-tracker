"""Queue/session integration: real submit + identity login, mocked HTTP only."""
from __future__ import annotations

import json
import stat
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


API = "https://tadoku.app/api/internal/immersion"
LOGIN = "https://tadoku.app/api/internal/identity/login"
REMOTE_ID = "10000000-0000-4000-8000-000000000001"
UNIT_ID = "20000000-0000-4000-8000-000000000002"
EMAIL = "queue-regression@example.invalid"
PASSWORD = "synthetic-test-password"
EXPIRED = "tadoku_session=synthetic-expired"
FRESH = "tadoku_session=synthetic-fresh"


@pytest.fixture
def isolated_settings(monkeypatch):
    """Install defaults before conftest can load local settings or .env secrets."""
    from app.core import config
    from app.tadoku import client, queue, session

    settings = SimpleNamespace(
        yaml_config=config.AppYamlConfig(), tadoku_cookie=""
    )
    for module in (config, client, queue, session):
        monkeypatch.setattr(module, "get_settings", lambda: settings)
    return settings


@pytest.fixture(autouse=True)
def _never_live_tadoku(isolated_settings, _never_live_tadoku):
    """Wrap the original safety fixture; preserve its forced-dry-run constructor."""
    yield


@pytest.fixture
def queue_session(tmp_path, monkeypatch, isolated_settings, _never_live_tadoku):
    from app.db.models import Base, LogEntry
    from app.tadoku import auth, client, credentials, queue, session

    cookie_path = tmp_path / "session.cookie"
    export_dir = tmp_path / "exports"
    monkeypatch.setattr(credentials, "_data_dir", lambda: tmp_path / "credentials")
    monkeypatch.setattr(session, "cookie_file_path", lambda: cookie_path)
    monkeypatch.setattr(session, "_login_retry_after", 0.0)
    session.invalidate_session_cache()
    # Queue processing otherwise also checks the independent GSM export store.
    monkeypatch.setattr(queue, "_maybe_complete_gsm_export", lambda db: None)
    cfg = isolated_settings.yaml_config.tadoku
    cfg.live_submit = True
    cfg.auto_submit_on_approve = False
    cfg.api_base = API
    credentials.save_credentials(EMAIL, PASSWORD)
    session.save_cookie(EXPIRED)

    calls = []
    real_http_client = httpx.Client

    def install(handler):
        def respond(request):
            calls.append(request)
            return handler(request)

        monkeypatch.setattr(httpx, "Client", lambda **kwargs: real_http_client(
            transport=httpx.MockTransport(respond), **kwargs
        ))
        # Only lift these local guards after every HTTP client uses MockTransport.
        # Keep the environment guard and conftest constructor wrapper in place.
        monkeypatch.setattr(client, "live_submit_blocked", lambda: False)
        monkeypatch.setattr(auth, "live_auth_blocked", lambda: False)
        submitter = client.TadokuClient(export_dir=str(export_dir), dry_run=False)
        assert submitter.dry_run is True  # conftest's wrapper is still effective
        submitter.dry_run = False
        return submitter

    # Fail closed if an unexpected code path constructs a real HTTP transport.
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", lambda *args, **kwargs:
        pytest.fail("session regression attempted an unmocked HTTP request"))
    engine = create_engine(f"sqlite:///{tmp_path / 'queue.db'}")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            entry = LogEntry(
                content_type="anime", title="Synthetic queue regression", source="manual",
                amount=24, unit="minutes", activity="listening", language="ja",
                tadoku_mode="auto", tadoku_status="pending",
            )
            db.add(entry)
            db.commit()
            db.refresh(entry)
            yield SimpleNamespace(
                db=db, entry=entry, calls=calls, install=install,
                cookie_path=cookie_path, export_dir=export_dir,
            )
    finally:
        engine.dispose()
        session.invalidate_session_cache()


def expiry_handler(state, *, login_status=200, return_cookie=True, retry_status=200):
    """Reject the expired cookie; accept only one login and at most one retry."""
    from app.db.models import LogEntry

    def handle(request):
        url = str(request.url)
        if request.method == "GET" and url == f"{API}/logs/configuration-options":
            assert request.headers["Cookie"] == EXPIRED
            return httpx.Response(200, json={"units": [
                {"id": UNIT_ID, "name": "minute", "log_activity_id": 2},
            ]})
        if request.method == "POST" and url == LOGIN:
            assert sum(str(r.url) == LOGIN for r in state.calls) == 1
            assert request.headers["Content-Type"] == "application/json"
            assert request.headers["Origin"] == "https://tadoku.app"
            assert "Cookie" not in request.headers
            assert json.loads(request.content) == {"email": EMAIL, "password": PASSWORD}
            assert not state.cookie_path.exists()  # rejected cookie was discarded
            headers = {"Set-Cookie": f"{FRESH}; Path=/; Secure; HttpOnly"} if return_cookie else {}
            return httpx.Response(login_status, headers=headers, json={"account": {"id": "synthetic-account"}})
        if request.method == "POST" and url == f"{API}/logs":
            # Inspect the committed claim through a separate ORM session.
            with Session(state.db.get_bind()) as observer:
                claimed = observer.get(LogEntry, state.entry.id)
                assert claimed.tadoku_status == "ready"
                assert claimed.tadoku_remote_id.startswith("submitting:")
            body = json.loads(request.content)
            assert body["amount"] == 24
            assert body["unit_id"] == UNIT_ID
            assert body["language_code"] == "jpn"
            if request.headers["Cookie"] == EXPIRED:
                return httpx.Response(401)
            assert request.headers["Cookie"] == FRESH
            assert state.cookie_path.read_text().strip() == FRESH
            assert stat.S_IMODE(state.cookie_path.stat().st_mode) == 0o600
            return httpx.Response(retry_status, json={"id": REMOTE_ID})
        pytest.fail(f"Unexpected mocked Tadoku request: {request.method} {url}")

    return handle


def request_sequence(state):
    return [(r.method, str(r.url)) for r in state.calls]


def test_expired_session_refreshes_once_and_queue_does_not_duplicate(queue_session):
    from app.tadoku import queue

    state = queue_session
    submitter = state.install(expiry_handler(state))
    result = queue.process_ready(state.db, client=submitter)
    state.db.refresh(state.entry)

    assert result["promoted_auto"] == 1
    assert result["pushed"] == 1
    assert result["failed"] == 0
    assert result["results"] == [{
        "id": state.entry.id, "status": "pushed", "remote_id": REMOTE_ID, "note": None,
    }]
    assert state.entry.tadoku_status == "pushed"
    assert state.entry.tadoku_remote_id == REMOTE_ID  # actual API id, never export-*
    assert request_sequence(state) == [
        ("GET", f"{API}/logs/configuration-options"),
        ("POST", f"{API}/logs"), ("POST", LOGIN), ("POST", f"{API}/logs"),
    ]
    posts = [r for r in state.calls if str(r.url) == f"{API}/logs"]
    assert posts[0].content == posts[1].content
    assert state.cookie_path.read_text().strip() == FRESH
    assert stat.S_IMODE(state.cookie_path.stat().st_mode) == 0o600
    exports = list(state.export_dir.glob("*.json"))
    assert len(exports) == 1
    assert json.loads(exports[0].read_text())["api"]["response"]["id"] == REMOTE_ID

    assert queue.process_ready(state.db, client=submitter)["results"] == []
    assert queue.approve(state.db, state.entry.id).tadoku_remote_id == REMOTE_ID
    assert len(state.calls) == 4
    assert len(list(state.export_dir.glob("*.json"))) == 1


@pytest.mark.parametrize("login_status,return_cookie,retry_status,expected_requests", [
    pytest.param(401, True, 200, 3, id="wrong-password"),
    pytest.param(429, True, 200, 3, id="identity-rate-limited"),
    pytest.param(503, True, 200, 3, id="identity-unavailable"),
    pytest.param(200, False, 200, 3, id="identity-without-cookie"),
    pytest.param(200, True, 401, 4, id="retry-still-unauthorized"),
])
def test_failed_session_refresh_releases_queue_claim_for_retry(
    queue_session, login_status, return_cookie, retry_status, expected_requests, caplog,
):
    from app.tadoku import queue, session

    state = queue_session
    submitter = state.install(expiry_handler(
        state, login_status=login_status, return_cookie=return_cookie,
        retry_status=retry_status,
    ))
    result = queue.process_ready(state.db, client=submitter)
    state.db.refresh(state.entry)

    assert result["pushed"] == 0
    assert result["failed"] == 1
    assert result["results"][0]["status"] == "failed"
    assert "HTTP 401" in result["results"][0]["error"]
    assert state.entry.tadoku_status == "failed"
    assert state.entry.tadoku_remote_id is None  # no claim, export id, or remote id
    assert state.entry in queue.list_queue(state.db, status="failed")
    assert "HTTP 401" in state.entry.notes
    expected_sequence = [
        ("GET", f"{API}/logs/configuration-options"),
        ("POST", f"{API}/logs"), ("POST", LOGIN),
    ]
    if expected_requests == 4:
        expected_sequence.append(("POST", f"{API}/logs"))
        assert state.cookie_path.read_text().strip() == FRESH
    else:
        assert not state.cookie_path.exists()
    assert request_sequence(state) == expected_sequence
    assert session.get_cached_session_health().status == "expired"

    # A scheduler pass must leave failed work alone, without further login/POSTs.
    assert queue.process_ready(state.db, client=submitter)["results"] == []
    assert len(state.calls) == expected_requests

    # The real approve path can make this failed row actionable again.
    retried = queue.approve(state.db, state.entry.id)
    assert retried.tadoku_status == "ready"
    assert retried.tadoku_remote_id is None

    if expected_requests == 3:
        # Even explicitly requeued work cannot hammer rejected credentials during
        # the automatic-login cooldown or turn an audit export into "pushed".
        result = queue.process_ready(state.db, client=submitter)
        state.db.refresh(state.entry)
        assert result["failed"] == 1
        assert result["pushed"] == 0
        assert state.entry.tadoku_status == "failed"
        assert state.entry.tadoku_remote_id is None
        assert len(state.calls) == expected_requests
        assert queue.approve(state.db, state.entry.id).tadoku_status == "ready"

    assert not any(secret in caplog.text + state.entry.notes for secret in (
        PASSWORD, EXPIRED, FRESH,
    ))

    def recovered(request):
        if request.method == "GET" and str(request.url) == f"{API}/logs/configuration-options":
            assert request.headers["Cookie"] == FRESH
            return httpx.Response(200, json={"units": [
                {"id": UNIT_ID, "name": "minute", "log_activity_id": 2},
            ]})
        assert request.method == "POST" and str(request.url) == f"{API}/logs"
        assert request.headers["Cookie"] == FRESH
        return httpx.Response(200, json={"id": REMOTE_ID})

    # Simulate successful explicit refresh after the user fixes their credentials.
    session.save_cookie(FRESH)
    submitter = state.install(recovered)
    result = queue.process_ready(state.db, client=submitter)
    state.db.refresh(state.entry)
    assert result["pushed"] == 1
    assert result["failed"] == 0
    assert state.entry.tadoku_status == "pushed"
    assert state.entry.tadoku_remote_id == REMOTE_ID
    assert len(state.calls) == expected_requests + 2
    assert queue.process_ready(state.db, client=submitter)["results"] == []
    assert len(state.calls) == expected_requests + 2
