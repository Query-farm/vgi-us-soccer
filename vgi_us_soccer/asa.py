"""American Soccer Analysis API (CC BY-SA 4.0): xG, goals added, and salaries.

ASA publishes advanced metrics for MLS, MLS NEXT Pro, NWSL, the USL
Championship, USL League One, the USL Super League, and the NASL. Results carry
opaque ASA identifiers; this module joins ASA's own player and team directories
so every row also has readable names. Data returned through these functions is
licensed by American Soccer Analysis under CC BY-SA 4.0 and must be attributed.
"""

from __future__ import annotations

from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pyarrow as pa

from vgi_us_soccer import api
from vgi_us_soccer.meta import (
    TIMESTAMP,
    field,
    mapping,
    records,
    to_date,
    to_float,
    to_int,
    to_str,
    to_timestamp,
)

ATTRIBUTION = "Data: American Soccer Analysis (americansocceranalysis.com), CC BY-SA 4.0"
DIRECTORY_TTL = 3_600.0
LEAGUES = {
    "mls": "Major League Soccer",
    "mlsnp": "MLS NEXT Pro",
    "nwsl": "National Women's Soccer League",
    "uslc": "USL Championship",
    "usl1": "USL League One",
    "usls": "USL Super League",
    "nasl": "North American Soccer League (2011-2017)",
}
GOALS_ADDED_ACTIONS = ("dribbling", "fouling", "interrupting", "passing", "receiving", "shooting")
FIRST_SEASON = 2013
STAGES = {"regular_season": "Regular Season", "playoffs": "Playoffs", "all": None}


@dataclass(frozen=True, slots=True)
class Result:
    """Flattened rows plus the freshness the connector may advertise."""

    rows: list[dict[str, Any]]
    max_age: int | None = None


_LEAGUE_COLUMN = field("league", pa.string(), "ASA league code, for example mls or nwsl.")
_SEASON_COLUMN = field("season", pa.int32(), "Season year.")
_PLAYER_COLUMNS = [
    field("player_id", pa.string(), "Opaque ASA player identifier.", nullable=False),
    field("player_name", pa.string(), "Player name from ASA's player directory."),
]
_TEAM_COLUMNS = [
    field("team_id", pa.string(), "Opaque ASA team identifier."),
    field("team_name", pa.string(), "Team name from ASA's team directory."),
    field("team_abbreviation", pa.string(), "Team abbreviation."),
]

TEAMS_SCHEMA = pa.schema(
    [
        _LEAGUE_COLUMN,
        field("team_id", pa.string(), "Opaque ASA team identifier.", nullable=False),
        field("team_name", pa.string(), "Team name."),
        field("team_short_name", pa.string(), "Short team name."),
        field("team_abbreviation", pa.string(), "Team abbreviation."),
    ]
)

XG_PLAYERS_SCHEMA = pa.schema(
    [
        _LEAGUE_COLUMN,
        _SEASON_COLUMN,
        *_PLAYER_COLUMNS,
        *_TEAM_COLUMNS,
        field("general_position", pa.string(), "Most common position: GK, CB, FB, DM, CM, AM, W, or ST."),
        field("minutes_played", pa.int32(), "Minutes played for this team."),
        field("shots", pa.int32(), "Shots attempted."),
        field("shots_on_target", pa.int32(), "Shots on target."),
        field("goals", pa.int32(), "Non-own goals scored."),
        field("xgoals", pa.float64(), "Expected goals from ASA's shot model."),
        field("xplace", pa.float64(), "Goals added by shot placement beyond the pre-shot xG."),
        field("goals_minus_xgoals", pa.float64(), "Goals minus expected goals."),
        field("key_passes", pa.int32(), "Passes leading to a shot."),
        field("primary_assists", pa.int32(), "Primary assists."),
        field("xassists", pa.float64(), "Expected assists."),
        field("primary_assists_minus_xassists", pa.float64(), "Primary assists minus expected assists."),
        field("goals_plus_primary_assists", pa.int32(), "Goals plus primary assists."),
        field("xgoals_plus_xassists", pa.float64(), "Expected goals plus expected assists."),
        field("points_added", pa.float64(), "Expected league points added by the player's shots and passes."),
        field("xpoints_added", pa.float64(), "Expected points added under the xG model."),
    ]
)

