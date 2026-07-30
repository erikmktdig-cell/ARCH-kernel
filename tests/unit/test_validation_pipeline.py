"""Behavior tests for the WP-K08 unified validation pipeline."""

from __future__ import annotations

from datetime import timedelta
from typing import cast

from arch_kernel.contracts import (
    InvariantEvaluationTarget,
    InvariantKind,
    InvariantSeverity,
    ValidationDisposition,
    ValidationFindingKind,
    ValidationIntent,
    ValidationPipelinePolicy,
    ValidationPipelineRequest,
    ValidationStage,
)
from arch_kernel.kernel import ErrorCode, InvariantRegistry, run_validation_pipeline
from arch_kernel.kernel.fingerprints import canonicalize_json
from tests.invariant_helpers import definition
from tests.validation_helpers import (
    EVALUATED_AT,
    invariant_registry,
    load_state,
    patch_request,
    state_request,
    transition_request,
)


def test_validate_state_executes_canonical_stages_and_accepts() -> None:
    result = run_validation_pipeline(state_request())
    stages = (
        result.contract_stage,
        result.aggregate_stage,
        result.patch_stage,
        result.transition_stage,
        result.invariant_stage,
        result.finalization_stage,
    )
    assert tuple(stage.stage for stage in stages) == tuple(ValidationStage)
    assert tuple(stage.executed for stage in stages) == (
        True,
        True,
        False,
        False,
        False,
        True,
    )
    assert result.disposition is ValidationDisposition.ACCEPTED
    assert result.validated_state == load_state()


def test_raw_state_and_equivalent_typed_state_are_accepted() -> None:
    state = load_state()
    raw_only = ValidationPipelineRequest.model_validate(
        {
            "intent": ValidationIntent.VALIDATE_STATE,
            "evaluated_at": EVALUATED_AT,
            "raw_state": state.model_dump(mode="json"),
        }
    )
    both = state_request(state, raw_state=state.model_dump(mode="json"))
    typed_result = run_validation_pipeline(state_request(state))
    raw_result = run_validation_pipeline(raw_only)
    both_result = run_validation_pipeline(both)
    assert raw_result.success
    assert both_result.success
    assert {
        typed_result.input_fingerprint,
        raw_result.input_fingerprint,
        both_result.input_fingerprint,
    } == {typed_result.input_fingerprint}


def test_conflicting_typed_and_raw_state_is_invalid_input() -> None:
    state = load_state()
    raw = state.model_dump(mode="json")
    raw["profile"]["project_type"] = "different"
    result = run_validation_pipeline(state_request(state, raw_state=raw))
    assert result.disposition is ValidationDisposition.INVALID_INPUT
    assert result.contract_stage.blocking_failure
    assert result.aggregate_stage.executed is False
    assert result.findings[0].code == ErrorCode.INVALID_VALIDATION_REQUEST.value


def test_malformed_raw_state_stops_before_aggregate() -> None:
    request = ValidationPipelineRequest.model_validate(
        {
            "intent": ValidationIntent.VALIDATE_STATE,
            "evaluated_at": EVALUATED_AT,
            "raw_state": {"contract_name": "project_state"},
        }
    )
    result = run_validation_pipeline(request)
    assert result.disposition is ValidationDisposition.INVALID_INPUT
    assert result.contract_stage.findings[0].kind is ValidationFindingKind.CONTRACT_ERROR
    assert not result.aggregate_stage.executed


def test_successful_patch_delegates_to_k05_then_k07() -> None:
    result = run_validation_pipeline(
        patch_request(),
        invariant_registry=invariant_registry(),
    )
    assert result.disposition is ValidationDisposition.ACCEPTED
    assert result.patch_stage.executed
    assert result.patch_stage.metadata["status"] == "completed"
    assert result.projected_state is not None
    assert result.projected_state.record_version == load_state().record_version + 1
    assert result.invariant_stage.executed


def test_patch_requires_invariant_registry_by_default() -> None:
    result = run_validation_pipeline(patch_request())
    assert result.disposition is ValidationDisposition.INVALID_INPUT
    assert result.findings[-1].code == ErrorCode.MISSING_INVARIANT_REGISTRY.value


