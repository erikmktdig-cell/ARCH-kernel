"""Contract tests for the minimal ProjectState fixture."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from arch_kernel.contracts import ProjectState

_FIXTURE_PATH = Path(__file__).parents[2] / "fixtures" / "valid" / "minimal_project_state.json"
_INVALID_FIXTURE_PATH = Path(__file__).parents[2] / "fixtures" / "invalid" / "project_state"


def test_minimal_project_state_fixture_loads_and_round_trips() -> None:
    payload = _FIXTURE_PATH.read_text(encoding="utf-8")

    state = ProjectState.model_validate_json(payload)
    restored = ProjectState.model_validate_json(state.model_dump_json())

    assert restored == state
    assert restored.model_dump(mode="json") == state.model_dump(mode="json")
    assert state.lifecycle.current_phase_id in state.phase_execution_records
    assert state.active_baseline_artifact_ids[0] in state.artifact_registry


def test_project_state_fixture_schema_is_strict() -> None:
    schema = ProjectState.model_json_schema()

    assert schema["additionalProperties"] is False
    assert {"metadata", "profile", "lifecycle"} <= set(schema["required"])


@pytest.mark.parametrize(
    ("filename", "message"),
    [
        ("two_active_phases.json", "more than one active phase"),
        ("registry_key_mismatch.json", "artifact_registry key"),
        ("lifecycle_missing_phase.json", "must exist in phase_execution_records"),
        ("baseline_missing.json", "must exist in artifact_registry"),
        ("baseline_draft.json", "approved or conditionally approved"),
        ("requirement_missing_artifact.json", "Requirement artifact_ids"),
        ("dependency_self_reference.json", "cannot be identical"),
    ],
)
def test_invalid_project_state_fixtures_are_rejected(filename: str, message: str) -> None:
    payload = (_INVALID_FIXTURE_PATH / filename).read_text(encoding="utf-8")

    with pytest.raises(ValidationError, match=message):
        ProjectState.model_validate_json(payload)
