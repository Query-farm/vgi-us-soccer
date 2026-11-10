"""VGI table functions for the ``nwsl`` schema (NWSL Sports Data Platform)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, ClassVar

import pyarrow as pa
from vgi.arguments import Arg
from vgi.metadata import FunctionExample
from vgi.table_function import TableFunctionGenerator, bind_fixed_schema, init_single_worker

from vgi_us_soccer import nwsl
from vgi_us_soccer.base import Scan, tags

PROVIDER = "nwsl"

_SEASON = Arg(
    "season",
    default=None,
    arrow_type=pa.int32(),
    ge=2013,
    le=2100,
    doc="Season year. NULL selects the season that most recently started.",
)
_COMPETITION = Arg(
    "competition",
    default=nwsl.DEFAULT_COMPETITION,
    arrow_type=pa.string(),
    doc="Competition name from the competitions table (for example NWSL Challenge Cup) or its opaque id.",
)


@dataclass(kw_only=True)
class CompetitionArgs:
    """Arguments naming one competition."""

    competition: Annotated[str, _COMPETITION]


@dataclass(kw_only=True)
class SeasonArgs:
    """Arguments naming one competition season."""

    season: Annotated[int | None, _SEASON]
    competition: Annotated[str, _COMPETITION]


@dataclass(kw_only=True)
class StandingsArgs:
    """Arguments accepted by ``standings``."""

    season: Annotated[int | None, _SEASON]
    competition: Annotated[str, _COMPETITION]
    split: Annotated[
        str,
        Arg(
            "split",
            default="overall",
            arrow_type=pa.string(),
            choices=tuple(nwsl.STANDINGS_SPLITS),
            doc="overall for the league table, home or away for venue tables.",
        ),
    ]


@dataclass(kw_only=True)
class MatchArgs:
    """Arguments naming one match."""

    match_id: Annotated[
        str,
        Arg(
            0,
            arrow_type=pa.string(),
            pattern=r"^nwsl::Football_Match::[0-9a-f]{32}$",
            doc="Opaque NWSL match id from matches(), for example nwsl::Football_Match::834675f3....",
        ),
    ]


@dataclass(kw_only=True)
class RosterArgs:
    """Arguments accepted by ``roster``."""

    team: Annotated[
        str,
        Arg(
            0, arrow_type=pa.string(), doc="Team acronym (GFC), short name, official name, or opaque team id."
        ),
    ]
    season: Annotated[int | None, _SEASON]


def _meta_class(
    *,
    name: str,
    description: str,
    category: str,
    title: str,
    llm: str,
    schema: pa.Schema,
    examples: list[tuple[str, str]],
) -> type:
    """Build the nested ``Meta`` class VGI reads discovery metadata from."""
    return type(
        "Meta",
        (),
        {
            "__doc__": "Function discovery metadata.",
            "name": name,
            "description": description,
            "categories": ["soccer", "nwsl", category],
            "projection_pushdown": True,
            "tags": tags(
                provider=PROVIDER, category=category, title=title, llm=llm, schema=schema, examples=examples
            ),
            "examples": [FunctionExample(sql=sql, description=text) for text, sql in examples],
        },
    )


@init_single_worker
@bind_fixed_schema
class CompetitionsFunction(Scan, TableFunctionGenerator[None]):
    """Competitions on the NWSL platform."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = nwsl.COMPETITIONS_SCHEMA
    ESTIMATE, MAX = 20, 100
    Meta = _meta_class(
        name="all_competitions",
        description="Competitions on the NWSL Sports Data Platform (scan behind the competitions table)",
        category="reference",
        title="NWSL Competitions",
        llm=(
            "Competitions the NWSL platform publishes: the NWSL regular season, Challenge Cup, Summer Cup, "
            "and international tournaments involving NWSL players. Names feed the competition argument."
        ),
        schema=nwsl.COMPETITIONS_SCHEMA,
        examples=[
            (
                "Every competition name.",
                "SELECT competition_name FROM us_soccer.nwsl.all_competitions() ORDER BY 1",
            )
        ],
    )

    @classmethod
    def fetch(cls, args: None) -> nwsl.Result:
        """Fetch the competition list."""
        return nwsl.fetch_competitions()


