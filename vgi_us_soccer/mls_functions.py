"""VGI table functions for the ``mls`` schema (MLS Stats API)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Annotated, Any, ClassVar

import pyarrow as pa
from vgi.arguments import Arg
from vgi.metadata import FunctionExample
from vgi.table_function import TableFunctionGenerator, bind_fixed_schema, init_single_worker

from vgi_us_soccer import mls
from vgi_us_soccer.base import Scan, tags

PROVIDER = "mls"

_COMPETITION = Arg(
    "competition",
    default="mls",
    arrow_type=pa.string(),
    pattern=mls.COMPETITION_PATTERN,
    doc=(
        "Competition alias (mls, mls_playoffs, next_pro, next_pro_playoffs, leagues_cup, us_open_cup, "
        "canadian_championship, champions_cup, campeones_cup, all_star) or a raw MLS-COM- id."
    ),
)
_SEASON = Arg(
    "season",
    default=None,
    arrow_type=pa.int32(),
    ge=1996,
    le=2100,
    doc="Season year. NULL selects the current season.",
)
_MATCH_ID = Arg(
    0,
    arrow_type=pa.string(),
    pattern=r"^MLS-MAT-[0-9A-Z]{6}$",
    doc="MLS match identifier, for example MLS-MAT-0009NL, from schedule().",
)
_PLAYER_ID = Arg(
    0,
    arrow_type=pa.string(),
    pattern=r"^MLS-OBJ-[0-9A-Z]{6}$",
    doc="MLS player identifier, for example MLS-OBJ-000396, from player_stats().",
)


@dataclass(kw_only=True)
class CompetitionArgs:
    """Arguments naming one competition."""

    competition: Annotated[str, _COMPETITION]


@dataclass(kw_only=True)
class SeasonArgs:
    """Arguments naming one competition and season."""

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
            choices=tuple(mls.STANDINGS_SPLITS),
            doc="overall for the full table, home or away for venue tables, form for recent form.",
        ),
    ]


@dataclass(kw_only=True)
class ScheduleArgs:
    """Arguments accepted by ``schedule``."""

    season: Annotated[int | None, _SEASON]
    competition: Annotated[
        str | None,
        Arg(
            "competition",
            default=None,
            arrow_type=pa.string(),
            pattern=mls.COMPETITION_PATTERN,
            doc="Competition alias or MLS-COM- id; NULL returns every competition in the season.",
        ),
    ]
    start_date: Annotated[
        date | None,
        Arg("start_date", default=None, arrow_type=pa.date32(), doc="Inclusive first match day, in UTC."),
    ]
    end_date: Annotated[
        date | None,
        Arg("end_date", default=None, arrow_type=pa.date32(), doc="Inclusive last match day, in UTC."),
    ]


@dataclass(kw_only=True)
class MatchArgs:
    """Arguments naming one match."""

    match_id: Annotated[str, _MATCH_ID]


@dataclass(kw_only=True)
class PlayerLogArgs:
    """Arguments accepted by ``player_match_log``."""

    player_id: Annotated[str, _PLAYER_ID]
    season: Annotated[
        int | None,
        Arg(
            "season", default=None, arrow_type=pa.int32(), ge=1996, le=2100, doc="Season year; NULL for all."
        ),
    ]
    competition: Annotated[
        str | None,
        Arg(
            "competition",
            default=None,
            arrow_type=pa.string(),
            pattern=mls.COMPETITION_PATTERN,
            doc="Competition alias or MLS-COM- id; NULL for every competition.",
        ),
    ]


def _meta(
    *,
    name: str,
    description: str,
    category: str,
    title: str,
    llm: str,
    schema: pa.Schema,
    examples: list[tuple[str, str]],
    md: str | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "categories": ["soccer", "mls", category],
        "projection_pushdown": True,
        "tags": tags(
            provider=PROVIDER,
            category=category,
            title=title,
            llm=llm,
            md=md,
            schema=schema,
            examples=examples,
        ),
        "examples": [FunctionExample(sql=sql, description=text) for text, sql in examples],
    }


def _meta_class(**kwargs: Any) -> type:
    """Build the nested ``Meta`` class VGI reads discovery metadata from."""
    return type("Meta", (), {"__doc__": "Function discovery metadata.", **_meta(**kwargs)})


# Composed examples combine two of this schema's functions. Each is defined once (this one here,
# STARTER_BOX_SCORE_EXAMPLE beside the match functions) and listed both on the function that drives the
# query and in the schema-level example list (see worker.py).
PLAYER_GOAL_SHARE_EXAMPLE = (
    "2025 MLS players who scored the largest share of their club's regular-season goals, joining "
    "player_stats to the final standings.",
    "SELECT p.player_name, p.club_abbreviation, p.goals, s.goals_for AS club_goals, "
    "round(100.0 * p.goals / s.goals_for, 1) AS pct_of_club_goals "
    "FROM us_soccer.mls.player_stats(season := 2025) AS p "
    "JOIN us_soccer.mls.standings(season := 2025) AS s USING (club_id) "
    "ORDER BY pct_of_club_goals DESC, p.player_name LIMIT 10",
)


# ------------------------------------------------------------------ reference


@init_single_worker
@bind_fixed_schema
class CompetitionsFunction(Scan, TableFunctionGenerator[None]):
    """Competitions published by the MLS Stats API."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = mls.COMPETITIONS_SCHEMA
    ESTIMATE, MAX = 20, 100
    Meta = _meta_class(
        name="all_competitions",
        description="Competitions in the MLS Stats API (scan behind the competitions table)",
        category="reference",
        title="MLS Competitions",
        llm=(
            "Lists every competition the MLS Stats API covers with its MLS-COM- id and the short alias "
            "accepted by the competition argument of other mls functions."
        ),
        schema=mls.COMPETITIONS_SCHEMA,
        examples=[
            (
                "Competitions with their catalog aliases.",
                "SELECT competition_id, competition_name, alias "
                "FROM us_soccer.mls.all_competitions() ORDER BY 1",
            )
        ],
    )

    @classmethod
    def fetch(cls, args: None) -> mls.Result:
        """Fetch the competition list."""
        return mls.fetch_competitions()


