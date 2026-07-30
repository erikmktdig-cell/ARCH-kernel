"""Contract tests for WP-K08 immutable validation models."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from arch_kernel.contracts import (
    FrozenJsonObject,
    InvariantEvaluationTarget,
    ValidationDisposition,
    ValidationFinding,
    ValidationFindingKind,
    ValidationIntent,
    ValidationPipelinePolicy,
    ValidationPipelineRequest,
    ValidationPipelineResult,
    ValidationStage,
)
from arch_kernel.kernel import Severity, run_validation_pipeline
from tests.validation_helpers import load_state, state_request


def test_required_enums_are_closed_and_canonical() -> None:
    assert tuple(item.value for item in ValidationStage) == (
        "contract",
        "aggregate",
        "patch",
        "transition",
        "invariant",
        "finalization",
    )
    assert len(ValidationIntent) == 5
    assert len(ValidationDisposition) == 5
    assert len(ValidationFindingKind) == 7


def test_policy_is_frozen_and_rejects_duplicate_stages() -> None:
    policy = ValidationPipelinePolicy(invariant_target=InvariantEvaluationTarget.ORIGINAL)
    with pytest.raises(ValidationError, match="frozen"):
        policy.invariant_target = InvariantEvaluationTarget.BOTH
    with pytest.raises(ValidationError, match="enabled_stages"):
        ValidationPipelinePolicy(enabled_stages=(ValidationStage.PATCH, ValidationStage.PATCH))


@pytest.mark.parametrize(
    ("intent", "extra"),
    [
        (ValidationIntent.VALIDATE_PATCH, {}),
        (ValidationIntent.VALIDATE_TRANSITION, {}),
        (
            ValidationIntent.VALIDATE_STATE,
            {"previous_snapshots": (load_state(),)},
        ),
    ],
)
def test_intent_requires_its_specific_inputs(
    intent: ValidationIntent, extra: dict[str, object]
) -> None:
    with pytest.raises(ValidationError):
        ValidationPipelineRequest.model_validate(
            {
                "intent": intent,
                "evaluated_at": datetime(2026, 7, 26, tzinfo=UTC),
                "state": load_state(),
                **extra,
            }
        )


def test_request_rejects_naive_evaluated_at_and_unknown_fields() -> None:
    payload = state_request().model_dump()
    payload["evaluated_at"] = datetime(2026, 7, 26)
    with pytest.raises(ValidationError, match="timezone"):
        ValidationPipelineRequest.model_validate(payload)
    payload = state_request().model_dump()
    payload["surprise"] = True
    with pytest.raises(ValidationError, match="Extra inputs"):
        ValidationPipelineRequest.model_validate(payload)


def test_finding_is_deeply_immutable_and_json_serializable() -> None:
    finding = ValidationFinding.model_validate(
        {
            "kind": ValidationFindingKind.PIPELINE_ERROR,
            "stage": ValidationStage.FINALIZATION,
            "code": "EXAMPLE",
            "message": "Example finding.",
            "severity": Severity.WARNING,
            "blocking": False,
            "sequence": 1,
            "actual": {"items": [1, 2]},
        }
    )
    assert isinstance(finding.actual, FrozenJsonObject)
    items = finding.actual["items"]
    assert isinstance(items, tuple)
    with pytest.raises((AttributeError, TypeError)):
        items.append(3)  # type: ignore[attr-defined]
    assert finding.model_dump(mode="json")["actual"] == {"items": [1, 2]}


def test_result_round_trip_preserves_equivalence() -> None:
    result = run_validation_pipeline(state_request())
    rebuilt = ValidationPipelineResult.model_validate_json(result.model_dump_json())
    assert rebuilt == result
    assert rebuilt.result_fingerprint == result.result_fingerprint
