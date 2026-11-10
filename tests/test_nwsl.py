"""Contract and parsing tests for the NWSL Sports Data Platform module."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from vgi_us_soccer import nwsl
from vgi_us_soccer.meta import batch_from_rows

SEASON_2026 = "nwsl::Football_Season::0b6761e4701749f593690c0f338da74c"


def _batch(result: nwsl.Result, schema):
    batch = batch_from_rows(result.rows, schema)
    assert batch.schema == schema
    return batch


def test_competitions_are_discovered_by_name(recorded_upstreams) -> None:
    result = nwsl.fetch_competitions()
    assert "NWSL" in {row["competition_name"] for row in result.rows}
    assert recorded_upstreams.last("/competitions").url.params["locale"] == "en-US"
    comp_id, name = nwsl.resolve_competition("nwsl challenge cup")
    assert name == "NWSL Challenge Cup"
    assert nwsl.resolve_competition(comp_id) == (comp_id, name)
    with pytest.raises(ValueError, match="unknown NWSL platform competition"):
        nwsl.resolve_competition("Premier League")
    _batch(result, nwsl.COMPETITIONS_SCHEMA)


def test_seasons_resolve_opaque_ids_from_years() -> None:
    result = nwsl.fetch_seasons()
    assert [row["season"] for row in result.rows] == [2026, 2025, 2024]
    assert result.rows[0]["start_date"] == date(2026, 3, 14)
    assert nwsl.resolve_season(None, now=datetime(2026, 11, 10, tzinfo=UTC)) == (2026, SEASON_2026)
    assert nwsl.resolve_season(None, now=datetime(2026, 1, 10, tzinfo=UTC))[0] == 2025
    assert nwsl.resolve_season(None, now=datetime(2000, 1, 1, tzinfo=UTC))[0] == 2026
    assert nwsl.resolve_season(2024)[0] == 2024
    with pytest.raises(ValueError, match="no NWSL season 2014"):
        nwsl.resolve_season(2014)
    _batch(result, nwsl.SEASONS_SCHEMA)


def test_standings_splits(recorded_upstreams) -> None:
    result = nwsl.fetch_standings(2026)
    assert recorded_upstreams.last("/standings/overall").url.path.endswith(f"{SEASON_2026}/standings/overall")
    leader = result.rows[0]
    assert (leader["position"], leader["team_name"], leader["points"]) == (1, "Gotham FC", 61)
    assert leader["form"] == "WWLDWW"
    assert leader["qualification"] == "Final Series"
    assert leader["wins"] * 3 + leader["draws"] == leader["points"]
    # NWSL advertises max-age=86400; the connector caps it at five minutes.
    assert result.max_age == 300
    home = nwsl.fetch_standings(2026, "home")
    assert home.rows and all(row["standings_split"] == "home" for row in home.rows)
    assert home.rows[0]["points"] != leader["points"]
    with pytest.raises(ValueError, match="split must be one of"):
        nwsl.fetch_standings(2026, "form")
    _batch(result, nwsl.STANDINGS_SCHEMA)


def test_teams_and_team_resolution() -> None:
    result = nwsl.fetch_teams(2026)
    assert {row["team_abbreviation"] for row in result.rows} == {"SEA", "BAY", "CHI"}
    _, season_id, team = nwsl.resolve_team("bay", 2026)
    assert season_id == SEASON_2026
    assert team["team_name"] == "Bay FC"
    with pytest.raises(ValueError, match="known acronyms: BAY, CHI, SEA"):
        nwsl.resolve_team("GFC", 2026)
    _batch(result, nwsl.TEAMS_SCHEMA)


def test_player_stats_pivot_stat_lists(recorded_upstreams) -> None:
    result = nwsl.fetch_player_stats(2026)
    params = recorded_upstreams.last("/stats/players").url.params
    assert (params["category"], params["page"]) == ("general", "1")
    sanchez = result.rows[0]
    assert sanchez["player_name"] == "Ashley Sanchez"
    assert sanchez["team_abbreviation"] == "NC"
    assert sanchez["position_name"] == "Midfielder"
    assert (sanchez["goals"], sanchez["assists"], sanchez["games_played"]) == (20, 5, 30)
    assert sanchez["xg"] == pytest.approx(16.0021)
    _batch(result, nwsl.PLAYER_STATS_SCHEMA)


def test_team_stats() -> None:
    result = nwsl.fetch_team_stats(2026)
    bay = next(row for row in result.rows if row["team_abbreviation"] == "BAY")
    assert (bay["points"], bay["wins"], bay["draws"], bay["losses"]) == (27, 7, 6, 17)
    assert bay["possession_pct"] == pytest.approx(49.6)
    _batch(result, nwsl.TEAM_STATS_SCHEMA)


def test_paging_stops_at_last_page(monkeypatch: pytest.MonkeyPatch) -> None:
    pages = [
        {"players": [{"playerId": "a"}], "pagination": {"totalPages": 2, "isLastPage": False}},
        {"players": [{"playerId": "b"}], "pagination": {"totalPages": 2, "isLastPage": True}},
    ]
    monkeypatch.setattr(
        nwsl, "_get", lambda path, params=None, **kwargs: nwsl.api.JsonResponse(pages[params["page"] - 1])
    )
    items, _ = nwsl._paged("x", "players", {})
    assert [item["playerId"] for item in items] == ["a", "b"]
    monkeypatch.setattr(
        nwsl,
        "_get",
        lambda path, params=None, **kwargs: nwsl.api.JsonResponse(
            {"pagination": {"isLastPage": False, "totalPages": 99}}
        ),
    )
    with pytest.raises(RuntimeError, match="exceeded"):
        nwsl._paged("x", "players", {})


def test_matches_null_scores_before_kickoff() -> None:
    result = nwsl.fetch_matches(2026)
    finished = [row for row in result.rows if row["status"] == "FINISHED"]
    upcoming = [row for row in result.rows if row["status"] == "UPCOMING"]
    assert finished and upcoming
    opener = next(row for row in finished if row["home_team_abbreviation"] == "WAS")
    assert (opener["home_score"], opener["away_score"]) == (0, 1)
    assert opener["matchday"] == "Matchday 1"
    assert opener["winner_team_id"] == opener["away_team_id"]
    assert all(row["home_score"] is None for row in upcoming)
    _batch(result, nwsl.MATCHES_SCHEMA)


def test_match_events() -> None:
    result = nwsl.fetch_match_events("nwsl::Football_Match::834675f37cea4328bece6743d94c7d2d")
    assert result.rows[-1]["event_type"] == "full-time"
    sub = next(row for row in result.rows if row["event_type"] == "substitution")
    assert sub["player_name"] and sub["team_abbreviation"] in {"WAS", "POR"}
    assert sub["minute"] is not None
    _batch(result, nwsl.EVENTS_SCHEMA)


def test_roster(recorded_upstreams) -> None:
    result = nwsl.fetch_roster("SEA", 2026)
    assert recorded_upstreams.last("/roster").url.params["seasonId"] == SEASON_2026
    reiten = next(row for row in result.rows if row["player_name"] == "Guro Reiten")
    assert reiten["shirt_number"] == 18
    assert reiten["date_of_birth"] == date(1994, 7, 26)
    assert reiten["height_cm"] == 166
    assert result.rows[-1]["shirt_number"] is None  # blank bib numbers sort last
    _batch(result, nwsl.ROSTER_SCHEMA)
