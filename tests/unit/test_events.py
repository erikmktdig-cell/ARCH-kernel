"""Unit tests for immutable event contracts."""

from datetime import UTC, datetime, timedelta, timezone
from typing import Any, cast

import pytest
from pydantic import ValidationError

from arch_kernel.contracts import (
    ActorType,
    EventActor,
    EventEnvelope,
    EventId,
    ProjectId,
    SemanticVersion,
    TypedReference,
)

_EVENT_ID = EventId.from_str("EVT-01HZX7M3FQ1T2Q9V8Y6K4C2B1G")
_CORRELATION_ID = EventId.from_str("EVT-01HZX7M3FQ1T2Q9V8Y6K4C2B1H")
_PROJECT_ID = ProjectId.from_str("PRJ-01HZX7M3FQ1T2Q9V8Y6K4C2B1A")
_CREATED_AT = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)


def _metadata(contract_name: str, *, updated_at: datetime | None = None) -> dict[str, object]:
    return {
        "contract_name": contract_name,
        "contract_version": SemanticVersion.parse("1.0.0"),
        "schema_uri": f"urn:arch:contracts:{contract_name}:1.0.0",
        "created_at": _CREATED_AT,
        "updated_at": updated_at,
    }


def _actor(**changes: object) -> EventActor:
    values = {
        **_metadata("event_actor"),
        "actor_type": ActorType.SYSTEM,
        "actor_id": "arch-kernel",
        "display_name": "ARch Kernel",
        **changes,
    }
    return EventActor.model_validate(values)


def _event(**changes: object) -> EventEnvelope:
    values = {
        **_metadata("event_envelope"),
        "event_id": _EVENT_ID,
        "event_type": "project.phase.activated",
        "project_id": _PROJECT_ID,
        "aggregate": TypedReference(target_type="project", target_id=_PROJECT_ID),
        "occurred_at": _CREATED_AT,
        "recorded_at": _CREATED_AT + timedelta(seconds=1),
        "actor": _actor(),
        "correlation_id": None,
        "causation_id": None,
        "idempotency_key": "phase-activation:001",
        "schema_version": SemanticVersion.parse("1.0.0"),
        "payload": {"phase": "F02", "active": True, "attempt": 1},
        **changes,
    }
    return EventEnvelope.model_validate(values)


def test_event_envelope_constructs_directly_and_generates_strict_schema() -> None:
    event = _event()
    schema = EventEnvelope.model_json_schema()

    assert event.event_id == _EVENT_ID
    assert schema["additionalProperties"] is False
    assert {"event_id", "aggregate", "payload", "schema_version"} <= set(schema["required"])


def test_event_envelope_parses_json_and_round_trips_without_loss() -> None:
    original = _event()

    restored = EventEnvelope.model_validate_json(original.model_dump_json())

    assert restored == original
    assert restored.model_dump(mode="json") == original.model_dump(mode="json")
    assert restored.canonical_json() == original.canonical_json()


def test_event_envelope_and_payload_are_recursively_immutable() -> None:
    event = _event(
        payload={
            "status": "created",
            "nested": {"value": 1},
            "items": ["first"],
        }
    )
    payload = cast(Any, event.payload)
    mutable_event = cast(Any, event)

    with pytest.raises(ValidationError, match="Instance is frozen"):
        event.event_type = "project.phase.completed"
    with pytest.raises(ValidationError, match="Instance is frozen"):
        mutable_event.payload = {}
    with pytest.raises(TypeError):
        payload["status"] = "changed"
    with pytest.raises(TypeError):
        payload["nested"]["value"] = 2
    with pytest.raises(AttributeError):
        payload["items"].append("x")


def test_event_payload_is_defensively_copied() -> None:
    payload: dict[str, Any] = {"nested": [{"value": "original"}]}
    event = _event(payload=payload)

    payload["nested"][0]["value"] = "changed"

    assert event.payload == {"nested": [{"value": "original"}]}


def test_event_payload_dumps_as_normal_json_objects_and_arrays() -> None:
    event = _event(payload={"nested": {"value": 1}, "items": ["first", None]})

    dumped = event.model_dump(mode="json")

    assert isinstance(dumped["payload"], dict)
    assert isinstance(dumped["payload"]["nested"], dict)
    assert isinstance(dumped["payload"]["items"], list)
    assert dumped["payload"] == {
        "nested": {"value": 1},
        "items": ["first", None],
    }


