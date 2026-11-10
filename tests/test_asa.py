"""Parsing tests for the American Soccer Analysis module."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from vgi_us_soccer import asa
from vgi_us_soccer.meta import batch_from_rows


def _batch(result: asa.Result, schema):
    batch = batch_from_rows(result.rows, schema)
    assert batch.schema == schema
    return batch


def test_argument_validation() -> None:
    with pytest.raises(ValueError, match="league must be one of"):
        asa.fetch_teams("epl")
    with pytest.raises(ValueError, match="starts with the 2013"):
        asa.fetch_xg_teams("mls", 2010)
    with pytest.raises(ValueError, match="stage must be one of"):
        asa.fetch_xg_teams("mls", 2025, "friendlies")
    assert asa._season(None) == datetime.now(UTC).year


def test_usl_super_league_split_season_names() -> None:
    assert asa._season_name("usls", 2024) == "2024-25"
    assert asa._season_name("usls", 2025) == "2025-26"
    assert asa._season_name("usls", 2026) == "2026"
    assert asa._season_name("mls", 2025) == "2025"


def test_teams_directory() -> None:
    result = asa.fetch_teams("mls")
    assert len(result.rows) == 31
    assert {"team_name": "San Jose Earthquakes", "team_abbreviation": "SJE"}.items() <= next(
        row for row in result.rows if row["team_id"] == "0KPqjA456v"
    ).items()
    _batch(result, asa.TEAMS_SCHEMA)


def test_xg_players_split_by_team_with_names(recorded_upstreams) -> None:
    result = asa.fetch_xg_players("mls", 2026, minimum_minutes=2000)
    params = recorded_upstreams.last("/players/xgoals").url.params
    assert params["split_by_teams"] == "true"
    assert params["minimum_minutes"] == "2000"
    assert params["stage_name"] == "Regular Season"
    assert all(row["player_name"] for row in result.rows)
    assert all(row["team_name"] for row in result.rows)
    first = result.rows[0]
    assert first["goals"] == 3 and first["xgoals"] == pytest.approx(1.79)
    _batch(result, asa.XG_PLAYERS_SCHEMA)

    asa.fetch_xg_players("mls", 2026, stage="all")
    assert "stage_name" not in recorded_upstreams.last("/players/xgoals").url.params


def test_goals_added_pivot() -> None:
    result = asa.fetch_goals_added("mls", 2026, minimum_minutes=2000)
    row = result.rows[0]
    assert row["passing_above_avg"] == pytest.approx(-0.266)
    expected = -0.0461 + 0.4215 - 0.1047 - 0.266 + 0.1611 + 0.287
    assert row["goals_added_above_avg"] == pytest.approx(expected, abs=1e-4)
    assert row["goals_added_raw"] > 0
    _batch(result, asa.GOALS_ADDED_SCHEMA)


def test_xg_teams_and_games() -> None:
    teams = asa.fetch_xg_teams("mls", 2026)
    assert teams.rows[0]["team_name"] == "San Jose Earthquakes"
    assert teams.rows[0]["goal_difference"] == teams.rows[0]["goals_for"] - teams.rows[0]["goals_against"]
    _batch(teams, asa.XG_TEAMS_SCHEMA)

    games = asa.fetch_xg_games("mls", 2026)
    kickoffs = [row["kickoff"] for row in games.rows]
    assert kickoffs == sorted(kickoffs)
    assert games.rows[-1]["kickoff"] == datetime(2026, 11, 8, tzinfo=UTC)
    assert all(row["home_team_name"] for row in games.rows)
    _batch(games, asa.XG_GAMES_SCHEMA)


def test_salaries() -> None:
    result = asa.fetch_salaries(2026)
    first = result.rows[0]
    assert first["base_salary"] == 113400
    assert first["release_date"] == date(2026, 4, 16)
    assert first["mlspa_position"] == "D"
    assert first["player_name"]
    _batch(result, asa.SALARIES_SCHEMA)


def test_non_list_payload_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(asa, "_get", lambda path, params=None, **kwargs: asa.api.JsonResponse({"error": "x"}))
    with pytest.raises(ValueError, match="not a list"):
        asa.fetch_teams("mls")
    monkeypatch.setattr(
        asa, "_get", lambda path, params=None, **kwargs: asa.api.JsonResponse(None, status=404)
    )
    assert asa.fetch_teams("mls").rows == []
