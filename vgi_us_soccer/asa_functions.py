"""VGI table functions for the ``asa`` schema (American Soccer Analysis, CC BY-SA 4.0)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, ClassVar

import pyarrow as pa
from vgi.arguments import Arg
from vgi.metadata import FunctionExample
from vgi.table_function import TableFunctionGenerator, bind_fixed_schema, init_single_worker

from vgi_us_soccer import asa
from vgi_us_soccer.base import Scan, tags

PROVIDER = "american-soccer-analysis"

_LEAGUE = Arg(
    "league",
    default="mls",
    arrow_type=pa.string(),
    choices=tuple(asa.LEAGUES),
    doc="ASA league code: mls, mlsnp (MLS NEXT Pro), nwsl, uslc, usl1, usls (USL Super League), or nasl.",
)
_SEASON = Arg(
    "season",
    default=None,
    arrow_type=pa.int32(),
    ge=asa.FIRST_SEASON,
    le=2100,
    doc="Season year (start year for usls 2024-25 style seasons). NULL selects the current year.",
)
_MINIMUM_MINUTES = Arg(
    "minimum_minutes",
    default=0,
    arrow_type=pa.int32(),
    ge=0,
    doc="Only return player-team lines with at least this many minutes.",
)
_STAGE = Arg(
    "stage",
    default="regular_season",
    arrow_type=pa.string(),
    choices=tuple(asa.STAGES),
    doc="regular_season (default), playoffs, or all games.",
)
_ATTRIBUTION = f" {asa.ATTRIBUTION}."


@dataclass(kw_only=True)
class LeagueArgs:
    """Arguments naming one ASA league."""

    league: Annotated[str, _LEAGUE]


@dataclass(kw_only=True)
class LeagueSeasonArgs:
    """Arguments naming one ASA league, season, and competition stage."""

    league: Annotated[str, _LEAGUE]
    season: Annotated[int | None, _SEASON]
    stage: Annotated[str, _STAGE]


@dataclass(kw_only=True)
class PlayerArgs:
    """Arguments for player-level ASA metrics."""

    league: Annotated[str, _LEAGUE]
    season: Annotated[int | None, _SEASON]
    minimum_minutes: Annotated[int, _MINIMUM_MINUTES]
    stage: Annotated[str, _STAGE]


@dataclass(kw_only=True)
class SalaryArgs:
    """Arguments for MLS salary releases."""

    season: Annotated[int | None, _SEASON]


# A composed example joining two of this schema's functions. It is defined once here and listed both on
# goals_added_players() and in the schema-level example list (see worker.py).
GPLUS_PER_SALARY_EXAMPLE = (
    "2025 MLS players with 1,500+ minutes ranked by goals added above average per US$1M of guaranteed "
    "compensation, joining goals_added_players to each player's latest salaries() release.",
    "WITH pay AS (SELECT player_id, team_id, guaranteed_compensation "
    "FROM us_soccer.asa.salaries(season := 2025) "
    "QUALIFY release_date = max(release_date) OVER (PARTITION BY player_id, team_id)) "
    "SELECT g.player_name, g.team_abbreviation, round(g.goals_added_above_avg, 2) AS gplus, "
    "p.guaranteed_compensation, "
    "round(g.goals_added_above_avg / (p.guaranteed_compensation / 1e6), 2) AS gplus_per_million "
    "FROM us_soccer.asa.goals_added_players(season := 2025, minimum_minutes := 1500) AS g "
    "JOIN pay AS p USING (player_id, team_id) "
    "ORDER BY gplus_per_million DESC LIMIT 10",
)


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
            "categories": ["soccer", "analytics", category],
            "projection_pushdown": True,
            "tags": {
                **tags(
                    provider=PROVIDER,
                    category=category,
                    title=title,
                    llm=llm + _ATTRIBUTION,
                    schema=schema,
                    examples=examples,
                ),
                "vgi.license": "CC-BY-SA-4.0",
                "vgi.copyright": asa.ATTRIBUTION,
            },
            "examples": [FunctionExample(sql=sql, description=text) for text, sql in examples],
        },
    )


@init_single_worker
@bind_fixed_schema
class TeamsFunction(Scan, TableFunctionGenerator[LeagueArgs]):
    """ASA's team directory."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = asa.TEAMS_SCHEMA
    ESTIMATE, MAX = 40, 200
    Meta = _meta_class(
        name="teams",
        description="American Soccer Analysis team directory for one league",
        category="reference",
        title="ASA Teams",
        llm="Every team ASA tracks for a league, with its opaque ASA team id, name, and abbreviation.",
        schema=asa.TEAMS_SCHEMA,
        examples=[
            (
                "USL Championship teams.",
                "SELECT team_abbreviation, team_name FROM us_soccer.asa.teams(league := 'uslc') ORDER BY 2",
            )
        ],
    )

    @classmethod
    def fetch(cls, args: LeagueArgs) -> asa.Result:
        """Fetch the team directory."""
        return asa.fetch_teams(args.league)


