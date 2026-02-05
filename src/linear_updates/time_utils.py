from __future__ import annotations

from datetime import UTC, datetime


def parse_linear_datetime(value: str) -> datetime:
    # Linear typically returns ISO 8601 timestamps like "2024-01-31T12:34:56.789Z".
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def to_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC).isoformat()
    return dt.isoformat()
