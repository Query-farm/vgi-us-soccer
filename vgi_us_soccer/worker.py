"""VGI worker exposing MLS, NWSL, and American Soccer Analysis data as a SQL catalog."""

from __future__ import annotations

import json
import os
import sys

from vgi import Worker
from vgi.catalog import Catalog, ConstraintInfo, Schema, Table, constraint_record

from vgi_us_soccer import asa, mls, nwsl
from vgi_us_soccer.asa_functions import ASA_FUNCTIONS, GPLUS_PER_SALARY_EXAMPLE
from vgi_us_soccer.meta import column_comments
from vgi_us_soccer.mls_functions import (
    MLS_FUNCTIONS,
    PLAYER_GOAL_SHARE_EXAMPLE,
    STARTER_BOX_SCORE_EXAMPLE,
    CompetitionsFunction,
    CurrentClubStatsFunction,
    CurrentPlayerStatsFunction,
    CurrentScheduleFunction,
    CurrentStandingsFunction,
)
from vgi_us_soccer.nwsl_functions import NWSL_FUNCTIONS, TOP_SCORER_BY_TEAM_EXAMPLE
from vgi_us_soccer.nwsl_functions import CompetitionsFunction as NwslCompetitionsFunction
from vgi_us_soccer.nwsl_functions import CurrentMatchesFunction as NwslCurrentMatchesFunction
from vgi_us_soccer.nwsl_functions import CurrentPlayerStatsFunction as NwslCurrentPlayerStatsFunction
from vgi_us_soccer.nwsl_functions import CurrentStandingsFunction as NwslCurrentStandingsFunction

CATALOG_NAME = "us_soccer"
SOURCE_URL = "https://github.com/Query-farm/vgi-us-soccer"


def _examples(*pairs: tuple[str, str]) -> str:
    return json.dumps([{"description": text, "sql": sql} for text, sql in pairs])


def _table_tags(
    *, provider: str, category: str, title: str, keywords: list[str], llm: str, md: str, examples: str
) -> dict[str, str]:
    return {
        "provider": provider,
        "vgi.category": category,
        "vgi.title": title,
        "vgi.keywords": json.dumps(keywords),
        "vgi.doc_llm": llm,
        "vgi.doc_md": md,
        "vgi.example_queries": examples,
    }


def _key_constraints(schema: str, table: str, key: tuple[str, ...]) -> tuple[ConstraintInfo, ...]:
    """Primary-key and NOT NULL records for a read-only table keyed by ``key``."""
    records = [
        constraint_record(
            [schema],
            table,
            "pk",
            "PRIMARY_KEY",
            [[column] for column in key],
            enforcement="ENFORCED",
            validation="ALL_ROWS",
        )
    ]
    records += [
        constraint_record(
            [schema],
            table,
            f"{column}_not_null",
            "NOT_NULL",
            [[column]],
            enforcement="ENFORCED",
            validation="ALL_ROWS",
        )
        for column in key
    ]
    return tuple(records)


_MLS_STANDINGS_PAIRS = (
    (
        "The current Supporters' Shield table.",
        "SELECT position, club_name, games_played, points, goal_difference "
        "FROM us_soccer.mls.current_standings ORDER BY position",
    ),
    (
        "Clubs with the best goal difference per game.",
        "SELECT club_name, goal_difference, games_played "
        "FROM us_soccer.mls.current_standings ORDER BY goal_difference DESC LIMIT 5",
    ),
)
_MLS_STANDINGS_EXAMPLES = _examples(*_MLS_STANDINGS_PAIRS)