@init_single_worker
@bind_fixed_schema
class SeasonsFunction(Scan, TableFunctionGenerator[CompetitionArgs]):
    """Seasons available for one competition."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = mls.SEASONS_SCHEMA
    ESTIMATE, MAX = 32, 64
    Meta = _meta_class(
        name="seasons",
        description="Seasons available for an MLS competition, newest first",
        category="reference",
        title="MLS Seasons",
        llm="Season years and MLS-SEA- ids for one competition; MLS regular season goes back to 1996.",
        schema=mls.SEASONS_SCHEMA,
        examples=[
            (
                "Every MLS NEXT Pro season.",
                "SELECT season, season_id "
                "FROM us_soccer.mls.seasons(competition := 'next_pro') ORDER BY season",
            )
        ],
    )

    @classmethod
    def fetch(cls, args: CompetitionArgs) -> mls.Result:
        """Fetch seasons for the competition."""
        return mls.fetch_seasons(args.competition)


# ------------------------------------------------------------------ standings

_STANDINGS_LLM = (
    "One row per club in a competition table: position, games played, wins, draws, losses, goals for and "
    "against, goal difference, points, and per-game rates. The MLS Stats API publishes a single league-wide "
    "table (the Supporters' Shield race) rather than conference tables. split => 'home', 'away', or "
    "'form' returns the venue or recent-form tables."
)


@init_single_worker
@bind_fixed_schema
class StandingsFunction(Scan, TableFunctionGenerator[StandingsArgs]):
    """League table for a competition and season."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = mls.STANDINGS_SCHEMA
    ESTIMATE, MAX = 30, 128
    Meta = _meta_class(
        name="standings",
        description="MLS-family league table by season, competition, and home/away/form split",
        category="standings",
        title="MLS Standings",
        llm=_STANDINGS_LLM,
        schema=mls.STANDINGS_SCHEMA,
        examples=[
            (
                "The final 2025 MLS regular-season table.",
                "SELECT position, club_name, points, goal_difference "
                "FROM us_soccer.mls.standings(season := 2025) ORDER BY position",
            ),
            (
                "The best home records in MLS NEXT Pro this season.",
                "SELECT position, club_name, wins, points "
                "FROM us_soccer.mls.standings(competition := 'next_pro', split := 'home') "
                "ORDER BY position LIMIT 10",
            ),
        ],
    )

    @classmethod
    def fetch(cls, args: StandingsArgs) -> mls.Result:
        """Fetch the requested table."""
        return mls.fetch_standings(args.competition, args.season, args.split)


