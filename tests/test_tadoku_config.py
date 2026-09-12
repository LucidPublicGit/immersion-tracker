from app.core.config import AppYamlConfig, TadokuConfig, TadokuContestConfig
from app.tadoku.client import ACTIVITY_IDS


def test_contest_default_shape():
    c = TadokuContestConfig(
        name="Example Year Contest",
        contest_id="00000000-0000-0000-0000-000000000001",
        registration_id="",
    )
    t = TadokuConfig(contest=c, auto_submit_on_approve=True, live_submit=True)
    assert "Example Year Contest" in t.contest.name
    assert t.auto_submit_on_approve is True


def test_activity_ids():
    assert ACTIVITY_IDS["listening"] == 2
    assert ACTIVITY_IDS["reading"] == 1


def test_yaml_parses_tadoku_block():
    cfg = AppYamlConfig.model_validate(
        {
            "tadoku": {
                "contest": {
                    "name": "Example Year Contest",
                    "contest_id": "00000000-0000-0000-0000-000000000001",
                }
            }
        }
    )
    assert cfg.tadoku.contest.contest_id.endswith("0001")