_MLS_TABLES = [
    Table(
        name="current_standings",
        function=CurrentStandingsFunction,
        comment="Current MLS regular-season table, one row per club",
        tags=_table_tags(
            provider="mls",
            category="standings",
            title="Current MLS Standings",
            keywords=["standings", "table", "points", "Supporters' Shield", "goal difference"],
            llm=(
                "The current MLS regular-season table, one row per club, league-wide (Supporters' Shield "
                "order). Start here for points, record, goals, and goal difference. For another season, "
                "another competition such as NEXT Pro, or home/away/form tables, call standings()."
            ),
            md=(
                "The current MLS regular-season standings as an ordinary read-only table. The MLS Stats "
                "API publishes a single league-wide table; use `standings()` for other seasons, "
                "competitions, and splits."
            ),
            examples=_MLS_STANDINGS_EXAMPLES,
        ),
        column_comments=column_comments(mls.STANDINGS_SCHEMA),
        constraints=_key_constraints("mls", "current_standings", ("club_id",)),
        cardinality_estimate=30,
    ),
    Table(
        name="current_player_stats",
        function=CurrentPlayerStatsFunction,
        comment="Current MLS regular-season player statistics, one row per player and club",
        tags=_table_tags(
            provider="mls",
            category="player-stats",
            title="Current MLS Player Statistics",
            keywords=["players", "goals", "assists", "xG", "Golden Boot", "goalkeepers", "saves"],
            llm=(
                "Current-season MLS regular-season statistics for every player, one row per player and "
                "club (traded players have one row per club). Use for goals, assists, xG, shots, "
                "passing, discipline, distance, top speed, and goalkeeper saves. Use player_stats() for "
                "other seasons or competitions."
            ),
            md="Complete current-season MLS player statistics at player-club grain.",
            examples=_examples(
                (
                    "Current Golden Boot race.",
                    "SELECT player_name, club_abbreviation, goals, assists, round(xg, 1) AS xg "
                    "FROM us_soccer.mls.current_player_stats ORDER BY goals DESC LIMIT 10",
                ),
                (
                    "Goalkeepers with the most saves.",
                    "SELECT player_name, club_abbreviation, goalkeeper_saves, clean_sheets "
                    "FROM us_soccer.mls.current_player_stats WHERE goalkeeper "
                    "ORDER BY goalkeeper_saves DESC LIMIT 10",
                ),
            ),
        ),
        column_comments=column_comments(mls.PLAYER_STATS_SCHEMA),
        constraints=_key_constraints("mls", "current_player_stats", ("player_id", "club_id")),
        cardinality_estimate=1_050,
    ),
    Table(
        name="current_club_stats",
        function=CurrentClubStatsFunction,
        comment="Current MLS regular-season club statistics, one row per club",
        tags=_table_tags(
            provider="mls",
            category="club-stats",
            title="Current MLS Club Statistics",
            keywords=["clubs", "team stats", "xG", "possession", "shots", "clean sheets"],
            llm=(
                "Current-season MLS regular-season club statistics: goals, goals conceded, xG, shots, "
                "possession, passing accuracy, discipline, set pieces, saves, and distance. Use "
                "club_stats() for other seasons or competitions."
            ),
            md="Complete current-season MLS club statistics, one row per club.",
            examples=_examples(
                (
                    "Clubs by expected goals.",
                    "SELECT club_name, goals, round(xg, 1) AS xg, possession_ratio "
                    "FROM us_soccer.mls.current_club_stats ORDER BY xg DESC",
                )
            ),
        ),
        column_comments=column_comments(mls.CLUB_STATS_SCHEMA),
        constraints=_key_constraints("mls", "current_club_stats", ("club_id",)),
        cardinality_estimate=30,
    ),
    Table(
        name="current_schedule",
        function=CurrentScheduleFunction,
        comment="MLS-family matches from seven days ago through fourteen days ahead",
        tags=_table_tags(
            provider="mls",
            category="schedule",
            title="Current MLS Schedule",
            keywords=["schedule", "fixtures", "results", "scores", "playoffs", "NEXT Pro"],
            llm=(
                "A rolling three-week window of MLS, MLS Cup Playoffs, NEXT Pro, and cup matches: recent "
                "results and upcoming fixtures with kickoff time, status, clubs, and score. It can be "
                "empty in the off-season. Use schedule() for any season or date range."
            ),
            md=(
                "Recent results and upcoming fixtures across MLS-family competitions, from seven days "
                "ago to fourteen days ahead. Scores are NULL until kickoff."
            ),
            examples=_examples(
                (
                    "Upcoming fixtures.",
                    "SELECT planned_kickoff, competition_name, home_club_name, away_club_name "
                    "FROM us_soccer.mls.current_schedule WHERE match_status = 'scheduled' "
                    "ORDER BY planned_kickoff",
                )
            ),
        ),
        column_comments=column_comments(mls.SCHEDULE_SCHEMA),
        constraints=_key_constraints("mls", "current_schedule", ("match_id",)),
        cardinality_estimate=60,
    ),
    Table(
        name="competitions",
        function=CompetitionsFunction,
        comment="Competitions covered by the MLS Stats API, with catalog aliases",
        tags=_table_tags(
            provider="mls",
            category="reference",
            title="MLS Competitions",
            keywords=["competitions", "NEXT Pro", "Leagues Cup", "US Open Cup", "aliases"],
            llm=(
                "Every competition the MLS Stats API covers: MLS regular season and playoffs, MLS NEXT Pro, "
                "Leagues Cup, US Open Cup, Canadian Championship, CONCACAF Champions Cup, friendlies, and "
                "more. alias is the short name accepted by the competition argument of mls functions."
            ),
            md=(
                "Competition identifiers and aliases for the `competition` argument of the `mls` "
                "functions. The upstream's internal test competition is omitted."
            ),
            examples=_examples(
                (
                    "Competitions with catalog aliases.",
                    "SELECT alias, competition_id, competition_name FROM us_soccer.mls.competitions "
                    "WHERE alias IS NOT NULL ORDER BY alias",
                )
            ),
        ),
        column_comments=column_comments(mls.COMPETITIONS_SCHEMA),
        constraints=_key_constraints("mls", "competitions", ("competition_id",)),
        cardinality_estimate=20,
    ),
]

