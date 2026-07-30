import pytest
from pydantic import BaseModel, ValidationError

from arch_kernel.contracts.enums import (
    ApprovalDecision,
    ArtifactStatus,
    ExecutionStatus,
    GateResult,
    PhaseCode,
    PhaseStatus,
    Route,
)


class EnumContainer(BaseModel):
    route: Route
    phase_code: PhaseCode
    phase_status: PhaseStatus
    artifact_status: ArtifactStatus
    gate_result: GateResult
    approval_decision: ApprovalDecision
    execution_status: ExecutionStatus


def test_all_canonical_enum_values() -> None:
    assert {value.value for value in Route} == {"quick", "standard", "critical"}
    assert {value.value for value in PhaseCode} == {f"F{index:02d}" for index in range(1, 16)}
    assert {value.value for value in PhaseStatus} == {
        "not_started",
        "eligible",
        "ready",
        "active",
        "blocked",
        "awaiting_approval",
        "in_review",
        "completed",
        "completed_with_conditions",
        "revalidation_pending",
        "reopened",
        "cancelled",
    }
    assert {value.value for value in ArtifactStatus} == {
        "draft",
        "proposed",
        "under_review",
        "changes_requested",
        "conditionally_approved",
        "approved",
        "rejected",
        "invalidated",
        "superseded",
        "archived",
    }
    assert {value.value for value in GateResult} == {
        "pass",
        "pass_with_condition",
        "fail",
        "not_applicable",
        "insufficient_evidence",
        "invalidated",
    }
    assert {value.value for value in ApprovalDecision} == {
        "approved",
        "approved_with_conditions",
        "rejected",
        "deferred",
        "revoked",
        "expired",
    }
    assert {value.value for value in ExecutionStatus} == {
        "completed",
        "completed_with_conditions",
        "blocked",
        "needs_review",
        "conflict_detected",
        "invalid_input",
        "stopped",
    }


def test_unknown_enum_values_are_rejected() -> None:
    with pytest.raises(ValueError, match="unknown"):
        Route("unknown")

    with pytest.raises(ValidationError):
        EnumContainer.model_validate(
            {
                "route": "fast",
                "phase_code": "F01",
                "phase_status": "active",
                "artifact_status": "draft",
                "gate_result": "pass",
                "approval_decision": "approved",
                "execution_status": "completed",
            }
        )


def test_enums_serialize_as_strings() -> None:
    container = EnumContainer(
        route=Route.STANDARD,
        phase_code=PhaseCode.F01,
        phase_status=PhaseStatus.ACTIVE,
        artifact_status=ArtifactStatus.APPROVED,
        gate_result=GateResult.PASS,
        approval_decision=ApprovalDecision.APPROVED,
        execution_status=ExecutionStatus.COMPLETED,
    )

    assert container.model_dump(mode="json") == {
        "route": "standard",
        "phase_code": "F01",
        "phase_status": "active",
        "artifact_status": "approved",
        "gate_result": "pass",
        "approval_decision": "approved",
        "execution_status": "completed",
    }


def test_enums_do_not_define_aliases() -> None:
    enum_types = (
        Route,
        PhaseCode,
        PhaseStatus,
        ArtifactStatus,
        GateResult,
        ApprovalDecision,
        ExecutionStatus,
    )

    for enum_type in enum_types:
        assert len(enum_type) == len(enum_type.__members__)
