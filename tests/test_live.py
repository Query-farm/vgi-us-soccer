"""Opt-in smoke tests against the real upstream APIs (``pytest -m live``).

They pin finished seasons and matches so assertions stay true: MLS 2025 and
match MLS-MAT-0009NL, NWSL 2025, and ASA 2025.
"""

from __future__ import annotations

from datetime import date

import pytest

from vgi_us_soccer import asa, mls, nwsl
from vgi_us_soccer.meta import batch_from_rows

pytestmark = pytest.mark.live


def test_mls_current_table_is_internally_consistent() -> None:
    rows = mls.fetch_standings().rows
    assert len(rows) >= 29
    assert sum(row["wins"] for row in rows) == sum(row["losses"] for row in rows)
    assert sum(row["goals_for"] for row in rows) == sum(row["goals_against"] for row in rows)
    for row in rows:
        assert row["points"] == 3 * row["wins"] + row["draws"]
    batch_from_rows(rows, mls.STANDINGS_SCHEMA)


def test_mls_player_goals_reconcile_with_the_table() -> None:
    table_goals = sum(row["goals_for"] for row in mls.fetch_standings(season=2025).rows)
    players = mls.fetch_player_stats(season=2025).rows
    own_goals = sum(row["own_goals"] or 0 for row in mls.fetch_club_stats(season=2025).rows)
    assert sum(row["goals"] or 0 for row in players) + own_goals == table_goals
    messi = next(row for row in players if row["player_id"] == "MLS-OBJ-000396")
    assert messi["goals"] == 29
    keys = [(row["player_id"], row["club_id"]) for row in players]
    assert len(keys) == len(set(keys))
    batch_from_rows(players, mls.PLAYER_STATS_SCHEMA)


def test_mls_pinned_match_detail() -> None:
    [match] = mls.fetch_match("MLS-MAT-0009NL").rows
    assert (match["home_club_abbreviation"], match["home_goals"], match["away_goals"]) == ("CIN", 0, 2)
    goals = [row["player_name"] for row in mls.fetch_match_events("MLS-MAT-0009NL").rows if row["is_goal"]]
    assert goals == ["Gonzalo Tapia", "Taha Habroune"]
    assert sum(row["goals"] for row in mls.fetch_match_player_stats("MLS-MAT-0009NL").rows) == 2
    assert len([row for row in mls.fetch_match_lineups("MLS-MAT-0009NL").rows if row["starter"]]) == 22
    assert len(mls.fetch_match_club_stats("MLS-MAT-0009NL").rows) == 2
    assert mls.fetch_match_commentary("MLS-MAT-0009NL").rows


def test_mls_schedule_and_match_log() -> None:
    day = mls.fetch_schedule(
        season=2026, competition="mls", start_date=date(2026, 10, 18), end_date=date(2026, 10, 18)
    ).rows
    assert "MLS-MAT-0009NL" in {row["match_id"] for row in day}
    season = mls.fetch_schedule(season=2025, competition="mls").rows
    assert len(season) == 510
    log = mls.fetch_player_match_log("MLS-OBJ-000396", season=2025, competition="mls").rows
    assert sum(row["goals"] for row in log) == 29


def test_mls_reference_lists() -> None:
    assert "MLS-COM-000003" in {row["competition_id"] for row in mls.fetch_competitions().rows}
    assert 1996 in {row["season"] for row in mls.fetch_seasons().rows}
    assert len(mls.fetch_clubs(season=2025).rows) == 30


def test_nwsl_2025_final_table() -> None:
    rows = nwsl.fetch_standings(2025).rows
    assert len(rows) == 14
    assert (rows[0]["team_name"], rows[0]["points"]) == ("Kansas City Current", 65)
    assert sum(row["wins"] for row in rows) == sum(row["losses"] for row in rows)


def test_nwsl_season_stats_matches_and_roster() -> None:
    players = nwsl.fetch_player_stats(2025).rows
    assert len(players) > 300
    assert max(row["goals"] or 0 for row in players) == 15
    teams = nwsl.fetch_team_stats(2025).rows
    assert len(teams) == 14
    matches = nwsl.fetch_matches(2025).rows
    assert len({row["match_id"] for row in matches}) == len(matches) >= 182
    roster = nwsl.fetch_roster("GFC", 2026).rows
    assert len(roster) >= 20
    events = nwsl.fetch_match_events("nwsl::Football_Match::834675f37cea4328bece6743d94c7d2d").rows
    assert [row["player_name"] for row in events if row["event_type"] == "goal"] == ["Olivia Moultrie"]


def test_asa_2025_regular_season() -> None:
    teams = asa.fetch_xg_teams("mls", 2025).rows
    assert len(teams) == 30
    games = asa.fetch_xg_games("mls", 2025).rows
    assert len(games) == 510
    assert sum(row["goals_for"] for row in teams) == sum(
        row["home_goals"] + row["away_goals"] for row in games
    )
    players = asa.fetch_xg_players("mls", 2025, minimum_minutes=1500).rows
    assert all(row["player_name"] and row["team_name"] for row in players)
    salaries = asa.fetch_salaries(2025).rows
    top = max(salaries, key=lambda row: row["guaranteed_compensation"] or 0)
    assert top["player_name"] == "Lionel Messi"
    assert asa.fetch_goals_added("nwsl", 2025, minimum_minutes=1000).rows


def test_nwsl_2025_goal_share_task_answer() -> None:
    """Pins the answer the judge expects for agent task nwsl_2025_goal_share."""
    teams = {row["team_id"]: row for row in nwsl.fetch_standings(2025).rows}
    shares = sorted(
        (
            (row["goals"] or 0) / teams[row["team_id"]]["goals_for"],
            row["player_name"],
            teams[row["team_id"]]["team_name"],
            row["goals"],
            teams[row["team_id"]]["goals_for"],
        )
        for row in nwsl.fetch_player_stats(2025).rows
        if row["team_id"] in teams
    )
    assert shares[-1][1:] == ("Esther González", "Gotham FC", 13, 35)
    assert shares[-1][0] - shares[-2][0] > 0.05  # not a near-tie


def test_asa_2025_bargain_gplus_task_answer() -> None:
    """Pins the answer the judge expects for agent task asa_2025_bargain_gplus."""
    salaries = asa.fetch_salaries(2025).rows
    latest = max(row["release_date"] for row in salaries)
    cheap = {
        (row["player_id"], row["team_id"])
        for row in salaries
        if row["release_date"] == latest and (row["guaranteed_compensation"] or 150_000) < 150_000
    }
    players = sorted(
        (
            row
            for row in asa.fetch_goals_added("mls", 2025, minimum_minutes=1500).rows
            if (row["player_id"], row["team_id"]) in cheap
        ),
        key=lambda row: row["goals_added_above_avg"],
        reverse=True,
    )
    assert (players[0]["player_name"], players[0]["team_abbreviation"]) == ("Alex Freeman", "ORL")
    assert players[0]["goals_added_above_avg"] - players[1]["goals_added_above_avg"] > 1.0
