"""Value coercion and metadata helpers."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

import pyarrow as pa
import pytest

from vgi_us_soccer import meta


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, None), (True, None), ("", None), ("7", 7), (" 7 ", 7), (3.0, 3), (3.5, None), ("x", None)],
)
def test_to_int(value, expected) -> None:
    assert meta.to_int(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        (False, None),
        ("", None),
        ("1.5", 1.5),
        (2, 2.0),
        ("nan", None),
        ("inf", None),
        ("x", None),
    ],
)
def test_to_float(value, expected) -> None:
    assert meta.to_float(value) == expected


def test_to_bool_str_and_names() -> None:
    assert meta.to_bool("true") is True
    assert meta.to_bool("False") is False
    assert meta.to_bool(True) is True
    assert meta.to_bool("maybe") is None
    assert meta.to_bool(1) is None
    assert meta.to_str("  ") is None
    assert meta.to_str({"a": 1}) is None
    assert meta.to_str(5) == "5"
    assert meta.join_name(" Leo", None, "", "Messi ") == "Leo Messi"
    assert meta.join_name(None, "") is None


def test_timestamps_and_dates() -> None:
    assert meta.to_timestamp("2026-10-18T21:00:00Z") == datetime(2026, 10, 18, 21, tzinfo=UTC)
    assert meta.to_timestamp("2026-11-08 00:00:00 UTC") == datetime(2026, 11, 8, tzinfo=UTC)
    assert meta.to_timestamp("2026-03-13T20:00:00") == datetime(2026, 3, 13, 20, tzinfo=UTC)
    assert meta.to_timestamp("not a time") is None
    assert meta.to_timestamp(None) is None
    assert meta.to_date("2026-04-16") == date(2026, 4, 16)
    assert meta.to_date("2026-13-40") is None
    assert meta.to_date("") is None


def test_records_and_mapping() -> None:
    assert meta.records([{"a": 1}, 2, None]) == [{"a": 1}]
    assert meta.records("x") == []
    assert meta.mapping([1]) == {}


def test_result_columns_schema_and_comments() -> None:
    schema = pa.schema(
        [
            meta.field("a", pa.int32(), "An integer."),
            meta.field("b", pa.int64(), "A big integer."),
            meta.field("c", pa.float64(), "A double."),
            meta.field("d", pa.string(), "Text."),
            meta.field("e", pa.bool_(), "Flag."),
            meta.field("f", pa.date32(), "Day."),
            meta.field("g", meta.TIMESTAMP, "Instant."),
            meta.field("h", pa.timestamp("us"), "Local instant."),
            pa.field("i", pa.string()),
        ]
    )
    rendered = json.loads(meta.result_columns_schema(schema))
    assert [column["type"] for column in rendered] == [
        "INTEGER",
        "BIGINT",
        "DOUBLE",
        "VARCHAR",
        "BOOLEAN",
        "DATE",
        "TIMESTAMP WITH TIME ZONE",
        "TIMESTAMP",
        "VARCHAR",
    ]
    assert rendered[0]["description"] == "An integer"
    assert "i" not in meta.column_comments(schema)
    with pytest.raises(ValueError, match="Unsupported"):
        meta.result_columns_schema(pa.schema([pa.field("x", pa.list_(pa.int32()))]))