def test_failed_patch_rejects_and_skips_projected_invariants() -> None:
    request = patch_request(base_state_record_version=999)
    result = run_validation_pipeline(
        request,
        invariant_registry=invariant_registry(),
    )
    assert result.disposition is ValidationDisposition.REJECTED
    assert result.patch_stage.blocking_failure
    assert not result.invariant_stage.executed
    assert result.projected_state is None


def test_successful_transition_delegates_to_k06_without_second_patch() -> None:
    request, registry = transition_request()
    result = run_validation_pipeline(
        request,
        transition_registry=registry,  # type: ignore[arg-type]
        invariant_registry=invariant_registry(),
    )
    assert result.disposition is ValidationDisposition.ACCEPTED
    assert result.transition_stage.metadata["allowed"] is True
    assert result.generated_patch is not None
    assert result.projected_state is not None
    assert result.patch_stage.executed is False


def test_transition_missing_registry_is_invalid_input() -> None:
    request, _ = transition_request()
    result = run_validation_pipeline(request, invariant_registry=invariant_registry())
    assert result.disposition is ValidationDisposition.INVALID_INPUT
    assert result.findings[-1].code == ErrorCode.MISSING_TRANSITION_REGISTRY.value
    assert not result.invariant_stage.executed


def test_release_requires_and_runs_invariants_on_original_state() -> None:
    request = state_request(intent=ValidationIntent.VALIDATE_RELEASE)
    missing = run_validation_pipeline(request)
    accepted = run_validation_pipeline(request, invariant_registry=invariant_registry())
    assert missing.disposition is ValidationDisposition.INVALID_INPUT
    assert missing.findings[-1].code == ErrorCode.MISSING_INVARIANT_REGISTRY.value
    assert accepted.disposition is ValidationDisposition.ACCEPTED
    assert accepted.invariant_stage.metadata["target"] == "original"


def test_expected_input_fingerprint_is_enforced() -> None:
    request = state_request(expected_input_fingerprint="sha256:" + ("0" * 64))
    result = run_validation_pipeline(request)
    assert result.disposition is ValidationDisposition.INVALID_INPUT
    assert result.contract_stage.blocking_failure


def test_result_fingerprint_excludes_evaluation_time_when_semantics_do_not_change() -> None:
    first = run_validation_pipeline(state_request())
    second_request = state_request().model_copy(
        update={"evaluated_at": EVALUATED_AT + timedelta(days=1)}
    )
    second = run_validation_pipeline(second_request)
    assert first.input_fingerprint == second.input_fingerprint
    assert first.result_fingerprint == second.result_fingerprint


def test_patch_result_fingerprint_excludes_projection_clock_metadata() -> None:
    first_request = patch_request()
    second_request = first_request.model_copy(
        update={"evaluated_at": EVALUATED_AT + timedelta(days=1)}
    )
    registry = invariant_registry()
    first = run_validation_pipeline(first_request, invariant_registry=registry)
    second = run_validation_pipeline(second_request, invariant_registry=registry)
    assert first.input_fingerprint == second.input_fingerprint
    assert first.projected_state.updated_at != second.projected_state.updated_at  # type: ignore[union-attr]
    assert first.result_fingerprint == second.result_fingerprint


def test_finding_sequence_and_counts_are_stable() -> None:
    result = run_validation_pipeline(
        patch_request(base_state_record_version=999),
        invariant_registry=invariant_registry(),
    )
    assert tuple(item.sequence for item in result.findings) == tuple(
        range(1, len(result.findings) + 1)
    )
    assert sum(cast(int, value) for value in result.counts_by_stage.values()) == len(
        result.findings
    )
    assert sum(cast(int, value) for value in result.counts_by_kind.values()) == len(result.findings)
    assert sum(cast(int, value) for value in result.counts_by_severity.values()) == len(
        result.findings
    )


