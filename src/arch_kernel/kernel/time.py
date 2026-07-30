"""UTC normalization utilities for contract timestamps."""

from __future__ import annotations

from datetime import UTC, datetime


def ensure_utc(value: datetime) -> datetime:
    """Return an aware datetime normalized to UTC.

    Naive values are rejected because their offset cannot be inferred
    deterministically. Canonical JSON represents UTC using ``+00:00``.
    """

    if not isinstance(value, datetime):
        raise TypeError("Timestamp values must be datetime instances.")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Naive datetimes are not allowed; provide an explicit timezone.")
    return value.astimezone(UTC)


def utc_now() -> datetime:
    """Return the current timezone-aware UTC timestamp."""

    return datetime.now(UTC)


__all__ = ("ensure_utc", "utc_now")