GOALS_ADDED_SCHEMA = pa.schema(
    [
        _LEAGUE_COLUMN,
        _SEASON_COLUMN,
        *_PLAYER_COLUMNS,
        *_TEAM_COLUMNS,
        field("general_position", pa.string(), "Most common position."),
        field("minutes_played", pa.int32(), "Minutes played for this team."),
        field("goals_added_raw", pa.float64(), "Total goals added (g+) across all action types."),
        field(
            "goals_added_above_avg", pa.float64(), "Total g+ relative to an average player at the position."
        ),
        *(
            field(
                f"{action}_above_avg",
                pa.float64(),
                f"g+ above positional average from {action} actions.",
            )
            for action in GOALS_ADDED_ACTIONS
        ),
    ]
)

XG_TEAMS_SCHEMA = pa.schema(
    [
        _LEAGUE_COLUMN,
        _SEASON_COLUMN,
        field("team_id", pa.string(), "Opaque ASA team identifier.", nullable=False),
        field("team_name", pa.string(), "Team name."),
        field("team_abbreviation", pa.string(), "Team abbreviation."),
        field("games", pa.int32(), "Matches played."),
        field("shots_for", pa.int32(), "Shots taken."),
        field("shots_against", pa.int32(), "Shots conceded."),
        field("goals_for", pa.int32(), "Goals scored."),
        field("goals_against", pa.int32(), "Goals conceded."),
        field("goal_difference", pa.int32(), "Goals for minus goals against."),
        field("xgoals_for", pa.float64(), "Expected goals for."),
        field("xgoals_against", pa.float64(), "Expected goals against."),
        field("xgoal_difference", pa.float64(), "Expected goal difference."),
        field(
            "goal_difference_minus_xgoal_difference", pa.float64(), "Actual minus expected goal difference."
        ),
        field("points", pa.int32(), "League points."),
        field("xpoints", pa.float64(), "Expected points from match xG."),
    ]
)

XG_GAMES_SCHEMA = pa.schema(
    [
        _LEAGUE_COLUMN,
        _SEASON_COLUMN,
        field("game_id", pa.string(), "Opaque ASA game identifier.", nullable=False),
        field("kickoff", TIMESTAMP, "Kickoff time (UTC)."),
        field("home_team_id", pa.string(), "Home team identifier."),
        field("home_team_name", pa.string(), "Home team name."),
        field("away_team_id", pa.string(), "Away team identifier."),
        field("away_team_name", pa.string(), "Away team name."),
        field("home_goals", pa.int32(), "Home goals."),
        field("away_goals", pa.int32(), "Away goals."),
        field("home_xgoals", pa.float64(), "Home team expected goals."),
        field("away_xgoals", pa.float64(), "Away team expected goals."),
        field("home_xpoints", pa.float64(), "Home expected points from the xG distribution."),
        field("away_xpoints", pa.float64(), "Away expected points from the xG distribution."),
    ]
)

SALARIES_SCHEMA = pa.schema(
    [
        _SEASON_COLUMN,
        *_PLAYER_COLUMNS,
        *_TEAM_COLUMNS,
        field("mlspa_position", pa.string(), "Position as reported by the MLS Players Association."),
        field("base_salary", pa.float64(), "Annualized base salary, in US dollars."),
        field("guaranteed_compensation", pa.float64(), "Annualized guaranteed compensation, in US dollars."),
        field("release_date", pa.date32(), "Date of the MLSPA salary release the figures come from."),
    ]
)


def _league(league: str) -> str:
    code = league.strip().lower()
    if code not in LEAGUES:
        raise ValueError(f"league must be one of {sorted(LEAGUES)}")
    return code


def _season(season: int | None) -> int:
    year = season if season is not None else datetime.now(UTC).year
    if year < FIRST_SEASON:
        raise ValueError(f"ASA data starts with the {FIRST_SEASON} season")
    return year


def _season_name(league: str, year: int) -> str:
    """ASA names the USL Super League's split seasons by start year, for example 2024-25."""
    if league == "usls" and year <= 2025:
        return f"{year}-{(year + 1) % 100:02d}"
    return str(year)


def _stage(stage: str) -> dict[str, str]:
    if stage not in STAGES:
        raise ValueError(f"stage must be one of {sorted(STAGES)}")
    value = STAGES[stage]
    return {"stage_name": value} if value else {}


def _get(path: str, params: Mapping[str, str | int] | None = None, **kwargs: Any) -> api.JsonResponse:
    return api.get_json(api.ASA, path, params, **kwargs)


def _with_directories(
    league: str, path: str, params: Mapping[str, str | int], *, players: bool
) -> tuple[api.JsonResponse, dict[str, str | None], dict[str, Mapping[str, Any]]]:
    """Fetch a metric and the name directories it needs concurrently.

    ASA computes aggregates on demand; overlapping the directory lookups with
    the metric request keeps the first batch within interactive latency.
    """
    with ThreadPoolExecutor(max_workers=3) as pool:
        metric = pool.submit(_get, path, params)
        directory = pool.submit(_players, league) if players else None
        teams = pool.submit(_teams, league)
        return metric.result(), (directory.result() if directory else {}), teams.result()


