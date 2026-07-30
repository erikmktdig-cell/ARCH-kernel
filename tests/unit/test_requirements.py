"""Tests for requirement records."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from arch_kernel.contracts import RequirementRecord

_FIXTURE_PATH = Path(__file__).parents[2] / "fixtures" / "valid" / "minimal_project_state.json"


def test_requirement_rejects_blank_text_and_duplicate_references() -> None:
    payload = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    requirement = next(iter(payload["requirement_registry"].values()))

    with pytest.raises(ValidationError, match="title cannot be empty"):
        RequirementRecord.model_validate_json(json.dumps({**requirement, "title": " "}))
    with pytest.raises(ValidationError, match="acceptance_criteria cannot contain duplicate"):
        RequirementRecord.model_validate_json(
            json.dumps({**requirement, "acceptance_criteria": ["same", "same"]})
        )
    with pytest.raises(ValidationError, match="artifact_ids cannot contain duplicate"):
        RequirementRecord.model_validate_json(
            json.dumps(
                {
                    **requirement,
                    "artifact_ids": ["ART-01HZX7M3FQ1T2Q9V8Y6K4C2B1C"] * 2,
                }
            )
        )
