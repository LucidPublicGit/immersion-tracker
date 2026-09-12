"""Unit tests for infrequent tadoku upstream path monitor (mocked HTTP)."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest


class _FakeResp:
    def __init__(self, status_code: int, *, text: str = "", json_data=None):
        self.status_code = status_code
        self.text = text
        self._json = json_data

    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json


def test_minimal_probes_ok(tmp_path, monkeypatch):
    from app.tadoku import upstream_monitor as mon

    monkeypatch.setattr(mon, "status_path", lambda: tmp_path / "status.json")

    def fake_get(url, **kwargs):
        if "/leaderboard/1" in url and "api" not in url:
            return _FakeResp(200, text="<html>ok</html>")
        if url.rstrip("/").endswith("/leaderboard") or "/leaderboard?" in url:
            return _FakeResp(
                200,
                json_data={
                    "entries": [
                        {
                            "rank": 1,
                            "score": 1.0,
                            "user_id": "u1",
                            "user_display_name": "A",
                        }
                    ]
                },
            )
        # path-based match for join_api URL without query in url string
        if "/leaderboard" in url:
            return _FakeResp(
                200,
                json_data={
                    "entries": [
                        {
                            "rank": 1,
                            "score": 1.0,
                            "user_id": "u1",
                            "user_display_name": "A",
                        }
                    ]
                },
            )
        return _FakeResp(404, text="nope")

    monkeypatch.setattr(httpx, "get", fake_get)

    report = mon.run_minimal_probes(
        contest_id="00000000-0000-0000-0000-000000000001",
        api_base="https://tadoku.app/api/internal/immersion",
    )
    assert report.ok is True
    assert report.error_count == 0
    assert len(report.probes) == 2
    saved = json.loads((tmp_path / "status.json").read_text(encoding="utf-8"))
    assert saved["ok"] is True


def test_minimal_probes_fail_on_html_404_body(tmp_path, monkeypatch):
    from app.tadoku import upstream_monitor as mon

    monkeypatch.setattr(mon, "status_path", lambda: tmp_path / "status.json")

    def fake_get(url, **kwargs):
        if "api" not in url:
            return _FakeResp(200, text="This page could not be found")
        return _FakeResp(
            200,
            json_data={"entries": [{"rank": 1, "score": 1, "user_id": "u", "user_display_name": "x"}]},
        )

    monkeypatch.setattr(httpx, "get", fake_get)
    report = mon.run_minimal_probes(contest_id="cid-1", api_base="https://example.test/api")
    assert report.ok is False
    assert any(p.name == "contest_leaderboard_page" and not p.ok for p in report.probes)


def test_minimal_probes_fail_empty_leaderboard(tmp_path, monkeypatch):
    from app.tadoku import upstream_monitor as mon

    monkeypatch.setattr(mon, "status_path", lambda: tmp_path / "status.json")

    def fake_get(url, **kwargs):
        if "api" not in url:
            return _FakeResp(200, text="<html/>")
        return _FakeResp(200, json_data={"entries": []})

    monkeypatch.setattr(httpx, "get", fake_get)
    report = mon.run_minimal_probes(contest_id="cid-1", api_base="https://example.test/api")
    assert report.ok is False
    assert any(p.name == "contest_leaderboard_api" and not p.ok for p in report.probes)


def test_no_contest_id(tmp_path, monkeypatch):
    from app.core.config import get_settings
    from app.tadoku import upstream_monitor as mon

    monkeypatch.setattr(mon, "status_path", lambda: tmp_path / "status.json")
    get_settings().yaml_config.tadoku.contest.contest_id = ""
    report = mon.run_minimal_probes(contest_id="", api_base="https://example.test/api")
    assert report.ok is False
    assert "contest_id" in report.skipped_reason


def test_api_upstream_status_and_force(client, tmp_path, monkeypatch):
    from app.tadoku import upstream_monitor as mon

    status = tmp_path / "status.json"
    monkeypatch.setattr(mon, "status_path", lambda: status)

    def fake_get(url, **kwargs):
        if "api" not in url:
            return _FakeResp(200, text="<html>board</html>")
        return _FakeResp(
            200,
            json_data={
                "entries": [
                    {
                        "rank": 1,
                        "score": 9,
                        "user_id": "u",
                        "user_display_name": "Z",
                    }
                ]
            },
        )

    monkeypatch.setattr(httpx, "get", fake_get)

    r = client.post("/api/tadoku/upstream/check")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["report"]["error_count"] == 0

    r2 = client.get("/api/tadoku/upstream")
    assert r2.status_code == 200
    assert "interval_hours" in r2.json()
    assert r2.json().get("last") is not None

    settings = client.get("/api/tadoku/settings").json()
    assert "upstream_monitor" in settings