@init_single_worker
@bind_fixed_schema
class SeasonsFunction(Scan, TableFunctionGenerator[CompetitionArgs]):
    """Seasons for one competition."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = nwsl.SEASONS_SCHEMA
    ESTIMATE, MAX = 15, 64
    Meta = _meta_class(
        name="seasons",
        description="Seasons for an NWSL platform competition, newest first",
        category="reference",
        title="NWSL Seasons",
        llm="Season years, opaque season ids, and start and end dates for one competition.",
        schema=nwsl.SEASONS_SCHEMA,
        examples=[
            (
                "NWSL regular seasons with their date ranges.",
                "SELECT season, start_date, end_date FROM us_soccer.nwsl.seasons() ORDER BY season",
            )
        ],
    )

    @classmethod
    def fetch(cls, args: CompetitionArgs) -> nwsl.Result:
        """Fetch seasons for the competition."""
        return nwsl.fetch_seasons(args.competition)


@init_single_worker
@bind_fixed_schema
class StandingsFunction(Scan, TableFunctionGenerator[StandingsArgs]):
    """League table for one season."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = nwsl.STANDINGS_SCHEMA
    ESTIMATE, MAX = 16, 64
    Meta = _meta_class(
        name="standings",
        description="NWSL league table by season with overall, home, and away splits",
        category="standings",
        title="NWSL Standings",
        llm=(
            "One row per team: position, games played, wins, draws, losses, goals for and against, goal "
            "difference, points, recent form letters, and the qualification zone label."
        ),
        schema=nwsl.STANDINGS_SCHEMA,
        examples=[
            (
                "The final 2025 NWSL table.",
                "SELECT position, team_name, points, goal_difference "
                "FROM us_soccer.nwsl.standings(season := 2025) ORDER BY position",
            )
        ],
    )

    @classmethod
    def fetch(cls, args: StandingsArgs) -> nwsl.Result:
        """Fetch the league table."""
        return nwsl.fetch_standings(args.season, args.split, args.competition)


@init_single_worker
@bind_fixed_schema
class CurrentStandingsFunction(Scan, TableFunctionGenerator[None]):
    """Current NWSL table backing ``current_standings``."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = nwsl.STANDINGS_SCHEMA
    ESTIMATE, MAX = 16, 64
    Meta = _meta_class(
        name="all_current_standings",
        description="Current NWSL league table (scan behind current_standings)",
        category="standings",
        title="Current NWSL Standings Scan",
        llm="The scan behind nwsl.current_standings. Prefer the table; use standings() for other seasons.",
        schema=nwsl.STANDINGS_SCHEMA,
        examples=[
            (
                "Read the current table directly from its backing scan.",
                "SELECT position, team_name, points FROM us_soccer.nwsl.all_current_standings() ORDER BY 1",
            )
        ],
    )

    @classmethod
    def fetch(cls, args: None) -> nwsl.Result:
        """Fetch the current table."""
        return nwsl.fetch_standings(None, "overall")


@init_single_worker
@bind_fixed_schema
class TeamsFunction(Scan, TableFunctionGenerator[SeasonArgs]):
    """Teams in one season."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = nwsl.TEAMS_SCHEMA
    ESTIMATE, MAX = 16, 64
    Meta = _meta_class(
        name="teams",
        description="Teams entered in an NWSL season",
        category="team-stats",
        title="NWSL Teams",
        llm="Team ids, official and short names, and acronyms for one season; acronyms feed roster().",
        schema=nwsl.TEAMS_SCHEMA,
        examples=[
            (
                "Teams in the 2026 NWSL season.",
                "SELECT team_abbreviation, team_name FROM us_soccer.nwsl.teams(season := 2026) ORDER BY 2",
            )
        ],
    )

    @classmethod
    def fetch(cls, args: SeasonArgs) -> nwsl.Result:
        """Fetch the teams."""
        return nwsl.fetch_teams(args.season, args.competition)


