"""Unit tests for pure event validation helpers."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from arch_kernel.contracts import EventId
from arch_kernel.kernel import (
    ErrorCode,
    EventValidationError,
    validate_event_causality,
    validate_event_temporal_order,
    validate_event_type,
    validate_idempotency_key,
    validate_json_object,
)

_EVENT_ID = EventId.from_str("EVT-01HZX7M3FQ1T2Q9V8Y6K4C2B1G")
_OTHER_EVENT_ID = EventId.from_str("EVT-01HZX7M3FQ1T2Q9V8Y6K4C2B1H")


@pytest.mark.parametrize(
    "value",
    ["project.phase.activated", "artifact.review.requested", "a.b.c", "risk_v2.item_1.accepted"],
)
def test_validate_event_type_accepts_canonical_values(value: str) -> None:
    assert validate_event_type(value) == value


@pytest.mark.parametrize(
    "value",
    ["Project.phase.activated", "project.phase", "project..activated", "project.phase.a-b"],
)
def test_validate_event_type_rejects_invalid_values(value: str) -> None:
    with pytest.raises(EventValidationError) as exc_info:
        validate_event_type(value)

    assert exc_info.value.detail.code == ErrorCode.INVALID_EVENT_TYPE
    assert exc_info.value.detail.path == ("event_type",)


def test_validate_event_type_rejects_excessive_length() -> None:
    with pytest.raises(EventValidationError):
        validate_event_type(f"domain.entity.{'a' * 150}")


@pytest.mark.parametrize(
    "value",
    ["retry:001", "Project/Event-42", "abc.def_1", "A2345678", "x" * 200],
)
def test_validate_idempotency_key_accepts_and_preserves_safe_ascii(value: str) -> None:
    assert validate_idempotency_key(value) == value


@pytest.mark.parametrize(
    "value",
    ["short", " leading-key", "trailing-key ", "internal key", "unsafe@key", "x" * 201],
)
def test_validate_idempotency_key_rejects_invalid_values(value: str) -> None:
    with pytest.raises(EventValidationError) as exc_info:
        validate_idempotency_key(value)

    assert exc_info.value.detail.code == ErrorCode.INVALID_IDEMPOTENCY_KEY


def test_validate_json_object_copies_nested_json_without_mutating_input() -> None:
    payload: dict[str, Any] = {
        "active": True,
        "attempt": 2,
        "ratio": 0.5,
        "note": None,
        "items": [{"name": "draft"}],
    }

    copied = validate_json_object(payload)
    payload["items"][0]["name"] = "approved"

    assert copied["items"] == [{"name": "draft"}]


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"key": (1, 2)},
        {"key": b"bytes"},
        {"key": {1, 2}},
        {"key": datetime(2026, 7, 23, tzinfo=UTC)},
        {"key": object()},
        {1: "non-string"},
        {"key": float("nan")},
        {"key": float("inf")},
        {"key": float("-inf")},
    ],
)
def test_validate_json_object_rejects_non_json_values(payload: object) -> None:
    with pytest.raises(EventValidationError) as exc_info:
        validate_json_object(payload)

    assert exc_info.value.detail.code == ErrorCode.INVALID_EVENT_PAYLOAD
    assert exc_info.value.detail.path[0] == "payload"


def test_validate_event_temporal_order_allows_equality_and_delay() -> None:
    occurred_at = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)

    validate_event_temporal_order(occurred_at, occurred_at)
    validate_event_temporal_order(occurred_at, occurred_at + timedelta(days=30))


def test_validate_event_temporal_order_rejects_reverse_order() -> None:
    recorded_at = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)

    with pytest.raises(EventValidationError) as exc_info:
        validate_event_temporal_order(recorded_at + timedelta(microseconds=1), recorded_at)

    assert exc_info.value.detail.code == ErrorCode.INVALID_EVENT_TIMESTAMP_ORDER


def test_validate_event_causality_accepts_supported_shapes() -> None:
    validate_event_causality(_EVENT_ID, None, None)
    validate_event_causality(_EVENT_ID, _OTHER_EVENT_ID, None)
    validate_event_causality(_EVENT_ID, _OTHER_EVENT_ID, _OTHER_EVENT_ID)


def test_validate_event_causality_rejects_self_references() -> None:
    with pytest.raises(EventValidationError, match="correlation_id cannot"):
        validate_event_causality(_EVENT_ID, _EVENT_ID, None)

    with pytest.raises(EventValidationError, match="causation_id cannot"):
        validate_event_causality(_EVENT_ID, _OTHER_EVENT_ID, _EVENT_ID)


def test_validate_event_causality_requires_correlation_for_causation() -> None:
    with pytest.raises(EventValidationError, match="requires correlation_id"):
        validate_event_causality(_EVENT_ID, None, _OTHER_EVENT_ID)
