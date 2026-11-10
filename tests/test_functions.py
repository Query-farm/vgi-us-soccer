"""Every table function's fetch-and-emit path, driven through recorded responses."""

from __future__ import annotations

import dataclasses
import typing
from typing import Any

import pyarrow as pa
import pytest
from vgi.arguments import Arg

from vgi_us_soccer import base
from vgi_us_soccer.worker import US_SOCCER_CATALOG

MATCH_IDS = {
    "mls": "MLS-MAT-0009NL",
    "nwsl": "nwsl::Football_Match::834675f37cea4328bece6743d94c7d2d",
}
POSITIONAL = {
    ("mls", "player_match_log"): {"player_id": "MLS-OBJ-000396"},
    ("nwsl", "roster"): {"team": "SEA"},
}


class _Out:
    def __init__(self) -> None:
        self.batches: list[pa.RecordBatch] = []
        self.cache: list[Any] = []
        self.finished = False

    def emit(self, batch: pa.RecordBatch, *, cache_control: Any = None) -> None:
        self.batches.append(batch)
        self.cache.append(cache_control)

    def finish(self) -> None:
        self.finished = True


@dataclasses.dataclass
class _Params:
    args: Any
    output_schema: pa.Schema


def _args(schema: str, function) -> Any:
    """Build the function's argument dataclass from its declared defaults."""
    cls = next(
        (
            arg
            for base_ in function.__orig_bases__
            for arg in getattr(base_, "__args__", ())
            if dataclasses.is_dataclass(arg)
        ),
        None,
    )
    if cls is None:
        return None
    values: dict[str, Any] = {}
    for name, hint in typing.get_type_hints(cls, include_extras=True).items():
        spec = next(meta for meta in hint.__metadata__ if isinstance(meta, Arg))
        values[name] = None if type(spec.default).__name__ == "_MissingType" else spec.default
    if "match_id" in values:
        values["match_id"] = MATCH_IDS[schema]
    values.update(POSITIONAL.get((schema, function.Meta.name), {}))
    if schema == "asa" and "season" in values:
        values["season"] = 2026
    return cls(**values)


CASES = [(schema.path[0], function) for schema in US_SOCCER_CATALOG.schemas for function in schema.functions]


@pytest.mark.parametrize(("schema", "function"), CASES, ids=lambda value: getattr(value, "__name__", value))
def test_function_emits_its_fixed_schema(schema: str, function) -> None:
    out = _Out()
    function.process(_Params(_args(schema, function), function.FIXED_SCHEMA), None, out)
    assert out.finished
    [batch] = out.batches
    assert batch.schema == function.FIXED_SCHEMA
    assert batch.num_rows > 0, function.Meta.name
    cardinality = function.cardinality(None)
    assert cardinality.estimate > 0


def test_projection_emits_only_requested_columns() -> None:
    function = next(
        f for f in US_SOCCER_CATALOG.schemas[0].functions if f.Meta.name == "all_current_standings"
    )
    projected = pa.schema([function.FIXED_SCHEMA.field("club_name"), function.FIXED_SCHEMA.field("points")])
    out = _Out()
    function.process(_Params(None, projected), None, out)
    assert out.batches[0].schema.names == ["club_name", "points"]


def test_cache_control_only_for_positive_max_age() -> None:
    assert base.cache_control(None) is None
    assert base.cache_control(0) is None
    assert base.cache_control(120).ttl == 120
    with pytest.raises(NotImplementedError):
        base.Scan.fetch(None)
