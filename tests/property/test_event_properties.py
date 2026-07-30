"""Property tests for event grammar, payloads, timestamps, and fingerprints."""

from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st
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
from arch_kernel.kernel import EventValidationError, validate_event_type

_SEGMENT = st.from_regex(r"[a-z0-9_]{1,12}", fullmatch=True)
_EVENT_TYPES = st.lists(_SEGMENT, min_size=3, max_size=5).map(".".join)
_JSON_SCALARS = (
    st.none()
    | st.booleans()
    | st.integers()
    | st.floats(allow_nan=False, allow_infinity=False)
    | st.text()
)
_JSON_VALUES = st.recursive(
    _JSON_SCALARS,
    lambda children: (
        st.lists(children, max_size=4) | st.dictionaries(st.text(), children, max_size=4)
    ),
    max_leaves=15,
)
_JSON_OBJECTS = st.dictionaries(st.text(), _JSON_VALUES, max_size=6)
_BASE_TIME = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)
_EVENT_ID = EventId.from_str("EVT-01HZX7M3FQ1T2Q9V8Y6K4C2B1G")
_PROJECT_ID = ProjectId.from_str("PRJ-01HZX7M3FQ1T2Q9V8Y6K4C2B1A")
_VERSION = SemanticVersion.parse("1.0.0")


def _event(payload: dict[str, object], **changes: object) -> EventEnvelope:
    actor = EventActor(
        contract_name="event_actor",
        contract_version=_VERSION,
        schema_uri="urn:arch:contracts:event_actor:1.0.0",
        created_at=_BASE_TIME,
        actor_type=ActorType.SYSTEM,
        actor_id="property-tests",
    )
    values = {
        "contract_name": "event_envelope",
        "contract_version": _VERSION,
        "schema_uri": "urn:arch:contracts:event_envelope:1.0.0",
        "created_at": _BASE_TIME,
        "event_id": _EVENT_ID,
        "event_type": "project.phase.activated",
        "project_id": _PROJECT_ID,
        "aggregate": TypedReference(target_type="project", target_id=_PROJECT_ID),
        "occurred_at": _BASE_TIME,
        "recorded_at": _BASE_TIME,
        "actor": actor,
        "correlation_id": None,
        "causation_id": None,
        "idempotency_key": "property:test",
        "schema_version": _VERSION,
        "payload": payload,
        **changes,
    }
    return EventEnvelope.model_validate(values)


@given(_JSON_OBJECTS)
def test_valid_json_payloads_round_trip(payload: dict[str, object]) -> None:
    event = _event(payload)

    restored = EventEnvelope.model_validate_json(event.model_dump_json())

    assert restored.payload == event.payload


@given(_JSON_OBJECTS)
def test_payload_key_order_does_not_affect_fingerprints(payload: dict[str, object]) -> None:
    reversed_payload = dict(reversed(tuple(payload.items())))

    assert _event(payload).record_fingerprint() == _event(reversed_payload).record_fingerprint()


@given(_EVENT_TYPES)
def test_generated_canonical_event_types_validate(value: str) -> None:
    assert validate_event_type(value) == value


@given(
    _EVENT_TYPES,
    st.sampled_from(["-", " ", "@", "/", "A"]),
)
def test_characters_outside_event_type_grammar_are_rejected(
    value: str, invalid_character: str
) -> None:
    invalid = f"{value}{invalid_character}"

    with pytest.raises(EventValidationError, match="at least three canonical"):
        validate_event_type(invalid)


@given(st.integers(min_value=1, max_value=10_000_000))
def test_recorded_at_before_occurred_at_is_always_rejected(microseconds: int) -> None:
    with pytest.raises(ValidationError):
        _event(
            {},
            occurred_at=_BASE_TIME + timedelta(microseconds=microseconds),
            recorded_at=_BASE_TIME,
        )


@given(st.integers(), st.integers().filter(lambda value: value != 0))
def test_contractual_payload_mutation_changes_content_fingerprint(value: int, delta: int) -> None:
    first = _event({"value": value})
    second = _event({"value": value + delta})

    assert first.contract_content_fingerprint() != second.contract_content_fingerprint()