_NWSL_TABLES = [
    Table(
        name="current_standings",
        function=NwslCurrentStandingsFunction,
        comment="Current NWSL regular-season table, one row per team",
        tags=_table_tags(
            provider="nwsl",
            category="standings",
            title="Current NWSL Standings",
            keywords=["NWSL", "standings", "table", "points", "playoffs", "Shield"],
            llm=(
                "The current NWSL table, one row per team, with record, goals, points, recent form, and "
                "playoff-zone label. Use nwsl.standings() for another season or home/away tables."
            ),
            md="The current NWSL regular-season table as an ordinary read-only table.",
            examples=_examples(
                (
                    "The current NWSL table.",
                    "SELECT position, team_name, points, form FROM us_soccer.nwsl.current_standings "
                    "ORDER BY position",
                )
            ),
        ),
        column_comments=column_comments(nwsl.STANDINGS_SCHEMA),
        constraints=_key_constraints("nwsl", "current_standings", ("team_id",)),
        cardinality_estimate=16,
    ),
    Table(
        name="current_player_stats",
        function=NwslCurrentPlayerStatsFunction,
        comment="Current NWSL season player statistics, one row per player",
        tags=_table_tags(
            provider="nwsl",
            category="player-stats",
            title="Current NWSL Player Statistics",
            keywords=["NWSL", "players", "goals", "assists", "xG", "saves"],
            llm=(
                "Current-season NWSL statistics for every player who appeared: goals, assists, xG, "
                "shots, passing, defensive actions, discipline, and goalkeeper saves. Use "
                "nwsl.player_stats() for another season."
            ),
            md="Complete current-season NWSL player statistics, one row per player.",
            examples=_examples(
                (
                    "Current NWSL scoring leaders.",
                    "SELECT player_name, team_abbreviation, goals, assists, round(xg, 1) AS xg "
                    "FROM us_soccer.nwsl.current_player_stats ORDER BY goals DESC LIMIT 10",
                )
            ),
        ),
        column_comments=column_comments(nwsl.PLAYER_STATS_SCHEMA),
        constraints=_key_constraints("nwsl", "current_player_stats", ("player_id",)),
        cardinality_estimate=480,
    ),
    Table(
        name="current_matches",
        function=NwslCurrentMatchesFunction,
        comment="Current NWSL season fixtures and results, one row per match",
        tags=_table_tags(
            provider="nwsl",
            category="schedule",
            title="Current NWSL Matches",
            keywords=["NWSL", "schedule", "fixtures", "results", "scores", "playoffs"],
            llm=(
                "Every match of the current NWSL season, regular season and playoffs, with kickoff time, "
                "status, teams, and score. Use nwsl.matches() for another season."
            ),
            md="Fixtures and results for the current NWSL season. Scores are NULL until kickoff.",
            examples=_examples(
                (
                    "Most recent NWSL results.",
                    "SELECT match_time, home_team_name, home_score, away_score, away_team_name "
                    "FROM us_soccer.nwsl.current_matches WHERE status = 'FINISHED' "
                    "ORDER BY match_time DESC LIMIT 10",
                )
            ),
        ),
        column_comments=column_comments(nwsl.MATCHES_SCHEMA),
        constraints=_key_constraints("nwsl", "current_matches", ("match_id",)),
        cardinality_estimate=250,
    ),
    Table(
        name="competitions",
        function=NwslCompetitionsFunction,
        comment="Competitions on the NWSL Sports Data Platform",
        tags=_table_tags(
            provider="nwsl",
            category="reference",
            title="NWSL Competitions",
            keywords=["competitions", "Challenge Cup", "Summer Cup", "NWSL"],
            llm=(
                "Competitions the NWSL platform publishes: the NWSL league, Challenge Cup, Summer Cup, and "
                "international tournaments involving NWSL players. competition_name is accepted by the "
                "competition argument of nwsl functions."
            ),
            md=(
                "Competition names and opaque identifiers on the NWSL platform. Pass a name such as "
                "`NWSL Challenge Cup` as the `competition` argument of `nwsl.seasons()` and friends."
            ),
            examples=_examples(
                (
                    "Every NWSL-branded competition.",
                    "SELECT competition_name FROM us_soccer.nwsl.competitions "
                    "WHERE competition_name LIKE 'NWSL%' ORDER BY 1",
                )
            ),
        ),
        column_comments=column_comments(nwsl.COMPETITIONS_SCHEMA),
        constraints=_key_constraints("nwsl", "competitions", ("competition_id",)),
        cardinality_estimate=20,
    ),
]

