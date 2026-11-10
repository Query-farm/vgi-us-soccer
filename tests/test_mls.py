"""Contract and parsing tests for the MLS Stats API module, against recorded responses."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from vgi_us_soccer import mls
from vgi_us_soccer.meta import batch_from_rows


def _batch(result: mls.Result, schema):
    batch = batch_from_rows(result.rows, schema)
    assert batch.schema == schema
    return batch


def test_competition_aliases() -> None:
    assert mls.competition_id(None) == "MLS-COM-000001"
    assert mls.competition_id("next_pro") == "MLS-COM-000003"
    assert mls.competition_id("US_OPEN_CUP") == "MLS-COM-00002U"
    assert mls.competition_id("MLS-COM-00000K") == "MLS-COM-00000K"
    with pytest.raises(ValueError, match="unknown MLS competition"):
        mls.competition_id("premier_league")


def test_competitions_hide_internal_test_feed() -> None:
    result = mls.fetch_competitions()
    ids = {row["competition_id"] for row in result.rows}
    assert "MLS-COM-000001" in ids
    assert mls.TEST_COMPETITION not in ids
    regular = next(row for row in result.rows if row["competition_id"] == "MLS-COM-000001")
    assert regular["alias"] == "mls"
    _batch(result, mls.COMPETITIONS_SCHEMA)


def test_seasons_and_current_season_resolution(recorded_upstreams) -> None:
    seasons = mls.fetch_seasons("mls").rows
    assert [row["season"] for row in seasons] == [2027, 2026, 2025, 2024]
    assert recorded_upstreams.last("/seasons").url.path == "/competitions/MLS-COM-000001/seasons"
    # A future season already listed upstream is not "current" until its year arrives.
    assert mls.resolve_season("mls", None, today=date(2026, 11, 10)) == (2026, "MLS-SEA-0001KA")
    assert mls.resolve_season("mls", None, today=date(2027, 3, 1))[0] == 2027
    assert mls.resolve_season("mls", 2025) == (2025, "MLS-SEA-0001K9")
    with pytest.raises(ValueError, match="available seasons: 2027, 2026, 2025, 2024"):
        mls.resolve_season("mls", 1999)


def test_standings_flatten_and_splits(recorded_upstreams) -> None:
    result = mls.fetch_standings("mls", 2026)
    leader = result.rows[0]
    assert leader["club_name"] == "Nashville SC"
    assert leader["points"] == 77
    assert leader["wins"] * 3 + leader["draws"] == leader["points"]
    assert leader["goal_difference"] == leader["goals_for"] - leader["goals_against"]
    assert leader["group_name"] is None
    assert result.max_age is None  # MLS sends Cache-Control: no-store
    assert "type" not in recorded_upstreams.last("/standings").url.params

    mls.fetch_standings("mls", 2026, "form")
    assert recorded_upstreams.last("/standings").url.params["type"] == "shape"
    with pytest.raises(ValueError, match="split must be one of"):
        mls.fetch_standings("mls", 2026, "conference")
    _batch(result, mls.STANDINGS_SCHEMA)


def test_standings_for_unpublished_season_are_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mls, "resolve_season", lambda comp, season: (2027, "MLS-SEA-NOPE00"))
    monkeypatch.setattr(
        mls,
        "_get",
        lambda path, params=None, **kwargs: mls.api.JsonResponse(payload=None, status=404),
    )
    assert mls.fetch_standings("mls", 2027).rows == []


def test_clubs_and_club_stats() -> None:
    clubs = mls.fetch_clubs("mls", 2026)
    assert clubs.rows[0]["club_abbreviation"] == "LAFC"
    assert clubs.rows[0]["city"] == "Los Angeles, CA"
    _batch(clubs, mls.CLUBS_SCHEMA)

    stats = mls.fetch_club_stats("mls", 2026)
    miami = next(row for row in stats.rows if row["club_abbreviation"] == "MIA")
    assert miami["goals"] == 80
    assert miami["matches_played"] == 34
    assert miami["xg"] == pytest.approx(69.1835)
    assert 0 < miami["pass_completion"] <= 1
    _batch(stats, mls.CLUB_STATS_SCHEMA)


def test_player_stats_requests_large_pages_and_flattens(recorded_upstreams) -> None:
    result = mls.fetch_player_stats("mls", 2026)
    request = recorded_upstreams.last("/seasons/MLS-SEA-0001KA")
    assert request.url.path == "/statistics/players/competitions/MLS-COM-000001/seasons/MLS-SEA-0001KA"
    assert request.url.params["per_page"] == "1000"
    messi = result.rows[0]
    assert messi["player_name"] == "Leo Messi"
    assert messi["club_abbreviation"] == "MIA"
    assert messi["goals"] == 26
    assert messi["goals_minus_xg"] == pytest.approx(26 - 20.0069, abs=1e-4)
    assert messi["goalkeeper"] is False
    assert messi["x_pass"] == pytest.approx(907.45)
    _batch(result, mls.PLAYER_STATS_SCHEMA)


def test_pagination_follows_page_token(monkeypatch: pytest.MonkeyPatch) -> None:
    pages = {
        None: {
            "player_statistics": [{"player_id": "MLS-OBJ-000001", "team_id": "A"}],
            "next_page_token": "t1",
        },
        "t1": {"player_statistics": [{"player_id": "MLS-OBJ-000002", "team_id": "B"}]},
    }
    tokens: list[str | None] = []

    def fake_get(path, params=None, **kwargs):
        token = (params or {}).get("page_token")
        tokens.append(token)
        return mls.api.JsonResponse(payload=pages[token])

    monkeypatch.setattr(mls, "_get", fake_get)
    items, _ = mls._paged("statistics/players/x", "player_statistics")
    assert [item["player_id"] for item in items] == ["MLS-OBJ-000001", "MLS-OBJ-000002"]
    assert tokens == [None, "t1"]


def test_pagination_has_a_page_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        mls,
        "_get",
        lambda path, params=None, **kwargs: mls.api.JsonResponse({"x": [], "next_page_token": "again"}),
    )
    with pytest.raises(RuntimeError, match="exceeded"):
        mls._paged("loop", "x")
    monkeypatch.setattr(mls, "_get", lambda path, params=None, **kwargs: mls.api.JsonResponse([]))
    with pytest.raises(ValueError, match="not an object"):
        mls._paged("bad", "x")


def test_schedule_uses_date_range_filters(recorded_upstreams) -> None:
    result = mls.fetch_schedule(
        season=2026, competition="mls", start_date=date(2026, 10, 18), end_date=date(2026, 10, 18)
    )
    params = recorded_upstreams.last("/matches/seasons/MLS-SEA-0001KA").url.params
    assert params["match_date[gte]"] == "2026-10-18"
    assert params["match_date[lte]"] == "2026-10-18"
    assert params["competition_id"] == "MLS-COM-000001"
    first = next(row for row in result.rows if row["match_id"] == "MLS-MAT-0009NL")
    assert (first["home_club_abbreviation"], first["home_goals"], first["away_goals"]) == ("CIN", 0, 2)
    assert first["conference"] == "EASTERN CONFERENCE"
    assert first["planned_kickoff"] == datetime(2026, 10, 18, 21, 0, tzinfo=UTC)
    _batch(result, mls.SCHEDULE_SCHEMA)

    mls.fetch_schedule(season=2026)
    whole = recorded_upstreams.last("/matches/seasons/MLS-SEA-0001KA").url.params
    assert (whole["match_date[gte]"], whole["match_date[lte]"]) == ("2026-01-01", "2026-12-31")
    assert "competition_id" not in whole
    with pytest.raises(ValueError, match="start_date"):
        mls.fetch_schedule(start_date=date(2026, 2, 1), end_date=date(2026, 1, 1))


def test_scheduled_matches_have_null_scores() -> None:
    row = mls._schedule_row(
        {"match_id": "MLS-MAT-000ADN", "match_status": "scheduled", "home_team_goals": 0, "result": "0:0"}
    )
    assert row["home_goals"] is None and row["away_goals"] is None and row["result"] is None


def test_current_schedule_window(recorded_upstreams) -> None:
    mls.fetch_current_schedule(today=date(2026, 11, 10))
    params = recorded_upstreams.last("/matches/seasons/MLS-SEA-0001KA").url.params
    assert (params["match_date[gte]"], params["match_date[lte]"]) == ("2026-11-03", "2026-11-24")


def test_match_summary() -> None:
    [row] = mls.fetch_match("MLS-MAT-0009NL").rows
    assert row["home_club_name"] == "FC Cincinnati"
    assert row["away_club_abbreviation"] == "CLB"
    assert (row["home_goals"], row["away_goals"]) == (0, 2)
    assert row["attendance"] == 25513
    assert row["home_formation"] == "3-5-2"
    assert row["home_head_coach"] == "Pat Noonan"
    assert row["referee"] == "Drew Fischer"
    assert row["stadium_name"] == "TQL Stadium"
    _batch(mls.Result([row]), mls.MATCH_SCHEMA)
    assert mls.fetch_match("MLS-MAT-ZZZZZZ").rows == []


def test_match_lineups() -> None:
    result = mls.fetch_match_lineups("MLS-MAT-0009NL")
    keeper = next(row for row in result.rows if row["player_name"] == "Roman Celentano")
    assert keeper["starter"] is True
    assert keeper["lineup_position"] == "GK"
    assert keeper["team_role"] == "home"
    bench = next(row for row in result.rows if row["player_name"] == "Evan Louro")
    assert bench["starter"] is False and bench["lineup_position"] is None
    _batch(result, mls.LINEUPS_SCHEMA)


def test_match_events_assign_actors_by_event_type() -> None:
    result = mls.fetch_match_events("MLS-MAT-0009NL")
    goals = [row for row in result.rows if row["is_goal"]]
    assert [row["player_name"] for row in goals] == ["Gonzalo Tapia", "Taha Habroune"]
    assert goals[0]["other_player_name"] == "Brais Méndez"
    assert goals[0]["xg"] == pytest.approx(0.1241)
    foul = next(row for row in result.rows if row["event_type"] == "fouls")
    assert foul["player_id"] and foul["other_player_id"] and foul["player_id"] != foul["other_player_id"]
    sub = next(row for row in result.rows if row["event_type"] == "substitutions")
    assert sub["player_name"] and sub["other_player_name"]
    card = next(row for row in result.rows if row["event_type"] == "cards")
    assert card["card_color"] == "yellow"
    times = [row["event_time"] for row in result.rows]
    assert times == sorted(times)
    _batch(result, mls.EVENTS_SCHEMA)


def test_match_commentary() -> None:
    result = mls.fetch_match_commentary("MLS-MAT-0009NL")
    assert result.rows
    assert all(row["commentary"] for row in result.rows)
    assert result.rows[-1]["commentary_type"] == "MatchEnd"
    _batch(result, mls.COMMENTARY_SCHEMA)


def test_match_club_and_player_stats() -> None:
    clubs = mls.fetch_match_club_stats("MLS-MAT-0009NL")
    assert {row["team_role"]: row["club_abbreviation"] for row in clubs.rows} == {
        "home": "CIN",
        "away": "CLB",
    }
    assert {row["club_abbreviation"]: row["goals"] for row in clubs.rows} == {"CIN": 0, "CLB": 2}
    _batch(clubs, mls.MATCH_CLUB_STATS_SCHEMA)

    players = mls.fetch_match_player_stats("MLS-MAT-0009NL")
    assert {row["club_abbreviation"] for row in players.rows} == {"CLB"}
    assert all(row["match_id"] == "MLS-MAT-0009NL" for row in players.rows)
    _batch(players, mls.MATCH_PLAYER_STATS_SCHEMA)


def test_player_match_log_filters_test_feed_and_narrows() -> None:
    every = mls.fetch_player_match_log("MLS-OBJ-000396")
    assert [row["match_id"] for row in every.rows] == ["MLS-MAT-0009P0", "MLS-MAT-00096T"]
    assert every.rows[0]["match_title"] == "Inter Miami CF:Charlotte FC"
    _batch(every, mls.PLAYER_MATCH_LOG_SCHEMA)
    assert [row["season"] for row in mls.fetch_player_match_log("MLS-OBJ-000396", season=2025).rows] == [2025]
    narrowed = mls.fetch_player_match_log("MLS-OBJ-000396", competition="mls_playoffs")
    assert [row["competition_id"] for row in narrowed.rows] == ["MLS-COM-000002"]
