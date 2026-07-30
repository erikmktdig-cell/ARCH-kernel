"""Tests for UTC timestamp helpers."""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from arch_kernel.kernel import ensure_utc, utc_now


def test_ensure_utc_converts_an_aware_datetime() -> None:
    source = datetime(2026, 7, 22, 8, 30, tzinfo=timezone(timedelta(hours=-6)))

    normalized = ensure_utc(source)

    assert normalized == datetime(2026, 7, 22, 14, 30, tzinfo=UTC)
    assert normalized.tzinfo is UTC


def test_ensure_utc_rejects_naive_datetimes() -> None:
    with pytest.raises(ValueError, match="Naive datetimes"):
        ensure_utc(datetime(2026, 7, 22, 14, 30))


def test_ensure_utc_rejects_non_datetime_values() -> None:
    with pytest.raises(TypeError, match="datetime instances"):
        ensure_utc("2026-07-22T14:30:00+00:00")  # type: ignore[arg-type]


def test_utc_now_is_aware_and_utc() -> None:
    now = utc_now()

    assert now.tzinfo is UTC
    assert now.utcoffset() == timedelta(0)