_EXECUTABLE_EXAMPLES = json.dumps(
    [
        {
            "name": "mls_current_standings_are_populated",
            "description": "The current MLS table contains club rows with stable identifiers.",
            "sql": (
                "SELECT count(*) > 0 AND count(club_id) = count(*) AS populated "
                "FROM us_soccer.mls.current_standings"
            ),
            "expected_result": [{"populated": True}],
        },
        {
            "name": "mls_historical_match_result",
            "description": "FC Cincinnati lost 0-2 at home to Columbus Crew on 18 October 2026.",
            "sql": (
                "SELECT home_club_abbreviation, home_goals, away_goals, away_club_abbreviation "
                "FROM us_soccer.mls.match('MLS-MAT-0009NL')"
            ),
            "expected_result": [
                {
                    "home_club_abbreviation": "CIN",
                    "home_goals": 0,
                    "away_goals": 2,
                    "away_club_abbreviation": "CLB",
                }
            ],
        },
        {
            "name": "mls_2025_has_thirty_clubs",
            "description": "The final 2025 MLS regular-season table has 30 clubs.",
            "sql": "SELECT count(*) AS clubs FROM us_soccer.mls.standings(season := 2025)",
            "expected_result": [{"clubs": 30}],
        },
        {
            "name": "nwsl_2025_has_fourteen_teams",
            "description": "The final 2025 NWSL table has 14 teams.",
            "sql": "SELECT count(*) AS teams FROM us_soccer.nwsl.standings(season := 2025)",
            "expected_result": [{"teams": 14}],
        },
        {
            "name": "asa_2025_mls_team_xg",
            "description": "ASA publishes 2025 team xG for all 30 MLS clubs.",
            "sql": "SELECT count(*) AS teams FROM us_soccer.asa.xg_teams(season := 2025)",
            "expected_result": [{"teams": 30}],
        },
    ]
)

