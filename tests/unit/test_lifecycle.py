"""Tests for lifecycle and phase execution records."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from arch_kernel.contracts import LifecycleState, PhaseExecutionRecord

_FIXTURE_PATH = Path(__file__).parents[2] / "fixtures" / "valid" / "minimal_project_state.json"


def _payload() -> dict[str, object]:
    value = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _mapping(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    return value


def test_lifecycle_rejects_unpaired_current_phase_fields() -> None:
    lifecycle = _mapping(_payload()["lifecycle"])

    with pytest.raises(ValidationError, match="provided together"):
        LifecycleState.model_validate_json(json.dumps({**lifecycle, "current_phase_id": None}))


def test_lifecycle_requires_blocked_reason_and_terminal_completed_at() -> None:
    lifecycle = _mapping(_payload()["lifecycle"])

    with pytest.raises(ValidationError, match="blocked_reason is required"):
        LifecycleState.model_validate_json(json.dumps({**lifecycle, "status": "blocked"}))
    with pytest.raises(ValidationError, match="terminal-compatible"):
        LifecycleState.model_validate_json(
            json.dumps({**lifecycle, "completed_at": "2026-07-23T12:02:00+00:00"})
        )


def test_phase_execution_rejects_duplicates_and_invalid_attempt() -> None:
    payload = _payload()
    records = payload["phase_execution_records"]
    assert isinstance(records, dict)
    record = next(iter(records.values()))

    with pytest.raises(ValidationError, match="artifact_ids cannot contain duplicate"):
        PhaseExecutionRecord.model_validate_json(
            json.dumps({**record, "artifact_ids": ["ART-01HZX7M3FQ1T2Q9V8Y6K4C2B1C"] * 2})
        )
    with pytest.raises(ValidationError):
        PhaseExecutionRecord.model_validate_json(json.dumps({**record, "attempt": 0}))