def test_policy_can_hide_transition_outputs_without_changing_decision() -> None:
    request, registry = transition_request()
    request = request.model_copy(
        update={"policy": ValidationPipelinePolicy(expose_transition_outputs=False)}
    )
    result = run_validation_pipeline(
        request,
        transition_registry=registry,  # type: ignore[arg-type]
        invariant_registry=invariant_registry(),
    )
    assert result.success
    assert result.generated_patch is None
    assert result.projected_state is None
    assert result.transition_summary is not None


def test_conflicting_typed_and_raw_patch_is_invalid_input() -> None:
    request = patch_request()
    raw = request.patch.model_dump(mode="json")  # type: ignore[union-attr]
    raw["reason"] = "A different patch intention."
    request = request.model_copy(update={"raw_patch": raw})
    result = run_validation_pipeline(request, invariant_registry=invariant_registry())
    assert result.disposition is ValidationDisposition.INVALID_INPUT
    assert not result.patch_stage.executed


def test_continue_policy_can_validate_original_after_failed_patch() -> None:
    policy = ValidationPipelinePolicy(
        continue_after_blocking_failure=True,
        invariant_target=InvariantEvaluationTarget.ORIGINAL,
    )
    result = run_validation_pipeline(
        patch_request(policy=policy, base_state_record_version=999),
        invariant_registry=invariant_registry(),
    )
    assert result.disposition is ValidationDisposition.REJECTED
    assert result.patch_stage.blocking_failure
    assert result.invariant_stage.executed


def test_missing_projection_can_be_an_explicit_pipeline_failure() -> None:
    policy = ValidationPipelinePolicy(
        invariant_target=InvariantEvaluationTarget.PROJECTED,
        prevent_projected_invariants_after_failed_projection=False,
    )
    result = run_validation_pipeline(
        state_request(policy=policy),
        invariant_registry=invariant_registry(),
    )
    assert result.disposition is ValidationDisposition.REJECTED
    assert result.invariant_stage.findings[0].code == ErrorCode.VALIDATION_STAGE_FAILED.value


def test_unknown_invariant_selection_is_normalized() -> None:
    request = state_request(selected_invariant_keys=("project.unknown.invariant",))
    result = run_validation_pipeline(request, invariant_registry=invariant_registry())
    assert result.disposition is ValidationDisposition.REJECTED
    assert result.invariant_stage.findings[0].code == ErrorCode.INVARIANT_EVALUATION_ERROR.value


def test_nonblocking_invariant_produces_accepted_with_findings() -> None:
    document = load_state().model_dump(mode="json")
    risk = next(iter(document["risk_registry"].values()))
    risk.update({"probability": 5, "impact": 5, "status": "open", "mitigation": None})
    state = type(load_state()).model_validate_json(canonicalize_json(document))
    invariant = definition(
        InvariantKind.CRITICAL_RISK_CONTROL,
        severity=InvariantSeverity.WARNING,
        blocking=False,
    )
    result = run_validation_pipeline(
        state_request(
            state,
            policy=ValidationPipelinePolicy(invariant_target=InvariantEvaluationTarget.ORIGINAL),
        ),
        invariant_registry=InvariantRegistry((invariant,)),
    )
    assert result.success
    assert result.disposition is ValidationDisposition.ACCEPTED_WITH_FINDINGS
    assert result.findings[0].blocking is False


def test_nonblocking_findings_can_leave_disposition_accepted() -> None:
    document = load_state().model_dump(mode="json")
    risk = next(iter(document["risk_registry"].values()))
    risk.update({"probability": 5, "impact": 5, "status": "open", "mitigation": None})
    state = type(load_state()).model_validate_json(canonicalize_json(document))
    invariant = definition(
        InvariantKind.CRITICAL_RISK_CONTROL,
        severity=InvariantSeverity.INFO,
        blocking=False,
    )
    policy = ValidationPipelinePolicy(
        invariant_target=InvariantEvaluationTarget.ORIGINAL,
        non_blocking_findings_affect_disposition=False,
    )
    result = run_validation_pipeline(
        state_request(state, policy=policy),
        invariant_registry=InvariantRegistry((invariant,)),
    )
    assert result.disposition is ValidationDisposition.ACCEPTED