@init_single_worker
@bind_fixed_schema
class CurrentStandingsFunction(Scan, TableFunctionGenerator[None]):
    """Current MLS regular-season table backing ``current_standings``."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = mls.STANDINGS_SCHEMA
    ESTIMATE, MAX = 30, 64
    Meta = _meta_class(
        name="all_current_standings",
        description="Current MLS regular-season table (scan behind current_standings)",
        category="standings",
        title="Current MLS Standings Scan",
        llm=(
            "The scan behind the current_standings table. Prefer the table; use standings() for another "
            "season, competition, or split."
        ),
        schema=mls.STANDINGS_SCHEMA,
        examples=[
            (
                "Read the current table directly from its backing scan.",
                "SELECT position, club_name, points "
                "FROM us_soccer.mls.all_current_standings() ORDER BY position",
            )
        ],
    )

    @classmethod
    def fetch(cls, args: None) -> mls.Result:
        """Fetch the current regular-season table."""
        return mls.fetch_standings(mls.REGULAR_SEASON, None, "overall")


# ------------------------------------------------------------------ clubs


@init_single_worker
@bind_fixed_schema
class ClubsFunction(Scan, TableFunctionGenerator[SeasonArgs]):
    """Clubs in one competition and season."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = mls.CLUBS_SCHEMA
    ESTIMATE, MAX = 30, 128
    Meta = _meta_class(
        name="clubs",
        description="Clubs registered in an MLS-family competition and season",
        category="club-stats",
        title="MLS Clubs",
        llm="Club ids, names, three-letter codes, and home cities for one competition and season.",
        schema=mls.CLUBS_SCHEMA,
        examples=[
            (
                "Clubs in the 2025 MLS regular season.",
                "SELECT club_abbreviation, club_name, city "
                "FROM us_soccer.mls.clubs(season := 2025) ORDER BY 2",
            )
        ],
    )

    @classmethod
    def fetch(cls, args: SeasonArgs) -> mls.Result:
        """Fetch clubs for the season."""
        return mls.fetch_clubs(args.competition, args.season)


_CLUB_STATS_LLM = (
    "Season club statistics: goals, goals conceded, tracking-model xG, shots, passing accuracy, "
    "possession, discipline, set pieces, goalkeeper saves, and distance covered, one row per club."
)


