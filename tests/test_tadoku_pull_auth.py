"""Mocked identity migration regressions; never access Tadoku."""
import httpx
import pytest

from app.tadoku import pull


def test_pull_reuses_refreshed_cookie_on_later_pages(monkeypatch):
    seen = []
    real_client = httpx.Client

    def handler(request):
        seen.append(request.headers.get("Cookie"))
        if len(seen) == 1:
            return httpx.Response(401)
        if len(seen) == 2:
            return httpx.Response(200, json={"logs": [{"id": "one"}], "next_page_token": "more"})
        return httpx.Response(200, json={"logs": []})

    refreshes = []
    monkeypatch.setattr(pull, "_cookie", lambda: "tadoku_session=old")
    monkeypatch.setattr(pull, "ensure_session", lambda **kw: refreshes.append(kw) or "tadoku_session=new")
    monkeypatch.setattr(pull.httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
    result = pull.fetch_remote_logs("test-user", page_size=1)
    assert result == [{"id": "one"}]
    assert seen == ["tadoku_session=old", "tadoku_session=new", "tadoku_session=new"]
    assert refreshes == [{"force_login": True}]


def test_pull_does_not_refresh_on_forbidden(monkeypatch):
    real_client = httpx.Client
    monkeypatch.setattr(pull, "_cookie", lambda: "tadoku_session=old")
    def forbidden_refresh(**kwargs):
        pytest.fail("403 must not trigger a login")
    monkeypatch.setattr(pull, "ensure_session", forbidden_refresh)
    monkeypatch.setattr(pull.httpx, "Client", lambda **kw: real_client(
        transport=httpx.MockTransport(lambda r: httpx.Response(403)), **kw))
    with pytest.raises(httpx.HTTPStatusError):
        pull.fetch_remote_logs("test-user")