def _list(response: api.JsonResponse, what: str) -> list[Mapping[str, Any]]:
    if response.payload is None:
        return []
    if not isinstance(response.payload, list):
        raise ValueError(f"American Soccer Analysis {what} response is not a list")
    return records(response.payload)


def _teams(league: str) -> dict[str, Mapping[str, Any]]:
    response = _get(f"{league}/teams", ttl=DIRECTORY_TTL)
    return {str(item.get("team_id")): item for item in _list(response, "teams")}


def _players(league: str) -> dict[str, str | None]:
    response = _get(f"{league}/players", ttl=DIRECTORY_TTL)
    return {
        str(item.get("player_id")): to_str(item.get("player_name")) for item in _list(response, "players")
    }


def _team_columns(teams: Mapping[str, Mapping[str, Any]], team_id: Any) -> dict[str, Any]:
    key = to_str(team_id)
    team = mapping(teams.get(key or ""))
    return {
        "team_id": key,
        "team_name": to_str(team.get("team_name")),
        "team_abbreviation": to_str(team.get("team_abbreviation")),
    }


def fetch_teams(league: str = "mls") -> Result:
    """ASA's team directory for one league."""
    code = _league(league)
    rows = [
        {
            "league": code,
            "team_id": to_str(item.get("team_id")),
            "team_name": to_str(item.get("team_name")),
            "team_short_name": to_str(item.get("team_short_name")),
            "team_abbreviation": to_str(item.get("team_abbreviation")),
        }
        for item in _teams(code).values()
    ]
    return Result(sorted((row for row in rows if row["team_id"]), key=lambda row: row["team_name"] or ""))


def fetch_xg_players(
    league: str = "mls", season: int | None = None, minimum_minutes: int = 0, stage: str = "regular_season"
) -> Result:
    """Player shooting and passing xG, one row per player and team."""
    code, year = _league(league), _season(season)
    response, players, teams = _with_directories(
        code,
        f"{code}/players/xgoals",
        {
            "season_name": _season_name(code, year),
            "minimum_minutes": minimum_minutes,
            "split_by_teams": "true",
            **_stage(stage),
        },
        players=True,
    )
    rows: list[dict[str, Any]] = []
    for item in _list(response, "player xgoals"):
        player_id = to_str(item.get("player_id"))
        rows.append(
            {
                "league": code,
                "season": year,
                "player_id": player_id,
                "player_name": players.get(player_id or ""),
                **_team_columns(teams, item.get("team_id")),
                "general_position": to_str(item.get("general_position")),
                "minutes_played": to_int(item.get("minutes_played")),
                "shots": to_int(item.get("shots")),
                "shots_on_target": to_int(item.get("shots_on_target")),
                "goals": to_int(item.get("goals")),
                "xgoals": to_float(item.get("xgoals")),
                "xplace": to_float(item.get("xplace")),
                "goals_minus_xgoals": to_float(item.get("goals_minus_xgoals")),
                "key_passes": to_int(item.get("key_passes")),
                "primary_assists": to_int(item.get("primary_assists")),
                "xassists": to_float(item.get("xassists")),
                "primary_assists_minus_xassists": to_float(item.get("primary_assists_minus_xassists")),
                "goals_plus_primary_assists": to_int(item.get("goals_plus_primary_assists")),
                "xgoals_plus_xassists": to_float(item.get("xgoals_plus_xassists")),
                "points_added": to_float(item.get("points_added")),
                "xpoints_added": to_float(item.get("xpoints_added")),
            }
        )
    return Result([row for row in rows if row["player_id"]], response.max_age)


