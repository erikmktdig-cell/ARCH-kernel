"""Tests for ProjectState intra-aggregate validation."""

import json
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from arch_kernel.contracts import ProjectMetadata, ProjectProfile, ProjectState

_FIXTURE_PATH = Path(__file__).parents[2] / "fixtures" / "valid" / "minimal_project_state.json"


def _payload() -> dict[str, object]:
    value = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _state_payload() -> dict[str, object]:
    return deepcopy(_payload())


def _validate(payload: dict[str, object]) -> ProjectState:
    return ProjectState.model_validate_json(json.dumps(payload))


def _mapping(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    return value


def test_initial_state_allows_empty_registries_without_a_current_phase() -> None:
    payload = _state_payload()
    lifecycle = _mapping(payload["lifecycle"])
    payload["lifecycle"] = {
        **lifecycle,
        "current_phase_id": None,
        "current_phase_code": None,
        "status": "not_started",
        "started_at": None,
    }
    payload["phase_execution_records"] = {}
    payload["artifact_registry"] = {}
    payload["requirement_registry"] = {}
    payload["risk_registry"] = {}
    payload["decision_log"] = []
    payload["dependency_graph"] = []
    payload["active_baseline_artifact_ids"] = []
    payload["open_items"] = []

    state = _validate(payload)

    assert state.phase_execution_records == {}


@pytest.mark.parametrize(
    ("field_name", "value", "message"),
    [
        ("name", " ", "name cannot be empty"),
        ("slug", "Not Kebab", "lowercase kebab-case"),
        ("owner", " ", "owner cannot be empty"),
    ],
)
def test_project_metadata_rejects_invalid_local_values(
    field_name: str, value: str, message: str
) -> None:
    payload = _mapping(_payload()["metadata"])

    with pytest.raises(ValidationError, match=message):
        ProjectMetadata.model_validate_json(json.dumps({**payload, field_name: value}))


def test_project_profile_rejects_duplicate_objectives() -> None:
    payload = _mapping(_payload()["profile"])

    with pytest.raises(ValidationError, match="objectives cannot contain duplicate"):
        ProjectProfile.model_validate_json(json.dumps({**payload, "objectives": ["same", "same"]}))


def test_project_state_rejects_two_active_phases() -> None:
    payload = _state_payload()
    phase_records = payload["phase_execution_records"]
    assert isinstance(phase_records, dict)
    record = next(iter(phase_records.values()))
    assert isinstance(record, dict)
    second_id = "PHS-01HZX7M3FQ1T2Q9V8Y6K4C2B1G"
    phase_records[second_id] = {**record, "phase_id": second_id, "phase_code": "F03"}

    with pytest.raises(ValidationError, match="more than one active phase"):
        _validate(payload)


def test_project_state_rejects_registry_key_mismatch() -> None:
    payload = _state_payload()
    artifacts = payload["artifact_registry"]
    assert isinstance(artifacts, dict)
    artifact = next(iter(artifacts.values()))
    assert isinstance(artifact, dict)
    artifacts.clear()
    artifacts["ART-01HZX7M3FQ1T2Q9V8Y6K4C2B1H"] = artifact

    with pytest.raises(ValidationError, match="artifact_registry key"):
        _validate(payload)


@pytest.mark.parametrize(
    ("field_name", "value", "message"),
    [
        ("current_phase_id", "PHS-01HZX7M3FQ1T2Q9V8Y6K4C2B1G", "must exist"),
        ("current_phase_code", "F03", "phase code must match"),
        ("status", "blocked", "status must match"),
    ],
)
def test_project_state_rejects_incoherent_lifecycle(
    field_name: str, value: str, message: str
) -> None:
    payload = _state_payload()
    lifecycle = payload["lifecycle"]
    assert isinstance(lifecycle, dict)
    lifecycle[field_name] = value
    if field_name == "status":
        lifecycle["blocked_reason"] = "Waiting for input."

    with pytest.raises(ValidationError, match=message):
        _validate(payload)


def test_project_state_rejects_missing_or_unapproved_baselines() -> None:
    payload = _state_payload()
    payload["active_baseline_artifact_ids"] = ["ART-01HZX7M3FQ1T2Q9V8Y6K4C2B1H"]

    with pytest.raises(ValidationError, match="must exist in artifact_registry"):
        _validate(payload)

    payload = _state_payload()
    artifacts = payload["artifact_registry"]
    assert isinstance(artifacts, dict)
    artifact = next(iter(artifacts.values()))
    assert isinstance(artifact, dict)
    artifact["status"] = "draft"

    with pytest.raises(ValidationError, match="approved or conditionally approved"):
        _validate(payload)


def test_project_state_rejects_missing_internal_references() -> None:
    payload = _state_payload()
    requirements = payload["requirement_registry"]
    assert isinstance(requirements, dict)
    requirement = next(iter(requirements.values()))
    assert isinstance(requirement, dict)
    requirement["artifact_ids"] = ["ART-01HZX7M3FQ1T2Q9V8Y6K4C2B1H"]

    with pytest.raises(ValidationError, match="Requirement artifact_ids"):
        _validate(payload)


def test_project_state_rejects_duplicate_decisions_edges_and_open_items() -> None:
    payload = _state_payload()
    decisions = payload["decision_log"]
    assert isinstance(decisions, list)
    decisions.append(deepcopy(decisions[0]))

    with pytest.raises(ValidationError, match="decision_log decision IDs"):
        _validate(payload)

    payload = _state_payload()
    edges = payload["dependency_graph"]
    assert isinstance(edges, list)
    edges.append(deepcopy(edges[0]))

    with pytest.raises(ValidationError, match="dependency_graph cannot contain duplicate"):
        _validate(payload)

    payload = _state_payload()
    payload["open_items"] = ["same", "same"]

    with pytest.raises(ValidationError, match="open_items cannot contain duplicate"):
        _validate(payload)


def test_project_state_fingerprint_semantics_are_preserved() -> None:
    first = _validate(_state_payload())
    payload = _state_payload()
    payload["updated_at"] = "2026-07-23T12:06:00+00:00"
    second = _validate(payload)

    assert first.fingerprint() != second.fingerprint()
    assert first.contract_content_fingerprint() == second.contract_content_fingerprint()
