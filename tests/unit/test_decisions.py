"""Tests for immutable decision records."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from arch_kernel.contracts import DecisionRecord

_FIXTURE_PATH = Path(__file__).parents[2] / "fixtures" / "valid" / "minimal_project_state.json"


def test_decision_is_superficially_immutable_and_rejects_self_supersession() -> None:
    payload = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    decision = payload["decision_log"][0]
    record = DecisionRecord.model_validate_json(json.dumps(decision))

    with pytest.raises(ValidationError, match="Instance is frozen"):
        record.title = "Changed"
    with pytest.raises(ValidationError, match="cannot supersede itself"):
        DecisionRecord.model_validate_json(
            json.dumps({**decision, "supersedes": decision["decision_id"]})
        )
