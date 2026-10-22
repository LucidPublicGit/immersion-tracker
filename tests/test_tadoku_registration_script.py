"""Cookie compatibility for the standalone registrations helper."""
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "tadoku_registrations", Path(__file__).resolve().parents[1] / "scripts/tadoku_list_registrations.py"
)
registrations = importlib.util.module_from_spec(spec)
spec.loader.exec_module(registrations)


@pytest.mark.parametrize("raw, expected", [
    ("token", "tadoku_session=token"),
    ("tadoku_session=token", "tadoku_session=token"),
    ("Cookie: other=value; tadoku_session=token", "tadoku_session=token"),
    ("ory_kratos_session=old", ""),
    ("", ""),
    ("tadoku_session=bad\r\nInjected: header", ""),
])
def test_normalize_cookie(raw, expected):
    assert registrations.normalize_cookie(raw) == expected


def test_old_cookie_file_does_not_hide_valid_env(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    (tmp_path / "data/tadoku_session.cookie").write_text("ory_kratos_session=old")
    monkeypatch.setattr(registrations, "ROOT", tmp_path)
    monkeypatch.setenv("TADOKU_COOKIE", "tadoku_session=current")
    assert registrations.load_cookie() == "tadoku_session=current"