def fetch_goals_added(
    league: str = "mls", season: int | None = None, minimum_minutes: int = 0, stage: str = "regular_season"
) -> Result:
    """Goals added (g+) by action type, one row per player and team."""
    code, year = _league(league), _season(season)
    response, players, teams = _with_directories(
        code,
        f"{code}/players/goals-added",
        {
            "season_name": _season_name(code, year),
            "minimum_minutes": minimum_minutes,
            "split_by_teams": "true",
            **_stage(stage),
        },
        players=True,
    )
    rows: list[dict[str, Any]] = []
    for item in _list(response, "player goals added"):
        player_id = to_str(item.get("player_id"))
        actions = {str(action.get("action_type", "")).lower(): action for action in records(item.get("data"))}
        raw = [to_float(action.get("goals_added_raw")) for action in actions.values()]
        above = [to_float(action.get("goals_added_above_avg")) for action in actions.values()]
        row = {
            "league": code,
            "season": year,
            "player_id": player_id,
            "player_name": players.get(player_id or ""),
            **_team_columns(teams, item.get("team_id")),
            "general_position": to_str(item.get("general_position")),
            "minutes_played": to_int(item.get("minutes_played")),
            "goals_added_raw": round(sum(v for v in raw if v is not None), 4) if actions else None,
            "goals_added_above_avg": round(sum(v for v in above if v is not None), 4) if actions else None,
        }
        for action in GOALS_ADDED_ACTIONS:
            row[f"{action}_above_avg"] = to_float(mapping(actions.get(action)).get("goals_added_above_avg"))
        rows.append(row)
    return Result([row for row in rows if row["player_id"]], response.max_age)


def fetch_xg_teams(league: str = "mls", season: int | None = None, stage: str = "regular_season") -> Result:
    """Team xG for and against, with expected points."""
    code, year = _league(league), _season(season)
    response, _, teams = _with_directories(
        code,
        f"{code}/teams/xgoals",
        {"season_name": _season_name(code, year), **_stage(stage)},
        players=False,
    )
    rows = [
        {
            "league": code,
            "season": year,
            **_team_columns(teams, item.get("team_id")),
            "games": to_int(item.get("count_games")),
            "shots_for": to_int(item.get("shots_for")),
            "shots_against": to_int(item.get("shots_against")),
            "goals_for": to_int(item.get("goals_for")),
            "goals_against": to_int(item.get("goals_against")),
            "goal_difference": to_int(item.get("goal_difference")),
            "xgoals_for": to_float(item.get("xgoals_for")),
            "xgoals_against": to_float(item.get("xgoals_against")),
            "xgoal_difference": to_float(item.get("xgoal_difference")),
            "goal_difference_minus_xgoal_difference": to_float(
                item.get("goal_difference_minus_xgoal_difference")
            ),
            "points": to_int(item.get("points")),
            "xpoints": to_float(item.get("xpoints")),
        }
        for item in _list(response, "team xgoals")
    ]
    return Result([row for row in rows if row["team_id"]], response.max_age)


def fetch_xg_games(league: str = "mls", season: int | None = None, stage: str = "regular_season") -> Result:
    """Match-level xG for every game in a season."""
    code, year = _league(league), _season(season)
    response, _, teams = _with_directories(
        code,
        f"{code}/games/xgoals",
        {"season_name": _season_name(code, year), **_stage(stage)},
        players=False,
    )
    rows: list[dict[str, Any]] = []
    for item in _list(response, "game xgoals"):
        home = _team_columns(teams, item.get("home_team_id"))
        away = _team_columns(teams, item.get("away_team_id"))
        rows.append(
            {
                "league": code,
                "season": year,
                "game_id": to_str(item.get("game_id")),
                "kickoff": to_timestamp(item.get("date_time_utc")),
                "home_team_id": home["team_id"],
                "home_team_name": home["team_name"],
                "away_team_id": away["team_id"],
                "away_team_name": away["team_name"],
                "home_goals": to_int(item.get("home_goals")),
                "away_goals": to_int(item.get("away_goals")),
                "home_xgoals": to_float(item.get("home_team_xgoals")),
                "away_xgoals": to_float(item.get("away_team_xgoals")),
                "home_xpoints": to_float(item.get("home_xpoints")),
                "away_xpoints": to_float(item.get("away_xpoints")),
            }
        )
    rows = [row for row in rows if row["game_id"]]
    rows.sort(key=lambda row: (row["kickoff"] or datetime.min.replace(tzinfo=UTC), row["game_id"]))
    return Result(rows, response.max_age)


def fetch_salaries(season: int | None = None) -> Result:
    """MLS Players Association salary releases for one season (MLS only)."""
    year = _season(season)
    response, players, teams = _with_directories(
        "mls", "mls/players/salaries", {"season_name": year}, players=True
    )
    rows = [
        {
            "season": to_int(item.get("season_name")) or year,
            "player_id": to_str(item.get("player_id")),
            "player_name": players.get(str(item.get("player_id"))),
            **_team_columns(teams, item.get("team_id")),
            "mlspa_position": to_str(item.get("position")),
            "base_salary": to_float(item.get("base_salary")),
            "guaranteed_compensation": to_float(item.get("guaranteed_compensation")),
            "release_date": to_date(item.get("mlspa_release")),
        }
        for item in _list(response, "salaries")
    ]
    return Result([row for row in rows if row["player_id"]], response.max_age)
