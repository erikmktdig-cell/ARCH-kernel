"""Cross-kernel canonical round-trip properties."""

from __future__ import annotations

from hypothesis import given

from arch_kernel.contracts import CanonicalId, EventEnvelope, ProjectState
from arch_kernel.kernel.event_validation import freeze_json_value, thaw_json
from arch_kernel.kernel.fingerprints import canonicalize_json
from tests.strategies.events import valid_events
from tests.strategies.ids import typed_ids
from tests.strategies.json_values import json_values
from tests.strategies.project_state import valid_project_states


@given(typed_ids())
def test_typed_id_parse_format_round_trip(identifier: CanonicalId) -> None:
    id_type = type(identifier)
    assert id_type.from_str(str(identifier)) == identifier


@given(json_values())
def test_freeze_thaw_freeze_preserves_canonical_json(value: object) -> None:
    frozen = freeze_json_value(value)
    thawed = thaw_json(frozen)

    assert canonicalize_json(thawed) == canonicalize_json(value)
    assert freeze_json_value(thawed) == frozen


@given(valid_events())
def test_event_json_round_trip_is_semantically_exact(event: EventEnvelope) -> None:
    assert EventEnvelope.model_validate_json(event.model_dump_json()) == event


@given(valid_project_states())
def test_project_state_json_round_trip_is_semantically_exact(
    state: ProjectState,
) -> None:
    rebuilt = ProjectState.model_validate_json(state.model_dump_json())
    assert rebuilt.contract_content_fingerprint() == state.contract_content_fingerprint()
