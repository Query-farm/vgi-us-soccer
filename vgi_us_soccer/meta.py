"""Metadata and value-coercion helpers shared by every schema in the catalog."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from typing import Any

import pyarrow as pa

_COMMENT_KEY = b"comment"

TIMESTAMP = pa.timestamp("us", tz="UTC")


def field(name: str, kind: pa.DataType, comment: str, *, nullable: bool = True) -> pa.Field:
    """Build an Arrow field carrying its SQL column comment."""
    return pa.field(name, kind, nullable=nullable, metadata={_COMMENT_KEY: comment.encode()})


def comment_of(value: pa.Field) -> str:
    """Return the comment stored on an Arrow field."""
    if value.metadata and _COMMENT_KEY in value.metadata:
        return value.metadata[_COMMENT_KEY].decode()
    return ""


def column_comments(schema: pa.Schema) -> dict[str, str]:
    """Return the column-comment mapping expected by a catalog table."""
    return {value.name: comment_of(value) for value in schema if comment_of(value)}


def _sql_type(kind: pa.DataType) -> str:
    if pa.types.is_timestamp(kind):
        return "TIMESTAMP WITH TIME ZONE" if kind.tz else "TIMESTAMP"
    if pa.types.is_date(kind):
        return "DATE"
    if pa.types.is_boolean(kind):
        return "BOOLEAN"
    if pa.types.is_int32(kind):
        return "INTEGER"
    if pa.types.is_int64(kind):
        return "BIGINT"
    if pa.types.is_float64(kind):
        return "DOUBLE"
    if pa.types.is_string(kind):
        return "VARCHAR"
    raise ValueError(f"Unsupported result type: {kind}")


def result_columns_schema(schema: pa.Schema) -> str:
    """Render a static Arrow result schema as VGI discovery metadata."""
    return json.dumps(
        [
            {
                "name": value.name,
                "type": _sql_type(value.type),
                "description": comment_of(value).removesuffix("."),
            }
            for value in schema
        ],
        separators=(",", ":"),
    )


def mapping(value: Any) -> Mapping[str, Any]:
    """Return ``value`` when it is a mapping, otherwise an empty mapping."""
    return value if isinstance(value, Mapping) else {}


def records(value: Any) -> list[Mapping[str, Any]]:
    """Return the mapping elements of a list, ignoring malformed entries."""
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def to_int(value: Any) -> int | None:
    """Parse an integer-like API value without treating booleans as integers."""
    if value is None or isinstance(value, bool) or value == "":
        return None
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError, OverflowError):
        return None


def to_float(value: Any) -> float | None:
    """Parse a finite floating-point value."""
    if value is None or isinstance(value, bool) or value == "":
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if result == result and result not in (float("inf"), float("-inf")) else None


def to_bool(value: Any) -> bool | None:
    """Parse booleans that upstream APIs sometimes encode as strings."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "1"}:
            return True
        if lowered in {"false", "no", "0"}:
            return False
    return None


def to_str(value: Any) -> str | None:
    """Return a non-empty string, mapping blanks to null."""
    if value is None or isinstance(value, (dict, list)):
        return None
    text = str(value).strip()
    return text or None


def to_timestamp(value: Any) -> datetime | None:
    """Parse an ISO-8601 or ``YYYY-MM-DD HH:MM:SS UTC`` timestamp into UTC."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith(" UTC"):
        text = text.removesuffix(" UTC") + "+00:00"
    text = text.replace("Z", "+00:00")
    try:
        result = datetime.fromisoformat(text)
    except (ValueError, OverflowError):
        return None
    if result.tzinfo is None:
        result = result.replace(tzinfo=UTC)
    return result.astimezone(UTC)


def to_date(value: Any) -> date | None:
    """Parse a ``YYYY-MM-DD`` prefix into a date."""
    if not isinstance(value, str) or len(value) < 10:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def join_name(*parts: Any) -> str | None:
    """Join non-empty name parts with a single space."""
    text = " ".join(str(part).strip() for part in parts if isinstance(part, str) and part.strip())
    return text or None


def batch_from_rows(rows: Sequence[Mapping[str, Any]], schema: pa.Schema) -> pa.RecordBatch:
    """Build a record batch in the declared column order, projecting to ``schema``."""
    return pa.RecordBatch.from_arrays(
        [pa.array([row.get(value.name) for row in rows], type=value.type) for value in schema],
        schema=schema,
    )
