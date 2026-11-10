"""MLS Stats API (stats-api.mlssoccer.com): endpoints, Arrow schemas, and flattening.

Every MLS path the connector uses is pinned in this module. The backend is
undocumented and changed shape in the 2024 Sportec migration, so the contract
tests in ``tests/test_mls.py`` exercise each path against recorded responses.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pyarrow as pa

from vgi_us_soccer import api
from vgi_us_soccer.meta import (
    TIMESTAMP,
    field,
    join_name,
    mapping,
    records,
    to_bool,
    to_float,
    to_int,
    to_str,
    to_timestamp,
)

PAGE_SIZE = 1_000
MAX_PAGES = 50
REFERENCE_TTL = 3_600.0

REGULAR_SEASON = "MLS-COM-000001"
TEST_COMPETITION = "MLS-COM-00002R"
COMPETITION_ALIASES: dict[str, str] = {
    "mls": REGULAR_SEASON,
    "mls_playoffs": "MLS-COM-000002",
    "next_pro": "MLS-COM-000003",
    "next_pro_playoffs": "MLS-COM-000004",
    "all_star": "MLS-COM-000005",
    "leagues_cup": "MLS-COM-000006",
    "campeones_cup": "MLS-COM-000007",
    "champions_cup": "MLS-COM-00000K",
    "us_open_cup": "MLS-COM-00002U",
    "canadian_championship": "MLS-COM-00002V",
}
COMPETITION_PATTERN = r"^(MLS-COM-[0-9A-Z]{6}|" + "|".join(COMPETITION_ALIASES) + r")$"
STANDINGS_SPLITS = {"overall": "table", "home": "home", "away": "away", "form": "shape"}


@dataclass(frozen=True, slots=True)
class Result:
    """Flattened rows plus the freshness the connector may advertise."""

    rows: list[dict[str, Any]]
    max_age: int | None = None


def competition_id(value: str | None) -> str:
    """Resolve a short alias such as ``next_pro`` or pass a raw ``MLS-COM-`` id through."""
    if value is None:
        return REGULAR_SEASON
    text = value.strip()
    resolved = COMPETITION_ALIASES.get(text.lower(), text)
    if not resolved.startswith("MLS-COM-"):
        raise ValueError(
            f"unknown MLS competition {value!r}; use an MLS-COM- id or one of {sorted(COMPETITION_ALIASES)}"
        )
    return resolved


# ---------------------------------------------------------------- schemas

_SEASON_COLUMNS = [
    field("season", pa.int32(), "Season year."),
    field("season_id", pa.string(), "MLS season id, e.g. MLS-SEA-0001KA."),
    field("competition_id", pa.string(), "MLS competition id, e.g. MLS-COM-000001."),
]

COMPETITIONS_SCHEMA = pa.schema(
    [
        field("competition_id", pa.string(), "MLS Stats API competition identifier.", nullable=False),
        field("competition_name", pa.string(), "Competition name in English."),
        field("competition_name_french", pa.string(), "Competition name in French."),
        field("competition_type", pa.string(), "League for round-robin play or Tournament for cups."),
        field("country", pa.string(), "Country code the competition is registered under."),
        field("alias", pa.string(), "Short alias accepted by this catalog's competition arguments."),
    ]
)

SEASONS_SCHEMA = pa.schema(
    [
        field("competition_id", pa.string(), "MLS Stats API competition identifier."),
        field("season", pa.int32(), "Season year."),
        field("season_id", pa.string(), "MLS Stats API season identifier.", nullable=False),
    ]
)

STANDINGS_SCHEMA = pa.schema(
    [
        *_SEASON_COLUMNS,
        field("competition_name", pa.string(), "Competition name."),
        field("standings_split", pa.string(), "Requested table: overall, home, away, or form."),
        field("group_name", pa.string(), "Group label for cup group stages; NULL for a single league table."),
        field("match_day", pa.int32(), "Latest matchday reflected in the table."),
        field("position", pa.int32(), "Table position."),
        field("club_id", pa.string(), "Stable MLS club identifier.", nullable=False),
        field("club_name", pa.string(), "Full club name."),
        field("club_short_name", pa.string(), "Short club name."),
        field("club_abbreviation", pa.string(), "Club three-letter code."),
        field("games_played", pa.int32(), "Matches played."),
        field("wins", pa.int32(), "Wins."),
        field("draws", pa.int32(), "Draws."),
        field("losses", pa.int32(), "Losses."),
        field("goals_for", pa.int32(), "Goals scored."),
        field("goals_against", pa.int32(), "Goals conceded."),
        field("goal_difference", pa.int32(), "Goals scored minus goals conceded."),
        field("points", pa.int32(), "League points."),
        field("points_per_game", pa.float64(), "Points per match as published by MLS."),
        field("goals_for_per_game", pa.float64(), "Goals scored per match."),
        field("goals_against_per_game", pa.float64(), "Goals conceded per match."),
        field("tendency", pa.string(), "Recent movement in the table: up, down, or stable."),
    ]
)

CLUBS_SCHEMA = pa.schema(
    [
        *_SEASON_COLUMNS,
        field("club_id", pa.string(), "Stable MLS club identifier.", nullable=False),
        field("club_name", pa.string(), "Full club name."),
        field("club_short_name", pa.string(), "Short club name."),
        field("club_abbreviation", pa.string(), "Club three-letter code."),
        field("city", pa.string(), "Home city."),
        field("country", pa.string(), "Country code."),
    ]
)

_CLUB_STAT_COLUMNS = [
    field("goals", pa.int32(), "Goals scored."),
    field("goals_conceded", pa.int32(), "Goals conceded."),
    field("xg", pa.float64(), "Expected goals created, from MLS's tracking-data model."),
    field("shots", pa.int32(), "Shots attempted."),
    field("shots_on_target", pa.int32(), "Shots on target."),
    field("shots_faced", pa.int32(), "Opponent shots on target."),
    field("passes", pa.int32(), "Passes attempted, open play and set pieces."),
    field("passes_successful", pa.int32(), "Completed passes."),
    field("pass_completion", pa.float64(), "Completed passes divided by passes, 0 to 1."),
    field("possession_ratio", pa.float64(), "Share of ball possession, in percent."),
    field("crosses", pa.int32(), "Crosses attempted."),
    field("corners", pa.int32(), "Corner kicks taken."),
    field("offsides", pa.int32(), "Times caught offside."),
    field("fouls_committed", pa.int32(), "Fouls committed."),
    field("fouls_suffered", pa.int32(), "Fouls suffered."),
    field("yellow_cards", pa.int32(), "Yellow cards."),
    field("red_cards", pa.int32(), "Straight red cards."),
    field("yellow_red_cards", pa.int32(), "Second-yellow dismissals."),
    field("penalties_scored", pa.int32(), "Penalties scored."),
    field("penalties_attempted", pa.int32(), "Penalties taken."),
    field("own_goals", pa.int32(), "Own goals conceded by this club's players."),
    field("goalkeeper_saves", pa.int32(), "Saves by the club's goalkeepers."),
    field("aerial_duels_won", pa.int32(), "Aerial duels won."),
    field("aerial_duels_lost", pa.int32(), "Aerial duels lost."),
    field("counter_attacks", pa.int32(), "Counter-attacks."),
    field("distance_covered_m", pa.float64(), "Total distance covered by the club's players, in meters."),
]

CLUB_STATS_SCHEMA = pa.schema(
    [
        *_SEASON_COLUMNS,
        field("club_id", pa.string(), "Stable MLS club identifier.", nullable=False),
        field("club_name", pa.string(), "Full club name."),
        field("club_short_name", pa.string(), "Short club name."),
        field("club_abbreviation", pa.string(), "Club three-letter code."),
        field("matches_played", pa.int32(), "Matches played in this competition and season."),
        field("clean_sheets", pa.int32(), "Matches without conceding."),
        *_CLUB_STAT_COLUMNS,
    ]
)

_PLAYER_STAT_COLUMNS = [
    field("minutes_played", pa.int32(), "Minutes played."),
    field("substitutions_in", pa.int32(), "Appearances as a substitute."),
    field("substitutions_out", pa.int32(), "Times substituted off."),
    field("goals", pa.int32(), "Goals scored."),
    field("assists", pa.int32(), "Assists."),
    field("second_assists", pa.int32(), "Second (pre-) assists."),
    field("goals_plus_assists", pa.int32(), "Goals plus assists."),
    field("xg", pa.float64(), "Expected goals (MLS tracking model)."),
    field("goals_minus_xg", pa.float64(), "Goals minus xg."),
    field("shots", pa.int32(), "Shots attempted."),
    field("shots_on_target", pa.int32(), "Shots on target."),
    field("shots_inside_box", pa.int32(), "Shots from inside the penalty area."),
    field("headed_shots", pa.int32(), "Headed shots."),
    field("shot_assists", pa.int32(), "Key passes: passes leading to a shot."),
    field("passes", pa.int32(), "Passes attempted."),
    field("passes_successful", pa.int32(), "Completed passes."),
    field("pass_completion", pa.float64(), "Completed passes divided by passes, 0 to 1."),
    field("crosses", pa.int32(), "Crosses attempted."),
    field("penalties_scored", pa.int32(), "Penalties scored."),
    field("penalties_attempted", pa.int32(), "Penalties taken."),
    field("offsides", pa.int32(), "Times caught offside."),
    field("fouls_committed", pa.int32(), "Fouls committed."),
    field("fouls_suffered", pa.int32(), "Fouls suffered."),
    field("yellow_cards", pa.int32(), "Yellow cards."),
    field("red_cards", pa.int32(), "Straight red cards."),
    field("yellow_red_cards", pa.int32(), "Second-yellow dismissals."),
    field("own_goals", pa.int32(), "Own goals."),
    field("aerial_duels_won", pa.int32(), "Aerial duels won."),
    field("aerial_duels_lost", pa.int32(), "Aerial duels lost."),
    field("clearances", pa.int32(), "Defensive clearances."),
    field("distance_covered_m", pa.float64(), "Distance covered, in meters."),
    field("max_speed_kmh", pa.float64(), "Top speed, km/h."),
    field("goalkeeper_saves", pa.int32(), "Saves; goalkeepers only."),
    field("goals_conceded", pa.int32(), "Goals conceded; goalkeepers only."),
    field("clean_sheets", pa.int32(), "Goalkeeper clean sheets; NULL per match."),
]

PLAYER_STATS_SCHEMA = pa.schema(
    [
        *_SEASON_COLUMNS,
        field("player_id", pa.string(), "Stable MLS player id, e.g. MLS-OBJ-000396.", nullable=False),
        field("player_name", pa.string(), "Display name."),
        field("first_name", pa.string(), "First name."),
        field("last_name", pa.string(), "Last name."),
        field("goalkeeper", pa.bool_(), "Whether the player is a goalkeeper."),
        field("club_id", pa.string(), "Club of this line; one row per club.", nullable=False),
        field("club_short_name", pa.string(), "Short club name."),
        field("club_abbreviation", pa.string(), "Club three-letter code."),
        field("matches_played", pa.int32(), "Matches played for this club."),
        *_PLAYER_STAT_COLUMNS,
        field("x_saves", pa.float64(), "Expected saves (goalkeepers)."),
        field("x_pass", pa.float64(), "Expected completed open-play passes."),
        field("passing_performance", pa.float64(), "Open-play completions minus x_pass."),
    ]
)

_MATCH_COLUMNS = [
    field(
        "match_id", pa.string(), "Stable MLS match identifier, for example MLS-MAT-0009NL.", nullable=False
    ),
    field("competition_id", pa.string(), "MLS Stats API competition identifier."),
    field("competition_name", pa.string(), "Competition name."),
    field("season", pa.int32(), "Season year."),
    field("season_id", pa.string(), "MLS Stats API season identifier."),
    field("match_day", pa.int32(), "Matchday number within the competition."),
    field("match_type", pa.string(), "Round label, for example MATCHWEEK 31 or Semifinals."),
    field("planned_kickoff", TIMESTAMP, "Scheduled kickoff time."),
    field("match_status", pa.string(), "Match state, for example scheduled or finalWhistle."),
    field("home_club_id", pa.string(), "Home club identifier."),
    field("home_club_name", pa.string(), "Home club name."),
    field("home_club_abbreviation", pa.string(), "Home club three-letter code."),
    field("away_club_id", pa.string(), "Away club identifier."),
    field("away_club_name", pa.string(), "Away club name."),
    field("away_club_abbreviation", pa.string(), "Away club three-letter code."),
    field("home_goals", pa.int32(), "Home goals; NULL before kickoff."),
    field("away_goals", pa.int32(), "Away goals; NULL before kickoff."),
    field("result", pa.string(), "Score as home:away; NULL before kickoff."),
    field("minute_of_play", pa.string(), "Last minute of play recorded, for example 90+6."),
    field("conference", pa.string(), "Conference of the fixture when MLS labels it."),
    field("stadium_id", pa.string(), "Stadium identifier."),
    field("stadium_name", pa.string(), "Stadium name."),
    field("stadium_city", pa.string(), "Stadium city."),
]

SCHEDULE_SCHEMA = pa.schema(
    [*_MATCH_COLUMNS, field("neutral_venue", pa.bool_(), "Whether the match is at a neutral venue.")]
)

MATCH_SCHEMA = pa.schema(
    [
        *_MATCH_COLUMNS,
        field("kickoff", TIMESTAMP, "Actual kickoff time."),
        field("attendance", pa.int32(), "Announced attendance."),
        field("stadium_capacity", pa.int32(), "Stadium capacity."),
        field("sold_out", pa.bool_(), "Whether the match was sold out."),
        field("temperature_c", pa.int32(), "Air temperature at kickoff, in degrees Celsius."),
        field("home_formation", pa.string(), "Home starting formation, for example 3-5-2."),
        field("away_formation", pa.string(), "Away starting formation."),
        field("home_head_coach", pa.string(), "Home head coach."),
        field("away_head_coach", pa.string(), "Away head coach."),
        field("referee", pa.string(), "Center referee."),
    ]
)

LINEUPS_SCHEMA = pa.schema(
    [
        field("match_id", pa.string(), "MLS match identifier.", nullable=False),
        field("team_role", pa.string(), "home or away."),
        field("club_id", pa.string(), "Club identifier."),
        field("club_abbreviation", pa.string(), "Club three-letter code."),
        field("player_id", pa.string(), "MLS player identifier.", nullable=False),
        field("player_name", pa.string(), "Player full name."),
        field("short_name", pa.string(), "Player short display name."),
        field("shirt_number", pa.int32(), "Shirt number."),
        field(
            "lineup_position", pa.string(), "Lineup position code, for example GK or LCB; NULL on the bench."
        ),
        field("starter", pa.bool_(), "Whether the player started."),
        field("captain", pa.bool_(), "Whether the player captained the side."),
    ]
)

EVENTS_SCHEMA = pa.schema(
    [
        field("match_id", pa.string(), "MLS match identifier.", nullable=False),
        field("event_id", pa.int64(), "Event identifier, unique within the match.", nullable=False),
        field(
            "event_type", pa.string(), "Event type: shot_at_goals, cards, substitutions, fouls, and so on."
        ),
        field("event_sub_type", pa.string(), "Sub-type; goals marks a shot that scored."),
        field("is_goal", pa.bool_(), "Whether the event is a goal."),
        field("event_time", TIMESTAMP, "Wall-clock event time."),
        field("game_section", pa.string(), "Period: firstHalf, secondHalf, extra time, or penalties."),
        field("minute_of_play", pa.string(), "Displayed match minute, for example 45+2."),
        field("club_id", pa.string(), "Acting club (shooter, booked player, fouler, or substituting club)."),
        field("club_abbreviation", pa.string(), "Acting club three-letter code."),
        field("team_role", pa.string(), "home or guest for the acting club."),
        field(
            "player_id", pa.string(), "Acting player: shooter, booked player, fouler, or player coming on."
        ),
        field("player_name", pa.string(), "Acting player name."),
        field("other_player_id", pa.string(), "Assister, fouled player, or player going off."),
        field("other_player_name", pa.string(), "Name of the other player."),
        field("card_color", pa.string(), "yellow, yellowRed, or red for card events."),
        field("shot_result", pa.string(), "Shot outcome, for example SavedShot or SuccessfulShot."),
        field("xg", pa.float64(), "Expected-goals value of a shot."),
        field("distance_to_goal_m", pa.float64(), "Shot distance from goal, in meters."),
        field("position_x", pa.float64(), "Pitch x coordinate, in meters."),
        field("position_y", pa.float64(), "Pitch y coordinate, in meters."),
        field("final_result", pa.string(), "Score at the final whistle of the section."),
    ]
)

COMMENTARY_SCHEMA = pa.schema(
    [
        field("match_id", pa.string(), "MLS match identifier.", nullable=False),
        field("event_id", pa.string(), "Commentary entry identifier.", nullable=False),
        field("event_time", TIMESTAMP, "Wall-clock time of the commented event."),
        field("minute", pa.int32(), "Elapsed match minute."),
        field("second", pa.int32(), "Elapsed second within the minute."),
        field("minute_of_play", pa.string(), "Displayed match minute, for example 90'+6."),
        field("game_section", pa.string(), "Period of play."),
        field("commentary_type", pa.string(), "Commentary category, for example Foul or ShotAtGoal."),
        field("commentary", pa.string(), "English commentary text."),
        field("club_id", pa.string(), "Club the entry concerns."),
        field("club_abbreviation", pa.string(), "Club three-letter code."),
        field("player_id", pa.string(), "Primary player identifier."),
        field("other_player_id", pa.string(), "Secondary player identifier."),
    ]
)

MATCH_CLUB_STATS_SCHEMA = pa.schema(
    [
        field("match_id", pa.string(), "MLS match identifier.", nullable=False),
        field("team_role", pa.string(), "home or away."),
        field("club_id", pa.string(), "Club identifier.", nullable=False),
        field("club_name", pa.string(), "Full club name."),
        field("club_abbreviation", pa.string(), "Club three-letter code."),
        *_CLUB_STAT_COLUMNS,
    ]
)

MATCH_PLAYER_STATS_SCHEMA = pa.schema(
    [
        field("match_id", pa.string(), "MLS match identifier.", nullable=False),
        field("club_id", pa.string(), "Club identifier."),
        field("club_abbreviation", pa.string(), "Club three-letter code."),
        field("player_id", pa.string(), "MLS player identifier.", nullable=False),
        field("player_name", pa.string(), "Player display name."),
        field("goalkeeper", pa.bool_(), "Whether the player is a goalkeeper."),
        *_PLAYER_STAT_COLUMNS,
    ]
)

PLAYER_MATCH_LOG_SCHEMA = pa.schema(
    [
        field("match_id", pa.string(), "MLS match identifier.", nullable=False),
        field("planned_kickoff", TIMESTAMP, "Scheduled kickoff time."),
        field("competition_id", pa.string(), "Competition identifier."),
        field("competition_name", pa.string(), "Competition name."),
        field("season", pa.int32(), "Season year."),
        field("match_title", pa.string(), "Home club and away club, separated by a colon."),
        field("result", pa.string(), "Final score as home:away."),
        field("club_id", pa.string(), "Club the player appeared for."),
        field("club_abbreviation", pa.string(), "Club three-letter code."),
        field("player_id", pa.string(), "MLS player identifier.", nullable=False),
        field("player_name", pa.string(), "Player display name."),
        *_PLAYER_STAT_COLUMNS,
    ]
)


# ---------------------------------------------------------------- fetch helpers


def _get(path: str, params: Mapping[str, str | int] | None = None, **kwargs: Any) -> api.JsonResponse:
    return api.get_json(api.MLS, path, params, **kwargs)


def _paged(
    path: str, key: str, params: Mapping[str, str | int] | None = None
) -> tuple[list[Any], int | None]:
    """Follow ``next_page_token`` until the upstream has no further pages."""
    items: list[Any] = []
    responses: list[api.JsonResponse] = []
    token: str | None = None
    for _ in range(MAX_PAGES):
        query: dict[str, str | int] = {**(params or {}), "per_page": PAGE_SIZE}
        if token:
            query["page_token"] = token
        response = _get(path, query, not_found_ok=True)
        if response.payload is None:
            return items, None
        if not isinstance(response.payload, dict):
            raise ValueError(f"MLS Stats API {path} response is not an object")
        responses.append(response)
        page = response.payload.get(key)
        if isinstance(page, list):
            items.extend(page)
        elif isinstance(page, dict):
            items.append(page)
        token = response.payload.get("next_page_token") or None
        if not token:
            return items, api.shortest_max_age(responses)
    raise RuntimeError(f"MLS Stats API pagination for {path} exceeded {MAX_PAGES} pages")


def fetch_competitions() -> Result:
    """Every competition the MLS Stats API publishes, excluding its internal test feed."""
    payload = _get("competitions", ttl=REFERENCE_TTL).payload
    aliases = {value: key for key, value in COMPETITION_ALIASES.items()}
    rows = [
        {
            "competition_id": to_str(item.get("competition_id")),
            "competition_name": to_str(item.get("competition_name")),
            "competition_name_french": to_str(item.get("competition_name_french")),
            "competition_type": to_str(item.get("competition_type")),
            "country": to_str(item.get("country")),
            "alias": aliases.get(str(item.get("competition_id"))),
        }
        for item in records(mapping(payload).get("competitions"))
        if item.get("competition_id") and item.get("competition_id") != TEST_COMPETITION
    ]
    return Result(rows)


def fetch_seasons(competition: str | None = None) -> Result:
    """Seasons published for one competition, newest first."""
    comp = competition_id(competition)
    response = _get(f"competitions/{comp}/seasons", ttl=REFERENCE_TTL, not_found_ok=True)
    rows = [
        {
            "competition_id": comp,
            "season": to_int(item.get("season")),
            "season_id": to_str(item.get("season_id")),
        }
        for item in records(mapping(response.payload).get("seasons"))
        if item.get("season_id")
    ]
    return Result(sorted(rows, key=lambda row: -(row["season"] or 0)))


def resolve_season(
    competition: str | None, season: int | None, *, today: date | None = None
) -> tuple[int, str]:
    """Map a season year (or NULL for the current season) to its MLS season id."""
    comp = competition_id(competition)
    seasons = [row for row in fetch_seasons(comp).rows if row["season"] is not None and row["season_id"]]
    if not seasons:
        raise ValueError(f"MLS Stats API lists no seasons for competition {comp}")
    if season is None:
        year = (today or datetime.now(UTC).date()).year
        eligible = [row for row in seasons if row["season"] <= year] or seasons
        chosen = max(eligible, key=lambda row: row["season"])
    else:
        chosen = next((row for row in seasons if row["season"] == season), None)
        if chosen is None:
            available = ", ".join(str(row["season"]) for row in seasons)
            raise ValueError(f"no {comp} season {season}; available seasons: {available}")
    return chosen["season"], chosen["season_id"]


def fetch_standings(
    competition: str | None = None, season: int | None = None, split: str = "overall"
) -> Result:
    """League table for one competition and season."""
    if split not in STANDINGS_SPLITS:
        raise ValueError(f"split must be one of {sorted(STANDINGS_SPLITS)}")
    comp = competition_id(competition)
    year, season_id = resolve_season(comp, season)
    response = _get(
        f"competitions/{comp}/seasons/{season_id}/standings",
        {"type": STANDINGS_SPLITS[split]} if split != "overall" else None,
        not_found_ok=True,
    )
    rows: list[dict[str, Any]] = []
    for table in records(mapping(response.payload).get("tables")):
        group = to_str(table.get("group")) or to_str(table.get("leagues_cup_group"))
        for entry in records(table.get("entries")):
            rows.append(
                {
                    "season": to_int(table.get("season")) or year,
                    "season_id": to_str(table.get("season_id")) or season_id,
                    "competition_id": to_str(table.get("competition_id")) or comp,
                    "competition_name": to_str(table.get("competition")),
                    "standings_split": split,
                    "group_name": group,
                    "match_day": to_int(table.get("match_day")),
                    "position": to_int(entry.get("position")),
                    "club_id": to_str(entry.get("club_id") or entry.get("team_id")),
                    "club_name": to_str(entry.get("club") or entry.get("team")),
                    "club_short_name": to_str(entry.get("team_short_name")),
                    "club_abbreviation": to_str(entry.get("team_three_letter_code")),
                    "games_played": to_int(entry.get("games_played")),
                    "wins": to_int(entry.get("wins")),
                    "draws": to_int(entry.get("draws")),
                    "losses": to_int(entry.get("losses")),
                    "goals_for": to_int(entry.get("goals_scored")),
                    "goals_against": to_int(entry.get("goals_against")),
                    "goal_difference": to_int(entry.get("goals_difference")),
                    "points": to_int(entry.get("points")),
                    "points_per_game": to_float(entry.get("points_per_game")),
                    "goals_for_per_game": to_float(entry.get("goals_scored_per_game")),
                    "goals_against_per_game": to_float(entry.get("goals_against_per_game")),
                    "tendency": to_str(entry.get("tendency")),
                }
            )
    return Result([row for row in rows if row["club_id"]], response.max_age)


def fetch_clubs(competition: str | None = None, season: int | None = None) -> Result:
    """Clubs registered in one competition and season."""
    comp = competition_id(competition)
    year, season_id = resolve_season(comp, season)
    items, max_age = _paged(f"clubs/competitions/{comp}/seasons/{season_id}", "clubs")
    rows = [
        {
            "season": to_int(item.get("season")) or year,
            "season_id": to_str(item.get("season_id")) or season_id,
            "competition_id": to_str(item.get("competition_id")) or comp,
            "club_id": to_str(item.get("club_id")),
            "club_name": to_str(item.get("club_name")),
            "club_short_name": to_str(item.get("club_short_name") or item.get("short_name")),
            "club_abbreviation": to_str(item.get("club_three_letter_code") or item.get("three_letter_code")),
            "city": to_str(item.get("city")),
            "country": to_str(item.get("country")),
        }
        for item in records(items)
    ]
    return Result([row for row in rows if row["club_id"]], max_age)


def _club_stats(item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "goals": to_int(item.get("goals")),
        "goals_conceded": to_int(item.get("goals_conceded")),
        "xg": to_float(item.get("xG")),
        "shots": to_int(item.get("shots_at_goal_sum")),
        "shots_on_target": to_int(item.get("shots_on_target")),
        "shots_faced": to_int(item.get("shots_faced")),
        "passes": to_int(item.get("passes_sum")),
        "passes_successful": to_int(item.get("passes_successful_sum")),
        "pass_completion": to_float(item.get("passes_conversion_rate")),
        "possession_ratio": to_float(item.get("possession_ratio")),
        "crosses": to_int(item.get("crosses_sum")),
        "corners": to_int(item.get("corner_kicks_sum")),
        "offsides": to_int(item.get("offsides")),
        "fouls_committed": to_int(item.get("fouls_sum")),
        "fouls_suffered": to_int(item.get("fouls_suffered")),
        "yellow_cards": to_int(item.get("cards_yellow")),
        "red_cards": to_int(item.get("cards_red")),
        "yellow_red_cards": to_int(item.get("cards_yellow_red")),
        "penalties_scored": to_int(item.get("penalties_successful")),
        "penalties_attempted": to_int(item.get("penalties_sum")),
        "own_goals": to_int(item.get("own_goals")),
        "goalkeeper_saves": to_int(item.get("goalkeeper_saves")),
        "aerial_duels_won": to_int(item.get("tackling_games_air_won")),
        "aerial_duels_lost": to_int(item.get("tackling_games_air_lost")),
        "counter_attacks": to_int(item.get("counter_attacks")),
        "distance_covered_m": to_float(item.get("distance_covered")),
    }


def fetch_club_stats(competition: str | None = None, season: int | None = None) -> Result:
    """Season club statistics for one competition."""
    comp = competition_id(competition)
    year, season_id = resolve_season(comp, season)
    items, max_age = _paged(f"statistics/clubs/competitions/{comp}/seasons/{season_id}", "team_statistics")
    rows = [
        {
            "season": year,
            "season_id": season_id,
            "competition_id": comp,
            "club_id": to_str(item.get("team_id")),
            "club_name": to_str(item.get("team_name")),
            "club_short_name": to_str(item.get("team_short_name")),
            "club_abbreviation": to_str(item.get("team_three_letter_code") or item.get("three_letter_code")),
            "matches_played": to_int(item.get("matches_played")),
            "clean_sheets": to_int(item.get("clean_sheets")),
            **_club_stats(item),
        }
        for item in records(items)
    ]
    return Result([row for row in rows if row["club_id"]], max_age)


def _player_name(item: Mapping[str, Any]) -> str | None:
    return to_str(item.get("player_alias")) or join_name(
        item.get("player_first_name"), item.get("player_last_name")
    )


def _player_stats(item: Mapping[str, Any]) -> dict[str, Any]:
    goals = to_int(item.get("goals"))
    xg = to_float(item.get("xG"))
    advanced = mapping(item.get("advanced_stats"))
    return {
        "minutes_played": to_int(item.get("normalized_player_minutes")),
        "substitutions_in": to_int(item.get("substitutions_in")),
        "substitutions_out": to_int(item.get("substitutions_out")),
        "goals": goals,
        "assists": to_int(item.get("assists")),
        "second_assists": to_int(item.get("second_assists")),
        "goals_plus_assists": to_int(item.get("goals_plus_assists")),
        "xg": xg,
        "goals_minus_xg": round(goals - xg, 4) if goals is not None and xg is not None else None,
        "shots": to_int(item.get("shots_at_goal_sum")),
        "shots_on_target": to_int(item.get("shots_on_target")),
        "shots_inside_box": to_int(item.get("shots_at_goal_inside_box")),
        "headed_shots": to_int(item.get("shots_at_goal_head")),
        "shot_assists": to_int(item.get("assists_shot_at_goal")),
        "passes": to_int(item.get("passes_sum")),
        "passes_successful": to_int(item.get("passes_successful_sum")),
        "pass_completion": to_float(item.get("passes_conversion_rate")),
        "crosses": to_int(item.get("crosses_sum")),
        "penalties_scored": to_int(item.get("penalties_successful")),
        "penalties_attempted": to_int(item.get("penalties_sum")),
        "offsides": to_int(item.get("offsides")),
        "fouls_committed": to_int(item.get("fouls_sum")),
        "fouls_suffered": to_int(item.get("fouls_suffered")),
        "yellow_cards": to_int(item.get("cards_yellow")),
        "red_cards": to_int(item.get("cards_red")),
        "yellow_red_cards": to_int(item.get("cards_yellow_red")),
        "own_goals": to_int(item.get("own_goals")),
        "aerial_duels_won": to_int(item.get("tackling_games_air_won")),
        "aerial_duels_lost": to_int(item.get("tackling_games_air_lost")),
        "clearances": to_int(item.get("defensive_clearances")),
        "distance_covered_m": to_float(item.get("distance_covered")),
        "max_speed_kmh": to_float(item.get("maximum_speed")),
        "goalkeeper_saves": to_int(item.get("goalkeeper_saves") or advanced.get("saves")),
        "goals_conceded": to_int(item.get("goals_conceded")),
        "clean_sheets": to_int(item.get("clean_sheets")),
        "x_saves": to_float(advanced.get("x_saves")),
        "x_pass": to_float(advanced.get("x_pass")),
        "passing_performance": to_float(advanced.get("passing_performance")),
    }


def fetch_player_stats(competition: str | None = None, season: int | None = None) -> Result:
    """Season player statistics for one competition, one row per player and club."""
    comp = competition_id(competition)
    year, season_id = resolve_season(comp, season)
    items, max_age = _paged(
        f"statistics/players/competitions/{comp}/seasons/{season_id}", "player_statistics"
    )
    rows = [
        {
            "season": to_int(item.get("season")) or year,
            "season_id": season_id,
            "competition_id": comp,
            "player_id": to_str(item.get("player_id")),
            "player_name": _player_name(item),
            "first_name": to_str(item.get("player_first_name")),
            "last_name": to_str(item.get("player_last_name")),
            "goalkeeper": to_bool(item.get("goal_keeper")),
            "club_id": to_str(item.get("team_id")),
            "club_short_name": to_str(item.get("team_short_name")),
            "club_abbreviation": to_str(item.get("team_three_letter_code")),
            "matches_played": to_int(item.get("matches_played")),
            **_player_stats(item),
        }
        for item in records(items)
    ]
    return Result([row for row in rows if row["player_id"] and row["club_id"]], max_age)


def _schedule_row(item: Mapping[str, Any]) -> dict[str, Any]:
    status = to_str(item.get("match_status"))
    played = status not in (None, "scheduled")
    return {
        "match_id": to_str(item.get("match_id")),
        "competition_id": to_str(item.get("competition_id")),
        "competition_name": to_str(item.get("competition_name")),
        "season": to_int(item.get("season")),
        "season_id": to_str(item.get("season_id")),
        "match_day": to_int(item.get("match_day")),
        "match_type": to_str(item.get("match_type")),
        "planned_kickoff": to_timestamp(item.get("planned_kickoff_time")),
        "match_status": status,
        "home_club_id": to_str(item.get("home_team_id")),
        "home_club_name": to_str(item.get("home_team_name")),
        "home_club_abbreviation": to_str(item.get("home_team_three_letter_code")),
        "away_club_id": to_str(item.get("away_team_id")),
        "away_club_name": to_str(item.get("away_team_name")),
        "away_club_abbreviation": to_str(item.get("away_team_three_letter_code")),
        "home_goals": to_int(item.get("home_team_goals")) if played else None,
        "away_goals": to_int(item.get("away_team_goals")) if played else None,
        "result": to_str(item.get("result")) if played else None,
        "minute_of_play": to_str(item.get("minute_of_play")) if played else None,
        "conference": to_str(item.get("sub_league")),
        "stadium_id": to_str(item.get("stadium_id")),
        "stadium_name": to_str(item.get("stadium_name")),
        "stadium_city": to_str(item.get("stadium_city")),
        "neutral_venue": to_bool(item.get("neutral_venue")),
    }


def fetch_schedule(
    *,
    season: int | None = None,
    competition: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> Result:
    """Matches in one season, optionally narrowed to a competition and inclusive date range.

    The upstream requires a date filter; when neither bound is given the whole
    calendar year of the season is requested. ``competition`` NULL returns every
    competition in the season except the API's internal test feed.
    """
    if start_date and end_date and start_date > end_date:
        raise ValueError("start_date must be on or before end_date")
    comp = competition_id(competition) if competition is not None else None
    year, season_id = resolve_season(comp or REGULAR_SEASON, season)
    lower = start_date or date(year, 1, 1)
    upper = end_date or date(year, 12, 31)
    params: dict[str, str | int] = {
        "match_date[gte]": lower.isoformat(),
        "match_date[lte]": upper.isoformat(),
    }
    if comp is not None:
        params["competition_id"] = comp
    items, max_age = _paged(f"matches/seasons/{season_id}", "schedule", params)
    rows = [_schedule_row(item) for item in records(items) if item.get("competition_id") != TEST_COMPETITION]
    rows = [row for row in rows if row["match_id"]]
    rows.sort(key=lambda row: (row["planned_kickoff"] or datetime.max.replace(tzinfo=UTC), row["match_id"]))
    return Result(rows, max_age)


def fetch_current_schedule(*, today: date | None = None) -> Result:
    """Every MLS-family match from seven days ago through fourteen days ahead."""
    anchor = today or datetime.now(UTC).date()
    return fetch_schedule(start_date=anchor - timedelta(days=7), end_date=anchor + timedelta(days=14))


def _staff(side: Mapping[str, Any], role: str) -> str | None:
    for person in records(side.get("trainer_staff")):
        if person.get("role") == role:
            return join_name(person.get("first_name"), person.get("last_name"))
    return None


def fetch_match_detail(match_id: str) -> api.JsonResponse:
    """Raw match document; shared by ``match`` and ``match_lineups``."""
    return _get(f"matches/{match_id}", not_found_ok=True)


def fetch_match(match_id: str) -> Result:
    """One row describing a match, its venue, officials, and formations."""
    response = fetch_match_detail(match_id)
    if response.payload is None:
        return Result([])
    payload = mapping(response.payload)
    info = mapping(payload.get("match_information"))
    environment = mapping(payload.get("environment"))
    home = mapping(payload.get("home"))
    away = mapping(payload.get("away"))
    row = _schedule_row(
        {
            **info,
            "home_team_id": home.get("team_id"),
            "home_team_name": home.get("team_name"),
            "home_team_three_letter_code": home.get("team_three_letter_code"),
            "away_team_id": away.get("team_id"),
            "away_team_name": away.get("team_name"),
            "away_team_three_letter_code": away.get("team_three_letter_code"),
            "stadium_id": environment.get("stadium_id"),
            "stadium_name": environment.get("stadium_name"),
            "stadium_city": environment.get("city"),
        }
    )
    row.pop("neutral_venue", None)
    referee = next(
        (person for person in records(payload.get("referees")) if person.get("role") == "referee"),
        {},
    )
    row.update(
        {
            "match_id": row["match_id"] or match_id,
            "kickoff": to_timestamp(info.get("kickoff_time")),
            "attendance": to_int(environment.get("number_of_spectators")),
            "stadium_capacity": to_int(environment.get("stadium_capacity")),
            "sold_out": to_bool(environment.get("sold_out")),
            "temperature_c": to_int(environment.get("temperature")),
            "home_formation": to_str(home.get("initial_line_up")),
            "away_formation": to_str(away.get("initial_line_up")),
            "home_head_coach": _staff(home, "headcoach"),
            "away_head_coach": _staff(away, "headcoach"),
            "referee": join_name(referee.get("first_name"), referee.get("last_name")),
        }
    )
    return Result([row], response.max_age)


def fetch_match_lineups(match_id: str) -> Result:
    """Matchday squads: starters and substitutes for both clubs."""
    response = fetch_match_detail(match_id)
    payload = mapping(response.payload)
    rows: list[dict[str, Any]] = []
    for role in ("home", "away"):
        side = mapping(payload.get(role))
        for player in records(side.get("players")):
            rows.append(
                {
                    "match_id": match_id,
                    "team_role": role,
                    "club_id": to_str(side.get("team_id")),
                    "club_abbreviation": to_str(side.get("team_three_letter_code")),
                    "player_id": to_str(player.get("person_id")),
                    "player_name": join_name(player.get("first_name"), player.get("last_name")),
                    "short_name": to_str(player.get("short_name")),
                    "shirt_number": to_int(player.get("shirt_number")),
                    "lineup_position": to_str(player.get("playing_position")),
                    "starter": to_bool(player.get("starting")),
                    "captain": to_bool(player.get("team_leader")),
                }
            )
    return Result([row for row in rows if row["player_id"]], response.max_age)


def _event_row(match_id: str, item: Mapping[str, Any]) -> dict[str, Any]:
    kind = to_str(item.get("type"))
    sub_type = to_str(item.get("sub_type"))
    event = mapping(item.get("event"))
    if kind == "fouls":
        club_id, club_code, role = (
            event.get("team_fouler_id"),
            event.get("team_fouler_three_letter_code"),
            event.get("team_fouler_role"),
        )
        player_id = event.get("fouler_id")
        player = join_name(event.get("fouler_first_name"), event.get("fouler_last_name"))
        other_id = event.get("fouled_id")
        other = join_name(event.get("fouled_first_name"), event.get("fouled_last_name"))
    elif kind == "substitutions":
        club_id, club_code, role = (
            event.get("team_id"),
            event.get("team_three_letter_code"),
            event.get("team_role"),
        )
        player_id = event.get("player_in_id")
        player = join_name(event.get("player_in_first_name"), event.get("player_in_last_name"))
        other_id = event.get("player_out_id")
        other = join_name(event.get("player_out_first_name"), event.get("player_out_last_name"))
    else:
        club_id, club_code, role = (
            event.get("team_id"),
            event.get("team_three_letter_code"),
            event.get("team_role"),
        )
        player_id = event.get("player_id")
        player = to_str(event.get("player_alias")) or join_name(
            event.get("player_first_name"), event.get("player_last_name")
        )
        other_id = event.get("assist_player_id")
        other = to_str(event.get("assist_player_alias")) or join_name(
            event.get("assist_player_first_name"), event.get("assist_player_last_name")
        )
    return {
        "match_id": match_id,
        "event_id": to_int(event.get("event_id")),
        "event_type": kind,
        "event_sub_type": sub_type,
        "is_goal": kind == "shot_at_goals" and sub_type == "goals",
        "event_time": to_timestamp(event.get("event_time")),
        "game_section": to_str(event.get("game_section")),
        "minute_of_play": to_str(event.get("minute_of_play")),
        "club_id": to_str(club_id),
        "club_abbreviation": to_str(club_code),
        "team_role": to_str(role),
        "player_id": to_str(player_id),
        "player_name": player,
        "other_player_id": to_str(other_id),
        "other_player_name": other,
        "card_color": to_str(event.get("card_color")),
        "shot_result": to_str(event.get("shot_result")),
        "xg": to_float(event.get("xG")),
        "distance_to_goal_m": to_float(event.get("distance_to_goal")),
        "position_x": to_float(event.get("position_x")),
        "position_y": to_float(event.get("position_y")),
        "final_result": to_str(event.get("final_result")),
    }


def fetch_match_events(match_id: str) -> Result:
    """Key events (goals, shots, cards, substitutions, fouls) in chronological order."""
    items, max_age = _paged(f"matches/{match_id}/key_events", "events")
    rows = [_event_row(match_id, item) for item in records(items)]
    rows = [row for row in rows if row["event_id"] is not None]
    rows.sort(key=lambda row: (row["event_time"] or datetime.min.replace(tzinfo=UTC), row["event_id"]))
    return Result(rows, max_age)


def fetch_match_commentary(match_id: str) -> Result:
    """English text commentary in chronological order."""
    items, max_age = _paged(f"matches/{match_id}/commentary", "commentary", {"language": "en"})
    rows = [
        {
            "match_id": match_id,
            "event_id": to_str(item.get("event_id")),
            "event_time": to_timestamp(item.get("event_time")),
            "minute": to_int(item.get("minute")),
            "second": to_int(item.get("second")),
            "minute_of_play": to_str(item.get("minute_of_play")),
            "game_section": to_str(item.get("game_section")),
            "commentary_type": to_str(item.get("type")),
            "commentary": to_str(item.get("commentary")),
            "club_id": to_str(item.get("team_id")),
            "club_abbreviation": to_str(item.get("team_three_letter_code")),
            "player_id": to_str(item.get("player_id")),
            "other_player_id": to_str(item.get("second_player_id")),
        }
        for item in records(items)
    ]
    rows = [row for row in rows if row["event_id"]]
    rows.sort(key=lambda row: (row["minute"] or 0, row["second"] or 0, row["event_id"]))
    return Result(rows, max_age)


def fetch_match_club_stats(match_id: str) -> Result:
    """Per-club statistics for one match."""
    items, max_age = _paged(f"statistics/clubs/matches/{match_id}", "match_statistics_list")
    rows: list[dict[str, Any]] = []
    for wrapper in records(items):
        statistics = mapping(wrapper.get("match_statistics"))
        if mapping(statistics).get("scope", "match") != "match":
            continue
        for team in records(statistics.get("team_statistics")):
            rows.append(
                {
                    "match_id": to_str(statistics.get("match_id")) or match_id,
                    "team_role": to_str(team.get("team_role")),
                    "club_id": to_str(team.get("team_id")),
                    "club_name": to_str(team.get("team_name")),
                    "club_abbreviation": to_str(team.get("team_three_letter_code")),
                    **_club_stats(team),
                }
            )
    return Result([row for row in rows if row["club_id"]], max_age)


def fetch_match_player_stats(match_id: str) -> Result:
    """Per-player box-score lines for one match."""
    items, max_age = _paged(f"statistics/players/matches/{match_id}", "match_statistics")
    rows: list[dict[str, Any]] = []
    for statistics in records(items):
        for item in records(statistics.get("player_statistics")):
            rows.append(
                {
                    "match_id": to_str(item.get("match_id")) or match_id,
                    "club_id": to_str(item.get("team_id")),
                    "club_abbreviation": to_str(item.get("team_three_letter_code")),
                    "player_id": to_str(item.get("player_id")),
                    "player_name": _player_name(item),
                    "goalkeeper": to_bool(item.get("goal_keeper")),
                    **_player_stats(item),
                }
            )
    rows = [row for row in rows if row["player_id"]]
    rows.sort(
        key=lambda row: (row["club_abbreviation"] or "", -(row["minutes_played"] or 0), row["player_id"])
    )
    return Result(rows, max_age)


def fetch_player_match_log(
    player_id: str, *, season: int | None = None, competition: str | None = None
) -> Result:
    """One player's per-match lines, newest first, optionally narrowed."""
    comp = competition_id(competition) if competition is not None else None
    items, max_age = _paged(f"statistics/players/{player_id}/matches", "match_log")
    rows: list[dict[str, Any]] = []
    for match in records(items):
        if match.get("competition_id") == TEST_COMPETITION or mapping(match).get("scope", "match") != "match":
            continue
        if comp is not None and match.get("competition_id") != comp:
            continue
        if season is not None and to_int(match.get("season")) != season:
            continue
        item = mapping(match.get("player_statistics"))
        rows.append(
            {
                "match_id": to_str(match.get("match_id")),
                "planned_kickoff": to_timestamp(match.get("planned_kick_off")),
                "competition_id": to_str(match.get("competition_id")),
                "competition_name": to_str(match.get("competition")),
                "season": to_int(match.get("season")),
                "match_title": to_str(match.get("game_title")),
                "result": to_str(match.get("result")),
                "club_id": to_str(item.get("team_id")),
                "club_abbreviation": to_str(item.get("team_three_letter_code")),
                "player_id": to_str(item.get("player_id")) or player_id,
                "player_name": _player_name(item),
                **_player_stats(item),
            }
        )
    rows = [row for row in rows if row["match_id"]]
    rows.sort(
        key=lambda row: row["planned_kickoff"] or datetime.min.replace(tzinfo=UTC),
        reverse=True,
    )
    return Result(rows, max_age)