@init_single_worker
@bind_fixed_schema
class TeamStatsFunction(Scan, TableFunctionGenerator[SeasonArgs]):
    """Season statistics per team."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = nwsl.TEAM_STATS_SCHEMA
    ESTIMATE, MAX = 16, 64
    Meta = _meta_class(
        name="team_stats",
        description="Season team statistics for the NWSL",
        category="team-stats",
        title="NWSL Team Statistics",
        llm=(
            "Opta-derived season team statistics: record, goals, shots, possession, passing accuracy, "
            "PPDA pressing intensity, defensive actions, clean sheets, and discipline."
        ),
        schema=nwsl.TEAM_STATS_SCHEMA,
        examples=[
            (
                "2025 NWSL teams by possession.",
                "SELECT team_name, possession_pct, pass_accuracy_pct, goals "
                "FROM us_soccer.nwsl.team_stats(season := 2025) ORDER BY possession_pct DESC",
            )
        ],
    )

    @classmethod
    def fetch(cls, args: SeasonArgs) -> nwsl.Result:
        """Fetch team statistics."""
        return nwsl.fetch_team_stats(args.season, args.competition)


_PLAYER_LLM = (
    "Opta-derived season statistics, one row per player: appearances, starts, minutes, goals, assists, xG "
    "(2026 onward; NULL earlier), "
    "shots, key passes, big chances created, passing, defensive actions, discipline, penalties, and "
    "goalkeeper saves and clean sheets. goals_conceded is the team's tally while the player was on the pitch."
)


@init_single_worker
@bind_fixed_schema
class PlayerStatsFunction(Scan, TableFunctionGenerator[SeasonArgs]):
    """Season statistics per player."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = nwsl.PLAYER_STATS_SCHEMA
    ESTIMATE, MAX = 480, 2_000
    Meta = _meta_class(
        name="player_stats",
        description="Season player statistics for the NWSL",
        category="player-stats",
        title="NWSL Player Statistics",
        llm=_PLAYER_LLM,
        schema=nwsl.PLAYER_STATS_SCHEMA,
        examples=[
            (
                "2025 NWSL Golden Boot race.",
                "SELECT player_name, team_abbreviation, goals, assists, shots "
                "FROM us_soccer.nwsl.player_stats(season := 2025) ORDER BY goals DESC LIMIT 10",
            )
        ],
    )

    @classmethod
    def fetch(cls, args: SeasonArgs) -> nwsl.Result:
        """Fetch player statistics."""
        return nwsl.fetch_player_stats(args.season, args.competition)


@init_single_worker
@bind_fixed_schema
class CurrentPlayerStatsFunction(Scan, TableFunctionGenerator[None]):
    """Current NWSL player statistics backing ``current_player_stats``."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = nwsl.PLAYER_STATS_SCHEMA
    ESTIMATE, MAX = 480, 1_000
    Meta = _meta_class(
        name="all_current_player_stats",
        description="Current NWSL player statistics (scan behind current_player_stats)",
        category="player-stats",
        title="Current NWSL Player Statistics Scan",
        llm="The scan behind nwsl.current_player_stats. Prefer the table; use player_stats() otherwise.",
        schema=nwsl.PLAYER_STATS_SCHEMA,
        examples=[
            (
                "Read current player statistics directly from the backing scan.",
                "SELECT player_name, goals FROM us_soccer.nwsl.all_current_player_stats() "
                "ORDER BY goals DESC LIMIT 5",
            )
        ],
    )

    @classmethod
    def fetch(cls, args: None) -> nwsl.Result:
        """Fetch current player statistics."""
        return nwsl.fetch_player_stats(None)


@init_single_worker
@bind_fixed_schema
class MatchesFunction(Scan, TableFunctionGenerator[SeasonArgs]):
    """Fixtures and results for one season."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = nwsl.MATCHES_SCHEMA
    ESTIMATE, MAX = 250, 1_000
    Meta = _meta_class(
        name="matches",
        description="NWSL fixtures and results for a season",
        category="schedule",
        title="NWSL Schedule and Scores",
        llm=(
            "Every match in a season, regular season and playoffs, with kickoff time, status, matchday, "
            "teams, score, shoot-out score, winner, and stadium. Scores are NULL before kickoff."
        ),
        schema=nwsl.MATCHES_SCHEMA,
        examples=[
            (
                "Gotham FC's 2025 results.",
                "SELECT match_time, home_team_abbreviation, home_score, away_score, away_team_abbreviation "
                "FROM us_soccer.nwsl.matches(season := 2025) "
                "WHERE 'GFC' IN (home_team_abbreviation, away_team_abbreviation) ORDER BY match_time",
            )
        ],
    )

    @classmethod
    def fetch(cls, args: SeasonArgs) -> nwsl.Result:
        """Fetch the season's matches."""
        return nwsl.fetch_matches(args.season, args.competition)