@init_single_worker
@bind_fixed_schema
class ClubStatsFunction(Scan, TableFunctionGenerator[SeasonArgs]):
    """Season club statistics."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = mls.CLUB_STATS_SCHEMA
    ESTIMATE, MAX = 30, 128
    Meta = _meta_class(
        name="club_stats",
        description="Season club statistics for an MLS-family competition",
        category="club-stats",
        title="MLS Club Statistics",
        llm=_CLUB_STATS_LLM,
        schema=mls.CLUB_STATS_SCHEMA,
        examples=[
            (
                "2025 MLS clubs by expected goals.",
                "SELECT club_name, goals, round(xg, 1) AS xg, possession_ratio "
                "FROM us_soccer.mls.club_stats(season := 2025) ORDER BY xg DESC",
            )
        ],
    )

    @classmethod
    def fetch(cls, args: SeasonArgs) -> mls.Result:
        """Fetch club statistics for the season."""
        return mls.fetch_club_stats(args.competition, args.season)


@init_single_worker
@bind_fixed_schema
class CurrentClubStatsFunction(Scan, TableFunctionGenerator[None]):
    """Current MLS regular-season club statistics backing ``current_club_stats``."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = mls.CLUB_STATS_SCHEMA
    ESTIMATE, MAX = 30, 64
    Meta = _meta_class(
        name="all_current_club_stats",
        description="Current MLS regular-season club statistics (scan behind current_club_stats)",
        category="club-stats",
        title="Current MLS Club Statistics Scan",
        llm="The scan behind current_club_stats. Prefer the table; use club_stats() for other seasons.",
        schema=mls.CLUB_STATS_SCHEMA,
        examples=[
            (
                "Read current club statistics directly from the backing scan.",
                "SELECT club_name, goals, xg FROM us_soccer.mls.all_current_club_stats() ORDER BY goals DESC",
            )
        ],
    )

    @classmethod
    def fetch(cls, args: None) -> mls.Result:
        """Fetch current club statistics."""
        return mls.fetch_club_stats(mls.REGULAR_SEASON, None)


# ------------------------------------------------------------------ players

_PLAYER_STATS_LLM = (
    "Season player statistics, one row per player and club (a player traded mid-season has one row per "
    "club). Includes minutes, goals, assists, tracking-model xG, shots, passing, discipline, aerial duels, "
    "distance covered, top speed, and goalkeeper saves, goals conceded, clean sheets, and expected saves."
)


@init_single_worker
@bind_fixed_schema
class PlayerStatsFunction(Scan, TableFunctionGenerator[SeasonArgs]):
    """Season player statistics."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = mls.PLAYER_STATS_SCHEMA
    ESTIMATE, MAX = 1_000, 5_000
    Meta = _meta_class(
        name="player_stats",
        description="Season player statistics for an MLS-family competition, per player and club",
        category="player-stats",
        title="MLS Player Statistics",
        llm=_PLAYER_STATS_LLM,
        schema=mls.PLAYER_STATS_SCHEMA,
        examples=[
            (
                "2025 MLS Golden Boot race.",
                "SELECT player_name, club_abbreviation, goals, assists, round(xg, 1) AS xg "
                "FROM us_soccer.mls.player_stats(season := 2025) ORDER BY goals DESC LIMIT 10",
            ),
            PLAYER_GOAL_SHARE_EXAMPLE,
        ],
    )

    @classmethod
    def fetch(cls, args: SeasonArgs) -> mls.Result:
        """Fetch player statistics for the season."""
        return mls.fetch_player_stats(args.competition, args.season)


@init_single_worker
@bind_fixed_schema
class CurrentPlayerStatsFunction(Scan, TableFunctionGenerator[None]):
    """Current MLS regular-season player statistics backing ``current_player_stats``."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = mls.PLAYER_STATS_SCHEMA
    ESTIMATE, MAX = 1_000, 3_000
    Meta = _meta_class(
        name="all_current_player_stats",
        description="Current MLS regular-season player statistics (scan behind current_player_stats)",
        category="player-stats",
        title="Current MLS Player Statistics Scan",
        llm="The scan behind current_player_stats. Prefer the table; use player_stats() for other seasons.",
        schema=mls.PLAYER_STATS_SCHEMA,
        examples=[
            (
                "Read current player statistics directly from the backing scan.",
                "SELECT player_name, goals FROM us_soccer.mls.all_current_player_stats() "
                "ORDER BY goals DESC LIMIT 5",
            )
        ],
    )

    @classmethod
    def fetch(cls, args: None) -> mls.Result:
        """Fetch current player statistics."""
        return mls.fetch_player_stats(mls.REGULAR_SEASON, None)


