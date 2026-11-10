"""NWSL Sports Data Platform (api-sdp.nwslsoccer.com): endpoints, schemas, and flattening.

Identifiers on this platform are opaque strings such as
``nwsl::Football_Season::<hex>``. They are always discovered from the
competitions and seasons endpoints and never hard-coded; SQL callers pass
ordinary season years.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pyarrow as pa

from vgi_us_soccer import api
from vgi_us_soccer.meta import (
    TIMESTAMP,
    field,
    join_name,
    mapping,
    records,
    to_date,
    to_float,
    to_int,
    to_str,
    to_timestamp,
)

LOCALE = {"locale": "en-US"}
REFERENCE_TTL = 3_600.0
PAGE_SIZE = 500
MAX_PAGES = 20
DEFAULT_COMPETITION = "NWSL"
STANDINGS_SPLITS = {"overall": "table", "home": "home", "away": "away"}


@dataclass(frozen=True, slots=True)
class Result:
    """Flattened rows plus the freshness the connector may advertise."""

    rows: list[dict[str, Any]]
    max_age: int | None = None


# ---------------------------------------------------------------- schemas

_SEASON_COLUMNS = [
    field("season", pa.int32(), "Season year."),
    field("season_id", pa.string(), "Opaque NWSL platform season identifier."),
]

_TEAM_COLUMNS = [
    field("team_id", pa.string(), "Opaque NWSL platform team identifier.", nullable=False),
    field("team_name", pa.string(), "Official team name."),
    field("team_short_name", pa.string(), "Short team name."),
    field("team_abbreviation", pa.string(), "Team acronym, for example GFC."),
]

COMPETITIONS_SCHEMA = pa.schema(
    [
        field("competition_id", pa.string(), "Opaque NWSL platform competition identifier.", nullable=False),
        field("competition_name", pa.string(), "Competition name, for example NWSL or NWSL Challenge Cup."),
        field("official_name", pa.string(), "Official competition name."),
        field("opta_id", pa.string(), "Opta provider identifier."),
    ]
)

SEASONS_SCHEMA = pa.schema(
    [
        field("competition_id", pa.string(), "Opaque NWSL platform competition identifier."),
        field("competition_name", pa.string(), "Competition name."),
        field("season", pa.int32(), "Season year."),
        field("season_id", pa.string(), "Opaque NWSL platform season identifier.", nullable=False),
        field("start_date", pa.date32(), "First scheduled day of the season (UTC)."),
        field("end_date", pa.date32(), "Last scheduled day of the season (UTC)."),
    ]
)

STANDINGS_SCHEMA = pa.schema(
    [
        *_SEASON_COLUMNS,
        field("standings_split", pa.string(), "Requested table: overall, home, or away."),
        field("position", pa.int32(), "Table position."),
        *_TEAM_COLUMNS,
        field("games_played", pa.int32(), "Matches played."),
        field("wins", pa.int32(), "Wins."),
        field("draws", pa.int32(), "Draws."),
        field("losses", pa.int32(), "Losses."),
        field("goals_for", pa.int32(), "Goals scored."),
        field("goals_against", pa.int32(), "Goals conceded."),
        field("goal_difference", pa.int32(), "Goals scored minus goals conceded."),
        field("points", pa.int32(), "League points."),
        field("form", pa.string(), "Recent results, oldest to newest, as W/D/L letters."),
        field("movement", pa.string(), "Recent movement in the table: up, down, or stable."),
        field("qualification", pa.string(), "Qualification zone label, for example Final Series."),
    ]
)

TEAMS_SCHEMA = pa.schema(
    [
        *_SEASON_COLUMNS,
        *_TEAM_COLUMNS,
        field("country_code", pa.string(), "Country code."),
        field("opta_id", pa.string(), "Opta provider identifier."),
    ]
)

# (column, upstream statsId, Arrow type, comment)
_PLAYER_STATS: tuple[tuple[str, str, pa.DataType, str], ...] = (
    ("games_played", "games-played", pa.int32(), "Appearances."),
    ("starts", "Starts", pa.int32(), "Starts."),
    ("minutes_played", "minutes-played", pa.int32(), "Minutes played."),
    ("goals", "goals", pa.int32(), "Goals scored."),
    ("assists", "assists", pa.int32(), "Assists."),
    ("goal_involvements", "goal-involvements", pa.int32(), "Goals plus assists."),
    ("xg", "Xg", pa.float64(), "Opta expected goals; NULL before 2026."),
    ("shots", "total-scoring-attempts", pa.int32(), "Shots attempted."),
    ("shots_on_target", "on-target-scoring-attempts", pa.int32(), "Shots on target."),
    ("key_passes", "total-attacking-assist", pa.int32(), "Passes leading to a shot."),
    ("big_chances_created", "Total Big Chances Created", pa.int32(), "Big chances created."),
    ("passes", "Total Passes", pa.int32(), "Passes attempted."),
    ("pass_accuracy_pct", "accurate-pass-percentage", pa.float64(), "Accurate passes, in percent."),
    ("tackles_won", "Tackles Won", pa.int32(), "Tackles won."),
    ("interceptions", "Interceptions", pa.int32(), "Interceptions."),
    ("recoveries", "Recoveries", pa.int32(), "Ball recoveries."),
    ("fouls_committed", "fouls-committed", pa.int32(), "Fouls committed."),
    ("fouls_suffered", "fouls-suffered", pa.int32(), "Fouls suffered."),
    ("offsides", "total-offside", pa.int32(), "Times caught offside."),
    ("yellow_cards", "yellow-cards", pa.int32(), "Yellow cards."),
    ("red_cards", "red-cards", pa.int32(), "Red cards."),
    ("penalties_attempted", "penalty-attempts", pa.int32(), "Penalties taken."),
    ("penalties_scored", "penalties-successful", pa.int32(), "Penalties scored."),
    ("saves", "Saves Made", pa.int32(), "Saves; goalkeepers only."),
    ("clean_sheets", "Clean Sheets", pa.int32(), "Clean sheets while on the pitch."),
    (
        "goals_conceded",
        "goals-conceded",
        pa.int32(),
        "Team goals conceded while the player was on the pitch.",
    ),
)

PLAYER_STATS_SCHEMA = pa.schema(
    [
        *_SEASON_COLUMNS,
        field("player_id", pa.string(), "Opaque NWSL platform player identifier.", nullable=False),
        field("player_name", pa.string(), "Player full name."),
        field("short_name", pa.string(), "Player short display name."),
        field("position_name", pa.string(), "Goalkeeper, Defender, Midfielder, or Forward."),
        field("shirt_number", pa.int32(), "Shirt number."),
        field("nationality", pa.string(), "Nationality."),
        *_TEAM_COLUMNS,
        *(field(name, kind, comment) for name, _, kind, comment in _PLAYER_STATS),
    ]
)

_TEAM_STATS: tuple[tuple[str, str, pa.DataType, str], ...] = (
    ("games_played", "games-played", pa.int32(), "Matches played."),
    ("points", "total-points", pa.int32(), "League points."),
    ("wins", "total-wins", pa.int32(), "Wins."),
    ("draws", "total-draws", pa.int32(), "Draws."),
    ("losses", "total-losses", pa.int32(), "Losses."),
    ("goals", "goals", pa.int32(), "Goals scored."),
    ("goals_against", "goals-against", pa.int32(), "Goals conceded."),
    ("home_goals", "Home Goals", pa.int32(), "Goals scored at home."),
    ("away_goals", "Away Goals", pa.int32(), "Goals scored away."),
    ("shots", "Total Shots", pa.int32(), "Shots attempted."),
    ("shots_on_target", "Shots On Target ( inc goals )", pa.int32(), "Shots on target, including goals."),
    ("shots_conceded", "Total Shots Conceded", pa.int32(), "Opponent shots."),
    ("possession_pct", "Possession Percentage", pa.float64(), "Average possession, in percent."),
    ("pass_accuracy_pct", "Passing Accuracy", pa.float64(), "Accurate passes, in percent."),
    ("passes", "Total Passes", pa.int32(), "Passes attempted."),
    ("ppda", "PPDA", pa.float64(), "Opponent passes allowed per defensive action; lower is more pressing."),
    ("tackles_won", "Tackles Won", pa.int32(), "Tackles won."),
    ("interceptions", "Interceptions", pa.int32(), "Interceptions."),
    ("recoveries", "Recoveries", pa.int32(), "Ball recoveries."),
    ("clearances", "Total Clearances", pa.int32(), "Clearances."),
    ("clean_sheets", "Clean Sheets", pa.int32(), "Matches without conceding."),
    ("corners", "corners", pa.int32(), "Corners won."),
    ("fouls_committed", "fouls-committed", pa.int32(), "Fouls committed."),
    ("yellow_cards", "yellow-cards", pa.int32(), "Yellow cards."),
    ("red_cards", "red-cards", pa.int32(), "Red cards."),
)

TEAM_STATS_SCHEMA = pa.schema(
    [
        *_SEASON_COLUMNS,
        *_TEAM_COLUMNS,
        *(field(name, kind, comment) for name, _, kind, comment in _TEAM_STATS),
    ]
)

MATCHES_SCHEMA = pa.schema(
    [
        *_SEASON_COLUMNS,
        field("match_id", pa.string(), "Opaque NWSL platform match identifier.", nullable=False),
        field("match_time", TIMESTAMP, "Kickoff time (UTC)."),
        field("status", pa.string(), "FINISHED, UPCOMING, LIVE, or another platform status."),
        field("phase", pa.string(), "Match phase, for example FULL_TIME."),
        field("matchday", pa.string(), "Matchday or round label."),
        field("home_team_id", pa.string(), "Home team identifier."),
        field("home_team_name", pa.string(), "Home team name."),
        field("home_team_abbreviation", pa.string(), "Home team acronym."),
        field("away_team_id", pa.string(), "Away team identifier."),
        field("away_team_name", pa.string(), "Away team name."),
        field("away_team_abbreviation", pa.string(), "Away team acronym."),
        field("home_score", pa.int32(), "Home goals; NULL before kickoff."),
        field("away_score", pa.int32(), "Away goals; NULL before kickoff."),
        field("home_penalty_score", pa.int32(), "Home shoot-out goals when decided on penalties."),
        field("away_penalty_score", pa.int32(), "Away shoot-out goals when decided on penalties."),
        field("winner_team_id", pa.string(), "Winning team identifier; NULL for a draw or unplayed match."),
        field("win_reason", pa.string(), "How the match was decided, for example RegularTime."),
        field("stadium_name", pa.string(), "Stadium name."),
        field("city", pa.string(), "Stadium city."),
    ]
)

EVENTS_SCHEMA = pa.schema(
    [
        field("match_id", pa.string(), "Opaque NWSL platform match identifier.", nullable=False),
        field("event_id", pa.string(), "Event identifier, unique within the match.", nullable=False),
        field(
            "event_type", pa.string(), "Event type, for example goal, attempt-saved, substitution, or foul."
        ),
        field("label", pa.string(), "Human-readable event label."),
        field("description", pa.string(), "Event description text."),
        field("event_time", TIMESTAMP, "Wall-clock event time."),
        field("phase", pa.string(), "Period of play, for example FirstHalf."),
        field("minute", pa.int32(), "Match minute."),
        field("added_time", pa.int32(), "Stoppage-time minute added to minute."),
        field("team_id", pa.string(), "Team the event belongs to."),
        field("team_abbreviation", pa.string(), "Team acronym."),
        field("player_id", pa.string(), "Primary player identifier."),
        field("player_name", pa.string(), "Primary player name."),
        field("home_score", pa.int32(), "Running home score at the time of the event."),
        field("away_score", pa.int32(), "Running away score at the time of the event."),
        field("shot_result", pa.string(), "Shot outcome for shot events."),
    ]
)

ROSTER_SCHEMA = pa.schema(
    [
        *_SEASON_COLUMNS,
        field("team_id", pa.string(), "Opaque NWSL platform team identifier."),
        field("team_name", pa.string(), "Team name."),
        field("player_id", pa.string(), "Opaque NWSL platform player identifier.", nullable=False),
        field("player_name", pa.string(), "Player full name."),
        field("shirt_number", pa.int32(), "Shirt number."),
        field("position_name", pa.string(), "Goalkeeper, Defender, Midfielder, or Forward."),
        field("nationality", pa.string(), "Nationality."),
        field("date_of_birth", pa.date32(), "Date of birth."),
        field("height_cm", pa.int32(), "Height, in centimeters."),
        field("weight_kg", pa.int32(), "Weight, in kilograms."),
        field("status", pa.string(), "Roster status, for example Active."),
    ]
)


# ---------------------------------------------------------------- fetch helpers


def _get(path: str, params: Mapping[str, str | int] | None = None, **kwargs: Any) -> api.JsonResponse:
    return api.get_json(api.NWSL, path, {**LOCALE, **(params or {})}, **kwargs)


def fetch_competitions() -> Result:
    """Competitions on the platform, including internationals NWSL players appear in."""
    payload = mapping(_get("competitions", ttl=REFERENCE_TTL).payload)
    rows = [
        {
            "competition_id": to_str(item.get("competitionId")),
            "competition_name": to_str(item.get("name")),
            "official_name": to_str(item.get("officialName")),
            "opta_id": to_str(item.get("providerId")),
        }
        for item in records(payload.get("competitions"))
    ]
    return Result(
        sorted((row for row in rows if row["competition_id"]), key=lambda row: row["competition_name"] or "")
    )


def resolve_competition(competition: str | None) -> tuple[str, str]:
    """Return ``(competition_id, name)`` for a competition name or opaque id."""
    wanted = (competition or DEFAULT_COMPETITION).strip()
    for row in fetch_competitions().rows:
        if wanted == row["competition_id"] or wanted.lower() == (row["competition_name"] or "").lower():
            return row["competition_id"], row["competition_name"] or wanted
    raise ValueError(
        f"unknown NWSL platform competition {wanted!r}; list them with SELECT * FROM nwsl.competitions"
    )


def fetch_seasons(competition: str | None = None) -> Result:
    """Seasons for one competition, newest first."""
    comp_id, comp_name = resolve_competition(competition)
    payload = mapping(_get(f"competitions/{comp_id}/seasons", ttl=REFERENCE_TTL).payload)
    rows = [
        {
            "competition_id": comp_id,
            "competition_name": comp_name,
            "season": to_int(item.get("seasonName")),
            "season_id": to_str(item.get("seasonId")),
            "start_date": to_date(item.get("startDateUtc")),
            "end_date": to_date(item.get("endDateUtc")),
        }
        for item in records(payload.get("seasons"))
    ]
    rows = [row for row in rows if row["season_id"]]
    return Result(sorted(rows, key=lambda row: -(row["season"] or 0)))


def resolve_season(
    season: int | None, competition: str | None = None, *, now: datetime | None = None
) -> tuple[int | None, str]:
    """Map a season year (NULL for the current season) to its opaque id."""
    seasons = fetch_seasons(competition).rows
    if not seasons:
        raise ValueError("the NWSL platform lists no seasons for this competition")
    if season is None:
        today = (now or datetime.now(UTC)).date()
        started = [row for row in seasons if row["start_date"] is not None and row["start_date"] <= today]
        chosen = max(started or seasons, key=lambda row: (row["start_date"] or today, row["season"] or 0))
    else:
        chosen = next((row for row in seasons if row["season"] == season), None)
        if chosen is None:
            available = ", ".join(str(row["season"]) for row in seasons)
            raise ValueError(f"no NWSL season {season}; available seasons: {available}")
    return chosen["season"], chosen["season_id"]


def _team(item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "team_id": to_str(item.get("teamId")),
        "team_name": to_str(item.get("officialName") or item.get("mediaName")),
        "team_short_name": to_str(item.get("shortName") or item.get("mediaShortName")),
        "team_abbreviation": to_str(item.get("acronymName")),
    }


def _stat_map(item: Mapping[str, Any]) -> dict[str, Any]:
    return {str(stat.get("statsId")): stat.get("statsValue") for stat in records(item.get("stats"))}


def fetch_standings(
    season: int | None = None, split: str = "overall", competition: str | None = None
) -> Result:
    """League table for a season: overall, home, or away."""
    if split not in STANDINGS_SPLITS:
        raise ValueError(f"split must be one of {sorted(STANDINGS_SPLITS)}")
    year, season_id = resolve_season(season, competition)
    response = _get(f"seasons/{season_id}/standings/overall", not_found_ok=True)
    rows: list[dict[str, Any]] = []
    for table in records(mapping(response.payload).get("standings")):
        if table.get("type") != STANDINGS_SPLITS[split]:
            continue
        for team in records(table.get("teams")):
            stats = _stat_map(team)
            form = stats.get("form")
            letters = "".join(
                str(mapping(result).get("formType") or "")
                for result in (form if isinstance(form, list) else [])
            )
            rows.append(
                {
                    "season": year,
                    "season_id": season_id,
                    "standings_split": split,
                    "position": to_int(stats.get("rank")),
                    **_team(team),
                    "games_played": to_int(stats.get("matches-played")),
                    "wins": to_int(stats.get("win")),
                    "draws": to_int(stats.get("draw")),
                    "losses": to_int(stats.get("lose")),
                    "goals_for": to_int(stats.get("goals-for")),
                    "goals_against": to_int(stats.get("goals-against")),
                    "goal_difference": to_int(stats.get("goal-difference")),
                    "points": to_int(stats.get("points")),
                    "form": letters or None,
                    "movement": to_str(stats.get("movement")),
                    "qualification": to_str(mapping(team.get("qualification")).get("qualificationLabel")),
                }
            )
    rows = [row for row in rows if row["team_id"]]
    rows.sort(key=lambda row: row["position"] or 99)
    return Result(rows, response.max_age)


def fetch_teams(season: int | None = None, competition: str | None = None) -> Result:
    """Teams entered in a season."""
    year, season_id = resolve_season(season, competition)
    response = _get(f"seasons/{season_id}/teams", ttl=REFERENCE_TTL, not_found_ok=True)
    rows = [
        {
            "season": year,
            "season_id": season_id,
            **_team(item),
            "country_code": to_str(item.get("countryCode")),
            "opta_id": to_str(item.get("providerId")),
        }
        for item in records(mapping(response.payload).get("teams"))
    ]
    rows = [row for row in rows if row["team_id"]]
    return Result(sorted(rows, key=lambda row: row["team_name"] or ""), response.max_age)


def resolve_team(team: str, season: int | None) -> tuple[int | None, str, dict[str, Any]]:
    """Accept a team id, acronym, short name, or official name for one season."""
    wanted = team.strip().lower()
    result = fetch_teams(season)
    for row in result.rows:
        candidates = {
            (row["team_id"] or "").lower(),
            (row["team_abbreviation"] or "").lower(),
            (row["team_short_name"] or "").lower(),
            (row["team_name"] or "").lower(),
        }
        if wanted in candidates:
            return row["season"], row["season_id"], row
    names = ", ".join(sorted(row["team_abbreviation"] or "" for row in result.rows))
    raise ValueError(f"unknown NWSL team {team!r}; known acronyms: {names}")


def _paged(path: str, key: str, params: Mapping[str, str | int]) -> tuple[list[Any], int | None]:
    items: list[Any] = []
    responses: list[api.JsonResponse] = []
    for page in range(1, MAX_PAGES + 1):
        response = _get(path, {**params, "page": page}, not_found_ok=True)
        if response.payload is None:
            return items, None
        payload = mapping(response.payload)
        responses.append(response)
        items.extend(records(payload.get(key)))
        pagination = mapping(payload.get("pagination"))
        total = to_int(pagination.get("totalPages")) or 1
        if pagination.get("isLastPage", True) or page >= total:
            return items, api.shortest_max_age(responses)
    raise RuntimeError(f"NWSL platform pagination for {path} exceeded {MAX_PAGES} pages")


def fetch_player_stats(season: int | None = None, competition: str | None = None) -> Result:
    """Season statistics for every player who appeared."""
    year, season_id = resolve_season(season, competition)
    items, max_age = _paged(
        f"seasons/{season_id}/stats/players",
        "players",
        {"category": "general", "orderBy": "goals", "direction": "desc", "pageNumElement": PAGE_SIZE},
    )
    rows: list[dict[str, Any]] = []
    for item in items:
        stats = _stat_map(item)
        row = {
            "season": year,
            "season_id": season_id,
            "player_id": to_str(item.get("playerId")),
            "player_name": join_name(item.get("mediaFirstName"), item.get("mediaLastName"))
            or to_str(item.get("shortName")),
            "short_name": to_str(item.get("shortName")),
            "position_name": to_str(item.get("roleLabel")),
            "shirt_number": to_int(item.get("bibNumber")),
            "nationality": to_str(item.get("nationality")),
            **_team(mapping(item.get("team"))),
        }
        for name, stat_id, kind, _ in _PLAYER_STATS:
            value = stats.get(stat_id)
            row[name] = to_float(value) if pa.types.is_floating(kind) else to_int(value)
        rows.append(row)
    rows = [row for row in rows if row["player_id"] and row["team_id"]]
    # Before 2026 the platform reports Xg as 0 for every player rather than omitting it;
    # a season with no non-zero value has no xG model, so report NULL instead of 0.0.
    if not any(row["xg"] for row in rows):
        for row in rows:
            row["xg"] = None
    return Result(rows, max_age)


def fetch_team_stats(season: int | None = None, competition: str | None = None) -> Result:
    """Season statistics for every team."""
    year, season_id = resolve_season(season, competition)
    items, max_age = _paged(f"seasons/{season_id}/stats/teams", "teams", {"category": "general"})
    rows: list[dict[str, Any]] = []
    for item in items:
        stats = _stat_map(item)
        row = {"season": year, "season_id": season_id, **_team(item)}
        for name, stat_id, kind, _ in _TEAM_STATS:
            value = stats.get(stat_id)
            row[name] = to_float(value) if pa.types.is_floating(kind) else to_int(value)
        rows.append(row)
    return Result([row for row in rows if row["team_id"]], max_age)


def fetch_matches(season: int | None = None, competition: str | None = None) -> Result:
    """Every match in a season with status, score, and venue."""
    year, season_id = resolve_season(season, competition)
    response = _get(f"seasons/{season_id}/matches", not_found_ok=True)
    rows: list[dict[str, Any]] = []
    for item in records(mapping(response.payload).get("matches")):
        status = to_str(item.get("status"))
        played = status not in (None, "UPCOMING", "POSTPONED", "CANCELLED")
        home = _team(mapping(item.get("home")))
        away = _team(mapping(item.get("away")))
        match_set = mapping(item.get("matchSet"))
        rows.append(
            {
                "season": year,
                "season_id": season_id,
                "match_id": to_str(item.get("matchId")),
                "match_time": to_timestamp(item.get("matchDateUtc")),
                "status": status,
                "phase": to_str(item.get("phase")),
                "matchday": to_str(match_set.get("name")) or to_str(item.get("roundName")),
                "home_team_id": home["team_id"],
                "home_team_name": home["team_name"],
                "home_team_abbreviation": home["team_abbreviation"],
                "away_team_id": away["team_id"],
                "away_team_name": away["team_name"],
                "away_team_abbreviation": away["team_abbreviation"],
                "home_score": to_int(item.get("providerHomeScore")) if played else None,
                "away_score": to_int(item.get("providerAwayScore")) if played else None,
                "home_penalty_score": to_int(item.get("providerPenaltyScoreHome")),
                "away_penalty_score": to_int(item.get("providerPenaltyScoreAway")),
                "winner_team_id": to_str(item.get("winTeamId")),
                "win_reason": to_str(item.get("winReason")) if played else None,
                "stadium_name": to_str(item.get("stadiumName")),
                "city": to_str(item.get("cityName")),
            }
        )
    rows = [row for row in rows if row["match_id"]]
    rows.sort(key=lambda row: (row["match_time"] or datetime.max.replace(tzinfo=UTC), row["match_id"]))
    return Result(rows, response.max_age)


def fetch_match_events(match_id: str, season: int | None = None) -> Result:
    """The full event feed for one match, oldest first."""
    _, season_id = resolve_season(season)
    items, max_age = _paged(f"seasons/{season_id}/matches/{match_id}/feed", "events", {})
    rows: list[dict[str, Any]] = []
    for item in items:
        side = mapping(item.get("home")) or mapping(item.get("away"))
        team = mapping(side.get("team"))
        player = mapping(side.get("player"))
        rows.append(
            {
                "match_id": match_id,
                "event_id": to_str(item.get("eventId")),
                "event_type": to_str(item.get("type")),
                "label": to_str(item.get("label")),
                "description": to_str(item.get("description")),
                "event_time": to_timestamp(item.get("timeStamp")),
                "phase": to_str(side.get("phase") or item.get("phase")),
                "minute": to_int(side.get("time")),
                "added_time": to_int(side.get("additionalTime")),
                "team_id": to_str(team.get("teamId")),
                "team_abbreviation": to_str(team.get("acronymName")),
                "player_id": to_str(player.get("playerId")),
                "player_name": join_name(player.get("mediaFirstName"), player.get("mediaLastName"))
                or to_str(player.get("shortName")),
                # providerHomeScore/providerAwayScore carry the final score on every event;
                # the *ScorePush fields carry the score as it stood when the event happened.
                "home_score": to_int(item.get("homeScorePush")),
                "away_score": to_int(item.get("awayScorePush")),
                "shot_result": to_str(item.get("shotResult")),
            }
        )
    rows = [row for row in rows if row["event_id"]]
    rows.sort(key=lambda row: (row["event_time"] or datetime.min.replace(tzinfo=UTC), row["event_id"]))
    return Result(rows, max_age)


def fetch_roster(team: str, season: int | None = None) -> Result:
    """One team's roster for a season."""
    year, season_id, team_row = resolve_team(team, season)
    response = _get(f"teams/{team_row['team_id']}/roster", {"seasonId": season_id}, not_found_ok=True)
    rows = [
        {
            "season": year,
            "season_id": season_id,
            "team_id": team_row["team_id"],
            "team_name": team_row["team_name"],
            "player_id": to_str(item.get("playerId")),
            "player_name": join_name(item.get("mediaFirstName"), item.get("mediaLastName"))
            or to_str(item.get("shortName")),
            "shirt_number": to_int(item.get("bibNumber")),
            "position_name": to_str(item.get("roleLabel")),
            "nationality": to_str(item.get("nationality")),
            "date_of_birth": to_date(item.get("dateOfBirth")),
            "height_cm": to_int(item.get("height")),
            "weight_kg": to_int(item.get("weight")),
            "status": to_str(item.get("playerStatus")),
        }
        for item in records(mapping(response.payload).get("players"))
    ]
    rows = [row for row in rows if row["player_id"]]
    rows.sort(
        key=lambda row: (row["shirt_number"] if row["shirt_number"] is not None else 999, row["player_id"])
    )
    return Result(rows, response.max_age)
