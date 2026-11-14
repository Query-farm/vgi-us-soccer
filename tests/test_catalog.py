"""Tests for the SQL-facing catalog shape and discovery metadata."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from vgi_us_soccer import asa_functions, mls_functions, nwsl_functions
from vgi_us_soccer.worker import US_SOCCER_CATALOG

ROOT = Path(__file__).resolve().parent.parent
SCHEMAS = {schema.path[0]: schema for schema in US_SOCCER_CATALOG.schemas}
ALL_FUNCTIONS = [function for schema in US_SOCCER_CATALOG.schemas for function in schema.functions]


def test_catalog_surface() -> None:
    assert US_SOCCER_CATALOG.name == "us_soccer"
    assert US_SOCCER_CATALOG.default_schema == "mls"
    assert set(SCHEMAS) == {"mls", "nwsl", "asa"}
    assert {table.name for table in SCHEMAS["mls"].tables} == {
        "current_standings",
        "current_player_stats",
        "current_club_stats",
        "current_schedule",
        "competitions",
    }
    assert {table.name for table in SCHEMAS["nwsl"].tables} == {
        "current_standings",
        "current_player_stats",
        "current_matches",
        "competitions",
    }
    assert SCHEMAS["asa"].tables == ()
    assert {function.Meta.name for function in SCHEMAS["mls"].functions} == {
        "all_competitions",
        "seasons",
        "standings",
        "all_current_standings",
        "clubs",
        "club_stats",
        "all_current_club_stats",
        "player_stats",
        "all_current_player_stats",
        "player_match_log",
        "schedule",
        "all_current_schedule",
        "match",
        "match_lineups",
        "match_events",
        "match_commentary",
        "match_club_stats",
        "match_player_stats",
    }
    assert {function.Meta.name for function in SCHEMAS["asa"].functions} == {
        "teams",
        "xg_players",
        "goals_added_players",
        "xg_teams",
        "xg_games",
        "salaries",
    }


def test_every_table_is_backed_by_a_parameterless_scan_in_its_schema() -> None:
    for schema in US_SOCCER_CATALOG.schemas:
        for table in schema.tables:
            assert table.function in schema.functions
            assert table.function.Meta.name == f"all_{table.name}"
            assert not table.function.get_metadata().parameters


def _key_of(table, kind: str) -> list[tuple[str, ...]]:
    return [
        tuple(name for path in record.definition.column_paths for name in path)
        for record in table.constraints
        if record.definition.kind == kind
    ]


@pytest.mark.parametrize(
    ("schema", "table", "key"),
    [
        ("mls", "current_standings", ("club_id",)),
        ("mls", "current_player_stats", ("player_id", "club_id")),
        ("mls", "current_club_stats", ("club_id",)),
        ("mls", "current_schedule", ("match_id",)),
        ("mls", "competitions", ("competition_id",)),
        ("nwsl", "current_standings", ("team_id",)),
        ("nwsl", "current_player_stats", ("player_id",)),
        ("nwsl", "current_matches", ("match_id",)),
        ("nwsl", "competitions", ("competition_id",)),
    ],
)
def test_table_keys(schema: str, table: str, key: tuple[str, ...]) -> None:
    declared = next(value for value in SCHEMAS[schema].tables if value.name == table)
    assert _key_of(declared, "PRIMARY_KEY") == [key]
    assert _key_of(declared, "NOT_NULL") == [(column,) for column in key]
    schema_fields = declared.function.FIXED_SCHEMA
    assert all(not schema_fields.field(column).nullable for column in key)


@pytest.mark.parametrize("function", ALL_FUNCTIONS, ids=lambda function: function.Meta.name)
def test_every_function_documents_itself(function) -> None:
    tags = function.Meta.tags
    for key in ("vgi.title", "vgi.doc_llm", "vgi.doc_md", "vgi.example_queries", "vgi.result_columns_schema"):
        assert tags[key], key
    columns = json.loads(tags["vgi.result_columns_schema"])
    assert [column["name"] for column in columns] == function.FIXED_SCHEMA.names
    assert all(column["description"] for column in columns)
    assert len(tags["vgi.result_columns_schema"]) <= 4_000
    examples = json.loads(tags["vgi.example_queries"])
    assert examples and all("us_soccer." in example["sql"] for example in examples)
    assert function.Meta.examples


def test_arguments_are_named_and_optional_except_identifiers() -> None:
    standings = {p.name: p for p in mls_functions.StandingsFunction.get_metadata().parameters}
    assert set(standings) == {"season", "competition", "split"}
    assert not any(p.required for p in standings.values())
    match = mls_functions.MatchFunction.get_metadata().parameters
    assert [p.name for p in match] == ["match_id"] and match[0].required
    roster = {p.name: p for p in nwsl_functions.RosterFunction.get_metadata().parameters}
    assert roster["team"].required and not roster["season"].required
    xg = {p.name for p in asa_functions.XgPlayersFunction.get_metadata().parameters}
    assert xg == {"league", "season", "minimum_minutes", "stage"}


def test_no_argument_uses_a_duckdb_keyword() -> None:
    reserved = {"end", "from", "interval", "to", "order", "group", "limit", "type", "default"}
    for function in ALL_FUNCTIONS:
        names = {parameter.name for parameter in function.get_metadata().parameters}
        assert not names & reserved, function.Meta.name


def test_catalog_discovery_contract_is_public_and_machine_readable() -> None:
    examples = json.loads(US_SOCCER_CATALOG.tags["vgi.executable_examples"])
    tasks = json.loads(US_SOCCER_CATALOG.tags["vgi.agent_test_tasks"])
    assert examples
    assert all({"name", "description", "sql", "expected_result"} <= example.keys() for example in examples)
    assert 6 <= len(tasks) <= 12
    assert all(set(task) == {"name", "prompt"} for task in tasks)
    assert len({task["name"] for task in tasks}) == len(tasks)


# Composed tasks whose answer only the judge can check: check_sql never sees the analyst's answer.
JUDGE_GRADED_TASKS = {"nwsl_2025_goal_share", "asa_2025_bargain_gplus"}


def test_agent_task_sidecar_grades_every_public_task() -> None:
    public = {task["name"] for task in json.loads(US_SOCCER_CATALOG.tags["vgi.agent_test_tasks"])}
    sidecar = yaml.safe_load((ROOT / "vgi-agent-tests.yaml").read_text())["tasks"]
    assert {task["name"] for task in sidecar} == public
    for task in sidecar:
        assert "reference_sql" not in task  # live data: exact compares cannot pass
        if task["name"] in JUDGE_GRADED_TASKS:
            # check_sql would outrank the judge and pass whatever the analyst answered.
            assert "check_sql" not in task
            assert task["success_criteria"].startswith("Pass only if")
        else:
            assert task["check_sql"].strip().upper().startswith("SELECT")


def test_asa_objects_carry_the_cc_by_sa_licence() -> None:
    assert SCHEMAS["asa"].tags["vgi.license"] == "CC-BY-SA-4.0"
    for function in SCHEMAS["asa"].functions:
        assert function.Meta.tags["vgi.license"] == "CC-BY-SA-4.0"
        assert "American Soccer Analysis" in function.Meta.tags["vgi.doc_llm"]


@pytest.mark.parametrize(
    ("schema", "function", "example"),
    [
        ("mls", mls_functions.PlayerStatsFunction, mls_functions.PLAYER_GOAL_SHARE_EXAMPLE),
        ("mls", mls_functions.MatchLineupsFunction, mls_functions.STARTER_BOX_SCORE_EXAMPLE),
        ("nwsl", nwsl_functions.StandingsFunction, nwsl_functions.TOP_SCORER_BY_TEAM_EXAMPLE),
        ("asa", asa_functions.GoalsAddedFunction, asa_functions.GPLUS_PER_SALARY_EXAMPLE),
    ],
)
def test_composed_examples_are_listed_on_the_schema_and_the_driving_function(
    schema: str, function: type, example: tuple[str, str]
) -> None:
    description, sql = example
    schema_examples = json.loads(SCHEMAS[schema].tags["vgi.example_queries"])
    assert {"description": description, "sql": sql} in schema_examples
    function_examples = json.loads(function.Meta.tags["vgi.example_queries"])[:5]
    assert {"description": description, "sql": sql} in function_examples
    assert [(e.description, e.sql) for e in function.Meta.examples][:5].count(example) == 1
    for json_tag in (SCHEMAS[schema].tags["vgi.example_queries"], function.Meta.tags["vgi.example_queries"]):
        assert len(json_tag) <= 8000