_AGENT_TEST_TASKS = json.dumps(
    [
        {
            "name": "mls_table_leader",
            "prompt": "Which club is top of the current MLS regular-season table, and with how many points?",
        },
        {
            "name": "mls_2025_golden_boot",
            "prompt": "Who scored the most MLS regular-season goals in 2025, and for which club?",
        },
        {
            "name": "mls_match_summary",
            "prompt": (
                "Summarize MLS match MLS-MAT-0009NL (FC Cincinnati vs Columbus Crew, 18 October 2026): "
                "the score, who scored, and which side created more expected goals."
            ),
        },
        {
            "name": "mls_match_lineups",
            "prompt": (
                "List Columbus Crew's starting eleven in MLS match MLS-MAT-0009NL and the commentary "
                "lines describing shots."
            ),
        },
        {
            "name": "mls_messi_log",
            "prompt": (
                "Using his match log, how many MLS regular-season goals did Lionel Messi (MLS player id "
                "MLS-OBJ-000396) score in 2025, and in how many matches?"
            ),
        },
        {
            "name": "mls_next_pro_2025",
            "prompt": "Which club finished top of MLS NEXT Pro in 2025, and how many goals did it score?",
        },
        {
            "name": "nwsl_2025_table",
            "prompt": "Which team topped the 2025 NWSL regular-season standings, and with how many points?",
        },
        {
            "name": "nwsl_2026_scorer",
            "prompt": (
                "Who was the top scorer of the 2026 NWSL season, is she on her team's 2026 roster, and who "
                "scored the first goal of the season opener between Washington Spirit and Portland Thorns?"
            ),
        },
        {
            "name": "asa_xg_overperformer",
            "prompt": (
                "Using American Soccer Analysis data, which 2025 MLS player with at least 1500 minutes "
                "beat their expected goals by the most?"
            ),
        },
        {
            "name": "nwsl_2025_goal_share",
            "prompt": (
                "In the 2025 NWSL regular season, which player scored the largest share of her own team's "
                "goals? Name the player and team, her goals, the team's goals, and the share."
            ),
        },
        {
            "name": "asa_2025_bargain_gplus",
            "prompt": (
                "Among 2025 MLS players with at least 1500 regular-season minutes whose guaranteed "
                "compensation in the latest 2025 salary release was under $150,000, who had the highest "
                "goals added (g+) above average according to American Soccer Analysis?"
            ),
        },
        {
            "name": "asa_top_salary",
            "prompt": (
                "Which MLS player had the highest guaranteed compensation in 2025, and what was his goals "
                "added (g+)?"
            ),
        },
    ]
)

_CATEGORIES = [
    ("standings", "Standings", "League tables and records.", ["standings", "table", "points"]),
    ("player-stats", "Player Statistics", "Season and per-match player lines.", ["players", "goals"]),
    ("club-stats", "Clubs", "Club directories and season club statistics.", ["clubs", "xG"]),
    ("team-stats", "Teams", "Team directories, rosters, and season team statistics.", ["teams", "roster"]),
    ("schedule", "Schedule and Scores", "Fixtures and results.", ["schedule", "results", "scores"]),
    ("match-detail", "Match Detail", "Lineups, events, commentary, box scores.", ["match", "events"]),
    ("reference", "Reference", "Competitions and seasons.", ["competitions", "seasons"]),
]


def _categories(names: set[str]) -> str:
    return json.dumps(
        [
            {"name": name, "title": title, "description": text, "keywords": keywords}
            for name, title, text, keywords in _CATEGORIES
            if name in names
        ]
    )


