"""Shared plumbing for the catalog's table functions."""

from __future__ import annotations

import json
from typing import Any, ClassVar, Protocol

import pyarrow as pa
from vgi.cache_control import CacheControl
from vgi.table_function import ProcessParams, TableCardinality
from vgi_rpc.rpc import OutputCollector

from vgi_us_soccer.meta import batch_from_rows, result_columns_schema


class _HasRows(Protocol):
    rows: list[dict[str, Any]]
    max_age: int | None


def cache_control(max_age: int | None) -> CacheControl | None:
    """Advertise freshness only when the origin supplied a cacheable max-age."""
    if max_age is None or max_age <= 0:
        return None
    return CacheControl(ttl=max_age)


class Scan:
    """Mixin implementing fetch-then-emit for read-only, single-batch scans.

    Subclasses set ``ESTIMATE`` and ``MAX`` for the planner and implement
    :meth:`fetch`, which returns flattened rows plus advertised freshness.
    """

    ESTIMATE: ClassVar[int] = 100
    MAX: ClassVar[int | None] = None

    @classmethod
    def fetch(cls, args: Any) -> _HasRows:
        """Return the rows for one invocation."""
        raise NotImplementedError

    @classmethod
    def cardinality(cls, params: object) -> TableCardinality:
        """Return the planner's row-count estimate."""
        return TableCardinality(estimate=cls.ESTIMATE, max=cls.MAX)

    @classmethod
    def process(cls, params: ProcessParams[Any], state: None, out: OutputCollector) -> None:
        """Fetch, flatten, and emit one Arrow batch."""
        result = cls.fetch(params.args)
        out.emit(
            batch_from_rows(result.rows, params.output_schema), cache_control=cache_control(result.max_age)
        )
        out.finish()


def tags(
    *,
    provider: str,
    category: str,
    title: str,
    llm: str,
    schema: pa.Schema,
    examples: list[tuple[str, str]],
    md: str | None = None,
) -> dict[str, str]:
    """Discovery tags shared by every function: title, docs, result schema, and examples."""
    return {
        "provider": provider,
        "vgi.category": category,
        "vgi.title": title,
        "vgi.result_columns_schema": result_columns_schema(schema),
        "vgi.doc_llm": llm,
        "vgi.doc_md": md or f"{llm}\n\nTypical use: {examples[0][0][0].lower()}{examples[0][0][1:]}",
        "vgi.example_queries": json.dumps([{"description": text, "sql": sql} for text, sql in examples]),
    }
