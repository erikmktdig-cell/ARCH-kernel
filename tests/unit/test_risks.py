"""Tests for risk records."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from arch_kernel.contracts import RiskRecord

_FIXTURE_PATH = Path(__file__).parents[2] / "fixtures" / "valid" / "minimal_project_state.json"


def test_risk_requires_mitigation_and_calculates_score() -> None:
    payload = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    risk = next(iter(payload["risk_registry"].values()))

    record = RiskRecord.model_validate_json(json.dumps(risk))

    assert record.score == 8
    with pytest.raises(ValidationError, match="mitigation is required"):
        RiskRecord.model_validate_json(json.dumps({**risk, "status": "mitigating"}))
    with pytest.raises(ValidationError):
        RiskRecord.model_validate_json(json.dumps({**risk, "probability": 6}))