@init_single_worker
@bind_fixed_schema
class PlayerMatchLogFunction(Scan, TableFunctionGenerator[PlayerLogArgs]):
    """One player's per-match statistics."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = mls.PLAYER_MATCH_LOG_SCHEMA
    ESTIMATE, MAX = 60, 1_000
    Meta = _meta_class(
        name="player_match_log",
        description="Per-match statistics for one MLS player, newest first",
        category="player-stats",
        title="MLS Player Match Log",
        llm=(
            "One row per match a player appeared in across MLS-family competitions, newest first, with the "
            "same statistic columns as match_player_stats. Narrow with season and competition."
        ),
        schema=mls.PLAYER_MATCH_LOG_SCHEMA,
        examples=[
            (
                "Lionel Messi's 2025 MLS regular-season match log.",
                "SELECT planned_kickoff, match_title, minutes_played, goals, assists "
                "FROM us_soccer.mls.player_match_log('MLS-OBJ-000396', season := 2025, competition := 'mls') "
                "ORDER BY planned_kickoff",
            )
        ],
    )

    @classmethod
    def fetch(cls, args: PlayerLogArgs) -> mls.Result:
        """Fetch the player's match log."""
        return mls.fetch_player_match_log(args.player_id, season=args.season, competition=args.competition)


# ------------------------------------------------------------------ schedule

_SCHEDULE_LLM = (
    "Fixtures and results, one row per match, with kickoff time, status, clubs, score, round, conference "
    "label, and stadium. Pass start_date/end_date to narrow; with no dates the whole season is returned. "
    "Scores are NULL until a match kicks off."
)


@init_single_worker
@bind_fixed_schema
class ScheduleFunction(Scan, TableFunctionGenerator[ScheduleArgs]):
    """Fixtures and results for a season."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = mls.SCHEDULE_SCHEMA
    ESTIMATE, MAX = 500, 5_000
    Meta = _meta_class(
        name="schedule",
        description="MLS-family fixtures and results by season, competition, and date range",
        category="schedule",
        title="MLS Schedule and Scores",
        llm=_SCHEDULE_LLM,
        schema=mls.SCHEDULE_SCHEMA,
        examples=[
            (
                "MLS regular-season results on 18 October 2026.",
                "SELECT match_id, home_club_abbreviation, home_goals, away_goals, away_club_abbreviation "
                "FROM us_soccer.mls.schedule(season := 2026, competition := 'mls', "
                "start_date := DATE '2026-10-18', end_date := DATE '2026-10-18') ORDER BY planned_kickoff",
            )
        ],
    )

    @classmethod
    def fetch(cls, args: ScheduleArgs) -> mls.Result:
        """Fetch the season schedule."""
        return mls.fetch_schedule(
            season=args.season,
            competition=args.competition,
            start_date=args.start_date,
            end_date=args.end_date,
        )


@init_single_worker
@bind_fixed_schema
class CurrentScheduleFunction(Scan, TableFunctionGenerator[None]):
    """Recent and upcoming matches backing ``current_schedule``."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = mls.SCHEDULE_SCHEMA
    ESTIMATE, MAX = 60, 1_000
    Meta = _meta_class(
        name="all_current_schedule",
        description="MLS-family matches from 7 days ago to 14 days ahead (scan behind current_schedule)",
        category="schedule",
        title="Current MLS Schedule Scan",
        llm="The scan behind current_schedule. Prefer the table; use schedule() for arbitrary date ranges.",
        schema=mls.SCHEDULE_SCHEMA,
        examples=[
            (
                "Read the rolling schedule window directly.",
                "SELECT planned_kickoff, home_club_name, away_club_name "
                "FROM us_soccer.mls.all_current_schedule() ORDER BY planned_kickoff",
            )
        ],
    )

    @classmethod
    def fetch(cls, args: None) -> mls.Result:
        """Fetch the rolling three-week schedule window."""
        return mls.fetch_current_schedule()


# ------------------------------------------------------------------ match detail

_MATCH_SQL = "'MLS-MAT-0009NL'"