US_SOCCER_CATALOG = Catalog(
    name=CATALOG_NAME,
    default_schema="mls",
    source_url=SOURCE_URL,
    comment="Read-only MLS, NWSL, and American Soccer Analysis data for US professional soccer",
    tags={
        "provider": "query-farm",
        "domain": "sports",
        "vgi.title": "US Professional Soccer Data",
        "vgi.subtitle": "MLS, NWSL, NEXT Pro, and USL standings, schedules, stats, and xG as SQL tables.",
        "vgi.source_url": SOURCE_URL,
        "vgi.author": "Query Farm LLC <hello@query.farm>",
        "vgi.copyright": (
            "Worker (c) 2026 Query Farm LLC. MLS data (c) Major League Soccer, L.L.C.; NWSL data (c) "
            "National Women's Soccer League, LLC and Opta; both are used subject to their owners' terms. "
            "American Soccer Analysis data is licensed CC BY-SA 4.0."
        ),
        "vgi.license": "MIT",
        "vgi.support_contact": "https://github.com/Query-farm/vgi-us-soccer/issues",
        "vgi.support_policy_url": "https://github.com/Query-farm/vgi-us-soccer/blob/main/README.md",
        "vgi.keywords": json.dumps(
            ["MLS", "NWSL", "soccer", "football", "xG", "NEXT Pro", "USL", "standings"]
        ),
        "vgi.executable_examples": _EXECUTABLE_EXAMPLES,
        "vgi.agent_test_tasks": _AGENT_TEST_TASKS,
        "vgi.doc_llm": (
            "Read-only US professional soccer data in three schemas. mls: the official MLS Stats API for "
            "MLS, MLS Cup Playoffs, MLS NEXT Pro, Leagues Cup, US Open Cup, Canadian Championship, and "
            "CONCACAF Champions Cup, with standings back to 1996, schedules and scores, club and player "
            "season statistics, and per-match lineups, events, commentary, and box scores keyed by "
            "MLS-MAT- and MLS-OBJ- ids. nwsl: the official NWSL platform with standings, teams, rosters, "
            "team and player statistics, matches, and event feeds; seasons are passed as years. asa: "
            "American Soccer Analysis xG, xA, goals added, and MLS salaries for MLS, NEXT Pro, NWSL, and "
            "the USL leagues (CC BY-SA 4.0, attribute ASA). Start with mls.current_standings, "
            "mls.current_player_stats, nwsl.current_standings, or nwsl.current_player_stats."
        ),
        "vgi.doc_md": (
            "# US professional soccer\n\n"
            "Query MLS, NWSL, and the wider US soccer pyramid directly from SQL.\n\n"
            "## Schemas\n\n"
            "- `mls` uses the official MLS Stats API. It covers MLS, NEXT Pro, and the cups.\n"
            "- `nwsl` uses the official NWSL Sports Data Platform.\n"
            "- `asa` uses American Soccer Analysis for expected goals, goals added, and salaries.\n\n"
            "Every call fetches on demand and nothing is rehosted. Seasons are passed as plain years. "
            "ASA data is CC BY-SA 4.0 and must be attributed to American Soccer Analysis. This worker "
            "is not affiliated with MLS, the NWSL, or ASA."
        ),
    },
    schemas=[
        Schema(
            path=["mls"],
            comment="MLS, MLS NEXT Pro, and North American cup competitions from the MLS Stats API",
            tags={
                "provider": "mls",
                "domain": "sports",
                "vgi.title": "Major League Soccer",
                "vgi.keywords": json.dumps(
                    ["MLS", "NEXT Pro", "Leagues Cup", "US Open Cup", "standings", "xG"]
                ),
                "vgi.categories": _categories(
                    {"standings", "player-stats", "club-stats", "schedule", "match-detail", "reference"}
                ),
                "vgi.doc_llm": (
                    "Use current_standings, current_player_stats, current_club_stats, and current_schedule "
                    "for the live MLS season. Parameterized functions take season (a year) and competition "
                    "(alias such as next_pro or leagues_cup). Match-level functions take MLS-MAT- ids from "
                    "schedule(); player_match_log takes MLS-OBJ- ids from player_stats()."
                ),
                "vgi.doc_md": (
                    "## MLS Stats API\n\n"
                    "Standings since 1996, schedules, season club and player statistics, and per-match "
                    "lineups, events, commentary, and box scores for MLS-family competitions.\n\n"
                    "Pass `season` as a year and `competition` as an alias from the `competitions` "
                    "table, such as `next_pro` or `leagues_cup`. Match functions take `MLS-MAT-` ids "
                    "from `schedule()`; `player_match_log()` takes `MLS-OBJ-` ids from `player_stats()`."
                ),
                "vgi.example_queries": _examples(
                    *_MLS_STANDINGS_PAIRS, PLAYER_GOAL_SHARE_EXAMPLE, STARTER_BOX_SCORE_EXAMPLE
                ),
            },
            functions=MLS_FUNCTIONS,
            tables=_MLS_TABLES,
        ),
        Schema(
            path=["nwsl"],
            comment="National Women's Soccer League data from the official NWSL Sports Data Platform",
            tags={
                "provider": "nwsl",
                "domain": "sports",
                "vgi.title": "National Women's Soccer League",
                "vgi.keywords": json.dumps(["NWSL", "women's soccer", "standings", "Challenge Cup", "xG"]),
                "vgi.categories": _categories(
                    {"standings", "player-stats", "team-stats", "schedule", "match-detail", "reference"}
                ),
                "vgi.doc_llm": (
                    "Use current_standings, current_player_stats, and current_matches for the live NWSL "
                    "season. Functions take season as a year; the platform's opaque ids are resolved "
                    "automatically. roster() accepts a team acronym such as GFC."
                ),
                "vgi.doc_md": (
                    "## NWSL\n\nStandings, teams, rosters, Opta-derived team and player statistics, "
                    "matches, and match event feeds from the official NWSL Sports Data Platform.\n\n"
                    "Pass `season` as a year; opaque platform ids are resolved automatically. "
                    "`roster()` accepts a team acronym such as `GFC`."
                ),
                "vgi.example_queries": _examples(
                    (
                        "The current NWSL table.",
                        "SELECT position, team_name, points FROM us_soccer.nwsl.current_standings "
                        "ORDER BY position",
                    ),
                    TOP_SCORER_BY_TEAM_EXAMPLE,
                ),
            },
            functions=NWSL_FUNCTIONS,
            tables=_NWSL_TABLES,
        ),
        Schema(
            path=["asa"],
            comment="American Soccer Analysis advanced metrics (CC BY-SA 4.0) for MLS, NWSL, and USL",
            tags={
                "provider": "american-soccer-analysis",
                "domain": "sports",
                "vgi.title": "American Soccer Analysis",
                "vgi.keywords": json.dumps(["xG", "expected goals", "goals added", "g+", "salaries", "USL"]),
                "vgi.license": "CC-BY-SA-4.0",
                "vgi.copyright": asa.ATTRIBUTION,
                "vgi.categories": json.dumps(
                    [
                        {
                            "name": "expected-goals",
                            "title": "Expected Goals",
                            "description": "Player, team, and game xG and xA.",
                            "keywords": ["xG", "xA", "expected points"],
                        },
                        {
                            "name": "goals-added",
                            "title": "Goals Added",
                            "description": "ASA's g+ possession-value model by action type.",
                            "keywords": ["g+", "goals added", "possession value"],
                        },
                        {
                            "name": "salaries",
                            "title": "Salaries",
                            "description": "MLS Players Association salary releases.",
                            "keywords": ["salary", "compensation", "MLSPA"],
                        },
                        {
                            "name": "reference",
                            "title": "Reference",
                            "description": "ASA team directory.",
                            "keywords": ["teams"],
                        },
                    ]
                ),
                "vgi.doc_llm": (
                    "Advanced metrics from American Soccer Analysis. Every function takes league (mls, "
                    "mlsnp, nwsl, uslc, usl1, usls, nasl) and season (a year). Player functions are at "
                    "player-team grain and accept minimum_minutes. salaries() is MLS-only. Data is "
                    "CC BY-SA 4.0: attribute American Soccer Analysis and share derived data alike."
                ),
                "vgi.doc_md": (
                    "## American Soccer Analysis\n\n"
                    "Expected goals, expected assists, goals added (g+), and MLS salaries. Licensed "
                    "[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/); attribute "
                    "American Soccer Analysis.\n\n"
                    "Every function takes `league` (`mls`, `mlsnp`, `nwsl`, `uslc`, `usl1`, `usls`, "
                    "`nasl`) and `season`. Player metrics are at player-team grain and accept "
                    "`minimum_minutes`; `stage` selects regular season, playoffs, or all games."
                ),
                "vgi.example_queries": _examples(
                    (
                        "2025 MLS teams by expected goal difference.",
                        "SELECT team_name, round(xgoal_difference, 1) AS xgd "
                        "FROM us_soccer.asa.xg_teams(season := 2025) ORDER BY xgd DESC",
                    ),
                    GPLUS_PER_SALARY_EXAMPLE,
                ),
            },
            functions=ASA_FUNCTIONS,
        ),
    ],
)


