"""Unit tests for contest momentum analytics (no live Tadoku)."""

from __future__ import annotations

from datetime import date

from app.tadoku.contest_cache import (
    analyze_user,
    build_daily_map,
    build_snapshot,
    classify_momentum,
    color_for_user,
    cumulative_series,
    daily_rate_for_model,
    days_until_contest_end,
    initials_for,
    project_score,
    project_series,
    project_standings,
    sum_window,
)


def test_initials_and_color_stable():
    assert initials_for("Kanji Eater") == "KE"
    assert initials_for("Zad") == "ZA"
    assert color_for_user("abc") == color_for_user("abc")
    assert color_for_user("abc") != color_for_user("xyz")


def test_build_daily_map_aggregates_languages():
    rows = [
        {"date": "2026-01-01", "language_code": "jpn", "score": 10},
        {"date": "2026-01-01", "language_code": "eng", "score": 5},
        {"date": "2026-01-02", "score": 3},
    ]
    d = build_daily_map(rows)
    assert d["2026-01-01"] == 15
    assert d["2026-01-02"] == 3


def test_cumulative_and_window():
    daily = {
        "2026-01-01": 10.0,
        "2026-01-02": 20.0,
        "2026-01-03": 0.0,
        "2026-01-04": 5.0,
    }
    series = cumulative_series(daily, date(2026, 1, 1), date(2026, 1, 4))
    assert [p["cumulative"] for p in series] == [10.0, 30.0, 30.0, 35.0]
    assert sum_window(daily, date(2026, 1, 4), 2) == 5.0
    assert sum_window(daily, date(2026, 1, 4), 4) == 35.0


def test_classify_momentum():
    assert classify_momentum(12.0, 20.0, 0) == "heating"
    assert classify_momentum(-12.0, 2.0, 0) == "cooling"
    assert classify_momentum(0.0, 10.0, 0) == "steady"
    assert classify_momentum(-1.0, 0.0, 20) == "idle"


def test_analyze_user_acceleration():
    # Strong recent week after slow baseline
    daily = {}
    for i in range(1, 31):
        # days 1-23 low, 24-30 high
        d = date(2026, 6, i)
        daily[d.isoformat()] = 2.0 if i < 24 else 30.0

    u = analyze_user(
        user_id="u1",
        display_name="Speedy",
        rank=2,
        score=sum(daily.values()),
        daily=daily,
        contest_start=date(2026, 6, 1),
        as_of=date(2026, 6, 30),
        rank_above_score=sum(daily.values()) + 50,
    )
    assert u["velocity_7d"] > u["velocity_30d"]
    assert u["acceleration"] > 0
    assert u["momentum"] == "heating"
    assert u["avatar_url"].startswith("data:image/svg+xml")
    assert len(u["sparkline"]) == 28
    assert len(u["series"]) == 30


def test_build_snapshot_catchup():
    leaderboard = [
        {
            "rank": 1,
            "score": 1000.0,
            "user_id": "a",
            "user_display_name": "Alpha",
        },
        {
            "rank": 2,
            "score": 900.0,
            "user_id": "b",
            "user_display_name": "Bravo",
        },
    ]
    as_of = date(2026, 7, 1)
    # Bravo logging hard recently; Alpha only early in the year
    act_a = [{"date": f"2026-01-{d:02d}", "score": 50.0} for d in range(1, 10)]
    act_b = [
        {"date": (date(2026, 6, d)).isoformat(), "score": 40.0}
        for d in range(1, 31)
    ]
    act_b += [
        {"date": (date(2026, 7, 1)).isoformat(), "score": 40.0},
    ]
    snap = build_snapshot(
        contest_id="test-contest",
        contest_meta={
            "title": "Test",
            "contest_start": "2026-01-01",
            "contest_end": "2026-12-31",
        },
        summary={"participant_count": 2, "total_score": 1900},
        leaderboard=leaderboard,
        activities={"a": act_a, "b": act_b},
        fetched_at="2026-07-01T00:00:00Z",
        as_of=as_of,
    )
    assert snap["contest"]["title"] == "Test"
    assert len(snap["users"]) == 2
    bravo = next(u for u in snap["users"] if u["user_id"] == "b")
    assert bravo["gap_above"] == 100.0
    # Bravo should be heating vs Alpha's old logs
    assert bravo["velocity_7d"] > 0
    assert "heating" in snap["highlights"]
    assert "chart" in snap


def test_daily_rate_models():
    assert daily_rate_for_model(velocity_7d=10, velocity_30d=4, acceleration=6, model="velocity") == 10
    assert daily_rate_for_model(velocity_7d=10, velocity_30d=4, acceleration=6, model="baseline") == 4
    # accel: avg of 10 and max(0, 10+6)=16 → 13
    assert daily_rate_for_model(velocity_7d=10, velocity_30d=4, acceleration=6, model="accel") == 13
    # cooling toward zero floor
    assert daily_rate_for_model(velocity_7d=2, velocity_30d=8, acceleration=-5, model="accel") == 1.0


def test_project_score_and_horizon():
    assert project_score(100, velocity_7d=10, days=5) == 150
    assert project_score(100, velocity_7d=10, days=0) == 100
    assert days_until_contest_end(date(2026, 7, 1), date(2026, 7, 31)) == 30
    assert days_until_contest_end(date(2026, 12, 31), date(2026, 12, 31)) == 0


def test_project_standings_reorders_by_pace():
    users = [
        {
            "user_id": "leader",
            "display_name": "Leader",
            "rank": 1,
            "score": 1000.0,
            "velocity_7d": 5.0,
            "velocity_30d": 5.0,
            "acceleration": 0.0,
        },
        {
            "user_id": "chaser",
            "display_name": "Chaser",
            "rank": 2,
            "score": 900.0,
            "velocity_7d": 20.0,
            "velocity_30d": 10.0,
            "acceleration": 10.0,
        },
    ]
    # 20d * 20 = 400 → chaser at 1300; leader 1000+100 = 1100
    out = project_standings(users, days=20, model="velocity")
    assert out[0]["user_id"] == "chaser"
    assert out[0]["projected_rank"] == 1
    assert out[0]["rank_delta"] == 1  # climbed one place
    assert out[1]["user_id"] == "leader"
    assert out[1]["projected_rank"] == 2
    assert out[1]["rank_delta"] == -1

    # baseline (30d) is slower for chaser — may not overtake in same window
    base = project_standings(users, days=5, model="baseline")
    chaser = next(u for u in base if u["user_id"] == "chaser")
    assert chaser["projected_daily_rate"] == 10.0


def test_project_series_extends_dates():
    pts = project_series(100.0, date(2026, 7, 1), daily_rate=10.0, days=3)
    assert len(pts) == 3
    assert pts[0]["date"] == "2026-07-02"
    assert pts[-1]["cumulative"] == 130.0
    assert all(p["projected"] for p in pts)
