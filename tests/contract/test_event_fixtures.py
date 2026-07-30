"""Contract tests for valid and invalid event fixtures."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from arch_kernel.contracts import EventEnvelope

_FIXTURE_ROOT = Path(__file__).parents[2] / "fixtures"
_VALID_FIXTURE = _FIXTURE_ROOT / "valid" / "event_envelope.json"
_INVALID_FIXTURES = _FIXTURE_ROOT / "invalid" / "events"


def test_event_fixture_loads_and_round_trips() -> None:
    event = EventEnvelope.model_validate_json(_VALID_FIXTURE.read_text(encoding="utf-8"))
    restored = EventEnvelope.model_validate_json(event.model_dump_json())

    assert restored == event
    assert restored.project_id == event.aggregate.target_id
    assert restored.canonical_json() == event.canonical_json()


@pytest.mark.parametrize(
    ("filename", "message"),
    [
        ("invalid_event_type.json", "at least three canonical"),
        ("naive_timestamp.json", "Naive datetimes"),
        ("reverse_timestamp_order.json", "recorded_at must be greater"),
        ("self_causation.json", "causation_id cannot"),
        ("causation_without_correlation.json", "requires correlation_id"),
        ("invalid_idempotency_key.json", "safe ASCII"),
        ("invalid_payload.json", "payload root must be a JSON object"),
        ("aggregate_type_mismatch.json", "target_type does not match"),
        ("unknown_field.json", "Extra inputs are not permitted"),
    ],
)
def test_invalid_event_fixtures_fail_for_expected_reason(filename: str, message: str) -> None:
    payload = (_INVALID_FIXTURES / filename).read_text(encoding="utf-8")

    with pytest.raises(ValidationError, match=message):
        EventEnvelope.model_validate_json(payload)
