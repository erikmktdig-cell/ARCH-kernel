"""Metamorphic properties for K08 validation orchestration."""

from __future__ import annotations

from arch_kernel.contracts import (
    ValidationDisposition,
    ValidationStage,
)
from arch_kernel.kernel import run_validation_pipeline
from tests.invariant_helpers import canonical_registry
from tests.patch_helpers import load_state
from tests.validation_helpers import state_request


def test_stage_and_flattened_finding_order_are_canonical() -> None:
    result = run_validation_pipeline(
        state_request(load_state()),
        invariant_registry=canonical_registry(),
    )
    stages = (
        result.contract_stage,
        result.aggregate_stage,
        result.patch_stage,
        result.transition_stage,
        result.invariant_stage,
        result.finalization_stage,
    )

    assert tuple(item.stage for item in stages) == tuple(ValidationStage)
    assert result.findings == tuple(finding for stage in stages for finding in stage.findings)


def test_invalid_raw_contract_is_always_invalid_input() -> None:
    validation_request = state_request(load_state()).model_copy(
        update={"state": None, "raw_state": {"project_id": "invalid"}}
    )

    result = run_validation_pipeline(validation_request)

    assert not result.success
    assert result.disposition is ValidationDisposition.INVALID_INPUT
    assert result.contract_stage.blocking_failure