# A composed example (see PLAYER_GOAL_SHARE_EXAMPLE): driven by match_lineups().
STARTER_BOX_SCORE_EXAMPLE = (
    "Minutes, shots, xG, and goals for every starter in MLS-MAT-0009NL, joining match_lineups to "
    "match_player_stats.",
    "SELECT l.club_abbreviation, l.shirt_number, l.player_name, s.minutes_played, s.shots, "
    "round(s.xg, 2) AS xg, s.goals "
    f"FROM us_soccer.mls.match_lineups({_MATCH_SQL}) AS l "
    f"JOIN us_soccer.mls.match_player_stats({_MATCH_SQL}) AS s USING (player_id) "
    "WHERE l.starter ORDER BY l.club_abbreviation, l.shirt_number",
)


@init_single_worker
@bind_fixed_schema
class MatchFunction(Scan, TableFunctionGenerator[MatchArgs]):
    """One match summary."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = mls.MATCH_SCHEMA
    ESTIMATE, MAX = 1, 1
    Meta = _meta_class(
        name="match",
        description="Summary of one MLS match: score, venue, attendance, formations, coaches, referee",
        category="match-detail",
        title="MLS Match Summary",
        llm=(
            "One row for a match id: competition, kickoff, status, clubs, score, stadium, attendance, "
            "temperature, starting formations, head coaches, and center referee."
        ),
        schema=mls.MATCH_SCHEMA,
        examples=[
            (
                "FC Cincinnati vs Columbus Crew, 18 October 2026.",
                "SELECT home_club_name, home_goals, away_goals, away_club_name, attendance, referee "
                f"FROM us_soccer.mls.match({_MATCH_SQL})",
            )
        ],
    )

    @classmethod
    def fetch(cls, args: MatchArgs) -> mls.Result:
        """Fetch the match summary."""
        return mls.fetch_match(args.match_id)


@init_single_worker
@bind_fixed_schema
class MatchLineupsFunction(Scan, TableFunctionGenerator[MatchArgs]):
    """Matchday squads for one match."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = mls.LINEUPS_SCHEMA
    ESTIMATE, MAX = 40, 80
    Meta = _meta_class(
        name="match_lineups",
        description="Starting lineups and substitutes for one MLS match",
        category="match-detail",
        title="MLS Match Lineups",
        llm="Both matchday squads with shirt numbers, lineup positions, starter and captain flags.",
        schema=mls.LINEUPS_SCHEMA,
        examples=[
            (
                "Starting elevens.",
                "SELECT team_role, shirt_number, player_name, lineup_position "
                f"FROM us_soccer.mls.match_lineups({_MATCH_SQL}) WHERE starter "
                "ORDER BY team_role, shirt_number",
            ),
            STARTER_BOX_SCORE_EXAMPLE,
        ],
    )

    @classmethod
    def fetch(cls, args: MatchArgs) -> mls.Result:
        """Fetch the matchday squads."""
        return mls.fetch_match_lineups(args.match_id)


@init_single_worker
@bind_fixed_schema
class MatchEventsFunction(Scan, TableFunctionGenerator[MatchArgs]):
    """Key events for one match."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = mls.EVENTS_SCHEMA
    ESTIMATE, MAX = 90, 500
    Meta = _meta_class(
        name="match_events",
        description="Key events for one MLS match: goals, shots with xG, cards, substitutions, fouls",
        category="match-detail",
        title="MLS Match Events",
        llm=(
            "Chronological key events. player_id/player_name are the shooter, booked player, fouler, or "
            "player coming on; other_player_* is the assister, fouled player, or player going off. "
            "Filter is_goal for goals; shots carry xg, distance, and pitch coordinates."
        ),
        schema=mls.EVENTS_SCHEMA,
        examples=[
            (
                "Goals and their assisters.",
                "SELECT minute_of_play, club_abbreviation, player_name, other_player_name AS assist, xg "
                f"FROM us_soccer.mls.match_events({_MATCH_SQL}) WHERE is_goal ORDER BY event_time",
            )
        ],
    )

    @classmethod
    def fetch(cls, args: MatchArgs) -> mls.Result:
        """Fetch the key events."""
        return mls.fetch_match_events(args.match_id)


@init_single_worker
@bind_fixed_schema
class MatchCommentaryFunction(Scan, TableFunctionGenerator[MatchArgs]):
    """English text commentary for one match."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = mls.COMMENTARY_SCHEMA
    ESTIMATE, MAX = 90, 500
    Meta = _meta_class(
        name="match_commentary",
        description="English text commentary for one MLS match",
        category="match-detail",
        title="MLS Match Commentary",
        llm="Minute-by-minute English commentary lines with type, minute, club, and player ids.",
        schema=mls.COMMENTARY_SCHEMA,
        examples=[
            (
                "Commentary on shots.",
                "SELECT minute_of_play, commentary "
                f"FROM us_soccer.mls.match_commentary({_MATCH_SQL}) WHERE commentary_type = 'ShotAtGoal' "
                "ORDER BY minute, second",
            )
        ],
    )

    @classmethod
    def fetch(cls, args: MatchArgs) -> mls.Result:
        """Fetch the commentary."""
        return mls.fetch_match_commentary(args.match_id)