class UsSoccerWorker(Worker):
    """Worker process hosting the read-only US soccer catalog."""

    catalog = US_SOCCER_CATALOG


def main() -> None:
    """Run over stdio by default, or HTTP when VGI's ``--http`` flag is supplied."""
    UsSoccerWorker.main()


def main_http() -> None:
    """Run HTTP with production-safe configuration requirements."""
    if not os.environ.get("VGI_SIGNING_KEY"):
        raise SystemExit(
            "VGI_SIGNING_KEY is required for HTTP mode so state remains valid across restarts and replicas"
        )
    auth_configured = bool(os.environ.get("VGI_BEARER_TOKENS") or os.environ.get("VGI_JWT_ISSUER"))
    auth_configured = auth_configured or os.environ.get("VGI_PROXY_PROOF_MODE", "").lower() == "require"
    if not auth_configured and os.environ.get("VGI_ALLOW_ANONYMOUS") != "1":
        raise SystemExit(
            "HTTP authentication is required; configure bearer/JWT/proxy proof, or explicitly set "
            "VGI_ALLOW_ANONYMOUS=1 for an intentionally public deployment"
        )
    argv = sys.argv[1:]
    if "--http" not in argv:
        argv = ["--http", *argv]
    if "--describe" not in argv and "--no-describe" not in argv:
        argv = ["--no-describe", *argv]
    if not any(value == "--cors-origins" or value.startswith("--cors-origins=") for value in argv):
        argv = ["--cors-origins", "", *argv]
    sys.argv = [sys.argv[0], *argv]
    UsSoccerWorker.main()