@init_single_worker
@bind_fixed_schema
class CurrentMatchesFunction(Scan, TableFunctionGenerator[None]):
    """Current-season matches backing ``current_matches``."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = nwsl.MATCHES_SCHEMA
    ESTIMATE, MAX = 250, 1_000
    Meta = _meta_class(
        name="all_current_matches",
        description="Current NWSL season fixtures and results (scan behind current_matches)",
        category="schedule",
        title="Current NWSL Matches Scan",
        llm="The scan behind nwsl.current_matches. Prefer the table; use matches() for other seasons.",
        schema=nwsl.MATCHES_SCHEMA,
        examples=[
            (
                "Upcoming matches this season.",
                "SELECT match_time, home_team_name, away_team_name FROM us_soccer.nwsl.all_current_matches() "
                "WHERE status = 'UPCOMING' ORDER BY match_time",
            )
        ],
    )

    @classmethod
    def fetch(cls, args: None) -> nwsl.Result:
        """Fetch the current season's matches."""
        return nwsl.fetch_matches(None)


@init_single_worker
@bind_fixed_schema
class MatchEventsFunction(Scan, TableFunctionGenerator[MatchArgs]):
    """Event feed for one match."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = nwsl.EVENTS_SCHEMA
    ESTIMATE, MAX = 80, 500
    Meta = _meta_class(
        name="match_events",
        description="Event feed for one NWSL match: goals, shots, cards, substitutions, fouls",
        category="match-detail",
        title="NWSL Match Events",
        llm=(
            "The full event feed for a match id, oldest first, with minute, team, primary player, running "
            "score, and shot outcome. Filter event_type = 'goal' for goals."
        ),
        schema=nwsl.EVENTS_SCHEMA,
        examples=[
            (
                "Goals and shots in the 2026 season opener.",
                "SELECT minute, team_abbreviation, player_name, event_type, description "
                "FROM us_soccer.nwsl.match_events('nwsl::Football_Match::834675f37cea4328bece6743d94c7d2d') "
                "WHERE event_type IN ('goal', 'attempt-saved', 'attempt-missed') ORDER BY event_time",
            )
        ],
    )

    @classmethod
    def fetch(cls, args: MatchArgs) -> nwsl.Result:
        """Fetch the event feed."""
        return nwsl.fetch_match_events(args.match_id)


@init_single_worker
@bind_fixed_schema
class RosterFunction(Scan, TableFunctionGenerator[RosterArgs]):
    """Roster for one team and season."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = nwsl.ROSTER_SCHEMA
    ESTIMATE, MAX = 30, 80
    Meta = _meta_class(
        name="roster",
        description="NWSL team roster for a season",
        category="team-stats",
        title="NWSL Team Roster",
        llm="Players on one team's roster with shirt number, position, nationality, birth date, and size.",
        schema=nwsl.ROSTER_SCHEMA,
        examples=[
            (
                "Gotham FC's 2026 roster.",
                "SELECT shirt_number, player_name, position_name, nationality "
                "FROM us_soccer.nwsl.roster('GFC', season := 2026) ORDER BY shirt_number",
            )
        ],
    )

    @classmethod
    def fetch(cls, args: RosterArgs) -> nwsl.Result:
        """Fetch the roster."""
        return nwsl.fetch_roster(args.team, args.season)


NWSL_FUNCTIONS = [
    CompetitionsFunction,
    SeasonsFunction,
    StandingsFunction,
    CurrentStandingsFunction,
    TeamsFunction,
    TeamStatsFunction,
    PlayerStatsFunction,
    CurrentPlayerStatsFunction,
    MatchesFunction,
    CurrentMatchesFunction,
    MatchEventsFunction,
    RosterFunction,
]