def test_event_fingerprint_remains_stable_after_payload_access() -> None:
    event = _event(payload={"nested": {"value": 1}, "items": ["first"]})
    before = (event.record_fingerprint(), event.contract_content_fingerprint())

    assert event.payload["nested"] == {"value": 1}
    assert event.payload["items"] == ("first",)

    assert (event.record_fingerprint(), event.contract_content_fingerprint()) == before


def test_event_actor_validates_identity_fields() -> None:
    assert _actor(actor_id="System/Primary").actor_id == "System/Primary"

    with pytest.raises(ValidationError, match="without surrounding whitespace"):
        _actor(actor_id=" actor")
    with pytest.raises(ValidationError, match="1 to 200"):
        _actor(actor_id="x" * 201)
    with pytest.raises(ValidationError, match="display_name cannot be empty"):
        _actor(display_name="   ")


def test_event_timestamps_normalize_offsets_to_utc() -> None:
    offset = timezone(timedelta(hours=-6))
    event = _event(
        occurred_at=datetime(2026, 7, 23, 6, 0, tzinfo=offset),
        recorded_at=datetime(2026, 7, 23, 6, 1, tzinfo=offset),
    )

    assert event.occurred_at == datetime(2026, 7, 23, 12, 0, tzinfo=UTC)
    assert event.recorded_at == datetime(2026, 7, 23, 12, 1, tzinfo=UTC)
    assert event.model_dump(mode="json")["occurred_at"].endswith("Z")


def test_event_timestamps_reject_naive_values_and_allow_equality() -> None:
    with pytest.raises(ValidationError, match="Naive datetimes"):
        _event(occurred_at=datetime(2026, 7, 23, 12, 0))

    equal = _event(occurred_at=_CREATED_AT, recorded_at=_CREATED_AT)
    assert equal.recorded_at == equal.occurred_at


def test_event_rejects_reverse_timestamp_order() -> None:
    with pytest.raises(ValidationError, match="recorded_at must be greater"):
        _event(recorded_at=_CREATED_AT - timedelta(seconds=1))


def test_event_supports_root_correlated_and_caused_events() -> None:
    root = _event()
    correlated = _event(correlation_id=_CORRELATION_ID)
    caused = _event(correlation_id=_CORRELATION_ID, causation_id=_CORRELATION_ID)

    assert root.correlation_id is None
    assert correlated.causation_id is None
    assert caused.correlation_id == caused.causation_id


def test_event_rejects_causal_self_reference_and_missing_correlation() -> None:
    with pytest.raises(ValidationError, match="correlation_id cannot"):
        _event(correlation_id=_EVENT_ID)
    with pytest.raises(ValidationError, match="causation_id cannot"):
        _event(correlation_id=_CORRELATION_ID, causation_id=_EVENT_ID)
    with pytest.raises(ValidationError, match="requires correlation_id"):
        _event(causation_id=_CORRELATION_ID)


def test_event_rejects_aggregate_self_reference() -> None:
    aggregate = TypedReference(target_type="event", target_id=_EVENT_ID)

    with pytest.raises(ValidationError, match="aggregate cannot reference"):
        _event(aggregate=aggregate)


def test_event_fingerprints_follow_k02_semantics() -> None:
    first = _event()
    reordered = _event(payload={"attempt": 1, "active": True, "phase": "F02"})
    payload_changed = _event(payload={"phase": "F03", "active": True, "attempt": 1})
    metadata_changed = _event(updated_at=_CREATED_AT + timedelta(minutes=5))

    assert first.record_fingerprint() == _event().record_fingerprint()
    assert first.record_fingerprint() == reordered.record_fingerprint()
    assert first.contract_content_fingerprint() == reordered.contract_content_fingerprint()
    assert first.record_fingerprint() != payload_changed.record_fingerprint()
    assert first.contract_content_fingerprint() != payload_changed.contract_content_fingerprint()
    assert first.record_fingerprint() != metadata_changed.record_fingerprint()
    assert first.contract_content_fingerprint() == metadata_changed.contract_content_fingerprint()