@init_single_worker
@bind_fixed_schema
class MatchClubStatsFunction(Scan, TableFunctionGenerator[MatchArgs]):
    """Per-club statistics for one match."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = mls.MATCH_CLUB_STATS_SCHEMA
    ESTIMATE, MAX = 2, 2
    Meta = _meta_class(
        name="match_club_stats",
        description="Team box score for one MLS match",
        category="match-detail",
        title="MLS Match Club Statistics",
        llm="Two rows, home and away, with shots, xG, possession, passing, discipline, and saves.",
        schema=mls.MATCH_CLUB_STATS_SCHEMA,
        examples=[
            (
                "Compare both sides.",
                "SELECT team_role, club_abbreviation, goals, shots, round(xg, 2) AS xg, possession_ratio "
                f"FROM us_soccer.mls.match_club_stats({_MATCH_SQL}) ORDER BY team_role DESC",
            )
        ],
    )

    @classmethod
    def fetch(cls, args: MatchArgs) -> mls.Result:
        """Fetch the team box score."""
        return mls.fetch_match_club_stats(args.match_id)


@init_single_worker
@bind_fixed_schema
class MatchPlayerStatsFunction(Scan, TableFunctionGenerator[MatchArgs]):
    """Per-player statistics for one match."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = mls.MATCH_PLAYER_STATS_SCHEMA
    ESTIMATE, MAX = 30, 60
    Meta = _meta_class(
        name="match_player_stats",
        description="Player box score for one MLS match",
        category="match-detail",
        title="MLS Match Player Statistics",
        llm="One row per player who appeared, with minutes, goals, assists, xG, shots, passing, and saves.",
        schema=mls.MATCH_PLAYER_STATS_SCHEMA,
        examples=[
            (
                "Players with the highest xG in the match.",
                "SELECT player_name, club_abbreviation, minutes_played, shots, round(xg, 2) AS xg "
                f"FROM us_soccer.mls.match_player_stats({_MATCH_SQL}) ORDER BY xg DESC LIMIT 5",
            )
        ],
    )

    @classmethod
    def fetch(cls, args: MatchArgs) -> mls.Result:
        """Fetch the player box score."""
        return mls.fetch_match_player_stats(args.match_id)


MLS_FUNCTIONS = [
    CompetitionsFunction,
    SeasonsFunction,
    StandingsFunction,
    CurrentStandingsFunction,
    ClubsFunction,
    ClubStatsFunction,
    CurrentClubStatsFunction,
    PlayerStatsFunction,
    CurrentPlayerStatsFunction,
    PlayerMatchLogFunction,
    ScheduleFunction,
    CurrentScheduleFunction,
    MatchFunction,
    MatchLineupsFunction,
    MatchEventsFunction,
    MatchCommentaryFunction,
    MatchClubStatsFunction,
    MatchPlayerStatsFunction,
]
