"""Property tests for project-state contracts."""

import json
from copy import deepcopy
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from arch_kernel.contracts import ProjectState, RiskRecord

_FIXTURE_PATH = Path(__file__).parents[2] / "fixtures" / "valid" / "minimal_project_state.json"


def _payload() -> dict[str, object]:
    value = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


@given(st.integers(min_value=1, max_value=5), st.integers(min_value=1, max_value=5))
def test_risk_score_is_always_within_documented_bounds(probability: int, impact: int) -> None:
    payload = _payload()
    risks = payload["risk_registry"]
    assert isinstance(risks, dict)
    risk = next(iter(risks.values()))

    record = RiskRecord.model_validate_json(
        json.dumps({**risk, "probability": probability, "impact": impact})
    )

    assert 1 <= record.score <= 25


@given(st.sampled_from(["ART-01HZX7M3FQ1T2Q9V8Y6K4C2B1G", "ART-01HZX7M3FQ1T2Q9V8Y6K4C2B1H"]))
def test_changing_a_registry_key_is_rejected(replacement_key: str) -> None:
    payload = deepcopy(_payload())
    artifacts = payload["artifact_registry"]
    assert isinstance(artifacts, dict)
    artifact = next(iter(artifacts.values()))
    artifacts.clear()
    artifacts[replacement_key] = artifact

    with pytest.raises(ValidationError, match="artifact_registry key"):
        ProjectState.model_validate_json(json.dumps(payload))


@given(st.sampled_from(["duplicate", "same open item"]))
def test_duplicate_aggregate_collections_are_rejected(value: str) -> None:
    payload = deepcopy(_payload())
    payload["open_items"] = [value, value]

    with pytest.raises(ValidationError, match="open_items cannot contain duplicate"):
        ProjectState.model_validate_json(json.dumps(payload))