@init_single_worker
@bind_fixed_schema
class XgPlayersFunction(Scan, TableFunctionGenerator[PlayerArgs]):
    """Player xG and xA."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = asa.XG_PLAYERS_SCHEMA
    ESTIMATE, MAX = 600, 3_000
    Meta = _meta_class(
        name="xg_players",
        description="Player expected goals and expected assists from American Soccer Analysis",
        category="expected-goals",
        title="ASA Player xG",
        llm=(
            "One row per player and team: minutes, shots, goals, ASA xG and xA, goals minus xG, key passes, "
            "and expected points added. Use minimum_minutes to drop small samples."
        ),
        schema=asa.XG_PLAYERS_SCHEMA,
        examples=[
            (
                "2025 MLS players who most outperformed their xG.",
                "SELECT player_name, team_abbreviation, goals, round(xgoals, 1) AS xg, "
                "round(goals_minus_xgoals, 1) AS diff "
                "FROM us_soccer.asa.xg_players(season := 2025, minimum_minutes := 1500) "
                "ORDER BY goals_minus_xgoals DESC LIMIT 10",
            )
        ],
    )

    @classmethod
    def fetch(cls, args: PlayerArgs) -> asa.Result:
        """Fetch player xG."""
        return asa.fetch_xg_players(args.league, args.season, args.minimum_minutes, args.stage)


@init_single_worker
@bind_fixed_schema
class GoalsAddedFunction(Scan, TableFunctionGenerator[PlayerArgs]):
    """Player goals added (g+)."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = asa.GOALS_ADDED_SCHEMA
    ESTIMATE, MAX = 600, 3_000
    Meta = _meta_class(
        name="goals_added_players",
        description="Player goals added (g+) by action type from American Soccer Analysis",
        category="goals-added",
        title="ASA Player Goals Added",
        llm=(
            "ASA's goals added (g+) per player and team: total raw g+, total g+ above the positional "
            "average, and above-average g+ from dribbling, fouling, interrupting, passing, receiving, and "
            "shooting actions."
        ),
        schema=asa.GOALS_ADDED_SCHEMA,
        examples=[
            (
                "Top 2025 NWSL players by goals added above average.",
                "SELECT player_name, team_abbreviation, general_position, "
                "round(goals_added_above_avg, 2) AS gplus "
                "FROM us_soccer.asa.goals_added_players(league := 'nwsl', season := 2025, "
                "minimum_minutes := 1000) ORDER BY goals_added_above_avg DESC LIMIT 10",
            ),
            GPLUS_PER_SALARY_EXAMPLE,
        ],
    )

    @classmethod
    def fetch(cls, args: PlayerArgs) -> asa.Result:
        """Fetch goals added."""
        return asa.fetch_goals_added(args.league, args.season, args.minimum_minutes, args.stage)


@init_single_worker
@bind_fixed_schema
class XgTeamsFunction(Scan, TableFunctionGenerator[LeagueSeasonArgs]):
    """Team xG for and against."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = asa.XG_TEAMS_SCHEMA
    ESTIMATE, MAX = 30, 100
    Meta = _meta_class(
        name="xg_teams",
        description="Team expected goals for and against with expected points",
        category="expected-goals",
        title="ASA Team xG",
        llm=(
            "One row per team: games, shots, goals and xG for and against, xG difference, actual minus "
            "expected goal difference, points, and expected points."
        ),
        schema=asa.XG_TEAMS_SCHEMA,
        examples=[
            (
                "2025 MLS teams by expected goal difference.",
                "SELECT team_name, points, round(xpoints, 1) AS xpts, round(xgoal_difference, 1) AS xgd "
                "FROM us_soccer.asa.xg_teams(season := 2025) ORDER BY xgoal_difference DESC",
            )
        ],
    )

    @classmethod
    def fetch(cls, args: LeagueSeasonArgs) -> asa.Result:
        """Fetch team xG."""
        return asa.fetch_xg_teams(args.league, args.season, args.stage)


@init_single_worker
@bind_fixed_schema
class XgGamesFunction(Scan, TableFunctionGenerator[LeagueSeasonArgs]):
    """Match xG."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = asa.XG_GAMES_SCHEMA
    ESTIMATE, MAX = 500, 2_000
    Meta = _meta_class(
        name="xg_games",
        description="Match-level expected goals and expected points for a season",
        category="expected-goals",
        title="ASA Game xG",
        llm="One row per match with both teams' goals, xG, and xG-implied expected points.",
        schema=asa.XG_GAMES_SCHEMA,
        examples=[
            (
                "The 2025 MLS matches with the highest combined xG.",
                "SELECT kickoff, home_team_name, away_team_name, home_goals, away_goals, "
                "round(home_xgoals + away_xgoals, 2) AS total_xg "
                "FROM us_soccer.asa.xg_games(season := 2025) ORDER BY total_xg DESC LIMIT 10",
            )
        ],
    )

    @classmethod
    def fetch(cls, args: LeagueSeasonArgs) -> asa.Result:
        """Fetch game xG."""
        return asa.fetch_xg_games(args.league, args.season, args.stage)


@init_single_worker
@bind_fixed_schema
class SalariesFunction(Scan, TableFunctionGenerator[SalaryArgs]):
    """MLS salary releases."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = asa.SALARIES_SCHEMA
    ESTIMATE, MAX = 900, 3_000
    Meta = _meta_class(
        name="salaries",
        description="MLS Players Association salary releases, as compiled by American Soccer Analysis",
        category="salaries",
        title="MLS Salaries",
        llm=(
            "MLS-only player salaries from MLSPA releases: base salary and guaranteed compensation in USD, "
            "position, team, and the release date. A player can appear once per release."
        ),
        schema=asa.SALARIES_SCHEMA,
        examples=[
            (
                "Highest guaranteed compensation in the latest 2025 release.",
                "SELECT player_name, team_abbreviation, guaranteed_compensation "
                "FROM us_soccer.asa.salaries(season := 2025) "
                "QUALIFY release_date = max(release_date) OVER () "
                "ORDER BY guaranteed_compensation DESC LIMIT 10",
            )
        ],
    )

    @classmethod
    def fetch(cls, args: SalaryArgs) -> asa.Result:
        """Fetch salary releases."""
        return asa.fetch_salaries(args.season)


ASA_FUNCTIONS = [
    TeamsFunction,
    XgPlayersFunction,
    GoalsAddedFunction,
    XgTeamsFunction,
    XgGamesFunction,
    SalariesFunction,
]
